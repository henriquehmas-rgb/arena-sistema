"""Geração de slots de disponibilidade (campo/quiosque) e checagem de
sobreposição usada tanto pela rota `GET /disponibilidade` quanto por
`POST /reservas` (fora do escopo desta task, mas consumido por ela).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entities import Bloqueio, Recurso, Reserva
from app.models.enums import ReservaStatus, TipoRecurso
from app.services.precos import PrecoNaoConfigurado, faixas_do_recurso, preco_da_lista

# Campo: slots de 1h fechada, horas cheias 08→22 (último início 22h, fim 23h).
CAMPO_HORA_INICIO = 8
CAMPO_ULTIMA_HORA_INICIO = 22

# Quiosque: períodos fixos (nome não faz parte do Slot, só da geração).
PERIODOS_QUIOSQUE = [(8, 12), (13, 17), (18, 22), (8, 22)]


@dataclass
class Slot:
    inicio: datetime
    fim: datetime
    preco_centavos: int
    livre: bool


def _horarios_do_recurso(recurso: Recurso) -> list[tuple[int, int]]:
    if recurso.tipo == TipoRecurso.campo:
        return [
            (h, h + 1)
            for h in range(CAMPO_HORA_INICIO, CAMPO_ULTIMA_HORA_INICIO + 1)
        ]
    return PERIODOS_QUIOSQUE


async def slots_do_dia(db: AsyncSession, recurso: Recurso, data_local: date) -> list[Slot]:
    """Gera os slots do `recurso` no `data_local` (data no fuso local).

    `livre=False` quando o slot intersecta reserva pendente/confirmada,
    bloqueio, ou já passou (`inicio < agora`).
    """
    tz = ZoneInfo(settings.tz_local)
    agora = datetime.now(timezone.utc)

    dia_inicio_local = datetime.combine(data_local, time(0, 0), tzinfo=tz)
    dia_fim_local = dia_inicio_local + timedelta(days=1)
    dia_inicio_utc = dia_inicio_local.astimezone(timezone.utc)
    dia_fim_utc = dia_fim_local.astimezone(timezone.utc)

    reservas = (
        await db.execute(
            select(Reserva).where(
                Reserva.recurso_id == recurso.id,
                Reserva.status.in_(
                    [ReservaStatus.pendente_pagamento, ReservaStatus.confirmada]
                ),
                Reserva.inicio < dia_fim_utc,
                Reserva.fim > dia_inicio_utc,
            )
        )
    ).scalars().all()

    bloqueios = (
        await db.execute(
            select(Bloqueio).where(
                Bloqueio.recurso_id == recurso.id,
                Bloqueio.inicio < dia_fim_utc,
                Bloqueio.fim > dia_inicio_utc,
            )
        )
    ).scalars().all()

    # Busca as faixas de preço UMA vez por chamada (não uma vez por slot) —
    # evita N+1 query de `FaixaPreco` ao gerar os ~15 slots de um dia de
    # campo. `preco_da_lista` (função pura) resolve o preço de cada slot
    # reusando essa mesma lista.
    faixas = await faixas_do_recurso(db, recurso.id)

    slots: list[Slot] = []
    for hora_inicio, hora_fim in _horarios_do_recurso(recurso):
        inicio_local = datetime.combine(data_local, time(hora_inicio, 0), tzinfo=tz)
        fim_local = datetime.combine(data_local, time(hora_fim, 0), tzinfo=tz)
        inicio_utc = inicio_local.astimezone(timezone.utc)
        fim_utc = fim_local.astimezone(timezone.utc)

        ocupado = any(r.inicio < fim_utc and r.fim > inicio_utc for r in reservas)
        bloqueado = any(b.inicio < fim_utc and b.fim > inicio_utc for b in bloqueios)
        passou = inicio_utc < agora

        try:
            preco = preco_da_lista(faixas, recurso.id, inicio_local)
        except PrecoNaoConfigurado:
            # Decisão própria (não especificada no brief): sem faixa de
            # preço cadastrada pro horário, o slot aparece com preço 0 em
            # vez de quebrar a listagem inteira do dia — evita que um
            # buraco de configuração de preços derrube `GET /disponibilidade`.
            preco = 0

        slots.append(
            Slot(
                inicio=inicio_utc,
                fim=fim_utc,
                preco_centavos=preco,
                livre=not (ocupado or bloqueado or passou),
            )
        )

    return slots


async def esta_livre(
    db: AsyncSession, recurso_id: int, inicio: datetime, fim: datetime
) -> bool:
    """True se `[inicio, fim)` não intersecta reserva pendente/confirmada,
    bloqueio, nem já passou."""
    agora = datetime.now(timezone.utc)
    if inicio < agora:
        return False

    reserva_conflito = (
        await db.execute(
            select(Reserva.id)
            .where(
                Reserva.recurso_id == recurso_id,
                Reserva.status.in_(
                    [ReservaStatus.pendente_pagamento, ReservaStatus.confirmada]
                ),
                Reserva.inicio < fim,
                Reserva.fim > inicio,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if reserva_conflito is not None:
        return False

    bloqueio_conflito = (
        await db.execute(
            select(Bloqueio.id)
            .where(
                Bloqueio.recurso_id == recurso_id,
                Bloqueio.inicio < fim,
                Bloqueio.fim > inicio,
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    return bloqueio_conflito is None
