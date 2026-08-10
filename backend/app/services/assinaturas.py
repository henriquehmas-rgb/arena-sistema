"""Assinaturas (mensalistas): criação (+ subscription na Pagar.me),
materialização semanal de reservas `mensalista`, processamento de eventos de
fatura vindos do webhook da Pagar.me, e pausar/reativar/cancelar.

Dependência cruzada com a Task T7 (`app.services.pagarme`, rodando em
paralelo): importamos `get_pagarme` com um fallback defensivo — se o módulo
ainda não existir quando este arquivo for carregado, um stub que levanta
`RuntimeError` toma o lugar só para não quebrar o import de
`app.main`/`app.routers.assinaturas` (e, por consequência, a suíte inteira de
testes via `tests/conftest.py`). Assim que `app/services/pagarme.py` existir
com a assinatura combinada (`PagarmeClient.criar_subscription` /
`.cancelar_subscription` / `get_pagarme()`), o import real passa a funcionar
sem qualquer mudança neste arquivo. Em `tests/test_assinaturas.py`, os testes
usam `monkeypatch.setattr(assinaturas, "get_pagarme", ...)` para substituir
esse nome pelo fake local — funciona tanto com o stub quanto com o real,
já que o teste nunca depende do que `get_pagarme` resolve por padrão.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entities import Assinatura, Bloqueio, Cliente, Recurso, Reserva, Staff
from app.models.enums import AssinaturaStatus, ReservaOrigem, ReservaStatus
from app.schemas.assinaturas import AssinaturaCriar
from app.services import email, email_templates

try:
    from app.services.pagarme import get_pagarme
except ImportError:  # pragma: no cover - só ocorre enquanto a Task T7 (em
    # paralelo) ainda não criou app/services/pagarme.py.
    def get_pagarme():  # type: ignore[misc]
        raise RuntimeError(
            "app.services.pagarme ainda não está disponível (Task T7 em "
            "andamento em paralelo). Em produção isso se resolve assim que "
            "aquele módulo existir; em teste, faça monkeypatch de "
            "app.services.assinaturas.get_pagarme com um fake."
        )


logger = logging.getLogger("app.assinaturas")

# Após esta quantidade de falhas de fatura *consecutivas*, a assinatura vira
# `inadimplente` (e `materializar` para de criar reservas novas para ela,
# pois só considera assinaturas `ativa`).
FALHAS_LIMITE = 2

# Ciclo de cobrança "padrão" quando não há mais informação disponível vinda
# do gateway: usado só para popular `proxima_cobranca` de forma razoável
# após uma fatura paga (decisão própria, não detalhada no brief/contrato —
# a Pagar.me normalmente informaria a data real na notificação, mas o
# formato exato do evento é definido pela Task T8, ainda não implementada).
DIAS_CICLO_COBRANCA = 30


def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url)


def _chave_falhas(assinatura_id: int) -> str:
    return f"sub:falhas:{assinatura_id}"


async def _incrementar_falhas(assinatura_id: int) -> int:
    """Incrementa o contador Redis de falhas consecutivas de fatura e
    retorna o novo total. Falha aberto (mesma política de `ratelimit.py`):
    se o Redis estiver indisponível, loga e retorna 0 — não bloqueia o
    processamento do evento por causa de uma instabilidade de infra."""
    client = _redis()
    try:
        try:
            return await client.incr(_chave_falhas(assinatura_id))
        except RedisError:
            logger.warning(
                "assinaturas: falha ao incrementar contador de falhas no Redis "
                "(assinatura_id=%s)",
                assinatura_id,
                exc_info=True,
            )
            return 0
    finally:
        await client.aclose()


async def _resetar_falhas(assinatura_id: int) -> None:
    client = _redis()
    try:
        try:
            await client.delete(_chave_falhas(assinatura_id))
        except RedisError:
            logger.warning(
                "assinaturas: falha ao zerar contador de falhas no Redis "
                "(assinatura_id=%s)",
                assinatura_id,
                exc_info=True,
            )
    finally:
        await client.aclose()


def _ocorrencia_semanal(
    dia_semana: int, hora_inicio: int, hora_fim: int, semanas_a_frente: int = 0
) -> tuple[datetime, datetime]:
    """Data/hora (UTC) do `[hora_inicio, hora_fim)` local mais próximo (>=
    hoje) que cai no `dia_semana` (0=segunda..6=domingo, mesma convenção de
    `datetime.weekday()` usada em `app.services.precos`), deslocado
    `semanas_a_frente` semanas adiante."""
    tz = ZoneInfo(settings.tz_local)
    hoje_local = datetime.now(tz).date()
    dias_ate = (dia_semana - hoje_local.weekday()) % 7
    data = hoje_local + timedelta(days=dias_ate, weeks=semanas_a_frente)

    inicio_local = datetime.combine(data, time(hora_inicio, 0), tzinfo=tz)
    fim_local = datetime.combine(data, time(hora_fim, 0), tzinfo=tz)
    return inicio_local.astimezone(timezone.utc), fim_local.astimezone(timezone.utc)


async def _conflita_com_assinatura_ativa(
    db: AsyncSession,
    recurso_id: int,
    dia_semana: int,
    hora_inicio: int,
    hora_fim: int,
    excluir_id: int | None = None,
) -> bool:
    query = select(Assinatura.id).where(
        Assinatura.recurso_id == recurso_id,
        Assinatura.dia_semana == dia_semana,
        Assinatura.status == AssinaturaStatus.ativa,
        Assinatura.hora_inicio < hora_fim,
        Assinatura.hora_fim > hora_inicio,
    )
    if excluir_id is not None:
        query = query.where(Assinatura.id != excluir_id)
    conflito = (await db.execute(query.limit(1))).scalar_one_or_none()
    return conflito is not None


async def _conflita_com_bloqueio(
    db: AsyncSession, recurso_id: int, inicio: datetime, fim: datetime
) -> bool:
    conflito = (
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
    return conflito is not None


async def _conflita_com_reserva_existente(
    db: AsyncSession, recurso_id: int, inicio: datetime, fim: datetime
) -> bool:
    """Além de bloqueios, `materializar` também precisa evitar tentar criar
    uma reserva que colidiria com outra reserva já existente (ex: uma
    reserva avulsa de balcão feita depois da assinatura) — sem essa checagem
    prévia, a constraint EXCLUDE do banco (`reservas_sem_sobreposicao`)
    levantaria `IntegrityError` e interromperia o laço inteiro de
    materialização. Não faz parte do texto literal do brief (que só cita
    bloqueios), mas é necessário para a garantia "não quebra"."""
    conflito = (
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
    return conflito is not None


async def _buscar_ou_404(db: AsyncSession, assinatura_id: int) -> Assinatura:
    assinatura = (
        await db.execute(select(Assinatura).where(Assinatura.id == assinatura_id))
    ).scalar_one_or_none()
    if assinatura is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="assinatura_nao_encontrada"
        )
    return assinatura


async def criar(db: AsyncSession, staff: Staff, dados: AssinaturaCriar) -> Assinatura:
    """Cria a assinatura + subscription na Pagar.me (real ou simulado,
    conforme `get_pagarme()`). 409 se o slot semanal (recurso/dia/horário)
    colidir com outra assinatura ativa ou com um bloqueio já cadastrado."""
    if await _conflita_com_assinatura_ativa(
        db, dados.recurso_id, dados.dia_semana, dados.hora_inicio, dados.hora_fim
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="slot_ocupado"
        )

    proxima_ocorrencia_inicio, proxima_ocorrencia_fim = _ocorrencia_semanal(
        dados.dia_semana, dados.hora_inicio, dados.hora_fim
    )
    if await _conflita_com_bloqueio(
        db, dados.recurso_id, proxima_ocorrencia_inicio, proxima_ocorrencia_fim
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="slot_ocupado"
        )

    cliente = await db.get(Cliente, dados.cliente_id)
    if cliente is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="cliente_nao_encontrado"
        )
    recurso = await db.get(Recurso, dados.recurso_id)
    if recurso is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="recurso_nao_encontrado"
        )

    pagarme = get_pagarme()
    sub = await pagarme.criar_subscription(
        cliente,
        dados.valor_mensal_centavos,
        proxima_ocorrencia_inicio.day,
        dados.metodo,
        dados.card_token,
    )

    assinatura = Assinatura(
        cliente_id=dados.cliente_id,
        recurso_id=dados.recurso_id,
        dia_semana=dados.dia_semana,
        hora_inicio=dados.hora_inicio,
        hora_fim=dados.hora_fim,
        valor_mensal_centavos=dados.valor_mensal_centavos,
        status=AssinaturaStatus.ativa,
        pagarme_subscription_id=sub.subscription_id,
        proxima_cobranca=proxima_ocorrencia_inicio,
    )
    try:
        db.add(assinatura)
        await db.flush()
    except Exception:
        # Achado na revisão final de branch: a subscription já existe (e já
        # cobra) na Pagar.me neste ponto — se o commit local falhar (ex:
        # conexão cai, corrida rara passando pelas checagens de conflito
        # acima), ficaria uma cobrança recorrente real sem NENHUM registro
        # local, sem forma de encontrar/cancelar depois. Compensa cancelando
        # a subscription antes de propagar o erro original.
        logger.error(
            "criar assinatura: commit local falhou após criar subscription_id=%s na "
            "Pagar.me — compensando com cancelamento",
            sub.subscription_id,
        )
        try:
            await pagarme.cancelar_subscription(sub.subscription_id)
        except Exception:
            logger.exception(
                "criar assinatura: falha ao compensar (cancelar) subscription_id=%s "
                "— requer cancelamento manual no painel da Pagar.me",
                sub.subscription_id,
            )
        raise
    # `cliente`/`recurso` já estão na identity map desta sessão (buscados
    # acima via `db.get`), então acessar `assinatura.cliente`/`.recurso` daqui
    # em diante resolve pelo cache local sem emitir lazy-load assíncrono.
    return assinatura


async def materializar(db: AsyncSession, semanas: int = 5) -> int:
    """Garante que cada assinatura `ativa` tenha reservas `confirmada` /
    `mensalista` criadas para as próximas `semanas` ocorrências futuras do
    seu slot semanal. Idempotente: reservas já materializadas (mesma
    `assinatura_id` + `inicio`) não são duplicadas. Ocorrências que colidem
    com um bloqueio (ou, defensivamente, com outra reserva já existente) são
    puladas com um aviso no log, sem interromper as demais."""
    assinaturas = (
        await db.execute(
            select(Assinatura).where(Assinatura.status == AssinaturaStatus.ativa)
        )
    ).scalars().all()

    agora = datetime.now(timezone.utc)
    criadas = 0

    for assinatura in assinaturas:
        for semana in range(semanas):
            inicio_utc, fim_utc = _ocorrencia_semanal(
                assinatura.dia_semana,
                assinatura.hora_inicio,
                assinatura.hora_fim,
                semana,
            )
            if inicio_utc <= agora:
                # Ocorrência "desta semana" já começou/passou — não
                # materializa reserva no passado.
                continue

            ja_existe = (
                await db.execute(
                    select(Reserva.id)
                    .where(
                        Reserva.assinatura_id == assinatura.id,
                        Reserva.inicio == inicio_utc,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if ja_existe is not None:
                continue

            if await _conflita_com_bloqueio(db, assinatura.recurso_id, inicio_utc, fim_utc):
                logger.warning(
                    "materializar: pulando assinatura_id=%s em %s — conflito com bloqueio",
                    assinatura.id,
                    inicio_utc.isoformat(),
                )
                continue

            if await _conflita_com_reserva_existente(
                db, assinatura.recurso_id, inicio_utc, fim_utc
            ):
                logger.warning(
                    "materializar: pulando assinatura_id=%s em %s — conflito com reserva existente",
                    assinatura.id,
                    inicio_utc.isoformat(),
                )
                continue

            db.add(
                Reserva(
                    recurso_id=assinatura.recurso_id,
                    cliente_id=assinatura.cliente_id,
                    inicio=inicio_utc,
                    fim=fim_utc,
                    status=ReservaStatus.confirmada,
                    origem=ReservaOrigem.mensalista,
                    # A cobrança é mensal via subscription, não por slot —
                    # a reserva materializada não gera cobrança própria.
                    valor_centavos=0,
                    assinatura_id=assinatura.id,
                )
            )
            await db.flush()
            criadas += 1

    return criadas


async def processar_evento_sub(db: AsyncSession, evento: dict) -> None:
    """Processa um evento `subscription.*`/`invoice.*` vindo do webhook da
    Pagar.me (dispatcher fica na Task T8, que deve chamar esta função).

    Formato esperado de `evento` (decisão própria — a Task T8, responsável
    pelo payload real do webhook, ainda não existe; ajustar aqui se o
    formato definitivo divergir):
        {"type": "invoice.paid" | "invoice.payment_failed", "subscription_id": "..."}

    - fatura paga: assinatura volta para `ativa`, `proxima_cobranca` é
      atualizada, e o contador de falhas consecutivas (Redis
      `sub:falhas:{id}`) é zerado.
    - fatura falhou: incrementa o contador; na 2ª falha consecutiva (ou
      mais) a assinatura vira `inadimplente` — e como `materializar` só
      considera assinaturas `ativa`, ela automaticamente para de gerar
      reservas novas a partir daí.
    """
    sub_id = evento.get("subscription_id")
    tipo = evento.get("type")
    if not sub_id:
        logger.warning("processar_evento_sub: evento sem subscription_id: %r", evento)
        return

    assinatura = (
        await db.execute(
            select(Assinatura).where(Assinatura.pagarme_subscription_id == sub_id)
        )
    ).scalar_one_or_none()
    if assinatura is None:
        logger.warning(
            "processar_evento_sub: nenhuma assinatura com pagarme_subscription_id=%s",
            sub_id,
        )
        return

    if tipo in ("invoice.paid", "invoice.payment_succeeded"):
        assinatura.status = AssinaturaStatus.ativa
        assinatura.proxima_cobranca = datetime.now(timezone.utc) + timedelta(
            days=DIAS_CICLO_COBRANCA
        )
        await _resetar_falhas(assinatura.id)
        await db.flush()
    elif tipo in ("invoice.payment_failed", "invoice.failed"):
        falhas = await _incrementar_falhas(assinatura.id)
        if falhas >= FALHAS_LIMITE:
            assinatura.status = AssinaturaStatus.inadimplente
            await db.flush()
            # Best-effort, igual aos demais e-mails transacionais: uma falha
            # de SMTP não pode interromper o processamento do evento (o
            # status já foi persistido acima).
            assunto, html = email_templates.cobranca_falhou_email(assinatura.cliente.nome)
            try:
                await email.enviar(assinatura.cliente.email, assunto, html)
            except Exception:
                logger.exception(
                    "processar_evento_sub: falha ao enviar e-mail de cobrança falhou "
                    "(assinatura_id=%s)",
                    assinatura.id,
                )
    else:
        logger.info("processar_evento_sub: evento tipo=%r ignorado", tipo)


async def pausar(db: AsyncSession, assinatura_id: int) -> Assinatura:
    """Pausa a assinatura — e a cobrança de verdade junto.

    Achado na revisão final de branch: antes, `pausar` só trocava o status
    local; a subscription continuava ativa na Pagar.me e o cliente seguia
    sendo cobrado todo mês enquanto o slot já não era mais materializado.
    Como a Pagar.me v5 não expõe um endpoint de "pausar" (só criar/cancelar
    subscription — a mesma interface combinada que `PagarmeClient` já
    define), pausar aqui *cancela* a subscription real; `reativar` cria uma
    nova quando o cliente quiser voltar."""
    assinatura = await _buscar_ou_404(db, assinatura_id)
    if assinatura.pagarme_subscription_id:
        pagarme = get_pagarme()
        await pagarme.cancelar_subscription(assinatura.pagarme_subscription_id)
        assinatura.pagarme_subscription_id = None
    assinatura.status = AssinaturaStatus.pausada
    await db.flush()
    return assinatura


async def reativar(db: AsyncSession, assinatura_id: int) -> Assinatura:
    """Reativa uma assinatura pausada, criando uma subscription nova na
    Pagar.me (a antiga foi cancelada de verdade em `pausar` — ver docstring
    lá). Simplificação própria, não coberta pelo brief original: como não
    guardamos `card_token` (token de uso único, não reutilizável depois do
    checkout original) nem qual `metodo` o cliente escolheu na criação, a
    subscription recriada aqui sempre usa `pix` — o único método que não
    depende de token salvo. Se o cliente pagava no cartão, a próxima
    cobrança passa a ser por PIX; não há hoje uma forma de reativar
    mantendo cartão sem coletar um novo token."""
    assinatura = await _buscar_ou_404(db, assinatura_id)

    cliente = await db.get(Cliente, assinatura.cliente_id)
    dia_cobranca = datetime.now(timezone.utc).day
    pagarme = get_pagarme()
    sub = await pagarme.criar_subscription(
        cliente, assinatura.valor_mensal_centavos, dia_cobranca, "pix"
    )
    assinatura.pagarme_subscription_id = sub.subscription_id
    assinatura.status = AssinaturaStatus.ativa
    await db.flush()
    return assinatura


async def cancelar(db: AsyncSession, assinatura_id: int) -> Assinatura:
    """Cancela na Pagar.me e remove as reservas futuras `mensalista` ainda
    não iniciadas (`inicio > now`) — as que já começaram/aconteceram ficam
    intactas como histórico."""
    assinatura = await _buscar_ou_404(db, assinatura_id)

    if assinatura.pagarme_subscription_id:
        pagarme = get_pagarme()
        await pagarme.cancelar_subscription(assinatura.pagarme_subscription_id)

    assinatura.status = AssinaturaStatus.cancelada

    agora = datetime.now(timezone.utc)
    futuras = (
        await db.execute(
            select(Reserva).where(
                Reserva.assinatura_id == assinatura.id,
                Reserva.origem == ReservaOrigem.mensalista,
                Reserva.inicio > agora,
            )
        )
    ).scalars().all()
    for reserva in futuras:
        await db.delete(reserva)

    await db.flush()
    return assinatura
