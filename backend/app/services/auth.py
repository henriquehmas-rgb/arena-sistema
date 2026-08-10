"""Serviço de autenticação: hashing de senha (bcrypt via passlib) e emissão
/validação de JWT (PyJWT, HS256).

Formato de claims: ``{"sub": "<id>", "tipo": "cliente"|"staff", "escopo":
"access"|"refresh", "iat": <timestamp>, "exp": <timestamp>}``. Tokens de
acesso e de refresh diferem tanto na validade (`settings.jwt_access_min` vs
`settings.jwt_refresh_dias`) quanto no claim `escopo` — isso evita que um
access token vazado (mais exposto que o cookie httpOnly do refresh) seja
reaproveitado como refresh token para gerar novos access tokens
indefinidamente. `deps.py` exige `escopo == "access"` para autenticar
requisições normais; `POST /auth/refresh` exige `escopo == "refresh"`.
O token de refresh só circula via cookie httpOnly, nunca no corpo da
resposta. Tokens de redefinição de senha usam ``tipo="redefinir_senha"``
(sem `escopo`, mecanismo à parte) e carregam um `jti` (ver
`token_redefinicao_ja_usado`/`marcar_token_redefinicao_usado`).

Achados na revisão final de branch, corrigidos aqui:
- Um link de recuperação de senha interceptado funcionava repetidamente
  dentro da 1h de validade (`jti` + marcador single-use no Redis fecha
  isso — replay bloqueado já na 2ª tentativa).
- Redefinir a senha não invalidava os refresh tokens já emitidos: quem já
  tinha uma sessão aberta continuava com ela válida mesmo depois da vítima
  "recuperar" a conta. `invalidar_sessoes`/`sessoes_invalidas_apos` guardam
  no Redis o instante da última troca de senha; `POST /auth/refresh`
  rejeita qualquer refresh token com `iat` anterior a esse instante.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import redis.asyncio as aioredis
from passlib.context import CryptContext
from redis.exceptions import RedisError

from app.config import settings

ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def _ttl_invalidacao_segundos() -> int:
    """TTL do marcador "senha trocada em" no Redis: precisa cobrir o maior
    TTL de token que essa troca deve invalidar (refresh token,
    `jwt_refresh_dias`)."""
    return settings.jwt_refresh_dias * 24 * 60 * 60


def hash_senha(senha: str) -> str:
    return pwd_context.hash(senha)


def verificar_senha(senha: str, senha_hash: str | None) -> bool:
    if not senha_hash:
        return False
    return pwd_context.verify(senha, senha_hash)


def _criar_token(
    sub: str, tipo: str, validade: timedelta, escopo: str | None = None, jti: str | None = None
) -> str:
    agora = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "tipo": tipo,
        "iat": agora,
        "exp": agora + validade,
    }
    if escopo is not None:
        payload["escopo"] = escopo
    if jti is not None:
        payload["jti"] = jti
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def criar_access_token(sub: str, tipo: str) -> str:
    return _criar_token(
        sub, tipo, timedelta(minutes=settings.jwt_access_min), escopo="access"
    )


def criar_refresh_token(sub: str, tipo: str) -> str:
    return _criar_token(
        sub, tipo, timedelta(days=settings.jwt_refresh_dias), escopo="refresh"
    )


def criar_tokens(sub: str, tipo: str) -> tuple[str, str]:
    """Gera (access_token, refresh_token) para o sujeito `sub` (id do
    cliente ou staff, como string) do `tipo` indicado ('cliente' ou
    'staff')."""
    return criar_access_token(sub, tipo), criar_refresh_token(sub, tipo)


def criar_token_redefinicao(cliente_id: int) -> str:
    """Token de redefinição de senha, TTL curto (1h) + `jti` único — o
    `jti` é o que permite ao chamador (`routers.auth.redefinir_senha`)
    recusar um reuso do mesmo link (`marcar_token_redefinicao_usado`)."""
    return _criar_token(
        str(cliente_id), "redefinir_senha", timedelta(hours=1), jti=uuid.uuid4().hex
    )


def decodificar_token(token: str) -> dict:
    """Decodifica e valida assinatura/expiração. Levanta
    `jwt.PyJWTError` (ou subclasses, ex: `jwt.ExpiredSignatureError`) se o
    token for inválido — quem chama deve tratar e converter em 401/400."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])


def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url)


async def marcar_token_redefinicao_usado(jti: str) -> bool:
    """`True` se este `jti` ainda não tinha sido usado (e acabou de ser
    marcado); `False` se já tinha sido — nesse caso o chamador deve recusar
    a redefinição. Falha aberto (Redis indisponível): permite o uso único
    passar em vez de derrubar o fluxo de redefinição de senha por causa de
    uma instabilidade de infra — mesma política de `services.ratelimit`."""
    client = _redis()
    try:
        try:
            # SET NX: só grava (e retorna True) se a chave ainda não existir.
            gravou = await client.set(f"redefinicao:usado:{jti}", "1", nx=True, ex=3600)
            return bool(gravou)
        except RedisError:
            return True
    finally:
        await client.aclose()


async def invalidar_sessoes(tipo: str, sub: str) -> None:
    """Registra "agora" como o instante mínimo de emissão pra refresh
    tokens de `sub` continuarem válidos — chamado ao redefinir senha, pra
    que sessões (refresh tokens) emitidas antes da redefinição parem de
    funcionar. Falha aberto: se o Redis estiver indisponível, loga e segue
    (não bloqueia a redefinição de senha em si, que já aconteceu no banco).

    Guardado com precisão de segundo inteiro (não fração), igual ao `iat`
    de um JWT: o PyJWT trunca `datetime` pra segundo inteiro ao codificar
    `iat`/`exp`. Guardar aqui com microssegundos e comparar depois com um
    `iat` truncado (`payload.get("iat") <= invalido_apos`) rejeitava até
    tokens novos, emitidos *depois* da invalidação mas no mesmo segundo —
    achado numa corrida de teste, não hipotético."""
    client = _redis()
    try:
        try:
            await client.set(
                f"sessoes_invalidas_apos:{tipo}:{sub}",
                str(int(datetime.now(timezone.utc).timestamp())),
                ex=_ttl_invalidacao_segundos(),
            )
        except RedisError:
            pass
    finally:
        await client.aclose()


async def sessoes_invalidas_apos(tipo: str, sub: str) -> int | None:
    """Timestamp Unix (segundo inteiro) da última invalidação de sessão pra
    `sub`, ou `None` se nunca houve uma (ou o Redis está inacessível —
    falha aberto: não invalidar nada é mais seguro do que rejeitar todo
    refresh por causa de uma instabilidade de infra)."""
    client = _redis()
    try:
        try:
            valor = await client.get(f"sessoes_invalidas_apos:{tipo}:{sub}")
        except RedisError:
            return None
        return int(valor) if valor is not None else None
    finally:
        await client.aclose()
