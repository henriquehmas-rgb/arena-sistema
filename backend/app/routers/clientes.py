"""Rotas de clientes: busca e cadastro pela equipe (staff, clientes de
balcão sem senha) + auto-atendimento (`/me`) para o próprio cliente logado
ver/editar seus dados de cadastro."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_cliente_atual, get_db, get_staff_atual
from app.models.entities import Cliente, Staff
from app.schemas.clientes import ClienteAdminCriar, ClienteMeAtualizar, ClienteOut
from app.services import auditoria

router = APIRouter()


@router.get("/me", response_model=ClienteOut)
async def meu_cadastro(cliente: Cliente = Depends(get_cliente_atual)) -> Cliente:
    return cliente


@router.put("/me", response_model=ClienteOut)
async def atualizar_meu_cadastro(
    dados: ClienteMeAtualizar,
    cliente: Cliente = Depends(get_cliente_atual),
    db: AsyncSession = Depends(get_db),
) -> Cliente:
    cliente.nome = dados.nome
    cliente.celular = dados.celular
    await db.flush()
    return cliente


@router.get("", response_model=list[ClienteOut])
async def buscar_clientes(
    busca: str | None = Query(default=None, description="Nome, e-mail ou celular"),
    db: AsyncSession = Depends(get_db),
    _staff: Staff = Depends(get_staff_atual),
) -> list[Cliente]:
    stmt = select(Cliente).order_by(Cliente.nome)
    if busca:
        padrao = f"%{busca}%"
        stmt = stmt.where(
            or_(
                Cliente.nome.ilike(padrao),
                Cliente.email.ilike(padrao),
                Cliente.celular.ilike(padrao),
            )
        )
    resultado = await db.execute(stmt)
    return list(resultado.scalars().all())


@router.post("", response_model=ClienteOut, status_code=status.HTTP_201_CREATED)
async def criar_cliente(
    dados: ClienteAdminCriar,
    db: AsyncSession = Depends(get_db),
    staff: Staff = Depends(get_staff_atual),
) -> Cliente:
    existente = await db.scalar(select(Cliente).where(Cliente.email == dados.email))
    if existente is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email_ja_cadastrado")

    cliente = Cliente(
        nome=dados.nome,
        email=dados.email,
        celular=dados.celular,
        cpf=dados.cpf,
        senha_hash=None,
    )
    db.add(cliente)
    await db.flush()

    await auditoria.registrar(
        db,
        staff_id=staff.id,
        acao="criar",
        entidade="cliente",
        entidade_id=cliente.id,
        dados={"nome": cliente.nome, "email": cliente.email},
    )
    return cliente
