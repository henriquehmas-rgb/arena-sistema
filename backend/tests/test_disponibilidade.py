"""Testes de `app.services.disponibilidade` (Task T5, Step 1) e das rotas
públicas `GET /recursos` / `GET /disponibilidade`, além do CRUD staff
`/bloqueios`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.models.entities import Bloqueio, FaixaPreco, Recurso, Reserva
from app.models.enums import ReservaOrigem, ReservaStatus, TipoRecurso
from app.services.disponibilidade import PERIODOS_QUIOSQUE, esta_livre, slots_do_dia

TZ = ZoneInfo(settings.tz_local)


def cuiaba(*args) -> datetime:
    return datetime(*args, tzinfo=TZ)


async def criar_campo(db, nome: str = "Campo T5") -> Recurso:
    campo = Recurso(nome=nome, tipo=TipoRecurso.campo, ativo=True, ordem=1)
    db.add(campo)
    await db.flush()
    db.add(
        FaixaPreco(
            recurso_id=campo.id,
            dias_semana=[0, 1, 2, 3, 4, 5, 6],
            hora_inicio=8,
            hora_fim=23,
            preco_centavos=15000,
        )
    )
    await db.flush()
    return campo


async def criar_quiosque(db, nome: str = "Quiosque T5") -> Recurso:
    quiosque = Recurso(nome=nome, tipo=TipoRecurso.quiosque, ativo=True, ordem=2)
    db.add(quiosque)
    await db.flush()
    db.add(
        FaixaPreco(
            recurso_id=quiosque.id,
            dias_semana=[0, 1, 2, 3, 4, 5, 6],
            hora_inicio=8,
            hora_fim=22,
            preco_centavos=25000,
        )
    )
    await db.flush()
    return quiosque


# Data bem futura (dentro da janela de 60d do quiosque a partir de "hoje",
# mas usada aqui só como referência fixa para os slots — os testes de
# serviço não checam janela, isso é responsabilidade do router).
DIA_FUTURO = date.today() + timedelta(days=3)


def _hora_local(hora: int) -> datetime:
    return cuiaba(DIA_FUTURO.year, DIA_FUTURO.month, DIA_FUTURO.day, hora)


async def test_slots_marcam_ocupado_por_reserva_bloqueio(db):
    campo = await criar_campo(db)

    db.add(
        Reserva(
            recurso_id=campo.id,
            inicio=_hora_local(18).astimezone(ZoneInfo("UTC")),
            fim=_hora_local(19).astimezone(ZoneInfo("UTC")),
            status=ReservaStatus.confirmada,
            origem=ReservaOrigem.balcao,
            valor_centavos=15000,
        )
    )
    db.add(
        Bloqueio(
            recurso_id=campo.id,
            inicio=_hora_local(20).astimezone(ZoneInfo("UTC")),
            fim=_hora_local(21).astimezone(ZoneInfo("UTC")),
            motivo="manutenção",
        )
    )
    await db.flush()

    slots = await slots_do_dia(db, campo, DIA_FUTURO)

    por_hora = {s.inicio.astimezone(TZ).hour: s for s in slots}
    assert por_hora[18].livre is False
    assert por_hora[20].livre is False
    for hora, slot in por_hora.items():
        if hora not in (18, 20):
            assert slot.livre is True, f"slot {hora}h deveria estar livre"


async def test_quiosque_gera_periodos(db):
    quiosque = await criar_quiosque(db)

    slots = await slots_do_dia(db, quiosque, DIA_FUTURO)

    assert len(slots) == 4
    gerados = {(s.inicio.astimezone(TZ).hour, s.fim.astimezone(TZ).hour) for s in slots}
    assert gerados == set(PERIODOS_QUIOSQUE)
    assert all(s.livre for s in slots)


async def test_campo_gera_15_slots_horas_cheias(db):
    campo = await criar_campo(db)
    slots = await slots_do_dia(db, campo, DIA_FUTURO)
    # 08..22 (último início 22h, fim 23h) → 15 slots de 1h
    assert len(slots) == 15
    assert slots[0].inicio.astimezone(TZ).hour == 8
    assert slots[-1].inicio.astimezone(TZ).hour == 22
    assert slots[-1].fim.astimezone(TZ).hour == 23


async def test_slot_passado_fica_indisponivel(db):
    campo = await criar_campo(db)
    ontem = date.today() - timedelta(days=1)
    slots = await slots_do_dia(db, campo, ontem)
    assert all(s.livre is False for s in slots)


async def test_esta_livre_true_sem_conflito(db):
    campo = await criar_campo(db)
    inicio = cuiaba(DIA_FUTURO.year, DIA_FUTURO.month, DIA_FUTURO.day, 10).astimezone(
        ZoneInfo("UTC")
    )
    fim = inicio + timedelta(hours=1)
    assert await esta_livre(db, campo.id, inicio, fim) is True


async def test_esta_livre_false_com_reserva(db):
    campo = await criar_campo(db)
    inicio = cuiaba(DIA_FUTURO.year, DIA_FUTURO.month, DIA_FUTURO.day, 10).astimezone(
        ZoneInfo("UTC")
    )
    fim = inicio + timedelta(hours=1)
    db.add(
        Reserva(
            recurso_id=campo.id,
            inicio=inicio,
            fim=fim,
            status=ReservaStatus.pendente_pagamento,
            origem=ReservaOrigem.online,
            valor_centavos=15000,
        )
    )
    await db.flush()

    assert await esta_livre(db, campo.id, inicio, fim) is False


# --- Rotas públicas GET /recursos e GET /disponibilidade ---


async def test_get_recursos_publico(client, db):
    await criar_campo(db, nome="Campo Público")

    resp = await client.get("/api/v1/recursos")
    assert resp.status_code == 200
    nomes = [r["nome"] for r in resp.json()]
    assert "Campo Público" in nomes


async def test_get_disponibilidade_publico(client, db):
    campo = await criar_campo(db)

    resp = await client.get(
        "/api/v1/disponibilidade",
        params={"recurso_id": campo.id, "data": DIA_FUTURO.isoformat()},
    )
    assert resp.status_code == 200
    corpo = resp.json()
    assert len(corpo["slots"]) == 15
    assert all(s["preco_centavos"] == 15000 for s in corpo["slots"])


async def test_get_disponibilidade_alem_da_janela_retorna_422(client, db):
    campo = await criar_campo(db)
    data_distante = (date.today() + timedelta(days=settings.janela_campo_dias + 5)).isoformat()

    resp = await client.get(
        "/api/v1/disponibilidade",
        params={"recurso_id": campo.id, "data": data_distante},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "janela_excedida"


async def test_get_disponibilidade_quiosque_janela_maior(client, db):
    quiosque = await criar_quiosque(db)
    # dentro da janela de quiosque (60d) mas além da de campo (14d)
    data = (date.today() + timedelta(days=settings.janela_campo_dias + 5)).isoformat()

    resp = await client.get(
        "/api/v1/disponibilidade",
        params={"recurso_id": quiosque.id, "data": data},
    )
    assert resp.status_code == 200


# --- CRUD staff `/bloqueios` (contrato: GET/POST/PUT/DELETE /bloqueios (staff)) ---


async def test_criar_bloqueio(client, db, staff_admin_logado):
    campo = await criar_campo(db)

    resp = await client.post(
        "/api/v1/bloqueios",
        json={
            "recurso_id": campo.id,
            "inicio": cuiaba(DIA_FUTURO.year, DIA_FUTURO.month, DIA_FUTURO.day, 9).isoformat(),
            "fim": cuiaba(DIA_FUTURO.year, DIA_FUTURO.month, DIA_FUTURO.day, 10).isoformat(),
            "motivo": "manutenção do gramado",
        },
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 201, resp.text
    bloqueio_id = resp.json()["id"]

    resp = await client.get(
        f"/api/v1/bloqueios?recurso_id={campo.id}", headers=staff_admin_logado["headers"]
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = await client.delete(
        f"/api/v1/bloqueios/{bloqueio_id}", headers=staff_admin_logado["headers"]
    )
    assert resp.status_code == 204


async def test_criar_bloqueio_sobrepondo_reserva_confirmada_retorna_409(
    client, db, staff_admin_logado
):
    campo = await criar_campo(db)
    inicio = cuiaba(DIA_FUTURO.year, DIA_FUTURO.month, DIA_FUTURO.day, 18).astimezone(
        ZoneInfo("UTC")
    )
    fim = inicio + timedelta(hours=1)
    db.add(
        Reserva(
            recurso_id=campo.id,
            inicio=inicio,
            fim=fim,
            status=ReservaStatus.confirmada,
            origem=ReservaOrigem.balcao,
            valor_centavos=15000,
        )
    )
    await db.flush()

    resp = await client.post(
        "/api/v1/bloqueios",
        json={
            "recurso_id": campo.id,
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
            "motivo": "manutenção",
        },
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 409
    corpo = resp.json()["detail"]
    assert corpo["detail"] == "conflito_com_reservas"
    assert len(corpo["conflitos"]) == 1


async def test_bloqueios_exige_autenticacao(client):
    resp = await client.get("/api/v1/bloqueios")
    assert resp.status_code == 401
