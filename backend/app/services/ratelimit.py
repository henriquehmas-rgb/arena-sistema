"""Rate-limit de tentativas de login, via Redis (`INCR` + `EXPIRE`).

Chave: ``login:{email}:{ip}``. Limite: `LIMITE` tentativas erradas em
`JANELA_SEGUNDOS` segundos — a tentativa seguinte ao limite ser atingido
deve ser rejeitada (429) pelo chamador (`app.routers.auth`) antes mesmo de
verificar a senha.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.config import settings

LIMITE = 5
JANELA_SEGUNDOS = 60


def _chave(email: str, ip: str) -> str:
    return f"login:{email}:{ip}"


def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url)


async def excedeu_limite(email: str, ip: str) -> bool:
    client = _redis()
    try:
        valor = await client.get(_chave(email, ip))
        return valor is not None and int(valor) >= LIMITE
    finally:
        await client.aclose()


async def registrar_falha(email: str, ip: str) -> int:
    """Incrementa o contador de tentativas erradas e retorna o novo total."""
    client = _redis()
    try:
        chave = _chave(email, ip)
        contagem = await client.incr(chave)
        if contagem == 1:
            await client.expire(chave, JANELA_SEGUNDOS)
        return contagem
    finally:
        await client.aclose()


async def limpar(email: str, ip: str) -> None:
    """Zera o contador (chamado em login bem-sucedido)."""
    client = _redis()
    try:
        await client.delete(_chave(email, ip))
    finally:
        await client.aclose()
