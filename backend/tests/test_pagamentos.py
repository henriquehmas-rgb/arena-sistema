"""Testes do cliente Pagar.me (Task T7) — parte 1: modo `simulado`.

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
from types import SimpleNamespace

import httpx
import pytest
import redis.asyncio as aioredis

from app.config import settings
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
