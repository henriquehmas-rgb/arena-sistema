"""`POST /webhooks/pagarme` — assinado (HMAC-SHA256), sem auth de usuário.

Substitui o `APIRouter()` vazio (stub da Wave 0 / Task T3).

## Validação de assinatura

Corpo bruto (`await request.body()`, antes de qualquer parse) contra o
header `X-Hub-Signature` (formato ``sha256=<hex>``), comparado via
`hmac.compare_digest` ao HMAC-SHA256 do corpo com `settings.
pagarme_webhook_secret` como chave. Em `PAGARME_MODE=simulado`, a validação
é pulada por completo (não há segredo real configurado nesse modo, e o
próprio `SimuladoClient` nunca envia um webhook assinado de verdade — quem
"dispara" o evento em teste/QA é o chamador simulando a Pagar.me).

## Idempotência

Cada evento tem um `id` (`event_id`) no payload. Antes de processar,
`SETNX wh:{event_id}` no Redis com TTL de 24h: se a chave já existia (outro
processamento do mesmo evento, seja um reenvio genuíno da Pagar.me ou uma
corrida entre duas requisições concorrentes), a requisição atual retorna
200 sem processar de novo. Falha aberta: se o Redis estiver inacessível,
loga e processa mesmo assim — `pagamentos.confirmar_por_order` já é
idempotente *por conteúdo* (não faz nada se o pagamento já está `pago`),
então processar duas vezes sem a proteção do Redis não corrompe o estado,
só faz um trabalho redundante.

## Shape do evento (decisão própria — Pagar.me v5 real, resumido ao que
usamos)

    {"id": "<event_id>", "type": "<tipo>", "data": {...}}

- `order.paid` / `order.payment_failed`: `data.id` = id da order.
- `charge.refunded`: `data.id` = id da charge.
- `subscription.*` / `invoice.*`: repassado para `app.services.assinaturas.
  processar_evento_sub`, que espera `{"type": ..., "subscription_id": ...}`
  — o id da assinatura é extraído de `data.subscription_id` OU
  `data.subscription.id` (formato de fatura/invoice) OU `data.id` (formato
  onde o próprio objeto de dados já é a subscription, ex. `subscription.*`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db
from app.services import assinaturas as assinaturas_service
from app.services import pagamentos as pagamentos_service

router = APIRouter()
logger = logging.getLogger("app.webhooks")

_EVENTO_TTL_SEGUNDOS = 24 * 60 * 60


def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url)


def _validar_assinatura(corpo: bytes, header: str | None) -> None:
    if settings.pagarme_mode == "simulado":
        return
    if not header or not header.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="assinatura_invalida"
        )
    recebida = header[len("sha256=") :]
    esperada = hmac.new(
        settings.pagarme_webhook_secret.encode(), corpo, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(recebida, esperada):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="assinatura_invalida"
        )


async def _primeiro_processamento(event_id: str) -> bool:
    """`True` se este é o primeiro processamento deste `event_id` (deve
    prosseguir), `False` se já visto (pular). Falha aberta em erro de Redis
    — ver docstring do módulo."""
    client = _redis()
    try:
        try:
            return bool(await client.set(f"wh:{event_id}", "1", nx=True, ex=_EVENTO_TTL_SEGUNDOS))
        except RedisError:
            logger.warning(
                "webhooks: falha ao checar idempotência no Redis, processando mesmo assim "
                "(event_id=%s)",
                event_id,
                exc_info=True,
            )
            return True
    finally:
        await client.aclose()


def _extrair_subscription_id(data: dict) -> str | None:
    if data.get("subscription_id"):
        return data["subscription_id"]
    subscription = data.get("subscription")
    if isinstance(subscription, dict) and subscription.get("id"):
        return subscription["id"]
    return data.get("id")


async def _despachar(db: AsyncSession, payload: dict) -> None:
    tipo = payload.get("type", "")
    data = payload.get("data") or {}

    if tipo == "order.paid":
        await pagamentos_service.confirmar_por_order(db, data.get("id", ""))
    elif tipo == "order.payment_failed":
        await pagamentos_service.marcar_falhou_por_order(db, data.get("id", ""))
    elif tipo == "charge.refunded":
        await pagamentos_service.marcar_estornado_por_charge(db, data.get("id", ""))
    elif tipo.startswith("subscription.") or tipo.startswith("invoice."):
        sub_id = _extrair_subscription_id(data)
        await assinaturas_service.processar_evento_sub(
            db, {"type": tipo, "subscription_id": sub_id}
        )
    else:
        logger.info("webhooks: evento tipo=%r ignorado", tipo)


@router.post("/pagarme", status_code=status.HTTP_200_OK)
async def webhook_pagarme(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    corpo = await request.body()
    _validar_assinatura(corpo, request.headers.get("X-Hub-Signature"))

    try:
        payload = json.loads(corpo or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="corpo_invalido"
        ) from None

    event_id = payload.get("id")
    if event_id and not await _primeiro_processamento(event_id):
        return {"status": "ok"}

    await _despachar(db, payload)
    return {"status": "ok"}
