"""CRUD de bloqueios de agenda (`Bloqueio`) — staff (contrato: `GET/POST/PUT/DELETE /bloqueios` (staff)).

POST/PUT validam sobreposição com reservas *confirmadas* do mesmo recurso
(reservas pendentes de pagamento não bloqueiam a criação — elas expiram
sozinhas via TTL) e retornam 409 com a lista de conflitos quando há
sobreposição.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, get_staff_atual
from app.models.entities import Bloqueio, Reserva, Staff
from app.models.enums import ReservaStatus
from app.schemas.recursos import BloqueioIn, BloqueioOut
from app.services import auditoria

router = APIRouter()


async def _conflitos_reservas_confirmadas(
    db: AsyncSession, recurso_id: int, inicio, fim
) -> list[Reserva]:
    resultado = await db.execute(
        select(Reserva).where(
            Reserva.recurso_id == recurso_id,
            Reserva.status == ReservaStatus.confirmada,
            Reserva.inicio < fim,
            Reserva.fim > inicio,
        )
    )
    return list(resultado.scalars().all())


def _erro_conflito(conflitos: list[Reserva]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "detail": "conflito_com_reservas",
            "conflitos": [
                {"id": r.id, "inicio": r.inicio.isoformat(), "fim": r.fim.isoformat()}
                for r in conflitos
            ],
        },
    )


@router.get("", response_model=list[BloqueioOut])
async def listar_bloqueios(
    recurso_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _staff: Staff = Depends(get_staff_atual),
) -> list[Bloqueio]:
    stmt = select(Bloqueio)
    if recurso_id is not None:
        stmt = stmt.where(Bloqueio.recurso_id == recurso_id)
    resultado = await db.execute(stmt.order_by(Bloqueio.inicio))
    return list(resultado.scalars().all())


@router.post("", response_model=BloqueioOut, status_code=status.HTTP_201_CREATED)
async def criar_bloqueio(
    dados: BloqueioIn,
    db: AsyncSession = Depends(get_db),
    staff: Staff = Depends(get_staff_atual),
) -> Bloqueio:
    conflitos = await _conflitos_reservas_confirmadas(db, dados.recurso_id, dados.inicio, dados.fim)
    if conflitos:
        raise _erro_conflito(conflitos)

    bloqueio = Bloqueio(
        recurso_id=dados.recurso_id,
        inicio=dados.inicio,
        fim=dados.fim,
        motivo=dados.motivo,
        staff_id=staff.id,
    )
    db.add(bloqueio)
    await db.flush()
    await auditoria.registrar(
        db,
        staff_id=staff.id,
        acao="criar",
        entidade="bloqueio",
        entidade_id=bloqueio.id,
        dados={
            "recurso_id": bloqueio.recurso_id,
            "inicio": bloqueio.inicio.isoformat(),
            "fim": bloqueio.fim.isoformat(),
            "motivo": bloqueio.motivo,
        },
    )
    return bloqueio


@router.put("/{bloqueio_id}", response_model=BloqueioOut)
async def atualizar_bloqueio(
    bloqueio_id: int,
    dados: BloqueioIn,
    db: AsyncSession = Depends(get_db),
    staff: Staff = Depends(get_staff_atual),
) -> Bloqueio:
    bloqueio = await db.get(Bloqueio, bloqueio_id)
    if bloqueio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bloqueio_nao_encontrado")

    conflitos = [
        r
        for r in await _conflitos_reservas_confirmadas(db, dados.recurso_id, dados.inicio, dados.fim)
    ]
    if conflitos:
        raise _erro_conflito(conflitos)

    bloqueio.recurso_id = dados.recurso_id
    bloqueio.inicio = dados.inicio
    bloqueio.fim = dados.fim
    bloqueio.motivo = dados.motivo
    await db.flush()
    await auditoria.registrar(
        db,
        staff_id=staff.id,
        acao="atualizar",
        entidade="bloqueio",
        entidade_id=bloqueio.id,
        dados={
            "recurso_id": bloqueio.recurso_id,
            "inicio": bloqueio.inicio.isoformat(),
            "fim": bloqueio.fim.isoformat(),
            "motivo": bloqueio.motivo,
        },
    )
    return bloqueio


@router.delete("/{bloqueio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remover_bloqueio(
    bloqueio_id: int,
    db: AsyncSession = Depends(get_db),
    staff: Staff = Depends(get_staff_atual),
) -> None:
    bloqueio = await db.get(Bloqueio, bloqueio_id)
    if bloqueio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bloqueio_nao_encontrado")
    bloqueio_id_removido, recurso_id = bloqueio.id, bloqueio.recurso_id
    await db.delete(bloqueio)
    await db.flush()
    await auditoria.registrar(
        db,
        staff_id=staff.id,
        acao="remover",
        entidade="bloqueio",
        entidade_id=bloqueio_id_removido,
        dados={"recurso_id": recurso_id},
    )
