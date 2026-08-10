"""Checkout, confirmação (webhook), estorno e reconciliação de pagamentos.

Task T8 — substitui o stub simples que a Task T6 tinha deixado aqui (só um
`estornar_se_pago` que funcionava em `PAGARME_MODE=simulado`, levantando
`NotImplementedError` em qualquer outro modo). A partir desta task, os
quatro pontos de entrada do contrato ficam implementados de verdade, e o
estorno passa a usar a mesma `PagarmeClient.estornar_charge` nos três modos
(`simulado`/`sandbox`/`producao`) — em vez de um `if settings.pagarme_mode
== "simulado"` especial, já que `SimuladoClient.estornar_charge` também
existe e sempre retorna `True` sem chamada de rede (Task T7), a lógica de
`estornar_se_pago` fica igual nos três modos.

`iniciar_checkout` retorna a entidade `Pagamento` já persistida (`flush`),
mas com dois atributos extras *não mapeados* (`pix_qr_code`/`pix_copia_cola`)
setados na instância quando o método é `pix` — não fazem parte da tabela
`pagamentos` (esses dados só existem enquanto o QR code é válido, não faz
sentido guardá-los), mas o router precisa deles para montar `CheckoutOut`
sem uma segunda chamada à Pagar.me. `getattr(pagamento, "pix_qr_code",
None)` no router lida com o caso `cartao` (onde esses atributos nem chegam a
ser setados).

Idempotência de webhook (SETNX `wh:{event_id}`) mora no router
(`app.routers.webhooks`), não aqui — este módulo só expõe operações
idempotentes *por conteúdo* (`confirmar_por_order` não faz nada se o
pagamento já está `pago`), que é uma segunda camada de proteção
independente do Redis (cobre inclusive reconciliação batendo o mesmo evento
que um webhook que chegou entre as duas checagens).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entities import Cliente, Pagamento, Reserva
from app.models.enums import MetodoPagamento, PagamentoStatus, ReservaStatus
from app.services import email
from app.services import email_templates
from app.services.pagarme import get_pagarme

logger = logging.getLogger("app.pagamentos")

# Tempo mínimo que um pagamento `pendente` precisa ter para entrar na
# reconciliação (`reconciliar_pendentes`) — evita bater na Pagar.me para
# pagamentos criados há poucos segundos, que ainda não teriam tido tempo de
# ser confirmados nem pelo caminho normal (webhook).
RECONCILIACAO_MIN_MINUTOS = 5


class ReservaInvalidaParaCheckoutError(Exception):
    """`iniciar_checkout` chamado para uma reserva que não é do cliente, não
    está `pendente_pagamento`, ou já expirou (TTL vencido). O router
    converte para HTTP 422 — mesmo detail`fora_da_janela`-style, mas com
    texto próprio (`checkout_invalido`), já que não é sobre janela de
    cancelamento."""


def _descricao(reserva: Reserva) -> str:
    return f"Reserva #{reserva.id} — {reserva.recurso.nome}"


async def _buscar_pagamento_por_order(
    db: AsyncSession, order_id: str, *, for_update: bool = False
) -> Pagamento | None:
    stmt = select(Pagamento).where(Pagamento.pagarme_order_id == order_id)
    if for_update:
        # Trava a linha até o fim da transação: webhook, reconciliação e o
        # polling ativo de `GET /pagamentos/{id}` podem chegar aqui pra o
        # mesmo `order_id` quase ao mesmo tempo — sem lock, duas chamadas
        # concorrentes leem `status == pendente` cada uma na sua própria
        # transação, e as duas passam pelo guard de idempotência abaixo
        # (double-confirm: e-mail duplicado, `pago_em` sobrescrito).
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _notificar_confirmacao(db: AsyncSession, reserva: Reserva) -> None:
    """E-mail de confirmação de pagamento — best-effort: uma falha de SMTP
    não deve derrubar a confirmação do pagamento em si (o pagamento já foi
    marcado `pago` no banco antes desta chamada)."""
    if reserva.cliente_id is None:
        return
    # `Reserva.cliente` não é uma relationship mapeada (só `recurso` é, ver
    # app/models/entities.py) — carregamos o Cliente explicitamente.
    cliente = await db.get(Cliente, reserva.cliente_id)
    if cliente is None:
        return
    assunto, html = email_templates.pagamento_confirmado_email(
        cliente.nome, reserva.id, reserva.recurso.nome, f"{reserva.inicio:%d/%m/%Y %H:%M}"
    )
    try:
        await email.enviar(cliente.email, assunto, html)
    except Exception:
        logger.exception(
            "pagamentos: falha ao enviar e-mail de confirmação (reserva_id=%s)", reserva.id
        )


async def iniciar_checkout(
    db: AsyncSession,
    cliente: Cliente,
    reserva_id: int,
    metodo: str,
    card_token: str | None = None,
) -> Pagamento:
    """Cria a `order` na Pagar.me e o `Pagamento` `pendente` correspondente
    para uma reserva online `pendente_pagamento` de `cliente`.

    Levanta `ReservaInvalidaParaCheckoutError` (422, via router) se a
    reserva não existir, não for do cliente, não estiver
    `pendente_pagamento`, ou já tiver estourado o TTL (`settings.
    reserva_ttl_min` após `criado_em`) — nesse último caso mesmo que o job
    de expiração (`reservas.expirar_pendentes`) ainda não tenha rodado."""
    reserva = await db.get(Reserva, reserva_id)
    if (
        reserva is None
        or reserva.cliente_id != cliente.id
        or reserva.status != ReservaStatus.pendente_pagamento
    ):
        raise ReservaInvalidaParaCheckoutError()

    criado_em = reserva.criado_em
    if criado_em.tzinfo is None:
        criado_em = criado_em.replace(tzinfo=timezone.utc)
    limite_ttl = criado_em + timedelta(minutes=settings.reserva_ttl_min)
    if datetime.now(timezone.utc) > limite_ttl:
        raise ReservaInvalidaParaCheckoutError()

    pagarme = get_pagarme()
    descricao = _descricao(reserva)
    if metodo == "pix":
        order = await pagarme.criar_order_pix(cliente, reserva.valor_centavos, descricao)
    else:
        order = await pagarme.criar_order_cartao(
            cliente, reserva.valor_centavos, descricao, card_token or ""
        )

    pagamento = Pagamento(
        reserva_id=reserva.id,
        metodo=MetodoPagamento(metodo),
        valor_centavos=reserva.valor_centavos,
        status=PagamentoStatus.pendente,
        pagarme_order_id=order.order_id,
        pagarme_charge_id=order.charge_id,
    )
    db.add(pagamento)
    await db.flush()

    if order.pix_qr_code is not None:
        pagamento.pix_qr_code = order.pix_qr_code  # type: ignore[attr-defined]
        pagamento.pix_copia_cola = order.pix_copia_cola  # type: ignore[attr-defined]

    return pagamento


async def confirmar_por_order(db: AsyncSession, order_id: str) -> None:
    """Confirma o `Pagamento` (e a `Reserva` associada) referente a
    `order_id`. Idempotente: se o pagamento já está `pago`, não faz nada
    (nem reenviar e-mail) — chamável tanto pelo webhook quanto pela
    reconciliação periódica sem risco de duplo processamento."""
    pagamento = await _buscar_pagamento_por_order(db, order_id, for_update=True)
    if pagamento is None:
        logger.warning("confirmar_por_order: nenhum pagamento com order_id=%s", order_id)
        return
    if pagamento.status == PagamentoStatus.pago:
        return

    pagamento.status = PagamentoStatus.pago
    pagamento.pago_em = datetime.now(timezone.utc)

    reserva = None
    if pagamento.reserva_id is not None:
        reserva = await db.get(Reserva, pagamento.reserva_id)
        if reserva is not None and reserva.status == ReservaStatus.pendente_pagamento:
            reserva.status = ReservaStatus.confirmada

    await db.flush()

    if reserva is not None:
        await _notificar_confirmacao(db, reserva)


async def marcar_falhou_por_order(db: AsyncSession, order_id: str) -> None:
    """`order.payment_failed`: marca o `Pagamento` como `falhou`. A reserva
    **não** é alterada aqui — ela segue `pendente_pagamento` até o job de
    expiração (`reservas.expirar_pendentes`) liberá-la pelo TTL normal, o
    que dá ao cliente a chance de tentar pagar de novo (novo checkout) sem
    perder o slot imediatamente."""
    pagamento = await _buscar_pagamento_por_order(db, order_id)
    if pagamento is None:
        logger.warning("marcar_falhou_por_order: nenhum pagamento com order_id=%s", order_id)
        return
    if pagamento.status in (PagamentoStatus.pago, PagamentoStatus.estornado):
        # Não regride um pagamento já confirmado/estornado por causa de um
        # evento de falha atrasado/fora de ordem.
        return
    pagamento.status = PagamentoStatus.falhou
    await db.flush()


async def marcar_estornado_por_charge(db: AsyncSession, charge_id: str) -> None:
    """`charge.refunded`: marca `pago` -> `estornado` o `Pagamento` cujo
    `pagarme_charge_id` bate com `charge_id`."""
    pagamento = (
        await db.execute(
            select(Pagamento).where(Pagamento.pagarme_charge_id == charge_id)
        )
    ).scalar_one_or_none()
    if pagamento is None:
        logger.warning("marcar_estornado_por_charge: nenhum pagamento com charge_id=%s", charge_id)
        return
    pagamento.status = PagamentoStatus.estornado
    await db.flush()


async def estornar_se_pago(db: AsyncSession, reserva: Reserva) -> None:
    """Estorna (via `PagarmeClient.estornar_charge`) o `Pagamento` `pago`
    associado a `reserva`, se houver algum — sem efeito se a reserva nunca
    teve um pagamento confirmado (ex: cancelamento de uma reserva online
    ainda `pendente_pagamento`). Funciona igual nos três `PAGARME_MODE`
    (`SimuladoClient.estornar_charge` não faz chamada de rede e sempre
    retorna `True`)."""
    pagamento = (
        await db.execute(
            select(Pagamento).where(
                Pagamento.reserva_id == reserva.id,
                Pagamento.status == PagamentoStatus.pago,
            )
        )
    ).scalar_one_or_none()
    if pagamento is None:
        return

    pagarme = get_pagarme()
    if pagamento.pagarme_charge_id:
        await pagarme.estornar_charge(pagamento.pagarme_charge_id)

    pagamento.status = PagamentoStatus.estornado
    await db.flush()


async def reconciliar_pendentes(db: AsyncSession) -> int:
    """Consulta na Pagar.me todo `Pagamento` `pendente` criado há mais de
    `RECONCILIACAO_MIN_MINUTOS` minutos e confirma (via `confirmar_por_order`)
    os que a Pagar.me já reporta como pagos; marca `falhou` os que a
    Pagar.me reporta como falhos. Retorna quantos pagamentos foram
    confirmados (`pago`) nesta rodada — chamado pelo job periódico em
    `app.services.jobs` (a cada 10 min) e diretamente em teste."""
    limite = datetime.now(timezone.utc) - timedelta(minutes=RECONCILIACAO_MIN_MINUTOS)
    pendentes = (
        await db.execute(
            select(Pagamento).where(
                Pagamento.status == PagamentoStatus.pendente,
                Pagamento.criado_em < limite,
                Pagamento.pagarme_order_id.is_not(None),
            )
        )
    ).scalars().all()

    pagarme = get_pagarme()
    confirmados = 0
    for pagamento in pendentes:
        status_remoto = await pagarme.consultar_order(pagamento.pagarme_order_id)
        if status_remoto == "pago":
            await confirmar_por_order(db, pagamento.pagarme_order_id)
            confirmados += 1
        elif status_remoto == "falhou":
            await marcar_falhou_por_order(db, pagamento.pagarme_order_id)

    return confirmados
