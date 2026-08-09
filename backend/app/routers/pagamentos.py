"""Rotas de pagamentos — conforme o contrato de API congelado:

    POST /pagamentos/checkout {reserva_id,metodo,card_token?} (cliente) -> {pagamento_id,status,pix_qr_code?,pix_copia_cola?}
    GET  /pagamentos/{id}                                     (cliente) -> {status}

Substitui o `APIRouter()` vazio (stub da Wave 0 / Task T3)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.config import settings
from app.deps import get_cliente_atual, get_db
from app.models.entities import Cliente, Pagamento, Reserva
from app.models.enums import PagamentoStatus
from app.schemas.pagamentos import CheckoutIn, CheckoutOut, PagamentoOut
from app.services import pagamentos as pagamentos_service
from app.services.pagarme import get_pagarme

router = APIRouter()

_COOLDOWN_CONSULTA_SEGUNDOS = 2


async def _pode_consultar_pagarme_agora(pagamento_id: int) -> bool:
    """Throttle do lado do servidor pra `consultar_order`: o frontend já faz
    polling de `GET /pagamentos/{id}` a cada poucos segundos, mas nada
    impede várias abas/requisições simultâneas pro mesmo pagamento — sem
    isso, cada uma dispararia sua própria chamada à Pagar.me. `SET NX EX`
    marca "já consultei este pagamento agora" por `_COOLDOWN_CONSULTA_SEGUNDOS`;
    se o Redis estiver indisponível, falha aberto (permite a consulta) —
    mesma política de `services.ratelimit`."""
    try:
        client = aioredis.from_url(settings.redis_url)
        try:
            return bool(
                await client.set(
                    f"pagamentos:consulta_ativa:{pagamento_id}",
                    "1",
                    nx=True,
                    ex=_COOLDOWN_CONSULTA_SEGUNDOS,
                )
            )
        finally:
            await client.aclose()
    except RedisError:
        logging.getLogger(__name__).warning(
            "consultar_pagamento: falha ao checar cooldown no Redis, permitindo consulta"
        )
        return True


@router.post("/checkout", response_model=CheckoutOut, status_code=status.HTTP_201_CREATED)
async def checkout(
    dados: CheckoutIn,
    cliente: Cliente = Depends(get_cliente_atual),
    db: AsyncSession = Depends(get_db),
) -> CheckoutOut:
    try:
        pagamento = await pagamentos_service.iniciar_checkout(
            db, cliente, dados.reserva_id, dados.metodo, dados.card_token
        )
    except pagamentos_service.ReservaInvalidaParaCheckoutError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="checkout_invalido",
        ) from None

    return CheckoutOut(
        pagamento_id=pagamento.id,
        status=pagamento.status,
        pix_qr_code=getattr(pagamento, "pix_qr_code", None),
        pix_copia_cola=getattr(pagamento, "pix_copia_cola", None),
    )


@router.get("/{pagamento_id}", response_model=PagamentoOut)
async def consultar_pagamento(
    pagamento_id: int,
    cliente: Cliente = Depends(get_cliente_atual),
    db: AsyncSession = Depends(get_db),
) -> PagamentoOut:
    pagamento = await db.get(Pagamento, pagamento_id)
    if pagamento is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="pagamento_nao_encontrado"
        )
    # Só o dono da reserva pode consultar o próprio pagamento — mesmo
    # detail de "não existe" que `reservas.cancelar_cliente` usa para não
    # vazar a existência de um pagamento de outro cliente.
    reserva = None
    if pagamento.reserva_id is not None:
        reserva = await db.get(Reserva, pagamento.reserva_id)
    if reserva is None or reserva.cliente_id != cliente.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="pagamento_nao_encontrado"
        )

    # O frontend faz polling nesta rota esperando a confirmação aparecer
    # "ao vivo" (poucos segundos em modo simulado). Sem isso, o pagamento só
    # mudaria de status quando o webhook chegasse ou no próximo ciclo do job
    # de reconciliação (10 min) — rápido demais pra esperar numa tela de
    # checkout. Então, se ainda está pendente e já tem order na Pagar.me,
    # consulta e confirma/marca falha na hora, antes de responder.
    if (
        pagamento.status == PagamentoStatus.pendente
        and pagamento.pagarme_order_id
        and await _pode_consultar_pagarme_agora(pagamento.id)
    ):
        status_pagarme = await get_pagarme().consultar_order(pagamento.pagarme_order_id)
        if status_pagarme == "pago":
            await pagamentos_service.confirmar_por_order(db, pagamento.pagarme_order_id)
        elif status_pagarme == "falhou":
            await pagamentos_service.marcar_falhou_por_order(db, pagamento.pagarme_order_id)

    return PagamentoOut.model_validate(pagamento)
