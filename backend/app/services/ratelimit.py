"""Rate-limit de tentativas de login, via Redis (`INCR` + `EXPIRE`).

Chave: ``login:{email}:{ip}``. Limite: `LIMITE` tentativas erradas em
`JANELA_SEGUNDOS` segundos — a tentativa seguinte ao limite ser atingido
deve ser rejeitada (429) pelo chamador (`app.routers.auth`) antes mesmo de
verificar a senha.

Falha aberto: se o Redis estiver inacessível, `excedeu_limite` loga o erro
e retorna `False` em vez de propagar a exceção. Trade-off deliberado:
disponibilidade do login (autenticação inteira) importa mais do que um
rate-limit perfeito durante uma instabilidade do Redis — sem isso, uma
falha do Redis derrubaria login de cliente e staff com 500.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger("app.ratelimit")

LIMITE = 5
JANELA_SEGUNDOS = 60


def _chave(email: str, ip: str) -> str:
    return f"login:{email}:{ip}"


def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url)


async def excedeu_limite(email: str, ip: str) -> bool:
    client = _redis()
    try:
        try:
            valor = await client.get(_chave(email, ip))
        except RedisError:
            # Falha aberto: Redis indisponível não deve derrubar login.
            logger.warning(
                "rate-limit: falha ao consultar Redis, permitindo login sem checagem",
                exc_info=True,
            )
            return False
        return valor is not None and int(valor) >= LIMITE
    finally:
        await client.aclose()


async def registrar_falha(email: str, ip: str) -> int | None:
    """Incrementa o contador de tentativas erradas e retorna o novo total.

    Se o Redis estiver inacessível, loga e retorna `None` (não propaga) —
    consistente com a política de falha aberto de `excedeu_limite`: perder
    o registro de uma tentativa errada durante uma instabilidade do Redis é
    aceitável, derrubar o fluxo de login não é.
    """
    client = _redis()
    try:
        try:
            chave = _chave(email, ip)
            contagem = await client.incr(chave)
            if contagem == 1:
                await client.expire(chave, JANELA_SEGUNDOS)
            return contagem
        except RedisError:
            logger.warning(
                "rate-limit: falha ao registrar tentativa no Redis, ignorando",
                exc_info=True,
            )
            return None
    finally:
        await client.aclose()


async def limpar(email: str, ip: str) -> None:
    """Zera o contador (chamado em login bem-sucedido).

    Mesma política de falha aberto: se o Redis estiver indisponível aqui,
    um login com credenciais corretas não pode virar 500 só porque não deu
    para limpar o contador de tentativas.
    """
    client = _redis()
    try:
        try:
            await client.delete(_chave(email, ip))
        except RedisError:
            logger.warning(
                "rate-limit: falha ao limpar contador no Redis, ignorando",
                exc_info=True,
            )
    finally:
        await client.aclose()
