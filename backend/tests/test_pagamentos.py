"""Testes do cliente Pagar.me (Task T7) — parte 1 — e checkout/estorno/
reconciliação (Task T8) — parte 2, ao final deste arquivo.

Parte 1: modo `simulado`.

Cobre só `SimuladoClient`/`get_pagarme()`: é a única implementação que roda
sem uma chave de API real, e por isso a única exigida pelo brief da task.
`HttpClient` (sandbox/produção) não é testado contra a API real do Pagar.me
aqui — não há chave disponível neste ambiente; a Task T8 (checkout/webhook,
que consome este serviço) e/ou uma task futura podem adicionar testes com
mock de HTTP (`respx`/`httpx.MockTransport`) se quiserem cobertura desse
caminho.

Não usa as fixtures `db`/`client` de `conftest.py` (não precisamos de
Postgres nem da app FastAPI para testar o serviço isoladamente) — só um
cliente Redis real, apontando para `settings.redis_url`/`TEST_REDIS_URL`.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
import redis.asyncio as aioredis

from app.config import settings
from app.models.entities import Cliente, Recurso, Reserva
from app.models.enums import (
    MetodoPagamento,
    PagamentoStatus,
    ReservaOrigem,
    ReservaStatus,
    TipoRecurso,
)
from app.services import pagamentos as pagamentos_service
from app.services.pagarme import HttpClient, SimuladoClient, get_pagarme

CLIENTE_TESTE = SimpleNamespace(
    nome="Cliente Teste",
    email="cliente.teste@example.com",
    cpf="12345678900",
    celular="65999990000",
)


@pytest.fixture
def simulado() -> SimuladoClient:
    return SimuladoClient(redis_url=settings.redis_url)


@pytest.fixture(autouse=True)
async def _limpa_redis_simulado():
    """Evita que chaves `simulado:order:*` de execuções anteriores vazem
    entre testes (o TTL é de 1h, então sem isso poderiam se acumular)."""
    client = aioredis.from_url(settings.redis_url)
    try:
        chaves = [k async for k in client.scan_iter("simulado:order:*")]
        if chaves:
            await client.delete(*chaves)
    finally:
        await client.aclose()
    yield


# ---------------------------------------------------------------------------
# get_pagarme() escolhe a implementação certa
# ---------------------------------------------------------------------------


def test_get_pagarme_retorna_simulado_client_por_padrao():
    assert settings.pagarme_mode == "simulado"
    assert isinstance(get_pagarme(), SimuladoClient)


# ---------------------------------------------------------------------------
# Order PIX
# ---------------------------------------------------------------------------


async def test_criar_order_pix_retorna_pix_copia_cola_simulado(simulado: SimuladoClient):
    resultado = await simulado.criar_order_pix(CLIENTE_TESTE, 5000, "Reserva campo 18h-19h")

    assert resultado.order_id
    assert resultado.charge_id
    assert resultado.status == "pendente"
    assert resultado.pix_qr_code is not None
    assert resultado.pix_copia_cola is not None
    assert resultado.pix_copia_cola.startswith("SIMULADO-")


async def test_criar_order_cartao_simulado_nao_gera_dados_pix(simulado: SimuladoClient):
    resultado = await simulado.criar_order_cartao(
        CLIENTE_TESTE, 5000, "Reserva campo 18h-19h", card_token="tok_fake"
    )

    assert resultado.order_id
    assert resultado.charge_id
    assert resultado.status == "pendente"
    assert resultado.pix_qr_code is None
    assert resultado.pix_copia_cola is None


# ---------------------------------------------------------------------------
# consultar_order: pendente -> pago com a passagem do tempo
# ---------------------------------------------------------------------------


async def test_consultar_order_pendente_logo_apos_criacao(simulado: SimuladoClient):
    resultado = await simulado.criar_order_pix(CLIENTE_TESTE, 5000, "Reserva")

    status = await simulado.consultar_order(resultado.order_id)

    assert status == "pendente"


async def test_consultar_order_pago_apos_5_segundos(simulado: SimuladoClient):
    resultado = await simulado.criar_order_pix(CLIENTE_TESTE, 5000, "Reserva")

    # Em vez de dormir 5s de verdade no teste, "adianta o relógio":
    # sobrescreve o timestamp de criação guardado no Redis para 6s no
    # passado, exercitando exatamente a mesma leitura que
    # `consultar_order` faria depois do tempo real passar.
    client = aioredis.from_url(settings.redis_url)
    try:
        chave = f"simulado:order:{resultado.order_id}"
        await client.set(chave, str(time.time() - 6), ex=3600)
    finally:
        await client.aclose()

    status = await simulado.consultar_order(resultado.order_id)

    assert status == "pago"


async def test_consultar_order_desconhecida_retorna_falhou(simulado: SimuladoClient):
    status = await simulado.consultar_order("order_SIMinexistente")

    assert status == "falhou"


# ---------------------------------------------------------------------------
# Estorno
# ---------------------------------------------------------------------------


async def test_estornar_charge_simulado_sempre_true(simulado: SimuladoClient):
    assert await simulado.estornar_charge("ch_SIMqualquercoisa") is True


# ---------------------------------------------------------------------------
# Subscription (assinatura)
# ---------------------------------------------------------------------------


async def test_criar_subscription_simulado_retorna_id_sub_sim(simulado: SimuladoClient):
    resultado = await simulado.criar_subscription(
        CLIENTE_TESTE, valor_centavos=15000, dia_cobranca=5, metodo="cartao", card_token="tok_fake"
    )

    assert resultado.subscription_id.startswith("sub_SIM")
    assert resultado.status


async def test_cancelar_subscription_simulado_sempre_true(simulado: SimuladoClient):
    assert await simulado.cancelar_subscription("sub_SIMqualquercoisa") is True


# ---------------------------------------------------------------------------
# HttpClient.criar_subscription: status cru da Pagar.me deve ser mapeado
# pro mesmo vocabulário que `SimuladoClient` usa (achado do code review:
# antes, `HttpClient` retornava o status cru da Pagar.me — ex. "active" —
# em vez do vocabulário interno "ativa" que `SimuladoClient` já retorna).
# ---------------------------------------------------------------------------


async def test_http_client_criar_subscription_mapeia_status_active_para_ativa():
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/subscriptions")
        return httpx.Response(200, json={"id": "sub_abc123", "status": "active"})

    cliente = HttpClient(api_key="sk_test_fake")
    cliente._request = _fake_request_factory(_handler)  # type: ignore[method-assign]

    resultado = await cliente.criar_subscription(
        CLIENTE_TESTE, valor_centavos=15000, dia_cobranca=5, metodo="cartao", card_token="tok_fake"
    )

    assert resultado.subscription_id == "sub_abc123"
    assert resultado.status == "ativa"


def _fake_request_factory(handler):
    """Substitui `HttpClient._request` por uma versão que usa
    `httpx.MockTransport` em vez de bater na rede real — não há chave de API
    real disponível neste ambiente para testar `HttpClient` fim a fim."""

    async def _fake_request(method: str, path: str, json: dict | None = None) -> dict:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="https://api.pagar.me/core/v5", transport=transport
        ) as client:
            resp = await client.request(method, path, json=json)
        return resp.json()

    return _fake_request


# ---------------------------------------------------------------------------
# Parte 2 (Task T8): app.services.pagamentos — checkout, confirmação,
# estorno e reconciliação.
#
# Roda em `PAGARME_MODE=simulado` (padrão) contra o Redis real de teste — o
# mesmo cliente (`SimuladoClient`, via `get_pagarme()`) exercitado na parte
# 1 acima, sem nenhum mock/monkeypatch, seguindo o mesmo espírito de
# `tests/test_expiracao.py` (testa o serviço diretamente com fixtures
# `db`/`client` de `conftest.py`).
# ---------------------------------------------------------------------------


async def _criar_recurso(db, nome: str = "Campo Pagamentos") -> Recurso:
    recurso = Recurso(nome=nome, tipo=TipoRecurso.campo, ativo=True, ordem=1)
    db.add(recurso)
    await db.flush()
    return recurso


async def _criar_outro_cliente(db, sufixo: str = "outro") -> Cliente:
    cliente = Cliente(
        nome="Outro Cliente",
        email=f"outro-{sufixo}-{uuid.uuid4().hex[:8]}@teste.com",
        senha_hash=None,
        celular="65988880000",
    )
    db.add(cliente)
    await db.flush()
    return cliente


async def _criar_reserva_pendente(
    db, recurso: Recurso, cliente_id: int, *, criado_em: datetime | None = None
) -> Reserva:
    agora = datetime.now(timezone.utc)
    reserva = Reserva(
        recurso_id=recurso.id,
        cliente_id=cliente_id,
        inicio=agora + timedelta(days=1),
        fim=agora + timedelta(days=1, hours=1),
        status=ReservaStatus.pendente_pagamento,
        origem=ReservaOrigem.online,
        valor_centavos=5000,
        criado_em=criado_em or agora,
    )
    db.add(reserva)
    await db.flush()
    return reserva


# --- iniciar_checkout --------------------------------------------------------


async def test_iniciar_checkout_pix_cria_pagamento_pendente_com_order(db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)

    pagamento = await pagamentos_service.iniciar_checkout(
        db, cliente, reserva.id, "pix", None
    )

    assert pagamento.id is not None
    assert pagamento.status == PagamentoStatus.pendente
    assert pagamento.reserva_id == reserva.id
    assert pagamento.metodo == MetodoPagamento.pix
    assert pagamento.pagarme_order_id
    assert pagamento.pagarme_order_id.startswith("order_SIM")
    assert getattr(pagamento, "pix_qr_code", None) is not None


async def test_iniciar_checkout_reserva_de_outro_cliente_levanta_erro(db, cliente_logado):
    dono_da_reserva = await _criar_outro_cliente(db)
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, dono_da_reserva.id)

    with pytest.raises(pagamentos_service.ReservaInvalidaParaCheckoutError):
        await pagamentos_service.iniciar_checkout(
            db, cliente_logado["cliente"], reserva.id, "pix", None
        )


async def test_iniciar_checkout_reserva_ja_confirmada_levanta_erro(db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)
    reserva.status = ReservaStatus.confirmada
    await db.flush()

    with pytest.raises(pagamentos_service.ReservaInvalidaParaCheckoutError):
        await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)


async def test_iniciar_checkout_reserva_expirada_levanta_erro(db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    criado_ha_muito = datetime.now(timezone.utc) - timedelta(
        minutes=settings.reserva_ttl_min + 1
    )
    reserva = await _criar_reserva_pendente(
        db, recurso, cliente.id, criado_em=criado_ha_muito
    )

    with pytest.raises(pagamentos_service.ReservaInvalidaParaCheckoutError):
        await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)


async def test_rota_checkout_reserva_invalida_422(client, db, cliente_logado):
    dono_da_reserva = await _criar_outro_cliente(db)
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, dono_da_reserva.id)

    resp = await client.post(
        "/api/v1/pagamentos/checkout",
        json={"reserva_id": reserva.id, "metodo": "pix"},
        headers=cliente_logado["headers"],
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "checkout_invalido"


async def test_rota_checkout_pix_201(client, db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)

    resp = await client.post(
        "/api/v1/pagamentos/checkout",
        json={"reserva_id": reserva.id, "metodo": "pix"},
        headers=cliente_logado["headers"],
    )

    assert resp.status_code == 201
    corpo = resp.json()
    assert corpo["status"] == "pendente"
    assert corpo["pix_qr_code"] is not None
    assert corpo["pix_copia_cola"] is not None


# --- confirmar_por_order: idempotência ---------------------------------------


async def test_confirmar_por_order_confirma_pagamento_e_reserva(db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)
    pagamento = await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)

    await pagamentos_service.confirmar_por_order(db, pagamento.pagarme_order_id)

    await db.refresh(pagamento)
    await db.refresh(reserva)
    assert pagamento.status == PagamentoStatus.pago
    assert pagamento.pago_em is not None
    assert reserva.status == ReservaStatus.confirmada


async def test_confirmar_por_order_2x_so_confirma_uma_vez(db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)
    pagamento = await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)

    await pagamentos_service.confirmar_por_order(db, pagamento.pagarme_order_id)
    await db.refresh(pagamento)
    primeiro_pago_em = pagamento.pago_em

    # 2ª chamada para o mesmo order_id: não deve alterar `pago_em` de novo
    # nem regredir o status — é a garantia "por conteúdo" (independente do
    # Redis) de que confirmar 2x confirma 1x.
    await pagamentos_service.confirmar_por_order(db, pagamento.pagarme_order_id)
    await db.refresh(pagamento)

    assert pagamento.status == PagamentoStatus.pago
    assert pagamento.pago_em == primeiro_pago_em


# --- marcar_falhou_por_order --------------------------------------------------


async def test_marcar_falhou_por_order_nao_mexe_na_reserva(db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)
    pagamento = await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)

    await pagamentos_service.marcar_falhou_por_order(db, pagamento.pagarme_order_id)

    await db.refresh(pagamento)
    await db.refresh(reserva)
    assert pagamento.status == PagamentoStatus.falhou
    assert reserva.status == ReservaStatus.pendente_pagamento


# --- estornar_se_pago ---------------------------------------------------------


async def test_estornar_se_pago_marca_estornado(db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)
    pagamento = await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)
    await pagamentos_service.confirmar_por_order(db, pagamento.pagarme_order_id)
    await db.refresh(pagamento)
    assert pagamento.status == PagamentoStatus.pago

    await pagamentos_service.estornar_se_pago(db, reserva)

    await db.refresh(pagamento)
    assert pagamento.status == PagamentoStatus.estornado


async def test_estornar_se_pago_sem_pagamento_pago_e_no_op(db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)

    # Não levanta, não faz nada — reserva nunca teve pagamento confirmado.
    await pagamentos_service.estornar_se_pago(db, reserva)


async def test_cancelar_cliente_com_pagamento_pago_estorna(db, cliente_logado):
    """Fim-a-fim com o hook de `reservas.cancelar_cliente` (Task T6): a
    substituição do stub por esta task não deve mudar quem chama
    `estornar_se_pago`, só o que ele faz de verdade."""
    from app.services import reservas as reservas_service

    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    # `inicio` bem além de `settings.cancelamento_horas` (default 24h) para
    # não cair na borda exata do limite de cancelamento — o teste é sobre
    # o estorno, não sobre a janela em si (já coberta em test_reservas.py).
    agora = datetime.now(timezone.utc)
    reserva = Reserva(
        recurso_id=recurso.id,
        cliente_id=cliente.id,
        inicio=agora + timedelta(days=3),
        fim=agora + timedelta(days=3, hours=1),
        status=ReservaStatus.pendente_pagamento,
        origem=ReservaOrigem.online,
        valor_centavos=5000,
        criado_em=agora,
    )
    db.add(reserva)
    await db.flush()
    pagamento = await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)
    await pagamentos_service.confirmar_por_order(db, pagamento.pagarme_order_id)

    await reservas_service.cancelar_cliente(db, cliente, reserva.id)

    await db.refresh(pagamento)
    assert pagamento.status == PagamentoStatus.estornado


# --- reconciliar_pendentes ----------------------------------------------------


async def test_reconciliar_pendentes_confirma_pagamento_ja_pago_na_pagarme(db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)
    pagamento = await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)

    # "Adianta o relógio" da order simulada (mesmo truque de
    # test_consultar_order_pago_apos_5_segundos acima) para `consultar_order`
    # já reportar "pago" sem esperar 5s de verdade.
    redis_client = aioredis.from_url(settings.redis_url)
    try:
        await redis_client.set(
            f"simulado:order:{pagamento.pagarme_order_id}", str(time.time() - 6), ex=3600
        )
    finally:
        await redis_client.aclose()

    # E "adianta" o próprio pagamento para fora da janela de
    # `RECONCILIACAO_MIN_MINUTOS` (senão `reconciliar_pendentes` o ignora
    # por ser recente demais).
    pagamento.criado_em = datetime.now(timezone.utc) - timedelta(
        minutes=pagamentos_service.RECONCILIACAO_MIN_MINUTOS + 1
    )
    await db.flush()

    confirmados = await pagamentos_service.reconciliar_pendentes(db)

    assert confirmados == 1
    await db.refresh(pagamento)
    await db.refresh(reserva)
    assert pagamento.status == PagamentoStatus.pago
    assert reserva.status == ReservaStatus.confirmada


async def test_reconciliar_pendentes_ignora_pagamento_recente(db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)
    await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)

    # Sem adiantar `criado_em`: ainda está dentro da janela de tolerância,
    # então nem deveria bater na Pagar.me pra checar.
    confirmados = await pagamentos_service.reconciliar_pendentes(db)

    assert confirmados == 0


# --- job de reconciliação (app.services.jobs) --------------------------------


def test_job_reconciliar_pendentes_registrado():
    """`jobs.iniciar` deve agendar o job `reconciliar_pendentes` a cada
    10 min, aditivamente ao que T6/T9 já registraram — mesmo padrão de
    `tests/test_expiracao.py::test_job_expirar_reservas_registrado`."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    from app.services.jobs import _registrar_reconciliar_pendentes

    scheduler = AsyncIOScheduler()
    _registrar_reconciliar_pendentes(scheduler)

    job = scheduler.get_job("reconciliar_pendentes")
    assert job is not None
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == 600
