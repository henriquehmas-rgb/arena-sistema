"""Motor de reservas: criação (online/balcão), cancelamento e expiração.

Preço é **sempre** recalculado no servidor via `precos.preco_para` — o
schema `ReservaCriar` (e `ReservaBalcaoCriar`) nem tem campo de preço, então
não há como um payload de cliente influenciar o valor cobrado; a garantia
já está na interface, este módulo só chama `preco_para` e usa o resultado.

Corrida de slot: `disponibilidade.esta_livre` é uma checagem otimista (evita,
no caminho comum, a viagem de ida-e-volta de inserir e falhar) — a garantia
real vem da constraint EXCLUDE no banco (Task T2, anti-double-booking em
`reservas`), que dispara `IntegrityError` no INSERT/flush quando duas
requisições concorrentes passam pela checagem otimista "ao mesmo tempo" e
tentam reservar o mesmo slot. `_inserir` executa o INSERT dentro do seu
próprio `db.begin_nested()` (SAVEPOINT) — se ele falhar com
`IntegrityError`, só ESSA tentativa é desfeita (o `begin_nested` já reverte
pro savepoint automaticamente ao sair do `async with` por exceção); o resto
da sessão (ex: outra reserva já inserida antes, no mesmo request) continua
intacto. Um `db.rollback()` "geral" aqui derrubaria a transação inteira da
sessão -- inclusive dentro dos testes, que rodam com
`join_transaction_mode="create_savepoint"` (um único savepoint pra sessão
toda, não um por operação).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entities import Cliente, Pagamento, Recurso, Reserva, Staff
from app.models.enums import PagamentoStatus, ReservaOrigem, ReservaStatus
from app.schemas.reservas import ReservaBalcaoCriar
from app.services import pagamentos
from app.services.disponibilidade import dentro_da_janela_online, esta_livre, slot_valido
from app.services.precos import preco_para


class SlotOcupadoError(Exception):
    """Slot já ocupado — pela checagem otimista (`esta_livre`) ou pela
    constraint EXCLUDE do banco (corrida real entre requisições
    concorrentes). O router converte para HTTP 409."""


class SlotInvalidoError(Exception):
    """`inicio`/`fim` não corresponde a um horário real da grade do
    recurso, ou cai fora da janela de reserva online — sem essa checagem,
    `preco_para` resolveria o preço só pelo horário de início e um payload
    arbitrário (ex: 08:00→23:00) seria cobrado como se fosse 1h. O router
    converte para HTTP 422."""


class ForaDaJanelaError(Exception):
    """Cancelamento de cliente pedido fora da janela permitida
    (`settings.cancelamento_horas` antes do início da reserva). O router
    converte para HTTP 422."""


async def _buscar_recurso_ou_404(db: AsyncSession, recurso_id: int) -> Recurso:
    recurso = await db.get(Recurso, recurso_id)
    if recurso is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="recurso_nao_encontrado"
        )
    return recurso


async def _buscar_reserva_ou_404(db: AsyncSession, reserva_id: int) -> Reserva:
    reserva = await db.get(Reserva, reserva_id)
    if reserva is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="reserva_nao_encontrada"
        )
    return reserva


async def _inserir(db: AsyncSession, reserva: Reserva) -> Reserva:
    try:
        async with db.begin_nested():
            db.add(reserva)
            await db.flush()
    except IntegrityError:
        raise SlotOcupadoError() from None
    return reserva


async def criar_online(
    db: AsyncSession,
    cliente: Cliente,
    recurso_id: int,
    inicio: datetime,
    fim: datetime,
) -> Reserva:
    """Cria uma reserva `online` `pendente_pagamento` para `cliente`. Preço
    sempre recalculado via `preco_para` (nunca aceito do chamador)."""
    recurso = await _buscar_recurso_ou_404(db, recurso_id)

    if not slot_valido(recurso, inicio, fim) or not dentro_da_janela_online(recurso, inicio):
        raise SlotInvalidoError()

    if not await esta_livre(db, recurso_id, inicio, fim):
        raise SlotOcupadoError()

    valor_centavos = await preco_para(db, recurso, inicio, fim)

    reserva = Reserva(
        recurso_id=recurso_id,
        cliente_id=cliente.id,
        inicio=inicio,
        fim=fim,
        status=ReservaStatus.pendente_pagamento,
        origem=ReservaOrigem.online,
        valor_centavos=valor_centavos,
    )
    reserva.recurso = recurso
    return await _inserir(db, reserva)


async def criar_balcao(
    db: AsyncSession, staff: Staff, dados: ReservaBalcaoCriar
) -> Reserva:
    """Cria uma reserva `balcao` já `confirmada` + `Pagamento` `pago`
    (o cliente paga na hora, no balcão — `dinheiro` ou `pix_manual`), com o
    `staff` autenticado registrado em `Pagamento.registrado_por_staff_id`."""
    recurso = await _buscar_recurso_ou_404(db, dados.recurso_id)

    if dados.cliente_id is not None:
        cliente = await db.get(Cliente, dados.cliente_id)
        if cliente is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="cliente_nao_encontrado"
            )

    # Sem checagem de janela aqui (staff pode agendar fixos/eventos além da
    # janela online do cliente), mas o horário ainda precisa bater com um
    # slot real da grade — mesmo motivo de `criar_online`.
    if not slot_valido(recurso, dados.inicio, dados.fim):
        raise SlotInvalidoError()

    if not await esta_livre(db, dados.recurso_id, dados.inicio, dados.fim):
        raise SlotOcupadoError()

    valor_centavos = await preco_para(db, recurso, dados.inicio, dados.fim)

    reserva = Reserva(
        recurso_id=dados.recurso_id,
        cliente_id=dados.cliente_id,
        nome_avulso=dados.nome_avulso,
        celular_avulso=dados.celular_avulso,
        inicio=dados.inicio,
        fim=dados.fim,
        status=ReservaStatus.confirmada,
        origem=ReservaOrigem.balcao,
        valor_centavos=valor_centavos,
    )
    reserva.recurso = recurso
    reserva = await _inserir(db, reserva)

    db.add(
        Pagamento(
            reserva_id=reserva.id,
            metodo=dados.metodo,
            valor_centavos=valor_centavos,
            status=PagamentoStatus.pago,
            pago_em=datetime.now(timezone.utc),
            registrado_por_staff_id=staff.id,
        )
    )
    await db.flush()
    return reserva


async def cancelar_cliente(
    db: AsyncSession, cliente: Cliente, reserva_id: int
) -> Reserva:
    """Cancela uma reserva do próprio `cliente`, se ainda dentro da janela
    (`settings.cancelamento_horas` antes do início) — fora da janela levanta
    `ForaDaJanelaError` (422). Dispara `pagamentos.estornar_se_pago`
    (sem efeito se a reserva nunca teve pagamento confirmado)."""
    reserva = await _buscar_reserva_ou_404(db, reserva_id)
    if reserva.cliente_id != cliente.id:
        # Não vaza a existência de uma reserva de outro cliente: mesmo
        # detail que "não existe".
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="reserva_nao_encontrada"
        )

    limite_cancelamento = reserva.inicio - timedelta(hours=settings.cancelamento_horas)
    if datetime.now(timezone.utc) > limite_cancelamento:
        raise ForaDaJanelaError()

    reserva.status = ReservaStatus.cancelada
    await pagamentos.estornar_se_pago(db, reserva)
    await db.flush()
    return reserva


async def cancelar_admin(
    db: AsyncSession, staff: Staff, reserva_id: int, estornar: bool
) -> Reserva:
    """Cancela qualquer reserva (staff), sem checagem de janela. Estorna o
    pagamento associado apenas se `estornar=True`."""
    reserva = await _buscar_reserva_ou_404(db, reserva_id)
    reserva.status = ReservaStatus.cancelada
    if estornar:
        await pagamentos.estornar_se_pago(db, reserva)
    await db.flush()
    return reserva


async def listar_staff(
    db: AsyncSession,
    recurso_id: int | None = None,
    de: datetime | None = None,
    ate: datetime | None = None,
    status_: ReservaStatus | None = None,
    cliente_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Reserva], int]:
    """Lista reservas para o painel staff (`GET /reservas?recurso_id&de&ate&status&cliente_id`),
    paginada (`limit`/`offset`, default 50). Retorna `(itens, total)` — `total`
    é a contagem sem paginação, para o frontend montar os controles de
    página sem um segundo request."""
    filtros = []
    if recurso_id is not None:
        filtros.append(Reserva.recurso_id == recurso_id)
    if de is not None:
        filtros.append(Reserva.inicio >= de)
    if ate is not None:
        # `ate` já vem como o limite superior exclusivo (meia-noite local do
        # dia seguinte ao último dia do período) — ver
        # `routers.reservas._limites_periodo_utc`.
        filtros.append(Reserva.inicio < ate)
    if status_ is not None:
        filtros.append(Reserva.status == status_)
    if cliente_id is not None:
        filtros.append(Reserva.cliente_id == cliente_id)

    total = (
        await db.execute(select(func.count()).select_from(Reserva).where(*filtros))
    ).scalar_one()

    resultado = await db.execute(
        select(Reserva)
        .where(*filtros)
        .order_by(Reserva.inicio)
        .limit(limit)
        .offset(offset)
    )
    itens = list(resultado.scalars().all())
    return itens, total


async def expirar_pendentes(db: AsyncSession) -> int:
    """Muda para `expirada` toda reserva `pendente_pagamento` cujo TTL
    (`criado_em + settings.reserva_ttl_min`) já venceu. Retorna quantas
    reservas foram expiradas. Chamada pelo job periódico em
    `app.services.jobs` (a cada 60s) e também pode ser chamada diretamente
    em teste."""
    limite = datetime.now(timezone.utc) - timedelta(minutes=settings.reserva_ttl_min)
    resultado = await db.execute(
        select(Reserva).where(
            Reserva.status == ReservaStatus.pendente_pagamento,
            Reserva.criado_em < limite,
        )
    )
    pendentes = resultado.scalars().all()
    for reserva in pendentes:
        reserva.status = ReservaStatus.expirada
    await db.flush()
    return len(pendentes)
