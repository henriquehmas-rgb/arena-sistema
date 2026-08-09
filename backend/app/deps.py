"""Dependências FastAPI compartilhadas entre routers.

`get_db` vem de `app.db` (reusado aqui em vez de duplicado — os testes em
`tests/conftest.py` fazem `app.dependency_overrides[get_db]` usando esse
mesmo objeto de função).

Task T4: `get_cliente_atual`, `get_staff_atual` e `require_admin` — leem o
`Authorization: Bearer <token>`, decodificam via `services.auth` e carregam
a entidade correspondente do banco.
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.entities import Cliente, Staff
from app.models.enums import PapelStaff
from app.services import auth as auth_service

__all__ = [
    "get_db",
    "get_cliente_atual",
    "get_staff_atual",
    "require_admin",
]

_bearer = HTTPBearer(auto_error=False)


def _decodificar(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="nao_autenticado"
        )
    try:
        return auth_service.decodificar_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token_invalido"
        ) from None


async def get_cliente_atual(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Cliente:
    payload = _decodificar(credentials)
    if payload.get("tipo") != "cliente":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token_invalido"
        )
    try:
        cliente_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token_invalido"
        ) from None

    cliente = await db.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="cliente_nao_encontrado"
        )
    return cliente


async def get_staff_atual(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Staff:
    payload = _decodificar(credentials)
    if payload.get("tipo") != "staff":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token_invalido"
        )
    try:
        staff_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token_invalido"
        ) from None

    staff = await db.get(Staff, staff_id)
    if staff is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="staff_nao_encontrado"
        )
    if not staff.ativo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="staff_inativo"
        )
    return staff


async def require_admin(staff: Staff = Depends(get_staff_atual)) -> Staff:
    if staff.papel != PapelStaff.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="requer_admin"
        )
    return staff
