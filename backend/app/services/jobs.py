"""Scheduler de jobs em background (APScheduler).

Placeholder da Task T3 (Wave 0): as tasks T6/T8/T9 vão registrar jobs reais
aqui (ex.: expiração de reservas pendentes, cobrança de assinaturas,
lembretes por e-mail).

`iniciar(app)` é o único ponto de entrada chamado por `app/main.py` no
startup. Cada task que precisa de um job periódico adiciona sua própria
função `_registrar_<job>(scheduler)` (que só faz `scheduler.add_job(...)`)
e uma chamada correspondente dentro de `iniciar()` — isso é aditivo por
construção: cada task mexe numa linha nova dentro de `iniciar()` mais uma
função nova no módulo, então adições em paralelo/sequência de T6/T8 não
colidem estruturalmente com o que outras tasks já registraram aqui.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings

logger = logging.getLogger("app.jobs")


def iniciar(app) -> None:
    scheduler = AsyncIOScheduler(timezone=settings.tz_local)

    _registrar_materializar_assinaturas(scheduler)  # Task T9
    _registrar_expirar_reservas(scheduler)  # Task T6

    scheduler.start()
    app.state.scheduler = scheduler


def _registrar_materializar_assinaturas(scheduler: AsyncIOScheduler) -> None:
    """Task T9: job diário às 03:00 (fuso `settings.tz_local`) que roda
    `app.services.assinaturas.materializar` para gerar as próximas reservas
    `confirmada`/`mensalista` das assinaturas ativas. Idempotente — rodar
    de novo no mesmo dia (ex.: reinício da app) não duplica reservas."""
    # Imports locais (não no topo do módulo) para não criar um import-time
    # hard-dependency de `app/services/jobs.py` (compartilhado entre várias
    # tasks) em `app.services.assinaturas`/`app.db` antes de serem
    # necessários — mantém o registro de cada job isolado dos demais.
    from app.db import AsyncSessionLocal
    from app.services.assinaturas import materializar

    async def _job() -> None:
        async with AsyncSessionLocal() as db:
            try:
                criadas = await materializar(db)
                await db.commit()
                logger.info("job materializar_assinaturas: %s reserva(s) criada(s)", criadas)
            except Exception:
                await db.rollback()
                logger.exception("job materializar_assinaturas falhou")

    scheduler.add_job(
        _job,
        CronTrigger(hour=3, minute=0),
        id="materializar_assinaturas",
        replace_existing=True,
    )


def _registrar_expirar_reservas(scheduler: AsyncIOScheduler) -> None:
    """Task T6: job a cada 60s que roda `app.services.reservas.expirar_pendentes`
    para mudar reservas `pendente_pagamento` cujo TTL (`settings.reserva_ttl_min`
    após `criado_em`) já venceu para `expirada` — libera o slot pra outra
    reserva. Sessão própria por execução (não reusa uma sessão global),
    mesmo padrão de `_registrar_materializar_assinaturas` acima."""
    from app.db import AsyncSessionLocal
    from app.services.reservas import expirar_pendentes

    async def _job() -> None:
        async with AsyncSessionLocal() as db:
            try:
                expiradas = await expirar_pendentes(db)
                await db.commit()
                if expiradas:
                    logger.info("job expirar_reservas: %s reserva(s) expirada(s)", expiradas)
            except Exception:
                await db.rollback()
                logger.exception("job expirar_reservas falhou")

    scheduler.add_job(
        _job,
        IntervalTrigger(seconds=60),
        id="expirar_reservas",
        replace_existing=True,
    )
