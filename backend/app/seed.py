"""Seed idempotente de dados iniciais (recursos, staff admin, faixas de preço).

Uso: `python -m app.seed` (usa app.db.AsyncSessionLocal / settings.database_url).
Pode ser executado múltiplas vezes sem duplicar registros: busca por
nome/email antes de inserir.
"""
import asyncio
import os

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.models.entities import FaixaPreco, Recurso, Staff
from app.models.enums import PapelStaff, TipoRecurso

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ADMIN_EMAIL = "admin@arenacacerense.com.br"

# dias da semana: 0=segunda .. 6=domingo (ISO-like, seg=0)
SEG_A_SEX = [0, 1, 2, 3, 4]
SAB_DOM = [5, 6]


async def _get_or_create_recurso(db: AsyncSession, nome: str, tipo: TipoRecurso, ordem: int) -> Recurso:
    result = await db.execute(select(Recurso).where(Recurso.nome == nome))
    recurso = result.scalar_one_or_none()
    if recurso is None:
        recurso = Recurso(nome=nome, tipo=tipo, ativo=True, ordem=ordem)
        db.add(recurso)
        await db.flush()
    return recurso


async def _get_or_create_faixa(
    db: AsyncSession,
    recurso: Recurso,
    dias_semana: list[int],
    hora_inicio: int,
    hora_fim: int,
    preco_centavos: int,
) -> None:
    result = await db.execute(
        select(FaixaPreco).where(
            FaixaPreco.recurso_id == recurso.id,
            FaixaPreco.dias_semana == dias_semana,
            FaixaPreco.hora_inicio == hora_inicio,
            FaixaPreco.hora_fim == hora_fim,
        )
    )
    faixa = result.scalar_one_or_none()
    if faixa is None:
        db.add(
            FaixaPreco(
                recurso_id=recurso.id,
                dias_semana=dias_semana,
                hora_inicio=hora_inicio,
                hora_fim=hora_fim,
                preco_centavos=preco_centavos,
            )
        )


async def _get_or_create_admin(db: AsyncSession) -> None:
    result = await db.execute(select(Staff).where(Staff.email == ADMIN_EMAIL))
    staff = result.scalar_one_or_none()
    if staff is None:
        senha = os.environ.get("SEED_ADMIN_SENHA", "trocar123")
        db.add(
            Staff(
                nome="Administrador",
                email=ADMIN_EMAIL,
                senha_hash=pwd_context.hash(senha),
                papel=PapelStaff.admin,
                ativo=True,
            )
        )


async def seed(db: AsyncSession) -> None:
    campo1 = await _get_or_create_recurso(db, "Campo 1", TipoRecurso.campo, ordem=1)
    campo2 = await _get_or_create_recurso(db, "Campo 2", TipoRecurso.campo, ordem=2)
    quiosque = await _get_or_create_recurso(db, "Quiosque", TipoRecurso.quiosque, ordem=3)

    for campo in (campo1, campo2):
        await _get_or_create_faixa(db, campo, SEG_A_SEX, 8, 18, 15000)
        await _get_or_create_faixa(db, campo, SEG_A_SEX, 18, 23, 18000)
        await _get_or_create_faixa(db, campo, SAB_DOM, 8, 23, 18000)

    await _get_or_create_faixa(db, quiosque, SEG_A_SEX + SAB_DOM, 8, 22, 25000)

    await _get_or_create_admin(db)

    await db.commit()


async def main() -> None:
    async with AsyncSessionLocal() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
