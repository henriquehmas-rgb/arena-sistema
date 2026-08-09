"""Testes de `GET /caixa` (staff) e `GET /relatorios/{faturamento,ocupacao}`
(admin) — Task T9b.

Cenário do Step 1 do brief: semeia pagamentos (2 pix pagos, 1 dinheiro
pago, 1 pendente) direto no banco (sem passar pelo fluxo de checkout, que é
da track T8 rodando em paralelo) e confirma que:
  - `GET /caixa?data=...` soma só os `pago`, agrupados por método;
  - `GET /relatorios/faturamento` bate por recurso/método/total.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import jwt
import pytest
import pytest_asyncio

from app.config import settings
from app.models.entities import Cliente, Pagamento, Recurso, Reserva, Staff
from app.models.enums import (
    MetodoPagamento,
    PagamentoStatus,
    PapelStaff,
    ReservaOrigem,
    ReservaStatus,
    TipoRecurso,
)

TZ = ZoneInfo(settings.tz_local)


def cuiaba(*args) -> datetime:
    """Datetime aware no fuso local (`settings.tz_local` = America/Cuiaba)."""
    return datetime(*args, tzinfo=TZ)


async def criar_recurso(db, nome="Campo T9b", tipo=TipoRecurso.campo, ordem=1) -> Recurso:
    recurso = Recurso(nome=nome, tipo=tipo, ativo=True, ordem=ordem)
    db.add(recurso)
    await db.flush()
    return recurso


async def criar_cliente(db, nome="Cliente Caixa") -> Cliente:
    cliente = Cliente(
        nome=nome,
        email=f"{uuid.uuid4().hex[:8]}@teste.com",
        senha_hash="x",
        celular="65999990000",
    )
    db.add(cliente)
    await db.flush()
    return cliente


async def criar_reserva(
    db, recurso: Recurso, cliente: Cliente, inicio_local: datetime, valor_centavos: int
) -> Reserva:
    inicio = inicio_local.astimezone(timezone.utc)
    fim = inicio + timedelta(hours=1)
    reserva = Reserva(
        recurso_id=recurso.id,
        cliente_id=cliente.id,
        inicio=inicio,
        fim=fim,
        status=ReservaStatus.confirmada,
        origem=ReservaOrigem.online,
        valor_centavos=valor_centavos,
    )
    db.add(reserva)
    await db.flush()
    return reserva


async def criar_pagamento(
    db,
    *,
    reserva: Reserva | None = None,
    metodo: MetodoPagamento,
    valor_centavos: int,
    status: PagamentoStatus,
    pago_em_local: datetime | None = None,
) -> Pagamento:
    pagamento = Pagamento(
        reserva_id=reserva.id if reserva else None,
        metodo=metodo,
        valor_centavos=valor_centavos,
        status=status,
        pago_em=pago_em_local.astimezone(timezone.utc) if pago_em_local else None,
    )
    db.add(pagamento)
    await db.flush()
    return pagamento


def _token(sub: int, tipo: str, papel: str | None = None) -> str:
    payload = {
        "sub": str(sub),
        "tipo": tipo,
        "escopo": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_min),
    }
    if papel is not None:
        payload["papel"] = papel
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@pytest_asyncio.fixture
async def staff_atendente_logado(db):
    staff = Staff(
        nome="Atendente T9b",
        email=f"atendente-{uuid.uuid4().hex[:8]}@arenacacerense.com.br",
        senha_hash="x",
        papel=PapelStaff.atendente,
        ativo=True,
    )
    db.add(staff)
    await db.flush()
    token = _token(staff.id, tipo="staff", papel=PapelStaff.atendente.value)
    return {"staff": staff, "headers": {"Authorization": f"Bearer {token}"}}


# --- GET /caixa ---------------------------------------------------------


async def test_caixa_do_dia_soma_apenas_pagos_agrupado_por_metodo(
    client, db, staff_atendente_logado
):
    recurso = await criar_recurso(db)
    cliente = await criar_cliente(db)

    dia = cuiaba(2026, 8, 10, 0)  # 2026-08-10, meia-noite local

    r1 = await criar_reserva(db, recurso, cliente, cuiaba(2026, 8, 10, 9), 15000)
    r2 = await criar_reserva(db, recurso, cliente, cuiaba(2026, 8, 10, 11), 12000)
    r3 = await criar_reserva(db, recurso, cliente, cuiaba(2026, 8, 10, 14), 8000)
    r4 = await criar_reserva(db, recurso, cliente, cuiaba(2026, 8, 10, 16), 20000)

    await criar_pagamento(
        db,
        reserva=r1,
        metodo=MetodoPagamento.pix,
        valor_centavos=15000,
        status=PagamentoStatus.pago,
        pago_em_local=cuiaba(2026, 8, 10, 9, 5),
    )
    await criar_pagamento(
        db,
        reserva=r2,
        metodo=MetodoPagamento.pix,
        valor_centavos=12000,
        status=PagamentoStatus.pago,
        pago_em_local=cuiaba(2026, 8, 10, 11, 5),
    )
    await criar_pagamento(
        db,
        reserva=r3,
        metodo=MetodoPagamento.dinheiro,
        valor_centavos=8000,
        status=PagamentoStatus.pago,
        pago_em_local=cuiaba(2026, 8, 10, 14, 0),
    )
    # pendente: não deve entrar na soma (nem tem pago_em ainda)
    await criar_pagamento(
        db,
        reserva=r4,
        metodo=MetodoPagamento.pix,
        valor_centavos=20000,
        status=PagamentoStatus.pendente,
        pago_em_local=None,
    )

    resp = await client.get(
        "/api/v1/caixa",
        params={"data": dia.date().isoformat()},
        headers=staff_atendente_logado["headers"],
    )
    assert resp.status_code == 200, resp.text
    corpo = resp.json()

    assert corpo["total_centavos"] == 35000
    assert corpo["por_metodo"] == {"pix": 27000, "dinheiro": 8000}
    assert len(corpo["itens"]) == 3
    valores = sorted(item["valor_centavos"] for item in corpo["itens"])
    assert valores == [8000, 12000, 15000]
    for item in corpo["itens"]:
        assert item["recurso_nome"] == recurso.nome
        assert item["cliente_nome"] == cliente.nome


async def test_caixa_ignora_pagamentos_de_outro_dia(client, db, staff_atendente_logado):
    recurso = await criar_recurso(db)
    cliente = await criar_cliente(db)
    r = await criar_reserva(db, recurso, cliente, cuiaba(2026, 8, 11, 9), 15000)
    await criar_pagamento(
        db,
        reserva=r,
        metodo=MetodoPagamento.pix,
        valor_centavos=15000,
        status=PagamentoStatus.pago,
        pago_em_local=cuiaba(2026, 8, 11, 9, 5),
    )

    resp = await client.get(
        "/api/v1/caixa",
        params={"data": "2026-08-10"},
        headers=staff_atendente_logado["headers"],
    )
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["total_centavos"] == 0
    assert corpo["itens"] == []


async def test_caixa_exige_autenticacao(client):
    resp = await client.get("/api/v1/caixa", params={"data": "2026-08-10"})
    assert resp.status_code == 401


# --- GET /relatorios/faturamento ----------------------------------------


async def test_faturamento_por_metodo_recurso_e_dia(client, db, staff_admin_logado):
    campo_a = await criar_recurso(db, nome="Campo A", ordem=1)
    campo_b = await criar_recurso(db, nome="Campo B", ordem=2)
    cliente = await criar_cliente(db)

    ra1 = await criar_reserva(db, campo_a, cliente, cuiaba(2026, 8, 10, 9), 15000)
    ra2 = await criar_reserva(db, campo_a, cliente, cuiaba(2026, 8, 11, 10), 12000)
    rb1 = await criar_reserva(db, campo_b, cliente, cuiaba(2026, 8, 10, 18), 18000)
    rb_pendente = await criar_reserva(db, campo_b, cliente, cuiaba(2026, 8, 10, 20), 9000)

    await criar_pagamento(
        db,
        reserva=ra1,
        metodo=MetodoPagamento.pix,
        valor_centavos=15000,
        status=PagamentoStatus.pago,
        pago_em_local=cuiaba(2026, 8, 10, 9, 5),
    )
    await criar_pagamento(
        db,
        reserva=ra2,
        metodo=MetodoPagamento.cartao,
        valor_centavos=12000,
        status=PagamentoStatus.pago,
        pago_em_local=cuiaba(2026, 8, 11, 10, 5),
    )
    await criar_pagamento(
        db,
        reserva=rb1,
        metodo=MetodoPagamento.dinheiro,
        valor_centavos=18000,
        status=PagamentoStatus.pago,
        pago_em_local=cuiaba(2026, 8, 10, 18, 5),
    )
    # pendente: fora do faturamento
    await criar_pagamento(
        db,
        reserva=rb_pendente,
        metodo=MetodoPagamento.pix,
        valor_centavos=9000,
        status=PagamentoStatus.pendente,
        pago_em_local=None,
    )

    resp = await client.get(
        "/api/v1/relatorios/faturamento",
        params={"de": "2026-08-10", "ate": "2026-08-11"},
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 200, resp.text
    corpo = resp.json()

    assert corpo["total_centavos"] == 45000
    assert corpo["por_metodo"] == {"pix": 15000, "cartao": 12000, "dinheiro": 18000}
    assert corpo["por_recurso"] == {"Campo A": 27000, "Campo B": 18000}

    por_dia = {item["data"]: item["total_centavos"] for item in corpo["por_dia"]}
    assert por_dia == {"2026-08-10": 33000, "2026-08-11": 12000}


async def test_faturamento_requer_admin(client, db, staff_atendente_logado):
    resp = await client.get(
        "/api/v1/relatorios/faturamento",
        params={"de": "2026-08-10", "ate": "2026-08-11"},
        headers=staff_atendente_logado["headers"],
    )
    assert resp.status_code == 403


# --- GET /relatorios/ocupacao -------------------------------------------


async def test_ocupacao_horas_vendidas_e_taxa(client, db, staff_admin_logado):
    campo = await criar_recurso(db, nome="Campo Ocupação", ordem=1)
    cliente = await criar_cliente(db)

    # Um único dia (2026-08-10, segunda-feira): 15h de capacidade nominal
    # pro campo (janela fechada 08-23h, sem bloqueios). 2 reservas
    # confirmadas de 1h cada -> 2h vendidas.
    await criar_reserva(db, campo, cliente, cuiaba(2026, 8, 10, 9), 15000)
    r2 = await criar_reserva(db, campo, cliente, cuiaba(2026, 8, 10, 10), 15000)
    r2.status = ReservaStatus.confirmada
    # reserva cancelada não deve contar como vendida
    r3 = await criar_reserva(db, campo, cliente, cuiaba(2026, 8, 10, 11), 15000)
    r3.status = ReservaStatus.cancelada
    await db.flush()

    resp = await client.get(
        "/api/v1/relatorios/ocupacao",
        params={"de": "2026-08-10", "ate": "2026-08-10"},
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 200, resp.text
    corpo = resp.json()

    itens = {item["recurso"]: item for item in corpo["por_recurso"]}
    assert "Campo Ocupação" in itens
    item = itens["Campo Ocupação"]
    assert item["horas_vendidas"] == 2.0
    assert item["horas_disponiveis"] == 15.0
    assert item["taxa"] == pytest.approx(2.0 / 15.0)


async def test_ocupacao_requer_admin(client, staff_atendente_logado):
    resp = await client.get(
        "/api/v1/relatorios/ocupacao",
        params={"de": "2026-08-10", "ate": "2026-08-10"},
        headers=staff_atendente_logado["headers"],
    )
    assert resp.status_code == 403
