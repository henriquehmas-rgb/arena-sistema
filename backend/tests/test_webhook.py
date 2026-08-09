"""Testes de `POST /api/v1/webhooks/pagarme` (Task T8).

Cobre, conforme o Step 1 do brief:
- checkout PIX cria `Pagamento` `pendente` com order (delegado a
  `tests/test_pagamentos.py`, que já cobre isso diretamente no serviço);
- webhook `order.paid` assinado confirma pagamento+reserva;
- mesmo evento 2x confirma 1x (idempotência via Redis `wh:{event_id}`);
- assinatura inválida -> 401;
- `order.payment_failed` marca pagamento `falhou` (reserva segue
  `pendente_pagamento` até o TTL);
- `charge.refunded` -> `estornado`;
- reconciliação (`pagamentos.reconciliar_pendentes`) é testada
  separadamente em `tests/test_pagamentos.py` — é um serviço chamado pelo
  job, não uma rota HTTP.

Em `PAGARME_MODE=simulado` (padrão da suíte), o webhook aceita qualquer
requisição sem checar `X-Hub-Signature` — por isso a maioria dos testes
abaixo nem precisa calcular uma assinatura. O teste de assinatura
inválida/válida troca `settings.pagarme_mode` para `sandbox` via
monkeypatch só durante sua própria execução.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models.entities import Pagamento, Recurso, Reserva
from app.models.enums import (
    MetodoPagamento,
    PagamentoStatus,
    ReservaOrigem,
    ReservaStatus,
    TipoRecurso,
)
from app.services import pagamentos as pagamentos_service

WEBHOOK_URL = "/api/v1/webhooks/pagarme"


async def _criar_recurso(db, nome: str = "Campo Webhook") -> Recurso:
    recurso = Recurso(nome=nome, tipo=TipoRecurso.campo, ativo=True, ordem=1)
    db.add(recurso)
    await db.flush()
    return recurso


async def _criar_reserva_pendente(db, recurso: Recurso, cliente_id: int) -> Reserva:
    agora = datetime.now(timezone.utc)
    reserva = Reserva(
        recurso_id=recurso.id,
        cliente_id=cliente_id,
        inicio=agora + timedelta(days=1),
        fim=agora + timedelta(days=1, hours=1),
        status=ReservaStatus.pendente_pagamento,
        origem=ReservaOrigem.online,
        valor_centavos=5000,
        criado_em=agora,
    )
    db.add(reserva)
    await db.flush()
    return reserva


def _novo_event_id() -> str:
    return f"evt_test_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# order.paid confirma pagamento + reserva
# ---------------------------------------------------------------------------


async def test_webhook_order_paid_confirma_pagamento_e_reserva(client, db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)
    pagamento = await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)
    order_id = pagamento.pagarme_order_id

    event_id = _novo_event_id()
    resp = await client.post(
        WEBHOOK_URL,
        json={"id": event_id, "type": "order.paid", "data": {"id": order_id}},
    )

    assert resp.status_code == 200
    await db.refresh(pagamento)
    await db.refresh(reserva)
    assert pagamento.status == PagamentoStatus.pago
    assert reserva.status == ReservaStatus.confirmada


# ---------------------------------------------------------------------------
# Idempotência: mesmo event_id 2x confirma 1x
# ---------------------------------------------------------------------------


async def test_webhook_mesmo_evento_2x_confirma_1x(client, db, cliente_logado, monkeypatch):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)
    pagamento = await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)
    order_id = pagamento.pagarme_order_id

    chamadas: list[str] = []
    original = pagamentos_service.confirmar_por_order

    async def _confirmar_espiao(db_, order_id_):
        chamadas.append(order_id_)
        return await original(db_, order_id_)

    monkeypatch.setattr(pagamentos_service, "confirmar_por_order", _confirmar_espiao)

    event_id = _novo_event_id()
    payload = {"id": event_id, "type": "order.paid", "data": {"id": order_id}}

    resp1 = await client.post(WEBHOOK_URL, json=payload)
    resp2 = await client.post(WEBHOOK_URL, json=payload)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    # O dispatcher só chegou a chamar `confirmar_por_order` na 1ª vez — a
    # 2ª foi barrada antes disso pelo SETNX no Redis.
    assert len(chamadas) == 1

    await db.refresh(pagamento)
    assert pagamento.status == PagamentoStatus.pago


# ---------------------------------------------------------------------------
# Assinatura inválida -> 401 (fora do modo simulado)
# ---------------------------------------------------------------------------


async def test_webhook_sem_assinatura_401_fora_do_simulado(client, monkeypatch):
    monkeypatch.setattr(settings, "pagarme_mode", "sandbox")
    monkeypatch.setattr(settings, "pagarme_webhook_secret", "segredo-teste")

    resp = await client.post(
        WEBHOOK_URL,
        json={"id": _novo_event_id(), "type": "order.paid", "data": {"id": "order_x"}},
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "assinatura_invalida"


async def test_webhook_assinatura_incorreta_401_fora_do_simulado(client, monkeypatch):
    monkeypatch.setattr(settings, "pagarme_mode", "sandbox")
    monkeypatch.setattr(settings, "pagarme_webhook_secret", "segredo-teste")

    corpo = json.dumps(
        {"id": _novo_event_id(), "type": "order.paid", "data": {"id": "order_x"}}
    ).encode()

    resp = await client.post(
        WEBHOOK_URL,
        content=corpo,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature": "sha256=" + "0" * 64,
        },
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "assinatura_invalida"


async def test_webhook_assinatura_correta_200_fora_do_simulado(client, db, monkeypatch):
    monkeypatch.setattr(settings, "pagarme_mode", "sandbox")
    monkeypatch.setattr(settings, "pagarme_webhook_secret", "segredo-teste")

    # Pagamento criado direto no banco (não via `iniciar_checkout`, que em
    # modo `sandbox` chamaria a API real da Pagar.me) — só precisa existir
    # com o `pagarme_order_id` que o evento referencia.
    pagamento = Pagamento(
        reserva_id=None,
        metodo=MetodoPagamento.pix,
        valor_centavos=5000,
        status=PagamentoStatus.pendente,
        pagarme_order_id="order_manual_teste",
    )
    db.add(pagamento)
    await db.flush()

    event_id = _novo_event_id()
    corpo = json.dumps(
        {"id": event_id, "type": "order.paid", "data": {"id": "order_manual_teste"}}
    ).encode()
    assinatura = hmac.new(b"segredo-teste", corpo, hashlib.sha256).hexdigest()

    resp = await client.post(
        WEBHOOK_URL,
        content=corpo,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature": f"sha256={assinatura}",
        },
    )

    assert resp.status_code == 200
    await db.refresh(pagamento)
    assert pagamento.status == PagamentoStatus.pago


# ---------------------------------------------------------------------------
# order.payment_failed: pagamento falhou, reserva segue pendente
# ---------------------------------------------------------------------------


async def test_webhook_order_payment_failed_marca_falhou_reserva_pendente(
    client, db, cliente_logado
):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)
    pagamento = await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)
    order_id = pagamento.pagarme_order_id

    resp = await client.post(
        WEBHOOK_URL,
        json={
            "id": _novo_event_id(),
            "type": "order.payment_failed",
            "data": {"id": order_id},
        },
    )

    assert resp.status_code == 200
    await db.refresh(pagamento)
    await db.refresh(reserva)
    assert pagamento.status == PagamentoStatus.falhou
    assert reserva.status == ReservaStatus.pendente_pagamento


# ---------------------------------------------------------------------------
# charge.refunded -> estornado
# ---------------------------------------------------------------------------


async def test_webhook_charge_refunded_marca_estornado(client, db, cliente_logado):
    cliente = cliente_logado["cliente"]
    recurso = await _criar_recurso(db)
    reserva = await _criar_reserva_pendente(db, recurso, cliente.id)
    pagamento = await pagamentos_service.iniciar_checkout(db, cliente, reserva.id, "pix", None)
    await pagamentos_service.confirmar_por_order(db, pagamento.pagarme_order_id)
    await db.refresh(pagamento)
    assert pagamento.status == PagamentoStatus.pago
    charge_id = pagamento.pagarme_charge_id

    resp = await client.post(
        WEBHOOK_URL,
        json={
            "id": _novo_event_id(),
            "type": "charge.refunded",
            "data": {"id": charge_id},
        },
    )

    assert resp.status_code == 200
    await db.refresh(pagamento)
    assert pagamento.status == PagamentoStatus.estornado


# ---------------------------------------------------------------------------
# subscription.*/invoice.* -> repassado para assinaturas.processar_evento_sub
# ---------------------------------------------------------------------------


async def test_webhook_invoice_paid_repassa_para_processar_evento_sub(client, db, monkeypatch):
    from app.services import assinaturas as assinaturas_service

    recebido = {}

    async def _fake_processar(db_, evento):
        recebido.update(evento)

    monkeypatch.setattr(assinaturas_service, "processar_evento_sub", _fake_processar)

    resp = await client.post(
        WEBHOOK_URL,
        json={
            "id": _novo_event_id(),
            "type": "invoice.paid",
            "data": {"subscription_id": "sub_abc123"},
        },
    )

    assert resp.status_code == 200
    assert recebido == {"type": "invoice.paid", "subscription_id": "sub_abc123"}
