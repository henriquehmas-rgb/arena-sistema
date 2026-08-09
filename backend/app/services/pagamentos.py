"""Hook de estorno consumido por `reservas.cancelar_cliente` / `.cancelar_admin`.

A assinatura de `estornar_se_pago` é definida aqui, pela Task T6 — a
implementação real (chamada de estorno à Pagar.me via `app.services.pagarme`)
é da Task T8, que deve substituir o corpo desta função sem precisar mudar
quem a chama.

Até lá: em `PAGARME_MODE=simulado` (o único modo em que o repo público
funciona sem chave de API), este stub apenas marca o `Pagamento` `pago`
associado à reserva como `estornado` — o suficiente para os fluxos de
cancelamento da Task T6 (cliente dentro da janela, admin com `estornar=True`)
serem exercitáveis fim-a-fim em teste/QA sem depender da Task T8. Em
`sandbox`/`producao`, levanta `NotImplementedError` explicitamente em vez de
fingir sucesso — não há integração real ainda.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entities import Pagamento, Reserva
from app.models.enums import PagamentoStatus


async def estornar_se_pago(db: AsyncSession, reserva: Reserva) -> None:
    """Estorna o `Pagamento` `pago` associado a `reserva`, se houver algum.

    Sem efeito (retorna silenciosamente) se a reserva nunca teve um
    pagamento confirmado — ex: cancelamento de uma reserva online ainda
    `pendente_pagamento`. Quando existe um pagamento `pago`:
    - `PAGARME_MODE=simulado`: marca o pagamento como `estornado` direto no
      banco, sem nenhuma chamada de rede.
    - `PAGARME_MODE` != `simulado`: levanta `NotImplementedError` (Task T8
      substitui esta função pela integração real com a Pagar.me).
    """
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

    if settings.pagarme_mode != "simulado":
        raise NotImplementedError(
            "estorno real via Pagar.me ainda não implementado (Task T8); "
            "só PAGARME_MODE=simulado é suportado por app.services.pagamentos "
            "por enquanto"
        )

    pagamento.status = PagamentoStatus.estornado
    await db.flush()
