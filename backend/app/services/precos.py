"""Cálculo de preço de reserva por faixa horária (`FaixaPreco`).

Preço é sempre recalculado no backend (Global Constraints) — nunca confiar
em valor vindo do cliente. `preco_para` resolve a faixa cujo `dias_semana`
contém o dia da semana local do início da reserva e cujo intervalo
[hora_inicio, hora_fim) cobre o horário local pedido.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entities import FaixaPreco, Recurso


class PrecoNaoConfigurado(Exception):
    """Levantada quando não existe `FaixaPreco` cobrindo o horário pedido."""


async def faixas_do_recurso(db: AsyncSession, recurso_id: int) -> list[FaixaPreco]:
    """Busca todas as `FaixaPreco` cadastradas pro `recurso_id`.

    Extraído de `preco_para` pra permitir buscar as faixas UMA vez e reusar
    o resultado em múltiplos cálculos de preço (ver `slots_do_dia`, que
    calcula o preço de cada slot do dia sem repetir essa query por slot).
    """
    resultado = await db.execute(
        select(FaixaPreco).where(FaixaPreco.recurso_id == recurso_id)
    )
    return list(resultado.scalars().all())


def preco_da_lista(
    faixas: list[FaixaPreco], recurso_id: int, inicio_local: datetime
) -> int:
    """Resolve o preço em centavos dado uma lista de `faixas` já carregada e
    o início *local* (`settings.tz_local`) da reserva.

    Função pura (sem I/O) — não faz query. `preco_para` a usa depois de
    buscar as faixas do banco; `slots_do_dia` busca as faixas uma vez por
    chamada e chama esta função pra cada slot, evitando N+1 query.
    """
    dia_semana = inicio_local.weekday()  # 0=segunda .. 6=domingo
    hora = inicio_local.hour

    for faixa in faixas:
        if dia_semana in faixa.dias_semana and faixa.hora_inicio <= hora < faixa.hora_fim:
            return faixa.preco_centavos

    raise PrecoNaoConfigurado(
        f"nenhuma faixa de preço cobre recurso_id={recurso_id} "
        f"dia_semana={dia_semana} hora={hora}"
    )


async def preco_para(
    db: AsyncSession, recurso: Recurso, inicio: datetime, fim: datetime
) -> int:
    """Retorna o preço em centavos da reserva `[inicio, fim)` no `recurso`.

    `inicio`/`fim` devem ser timestamps aware (UTC, como armazenado/comparado
    no banco). A faixa é resolvida pelo dia da semana e hora *local*
    (`settings.tz_local`) do início da reserva.
    """
    tz = ZoneInfo(settings.tz_local)
    inicio_local = inicio.astimezone(tz)

    faixas = await faixas_do_recurso(db, recurso.id)
    return preco_da_lista(faixas, recurso.id, inicio_local)
