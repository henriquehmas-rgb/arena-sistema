"""Rate-limit genérico via Redis (`INCR` + `EXPIRE`), usado por login,
cadastro e recuperação de senha (`app.routers.auth`).

Chave: ``{prefixo}:{identificador}``. Cada chamador escolhe seu próprio
`prefixo` (namespace) e `identificador` (o que está sendo limitado — ex.
`"{email}:{ip}"` pro login, só `ip` pra cadastro/recuperar) e pode ajustar
`limite`/`janela_segundos`; os defaults (`LIMITE`/`JANELA_SEGUNDOS`)
mantêm o comportamento original do login (5 tentativas erradas / 60s).

Falha aberto: se o Redis estiver inacessível, `excedeu_limite` loga o erro
e retorna `False` em vez de propagar a exceção. Trade-off deliberado:
disponibilidade do fluxo (login/cadastro/recuperação) importa mais do que
um rate-limit perfeito durante uma instabilidade do Redis — sem isso, uma
falha do Redis derrubaria esses fluxos inteiros com 500.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger("app.ratelimit")

LIMITE = 5
JANELA_SEGUNDOS = 60


def _chave(prefixo: str, identificador: str) -> str:
    return f"{prefixo}:{identificador}"


def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url)


async def excedeu_limite(
    identificador: str, *, prefixo: str = "login", limite: int = LIMITE
) -> bool:
    client = _redis()
    try:
        try:
            valor = await client.get(_chave(prefixo, identificador))
        except RedisError:
            # Falha aberto: Redis indisponível não deve derrubar o fluxo.
            logger.warning(
                "rate-limit (%s): falha ao consultar Redis, permitindo sem checagem",
                prefixo,
                exc_info=True,
            )
            return False
        return valor is not None and int(valor) >= limite
    finally:
        await client.aclose()


async def registrar_falha(
    identificador: str, *, prefixo: str = "login", janela_segundos: int = JANELA_SEGUNDOS
) -> int | None:
    """Incrementa o contador e retorna o novo total.

    Apesar do nome (herdado do uso original em login, onde só tentativas
    erradas incrementam), chamadores como cadastro/recuperar podem chamar
    isto a cada requisição — o que importa é limitar volume, não distinguir
    sucesso/falha. Se o Redis estiver inacessível, loga e retorna `None`
    (não propaga) — mesma política de falha aberto de `excedeu_limite`.
    """
    client = _redis()
    try:
        try:
            chave = _chave(prefixo, identificador)
            contagem = await client.incr(chave)
            if contagem == 1:
                await client.expire(chave, janela_segundos)
            return contagem
        except RedisError:
            logger.warning(
                "rate-limit (%s): falha ao registrar tentativa no Redis, ignorando",
                prefixo,
                exc_info=True,
            )
            return None
    finally:
        await client.aclose()


async def limpar(identificador: str, *, prefixo: str = "login") -> None:
    """Zera o contador (chamado em login bem-sucedido).

    Mesma política de falha aberto: se o Redis estiver indisponível aqui,
    um login com credenciais corretas não pode virar 500 só porque não deu
    para limpar o contador de tentativas.
    """
    client = _redis()
    try:
        try:
            await client.delete(_chave(prefixo, identificador))
        except RedisError:
            logger.warning(
                "rate-limit (%s): falha ao limpar contador no Redis, ignorando",
                prefixo,
                exc_info=True,
            )
    finally:
        await client.aclose()
