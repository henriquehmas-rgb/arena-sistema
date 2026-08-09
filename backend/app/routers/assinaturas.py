"""Rotas de assinaturas (mensalistas) — todas staff (contrato:
`GET/POST /assinaturas` e `POST /assinaturas/{id}/pausar|reativar|cancelar`,
todas `(staff)`, nenhuma exige `admin`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, get_staff_atual
from app.models.entities import Assinatura, Staff
from app.schemas.assinaturas import AssinaturaCriar, AssinaturaOut
from app.services import assinaturas as assinaturas_service

router = APIRouter()


def _to_out(assinatura: Assinatura) -> AssinaturaOut:
    return AssinaturaOut(
        id=assinatura.id,
        cliente_nome=assinatura.cliente.nome,
        recurso_nome=assinatura.recurso.nome,
        dia_semana=assinatura.dia_semana,
        hora_inicio=assinatura.hora_inicio,
        hora_fim=assinatura.hora_fim,
        valor_mensal_centavos=assinatura.valor_mensal_centavos,
        status=assinatura.status,
        proxima_cobranca=assinatura.proxima_cobranca,
    )


@router.get("", response_model=list[AssinaturaOut])
async def listar_assinaturas(
    staff: Staff = Depends(get_staff_atual),
    db: AsyncSession = Depends(get_db),
) -> list[AssinaturaOut]:
    resultado = await db.execute(select(Assinatura).order_by(Assinatura.id))
    return [_to_out(a) for a in resultado.scalars().all()]


@router.post("", response_model=AssinaturaOut, status_code=201)
async def criar_assinatura(
    dados: AssinaturaCriar,
    staff: Staff = Depends(get_staff_atual),
    db: AsyncSession = Depends(get_db),
) -> AssinaturaOut:
    assinatura = await assinaturas_service.criar(db, staff, dados)
    return _to_out(assinatura)


@router.post("/{assinatura_id}/pausar", response_model=AssinaturaOut)
async def pausar_assinatura(
    assinatura_id: int,
    staff: Staff = Depends(get_staff_atual),
    db: AsyncSession = Depends(get_db),
) -> AssinaturaOut:
    assinatura = await assinaturas_service.pausar(db, assinatura_id)
    return _to_out(assinatura)


@router.post("/{assinatura_id}/reativar", response_model=AssinaturaOut)
async def reativar_assinatura(
    assinatura_id: int,
    staff: Staff = Depends(get_staff_atual),
    db: AsyncSession = Depends(get_db),
) -> AssinaturaOut:
    assinatura = await assinaturas_service.reativar(db, assinatura_id)
    return _to_out(assinatura)


@router.post("/{assinatura_id}/cancelar", response_model=AssinaturaOut)
async def cancelar_assinatura(
    assinatura_id: int,
    staff: Staff = Depends(get_staff_atual),
    db: AsyncSession = Depends(get_db),
) -> AssinaturaOut:
    assinatura = await assinaturas_service.cancelar(db, assinatura_id)
    return _to_out(assinatura)
