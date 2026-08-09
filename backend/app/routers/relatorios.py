"""`GET /relatorios/faturamento` e `GET /relatorios/ocupacao` (admin).

Período `[de, ate]` (datas locais, inclusive nas duas pontas) é convertido
pra `[inicio_utc, fim_utc)` do mesmo jeito que `app.routers.caixa` faz pro
dia único — `de` vira meia-noite local do primeiro dia, `ate+1` vira meia-
noite local do dia seguinte ao último.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import settings
from app.deps import get_db, require_admin
from app.models.entities import Assinatura, Bloqueio, Pagamento, Recurso, Reserva, Staff
from app.models.enums import PagamentoStatus, ReservaStatus, TipoRecurso
from app.schemas.relatorios import (
    FaturamentoOut,
    FaturamentoPorDia,
    OcupacaoOut,
    OcupacaoRecurso,
)

router = APIRouter()


def _limites_periodo_utc(de: date, ate: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.tz_local)
    inicio_local = datetime.combine(de, time(0, 0), tzinfo=tz)
    fim_local = datetime.combine(ate, time(0, 0), tzinfo=tz) + timedelta(days=1)
    return inicio_local.astimezone(timezone.utc), fim_local.astimezone(timezone.utc)


@router.get("/faturamento", response_model=FaturamentoOut)
async def faturamento(
    de: date = Query(...),
    ate: date = Query(...),
    db: AsyncSession = Depends(get_db),
    _admin: Staff = Depends(require_admin),
) -> FaturamentoOut:
    inicio_utc, fim_utc = _limites_periodo_utc(de, ate)

    filtro = (
        Pagamento.status == PagamentoStatus.pago,
        Pagamento.pago_em >= inicio_utc,
        Pagamento.pago_em < fim_utc,
    )

    # --- total + por_metodo ---
    linhas_metodo = (
        await db.execute(
            select(Pagamento.metodo, func.sum(Pagamento.valor_centavos))
            .where(*filtro)
            .group_by(Pagamento.metodo)
        )
    ).all()
    por_metodo = {metodo.value: int(total) for metodo, total in linhas_metodo}
    total_centavos = sum(por_metodo.values())

    # --- por_recurso ---
    # `Pagamento` não guarda `recurso_id` direto (ver docstring de
    # `CaixaItem`/brief da task): pra pagamento de reserva, o recurso vem de
    # `Reserva.recurso_id`; pra pagamento de assinatura (mensalista), a
    # `Assinatura` TEM `recurso_id` próprio (é a vaga fixa do mensalista),
    # então também dá pra resolver o recurso — usamos
    # `COALESCE(Reserva.recurso_id, Assinatura.recurso_id)` pra cobrir os
    # dois casos com um join só. Só ficaria de fora um pagamento sem
    # `reserva_id` NEM `assinatura_id` (não deveria existir dado o modelo);
    # esse caso, se aparecer, simplesmente não entra em `por_recurso` (mas
    # continua contado em `total_centavos`/`por_metodo` acima) em vez de
    # quebrar o relatório.
    por_recurso = await _faturamento_por_recurso(db, filtro)

    # --- por_dia ---
    # Agrupa pela data *local* do pagamento: `pago_em` é UTC no banco,
    # `func.timezone(tz, col)` converte pra timestamp "sem fuso" que
    # representa o horário de parede em `settings.tz_local`; daí só falta
    # o cast pra `date` pra usar como chave de group_by/label.
    data_local_expr = cast(func.timezone(settings.tz_local, Pagamento.pago_em), Date)
    linhas_dia = (
        await db.execute(
            select(data_local_expr, func.sum(Pagamento.valor_centavos))
            .where(*filtro)
            .group_by(data_local_expr)
            .order_by(data_local_expr)
        )
    ).all()
    por_dia = [
        FaturamentoPorDia(data=dia.isoformat(), total_centavos=int(total))
        for dia, total in linhas_dia
    ]

    return FaturamentoOut(
        total_centavos=total_centavos,
        por_metodo=por_metodo,
        por_recurso=por_recurso,
        por_dia=por_dia,
    )


async def _faturamento_por_recurso(db: AsyncSession, filtro) -> dict[str, int]:
    RecursoReserva = aliased(Recurso)
    RecursoAssinatura = aliased(Recurso)
    recurso_nome_expr = func.coalesce(RecursoReserva.nome, RecursoAssinatura.nome)

    linhas = (
        await db.execute(
            select(
                recurso_nome_expr.label("recurso_nome"),
                func.sum(Pagamento.valor_centavos),
            )
            .select_from(Pagamento)
            .outerjoin(Reserva, Pagamento.reserva_id == Reserva.id)
            .outerjoin(Assinatura, Pagamento.assinatura_id == Assinatura.id)
            .outerjoin(RecursoReserva, Reserva.recurso_id == RecursoReserva.id)
            .outerjoin(RecursoAssinatura, Assinatura.recurso_id == RecursoAssinatura.id)
            .where(*filtro)
            .group_by(recurso_nome_expr)
        )
    ).all()
    return {nome: int(total) for nome, total in linhas if nome is not None}


# --- Ocupação ---

# Janelas horárias *disjuntas* usadas como capacidade nominal do recurso.
# Campo: 1 janela fechada 08–23 (15h, mesma faixa dos slots de
# `disponibilidade`). Quiosque: as 3 sub-janelas vendáveis (manhã/tarde/
# noite, 12h no total) — o período "dia" (08–22) de `disponibilidade` é uma
# alternativa de venda que *sobrepõe* essas 3 janelas (é o mesmo intervalo
# vendido de um jeito diferente), então não representa capacidade adicional
# e é deliberadamente excluído daqui pra não contar hora duas vezes.
_JANELAS_CAMPO = [(8, 23)]
_JANELAS_QUIOSQUE = [(8, 12), (13, 17), (18, 22)]


def _janelas_do_recurso(tipo: TipoRecurso) -> list[tuple[int, int]]:
    return _JANELAS_CAMPO if tipo == TipoRecurso.campo else _JANELAS_QUIOSQUE


async def _horas_disponiveis_por_recurso(
    db: AsyncSession, recursos: list[Recurso], de: date, ate: date
) -> dict[int, float]:
    """Horas disponíveis = capacidade nominal (janelas acima) × dias do
    período, menos horas efetivamente cobertas por `Bloqueio` dentro dessas
    janelas. Reservas (mesmo confirmadas) NÃO reduzem `horas_disponiveis` —
    capacidade vendida entra em `horas_vendidas`, e a taxa de ocupação é
    `horas_vendidas / horas_disponiveis`."""
    tz = ZoneInfo(settings.tz_local)
    inicio_utc, fim_utc = _limites_periodo_utc(de, ate)

    ids_recursos = [r.id for r in recursos]
    bloqueios = (
        await db.execute(
            select(Bloqueio).where(
                Bloqueio.recurso_id.in_(ids_recursos),
                Bloqueio.inicio < fim_utc,
                Bloqueio.fim > inicio_utc,
            )
        )
    ).scalars().all()
    bloqueios_por_recurso: dict[int, list[Bloqueio]] = {rid: [] for rid in ids_recursos}
    for b in bloqueios:
        bloqueios_por_recurso.setdefault(b.recurso_id, []).append(b)

    dias = [de + timedelta(days=i) for i in range((ate - de).days + 1)]

    resultado: dict[int, float] = {}
    for recurso in recursos:
        janelas = _janelas_do_recurso(recurso.tipo)
        total_horas = 0.0
        for dia in dias:
            for hora_inicio, hora_fim in janelas:
                jan_inicio_utc = datetime.combine(
                    dia, time(hora_inicio, 0), tzinfo=tz
                ).astimezone(timezone.utc)
                jan_fim_utc = datetime.combine(
                    dia, time(hora_fim, 0), tzinfo=tz
                ).astimezone(timezone.utc)
                horas_janela = (jan_fim_utc - jan_inicio_utc).total_seconds() / 3600

                horas_bloqueadas = 0.0
                for bloqueio in bloqueios_por_recurso.get(recurso.id, []):
                    overlap_inicio = max(bloqueio.inicio, jan_inicio_utc)
                    overlap_fim = min(bloqueio.fim, jan_fim_utc)
                    if overlap_fim > overlap_inicio:
                        horas_bloqueadas += (
                            overlap_fim - overlap_inicio
                        ).total_seconds() / 3600

                total_horas += max(horas_janela - horas_bloqueadas, 0.0)
        resultado[recurso.id] = total_horas

    return resultado


@router.get("/ocupacao", response_model=OcupacaoOut)
async def ocupacao(
    de: date = Query(...),
    ate: date = Query(...),
    db: AsyncSession = Depends(get_db),
    _admin: Staff = Depends(require_admin),
) -> OcupacaoOut:
    inicio_utc, fim_utc = _limites_periodo_utc(de, ate)

    recursos = (
        await db.execute(select(Recurso).where(Recurso.ativo.is_(True)).order_by(Recurso.ordem))
    ).scalars().all()

    # horas_vendidas: SQL agregado (sum/group_by), não iteração em Python.
    linhas_vendidas = (
        await db.execute(
            select(
                Reserva.recurso_id,
                func.sum(func.extract("epoch", Reserva.fim - Reserva.inicio)),
            )
            .where(
                Reserva.status.in_([ReservaStatus.confirmada, ReservaStatus.concluida]),
                Reserva.inicio >= inicio_utc,
                Reserva.inicio < fim_utc,
            )
            .group_by(Reserva.recurso_id)
        )
    ).all()
    horas_vendidas_por_recurso = {
        recurso_id: float(segundos or 0) / 3600 for recurso_id, segundos in linhas_vendidas
    }

    horas_disponiveis_por_recurso = await _horas_disponiveis_por_recurso(
        db, list(recursos), de, ate
    )

    por_recurso = []
    for recurso in recursos:
        horas_vendidas = horas_vendidas_por_recurso.get(recurso.id, 0.0)
        horas_disponiveis = horas_disponiveis_por_recurso.get(recurso.id, 0.0)
        taxa = horas_vendidas / horas_disponiveis if horas_disponiveis > 0 else 0.0
        por_recurso.append(
            OcupacaoRecurso(
                recurso=recurso.nome,
                horas_vendidas=horas_vendidas,
                horas_disponiveis=horas_disponiveis,
                taxa=taxa,
            )
        )

    return OcupacaoOut(por_recurso=por_recurso)
