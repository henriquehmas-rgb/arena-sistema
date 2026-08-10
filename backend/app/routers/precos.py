"""CRUD de faixas de preço (`FaixaPreco`) — somente admin (contrato: `GET/POST/PUT/DELETE /precos` (admin))."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_admin
from app.models.entities import FaixaPreco, Staff
from app.schemas.recursos import FaixaPrecoIn, FaixaPrecoOut
from app.services import auditoria

router = APIRouter()


@router.get("", response_model=list[FaixaPrecoOut])
async def listar_precos(
    recurso_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _admin: Staff = Depends(require_admin),
) -> list[FaixaPreco]:
    stmt = select(FaixaPreco)
    if recurso_id is not None:
        stmt = stmt.where(FaixaPreco.recurso_id == recurso_id)
    resultado = await db.execute(stmt.order_by(FaixaPreco.id))
    return list(resultado.scalars().all())


@router.post("", response_model=FaixaPrecoOut, status_code=status.HTTP_201_CREATED)
async def criar_preco(
    dados: FaixaPrecoIn,
    db: AsyncSession = Depends(get_db),
    admin: Staff = Depends(require_admin),
) -> FaixaPreco:
    faixa = FaixaPreco(**dados.model_dump())
    db.add(faixa)
    await db.flush()
    await auditoria.registrar(
        db,
        staff_id=admin.id,
        acao="criar",
        entidade="faixa_preco",
        entidade_id=faixa.id,
        dados=dados.model_dump(),
    )
    return faixa


@router.put("/{faixa_id}", response_model=FaixaPrecoOut)
async def atualizar_preco(
    faixa_id: int,
    dados: FaixaPrecoIn,
    db: AsyncSession = Depends(get_db),
    admin: Staff = Depends(require_admin),
) -> FaixaPreco:
    faixa = await db.get(FaixaPreco, faixa_id)
    if faixa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="faixa_nao_encontrada")
    for campo, valor in dados.model_dump().items():
        setattr(faixa, campo, valor)
    await db.flush()
    await auditoria.registrar(
        db,
        staff_id=admin.id,
        acao="atualizar",
        entidade="faixa_preco",
        entidade_id=faixa.id,
        dados=dados.model_dump(),
    )
    return faixa


@router.delete("/{faixa_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remover_preco(
    faixa_id: int,
    db: AsyncSession = Depends(get_db),
    admin: Staff = Depends(require_admin),
) -> None:
    faixa = await db.get(FaixaPreco, faixa_id)
    if faixa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="faixa_nao_encontrada")
    faixa_id_removida, recurso_id = faixa.id, faixa.recurso_id
    await db.delete(faixa)
    await db.flush()
    await auditoria.registrar(
        db,
        staff_id=admin.id,
        acao="remover",
        entidade="faixa_preco",
        entidade_id=faixa_id_removida,
        dados={"recurso_id": recurso_id},
    )
