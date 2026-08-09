"""Testes de `app.services.reservas.expirar_pendentes` (Task T6, Step 1) e
do registro do job periódico em `app.services.jobs`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models.entities import Recurso, Reserva
from app.models.enums import ReservaOrigem, ReservaStatus, TipoRecurso
from app.services import reservas as reservas_service


async def criar_recurso(db, nome: str = "Campo Expiracao") -> Recurso:
    recurso = Recurso(nome=nome, tipo=TipoRecurso.campo, ativo=True, ordem=1)
    db.add(recurso)
    await db.flush()
    return recurso


async def test_expirar_pendentes_muda_so_as_vencidas(db):
    recurso = await criar_recurso(db)
    agora = datetime.now(timezone.utc)

    # Vencida: criada há mais tempo que o TTL -> deve expirar.
    vencida = Reserva(
        recurso_id=recurso.id,
        inicio=agora + timedelta(days=1),
        fim=agora + timedelta(days=1, hours=1),
        status=ReservaStatus.pendente_pagamento,
        origem=ReservaOrigem.online,
        valor_centavos=1000,
        criado_em=agora - timedelta(minutes=settings.reserva_ttl_min + 1),
    )
    # Ainda dentro do TTL -> não deve expirar.
    recente = Reserva(
        recurso_id=recurso.id,
        inicio=agora + timedelta(days=1, hours=2),
        fim=agora + timedelta(days=1, hours=3),
        status=ReservaStatus.pendente_pagamento,
        origem=ReservaOrigem.online,
        valor_centavos=1000,
        criado_em=agora - timedelta(minutes=1),
    )
    # Já confirmada (nunca deve mudar, mesmo "vencida" por criado_em) —
    # `expirar_pendentes` só olha para `pendente_pagamento`.
    confirmada_antiga = Reserva(
        recurso_id=recurso.id,
        inicio=agora + timedelta(days=1, hours=4),
        fim=agora + timedelta(days=1, hours=5),
        status=ReservaStatus.confirmada,
        origem=ReservaOrigem.balcao,
        valor_centavos=1000,
        criado_em=agora - timedelta(minutes=settings.reserva_ttl_min + 1),
    )
    db.add_all([vencida, recente, confirmada_antiga])
    await db.flush()

    total_expiradas = await reservas_service.expirar_pendentes(db)

    assert total_expiradas == 1
    await db.refresh(vencida)
    await db.refresh(recente)
    await db.refresh(confirmada_antiga)
    assert vencida.status == ReservaStatus.expirada
    assert recente.status == ReservaStatus.pendente_pagamento
    assert confirmada_antiga.status == ReservaStatus.confirmada


async def test_expirar_pendentes_sem_vencidas_retorna_zero(db):
    recurso = await criar_recurso(db, nome="Campo Expiracao Zero")
    agora = datetime.now(timezone.utc)

    reserva = Reserva(
        recurso_id=recurso.id,
        inicio=agora + timedelta(days=1),
        fim=agora + timedelta(days=1, hours=1),
        status=ReservaStatus.pendente_pagamento,
        origem=ReservaOrigem.online,
        valor_centavos=1000,
        criado_em=agora,
    )
    db.add(reserva)
    await db.flush()

    assert await reservas_service.expirar_pendentes(db) == 0


def test_job_expirar_reservas_registrado():
    """`jobs.iniciar` deve agendar o job `expirar_reservas` a cada 60s,
    aditivamente ao que outras tasks (T9) já registraram — verifica isso
    sem precisar levantar a app inteira (`AsyncIOScheduler` isolado)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    from app.services.jobs import _registrar_expirar_reservas

    scheduler = AsyncIOScheduler()
    _registrar_expirar_reservas(scheduler)

    job = scheduler.get_job("expirar_reservas")
    assert job is not None
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == 60
