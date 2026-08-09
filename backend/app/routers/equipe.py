"""Rotas de gestão de equipe (staff) — somente admin."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_admin
from app.models.entities import Staff
from app.schemas.equipe import StaffAtualizar, StaffCriar, StaffOut
from app.services import auditoria
from app.services import auth as auth_service

router = APIRouter()


@router.get("", response_model=list[StaffOut])
async def listar_equipe(
    db: AsyncSession = Depends(get_db),
    _admin: Staff = Depends(require_admin),
) -> list[Staff]:
    resultado = await db.execute(select(Staff).order_by(Staff.nome))
    return list(resultado.scalars().all())


@router.post("", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
async def criar_membro_equipe(
    dados: StaffCriar,
    db: AsyncSession = Depends(get_db),
    admin: Staff = Depends(require_admin),
) -> Staff:
    existente = await db.scalar(select(Staff).where(Staff.email == dados.email))
    if existente is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email_ja_cadastrado")

    staff = Staff(
        nome=dados.nome,
        email=dados.email,
        senha_hash=auth_service.hash_senha(dados.senha),
        papel=dados.papel,
        ativo=True,
    )
    db.add(staff)
    await db.flush()

    await auditoria.registrar(
        db,
        staff_id=admin.id,
        acao="criar",
        entidade="staff",
        entidade_id=staff.id,
        dados={"nome": staff.nome, "email": staff.email, "papel": staff.papel.value},
    )
    return staff


@router.put("/{staff_id}", response_model=StaffOut)
async def atualizar_membro_equipe(
    staff_id: int,
    dados: StaffAtualizar,
    db: AsyncSession = Depends(get_db),
    admin: Staff = Depends(require_admin),
) -> Staff:
    staff = await db.get(Staff, staff_id)
    if staff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="staff_nao_encontrado")

    alteracoes: dict = {}
    if dados.nome is not None:
        staff.nome = dados.nome
        alteracoes["nome"] = dados.nome
    if dados.papel is not None:
        staff.papel = dados.papel
        alteracoes["papel"] = dados.papel.value
    if dados.ativo is not None:
        staff.ativo = dados.ativo
        alteracoes["ativo"] = dados.ativo
    if dados.senha is not None:
        staff.senha_hash = auth_service.hash_senha(dados.senha)
        alteracoes["senha"] = "alterada"

    await db.flush()

    await auditoria.registrar(
        db,
        staff_id=admin.id,
        acao="atualizar",
        entidade="staff",
        entidade_id=staff.id,
        dados=alteracoes,
    )
    return staff
