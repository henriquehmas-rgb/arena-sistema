"""Serviço de autenticação: hashing de senha (bcrypt via passlib) e emissão
/validação de JWT (PyJWT, HS256).

Formato de claims (deliberadamente simples, ver brief da Task T4):
``{"sub": "<id>", "tipo": "cliente"|"staff", "exp": <timestamp>}``.
Tokens de acesso e de refresh usam o mesmo formato de claims, diferindo
apenas na validade (`settings.jwt_access_min` vs `settings.jwt_refresh_dias`)
— o token de refresh só circula via cookie httpOnly, nunca no corpo da
resposta. Tokens de redefinição de senha usam ``tipo="redefinir_senha"``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.config import settings

ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_senha(senha: str) -> str:
    return pwd_context.hash(senha)


def verificar_senha(senha: str, senha_hash: str | None) -> bool:
    if not senha_hash:
        return False
    return pwd_context.verify(senha, senha_hash)


def _criar_token(sub: str, tipo: str, validade: timedelta) -> str:
    payload = {
        "sub": sub,
        "tipo": tipo,
        "exp": datetime.now(timezone.utc) + validade,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def criar_access_token(sub: str, tipo: str) -> str:
    return _criar_token(sub, tipo, timedelta(minutes=settings.jwt_access_min))


def criar_refresh_token(sub: str, tipo: str) -> str:
    return _criar_token(sub, tipo, timedelta(days=settings.jwt_refresh_dias))


def criar_tokens(sub: str, tipo: str) -> tuple[str, str]:
    """Gera (access_token, refresh_token) para o sujeito `sub` (id do
    cliente ou staff, como string) do `tipo` indicado ('cliente' ou
    'staff')."""
    return criar_access_token(sub, tipo), criar_refresh_token(sub, tipo)


def criar_token_redefinicao(cliente_id: int) -> str:
    """Token de uso único (na prática, TTL curto) para o fluxo de
    recuperação/redefinição de senha."""
    return _criar_token(str(cliente_id), "redefinir_senha", timedelta(hours=1))


def decodificar_token(token: str) -> dict:
    """Decodifica e valida assinatura/expiração. Levanta
    `jwt.PyJWTError` (ou subclasses, ex: `jwt.ExpiredSignatureError`) se o
    token for inválido — quem chama deve tratar e converter em 401/400."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
