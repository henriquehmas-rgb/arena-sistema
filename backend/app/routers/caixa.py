"""`GET /caixa?data=YYYY-MM-DD` (staff) — fechamento de caixa do dia.

Soma os `Pagamento` com `status=pago` cujo `pago_em` cai dentro do dia
*local* (`settings.tz_local`) pedido — mesmo padrão de conversão de fuso
usado em `app.services.disponibilidade.slots_do_dia` / `app.services.precos`
(dia local vira janela `[inicio_utc, fim_utc)` pra filtrar contra
`pago_em`, que é `timestamptz` UTC no banco).

Shape de `CaixaItem` (schemas/relatorios.py) veio marcado como "proposto" —
confirmado aqui como `{id, metodo, valor_centavos, recurso_nome,
cliente_nome}`: `recurso_nome`/`cliente_nome` resolvidos via LEFT JOIN em
`Reserva`/`Assinatura` (pagamento pode vir de qualquer um dos dois,
`reserva_id`/`assinatura_id` são mutuamente "opcionais" no modelo) e, dentro
de cada um, no `Cliente` associado (ou `Reserva.nome_avulso` pra reserva de
balcão sem cliente cadastrado). Quando nenhum dos dois liga a nada (não
deveria acontecer dado o modelo, mas defensivamente), os campos vêm `None`
em vez de quebrar a listagem.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import settings
from app.deps import get_db, get_staff_atual
from app.models.entities import Assinatura, Cliente, Pagamento, Recurso, Reserva, Staff
from app.models.enums import PagamentoStatus
from app.schemas.relatorios import CaixaItem, CaixaOut

router = APIRouter()


def limites_dia_utc(data_local: date) -> tuple[datetime, datetime]:
    """Converte uma data local (`settings.tz_local`) em `[inicio, fim)` UTC
    cobrindo esse dia — mesma lógica de `disponibilidade.slots_do_dia`."""
    tz = ZoneInfo(settings.tz_local)
    inicio_local = datetime.combine(data_local, time(0, 0), tzinfo=tz)
    fim_local = inicio_local + timedelta(days=1)
    return inicio_local.astimezone(timezone.utc), fim_local.astimezone(timezone.utc)


@router.get("", response_model=CaixaOut)
async def caixa_do_dia(
    data: date = Query(...),
    db: AsyncSession = Depends(get_db),
    _staff: Staff = Depends(get_staff_atual),
) -> CaixaOut:
    inicio_utc, fim_utc = limites_dia_utc(data)

    filtro_pago_no_dia = (
        Pagamento.status == PagamentoStatus.pago,
        Pagamento.pago_em >= inicio_utc,
        Pagamento.pago_em < fim_utc,
    )

    # Total + por_metodo: SQL agregado (group_by), não soma em Python.
    agregados = (
        await db.execute(
            select(Pagamento.metodo, func.sum(Pagamento.valor_centavos))
            .where(*filtro_pago_no_dia)
            .group_by(Pagamento.metodo)
        )
    ).all()
    por_metodo = {metodo.value: int(total) for metodo, total in agregados}
    total_centavos = sum(por_metodo.values())

    # Itens individuais (uma linha por pagamento) — join único em
    # Reserva/Assinatura + seus respectivos Recurso/Cliente, evitando N+1.
    RecursoReserva = aliased(Recurso)
    RecursoAssinatura = aliased(Recurso)
    ClienteReserva = aliased(Cliente)
    ClienteAssinatura = aliased(Cliente)

    stmt = (
        select(
            Pagamento.id,
            Pagamento.metodo,
            Pagamento.valor_centavos,
            Pagamento.pago_em,
            func.coalesce(RecursoReserva.nome, RecursoAssinatura.nome).label(
                "recurso_nome"
            ),
            func.coalesce(
                ClienteReserva.nome, Reserva.nome_avulso, ClienteAssinatura.nome
            ).label("cliente_nome"),
        )
        .select_from(Pagamento)
        .outerjoin(Reserva, Pagamento.reserva_id == Reserva.id)
        .outerjoin(Assinatura, Pagamento.assinatura_id == Assinatura.id)
        .outerjoin(RecursoReserva, Reserva.recurso_id == RecursoReserva.id)
        .outerjoin(RecursoAssinatura, Assinatura.recurso_id == RecursoAssinatura.id)
        .outerjoin(ClienteReserva, Reserva.cliente_id == ClienteReserva.id)
        .outerjoin(ClienteAssinatura, Assinatura.cliente_id == ClienteAssinatura.id)
        .where(*filtro_pago_no_dia)
        .order_by(Pagamento.pago_em)
    )
    linhas = (await db.execute(stmt)).all()

    itens = [
        CaixaItem(
            id=linha.id,
            metodo=linha.metodo.value,
            valor_centavos=linha.valor_centavos,
            horario=linha.pago_em,
            recurso_nome=linha.recurso_nome,
            cliente_nome=linha.cliente_nome,
        )
        for linha in linhas
    ]

    return CaixaOut(itens=itens, total_centavos=total_centavos, por_metodo=por_metodo)
