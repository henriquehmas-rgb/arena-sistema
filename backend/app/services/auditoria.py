"""Serviço de auditoria: registra ações administrativas (staff) sobre
entidades do domínio na tabela `auditoria`."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Auditoria


async def registrar(
    db: AsyncSession,
    staff_id: int | None,
    acao: str,
    entidade: str,
    entidade_id: int | None,
    dados: dict | None = None,
) -> Auditoria:
    registro = Auditoria(
        staff_id=staff_id,
        acao=acao,
        entidade=entidade,
        entidade_id=entidade_id,
        dados=dados,
    )
    db.add(registro)
    await db.flush()
    return registro
