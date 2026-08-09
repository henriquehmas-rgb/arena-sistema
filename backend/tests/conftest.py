"""Fixtures compartilhadas de teste.

Requer um Postgres real acessível via env `TEST_DATABASE_URL` (ou, na
ausência dela, `DATABASE_URL`/`Settings.database_url`) — a extensão
`btree_gist` e as constraints EXCLUDE só existem em Postgres, então SQLite
não serve para a suíte completa.

No início da sessão de testes, roda `alembic upgrade head` contra esse banco.

NOTA sobre `cliente_logado` / `staff_admin_logado`: como as rotas de
autenticação (login) ainda não foram implementadas nesta task (T2 cobre
apenas modelos/migração), essas fixtures criam o registro diretamente no
banco e emitem um JWT "equivalente" ao que o serviço de auth deve gerar
(claims `sub`, `tipo`, `papel`, `exp`), assinado com `settings.jwt_secret`.
Se uma task futura definir um formato de claims diferente para o serviço de
auth real, estas fixtures devem ser atualizadas para usar esse formato.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from alembic.config import Config as AlembicConfig

from app.config import settings
from app.db import get_db
from app.main import app
from app.models.entities import Cliente, Staff
from app.models.enums import PapelStaff

BACKEND_DIR = Path(__file__).resolve().parents[1]

TEST_DATABASE_URL = (
    os.environ.get("TEST_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or settings.database_url
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _run_migrations() -> None:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _migrate_db():
    _run_migrations()
    yield


@pytest_asyncio.fixture
async def db():
    """Sessão de banco isolada por teste: tudo roda dentro de uma transação
    externa (com SAVEPOINTs para operações internas do teste/app) que é
    sempre desfeita (rollback) ao final — nenhum teste persiste dados."""
    engine = create_async_engine(TEST_DATABASE_URL)
    connection = await engine.connect()
    outer_trans = await connection.begin()

    session_factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = session_factory()

    try:
        yield session
    finally:
        await session.close()
        await outer_trans.rollback()
        await connection.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db: AsyncSession):
    """AsyncClient ASGI apontando para a app FastAPI, com `get_db`
    sobrescrito para usar a mesma sessão/transação da fixture `db`."""

    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


def _gerar_token(sub: int, tipo: str, papel: str | None = None) -> str:
    payload = {
        "sub": str(sub),
        "tipo": tipo,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_min),
    }
    if papel is not None:
        payload["papel"] = papel
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@pytest_asyncio.fixture
async def cliente_logado(db: AsyncSession):
    email = f"cliente-{uuid.uuid4().hex[:8]}@teste.com"
    cliente = Cliente(
        nome="Cliente Teste",
        email=email,
        senha_hash=pwd_context.hash("senha12345"),
        celular="65999990000",
    )
    db.add(cliente)
    await db.flush()

    token = _gerar_token(cliente.id, tipo="cliente")
    return {
        "cliente": cliente,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest_asyncio.fixture
async def staff_admin_logado(db: AsyncSession):
    email = f"staff-{uuid.uuid4().hex[:8]}@arenacacerense.com.br"
    staff = Staff(
        nome="Staff Admin Teste",
        email=email,
        senha_hash=pwd_context.hash("senha12345"),
        papel=PapelStaff.admin,
        ativo=True,
    )
    db.add(staff)
    await db.flush()

    token = _gerar_token(staff.id, tipo="staff", papel=PapelStaff.admin.value)
    return {
        "staff": staff,
        "headers": {"Authorization": f"Bearer {token}"},
    }
