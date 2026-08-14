"""Rotas de reservas — conforme o contrato de API congelado:

    POST /reservas                                   (cliente) -> 201 | 409 slot_ocupado
    GET  /reservas/minhas                             (cliente) -> lista
    POST /reservas/{id}/cancelar                      (cliente) -> 200 | 422 fora_da_janela
    GET  /reservas?recurso_id&de&ate&status&cliente_id  (staff)   -> lista paginada
    POST /reservas/balcao                              (staff)   -> 201
    POST /reservas/{id}/cancelar-admin {estornar:bool} (staff)   -> 200

Task T4 (Wave 0) tinha adicionado aqui um placeholder mínimo de
`GET /minhas` só para exercitar `deps.get_cliente_atual` fim-a-fim em
`tests/test_auth.py`, documentando explicitamente que a Task T6 deveria
substituí-lo pela implementação completa — é o que este módulo faz agora.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_cliente_atual, get_db, get_staff_atual
from app.models.entities import Cliente, Reserva, Staff
from app.models.enums import ReservaStatus
from app.schemas.reservas import (
    CancelarAdminIn,
    ReservaBalcaoCriar,
    ReservaCriar,
    ReservaListaOut,
    ReservaOut,
    StatusOut,
)
from app.services import auditoria, reservas as reservas_service
from app.services.precos import PrecoNaoConfigurado

router = APIRouter()


def _limites_periodo_utc(
    de: date | None, ate: date | None
) -> tuple[datetime | None, datetime | None]:
    """Converte `de`/`ate` (datas locais, inclusive nas duas pontas — mesma
    convenção de `app.routers.relatorios`) pros limites `[inicio_utc,
    fim_utc)` que `listar_staff` usa pra filtrar. Antes desta função, o
    router aceitava `de`/`ate` como `datetime` cru: um `de=2026-08-13` do
    frontend virava meia-noite UTC (não meia-noite local), e o filtro
    `inicio <= ate` (também meia-noite) excluía o dia inteiro — a agenda do
    admin sempre voltava vazia."""
    tz = ZoneInfo(settings.tz_local)
    inicio_utc = (
        datetime.combine(de, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        if de is not None
        else None
    )
    fim_utc = (
        (datetime.combine(ate, time(0, 0), tzinfo=tz) + timedelta(days=1)).astimezone(
            timezone.utc
        )
        if ate is not None
        else None
    )
    return inicio_utc, fim_utc


def _para_out(reserva: Reserva) -> ReservaOut:
    expira_em = None
    if reserva.status == ReservaStatus.pendente_pagamento:
        expira_em = reserva.criado_em + timedelta(minutes=settings.reserva_ttl_min)

    if reserva.cliente_id is not None:
        cliente_nome = reserva.cliente.nome
        cliente_celular = reserva.cliente.celular
        cliente_email = reserva.cliente.email
    else:
        cliente_nome = reserva.nome_avulso
        cliente_celular = reserva.celular_avulso
        cliente_email = None

    return ReservaOut(
        id=reserva.id,
        recurso_id=reserva.recurso_id,
        recurso_nome=reserva.recurso.nome,
        inicio=reserva.inicio,
        fim=reserva.fim,
        status=reserva.status,
        origem=reserva.origem,
        valor_centavos=reserva.valor_centavos,
        expira_em=expira_em,
        cliente_nome=cliente_nome,
        cliente_celular=cliente_celular,
        cliente_email=cliente_email,
    )


@router.post("", response_model=ReservaOut, status_code=status.HTTP_201_CREATED)
async def criar_reserva(
    dados: ReservaCriar,
    cliente: Cliente = Depends(get_cliente_atual),
    db: AsyncSession = Depends(get_db),
) -> ReservaOut:
    try:
        reserva = await reservas_service.criar_online(
            db, cliente, dados.recurso_id, dados.inicio, dados.fim
        )
    except reservas_service.SlotInvalidoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="slot_invalido"
        ) from None
    except reservas_service.SlotOcupadoError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="slot_ocupado"
        ) from None
    except PrecoNaoConfigurado:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="preco_nao_configurado",
        ) from None
    return _para_out(reserva)


@router.get("/minhas", response_model=list[ReservaOut])
async def minhas_reservas(
    cliente: Cliente = Depends(get_cliente_atual),
    db: AsyncSession = Depends(get_db),
) -> list[ReservaOut]:
    resultado = await db.execute(
        select(Reserva).where(Reserva.cliente_id == cliente.id).order_by(Reserva.inicio)
    )
    reservas = resultado.scalars().all()
    return [_para_out(r) for r in reservas]


@router.post("/{reserva_id}/cancelar", response_model=StatusOut)
async def cancelar_reserva(
    reserva_id: int,
    cliente: Cliente = Depends(get_cliente_atual),
    db: AsyncSession = Depends(get_db),
) -> StatusOut:
    try:
        reserva = await reservas_service.cancelar_cliente(db, cliente, reserva_id)
    except reservas_service.ForaDaJanelaError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="fora_da_janela",
        ) from None
    return StatusOut(status=reserva.status)


@router.get("", response_model=ReservaListaOut)
async def listar_reservas_staff(
    recurso_id: int | None = Query(default=None),
    de: date | None = Query(default=None),
    ate: date | None = Query(default=None),
    status_filtro: ReservaStatus | None = Query(default=None, alias="status"),
    cliente_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _staff: Staff = Depends(get_staff_atual),
    db: AsyncSession = Depends(get_db),
) -> ReservaListaOut:
    inicio_utc, fim_utc = _limites_periodo_utc(de, ate)
    itens, total = await reservas_service.listar_staff(
        db,
        recurso_id=recurso_id,
        de=inicio_utc,
        ate=fim_utc,
        status_=status_filtro,
        cliente_id=cliente_id,
        limit=limit,
        offset=offset,
    )
    return ReservaListaOut(itens=[_para_out(r) for r in itens], total=total)


@router.post("/balcao", response_model=ReservaOut, status_code=status.HTTP_201_CREATED)
async def criar_reserva_balcao(
    dados: ReservaBalcaoCriar,
    staff: Staff = Depends(get_staff_atual),
    db: AsyncSession = Depends(get_db),
) -> ReservaOut:
    try:
        reserva = await reservas_service.criar_balcao(db, staff, dados)
    except reservas_service.SlotInvalidoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="slot_invalido"
        ) from None
    except reservas_service.SlotOcupadoError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="slot_ocupado"
        ) from None
    except PrecoNaoConfigurado:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="preco_nao_configurado",
        ) from None
    await auditoria.registrar(
        db,
        staff_id=staff.id,
        acao="criar_balcao",
        entidade="reserva",
        entidade_id=reserva.id,
        dados={
            "recurso_id": reserva.recurso_id,
            "valor_centavos": reserva.valor_centavos,
            "metodo": dados.metodo.value,
        },
    )
    return _para_out(reserva)


@router.post("/{reserva_id}/cancelar-admin", response_model=StatusOut)
async def cancelar_reserva_admin(
    reserva_id: int,
    dados: CancelarAdminIn,
    staff: Staff = Depends(get_staff_atual),
    db: AsyncSession = Depends(get_db),
) -> StatusOut:
    reserva = await reservas_service.cancelar_admin(
        db, staff, reserva_id, dados.estornar
    )
    await auditoria.registrar(
        db,
        staff_id=staff.id,
        acao="cancelar",
        entidade="reserva",
        entidade_id=reserva.id,
        dados={"estornar": dados.estornar},
    )
    return StatusOut(status=reserva.status)
