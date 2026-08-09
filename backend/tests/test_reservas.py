"""Testes de `app.services.reservas` (Task T6, Step 1) e das rotas
`POST/GET /reservas`, `POST /reservas/balcao`, `POST /reservas/{id}/cancelar`
e `POST /reservas/{id}/cancelar-admin`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.entities import Cliente, FaixaPreco, Pagamento, Recurso, Reserva
from app.models.enums import (
    MetodoPagamento,
    PagamentoStatus,
    ReservaOrigem,
    ReservaStatus,
    TipoRecurso,
)
from app.services import reservas as reservas_service

PRECO_PADRAO_CENTAVOS = 10000


async def criar_recurso(db, nome: str = "Campo T6") -> Recurso:
    recurso = Recurso(nome=nome, tipo=TipoRecurso.campo, ativo=True, ordem=1)
    db.add(recurso)
    await db.flush()
    return recurso


async def criar_faixa_padrao(db, recurso: Recurso, preco_centavos: int = PRECO_PADRAO_CENTAVOS) -> FaixaPreco:
    """Faixa que cobre qualquer dia/hora — mantém os testes desta task
    focados no motor de reservas, não na resolução de preço por faixa
    (isso já é coberto por `tests/test_precos.py`, Task T5)."""
    faixa = FaixaPreco(
        recurso_id=recurso.id,
        dias_semana=[0, 1, 2, 3, 4, 5, 6],
        hora_inicio=0,
        hora_fim=24,
        preco_centavos=preco_centavos,
    )
    db.add(faixa)
    await db.flush()
    return faixa


async def criar_cliente(db, nome: str = "Cliente T6") -> Cliente:
    cliente = Cliente(nome=nome, email=f"{nome.lower().replace(' ', '')}@teste.com", celular="65999990000")
    db.add(cliente)
    await db.flush()
    return cliente


def horario_futuro(dias: int = 5, hora: int = 18) -> tuple[datetime, datetime]:
    """Slot `[inicio, fim)` de 1h, `dias` no futuro a partir de agora (UTC),
    suficientemente distante para nunca cair dentro da janela de
    cancelamento (`settings.cancelamento_horas`) nos testes que não a
    testam explicitamente."""
    base = (datetime.now(timezone.utc) + timedelta(days=dias)).replace(
        hour=hora, minute=0, second=0, microsecond=0
    )
    return base, base + timedelta(hours=1)


# --- criar_online: preço sempre recalculado no servidor ---------------------


async def test_criar_online_calcula_preco_no_servidor(db):
    recurso = await criar_recurso(db)
    await criar_faixa_padrao(db, recurso)
    cliente = await criar_cliente(db)
    inicio, fim = horario_futuro()

    reserva = await reservas_service.criar_online(db, cliente, recurso.id, inicio, fim)

    assert reserva.valor_centavos == PRECO_PADRAO_CENTAVOS
    assert reserva.status == ReservaStatus.pendente_pagamento
    assert reserva.origem == ReservaOrigem.online
    assert reserva.cliente_id == cliente.id


async def test_rota_criar_reserva_ignora_preco_do_payload(client, db, cliente_logado):
    recurso = await criar_recurso(db)
    await criar_faixa_padrao(db, recurso)
    inicio, fim = horario_futuro(dias=6)

    resp = await client.post(
        "/api/v1/reservas",
        json={
            "recurso_id": recurso.id,
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
            # Campo que o schema `ReservaCriar` não declara — mesmo que um
            # cliente malicioso o envie, não há como influenciar o preço:
            # `ReservaCriar` nem tem esse campo, então o Pydantic o descarta
            # antes do service sequer ver o payload.
            "valor_centavos": 1,
        },
        headers=cliente_logado["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["valor_centavos"] == PRECO_PADRAO_CENTAVOS
    assert resp.json()["expira_em"] is not None


# --- slot ocupado -> 409 -----------------------------------------------------


async def test_criar_online_slot_ocupado_levanta_erro(db):
    recurso = await criar_recurso(db)
    await criar_faixa_padrao(db, recurso)
    cliente = await criar_cliente(db)
    inicio, fim = horario_futuro()

    db.add(
        Reserva(
            recurso_id=recurso.id,
            inicio=inicio,
            fim=fim,
            status=ReservaStatus.confirmada,
            origem=ReservaOrigem.balcao,
            valor_centavos=0,
        )
    )
    await db.flush()

    with pytest.raises(reservas_service.SlotOcupadoError):
        await reservas_service.criar_online(db, cliente, recurso.id, inicio, fim)


async def test_rota_criar_reserva_slot_ocupado_409(client, db, cliente_logado):
    recurso = await criar_recurso(db)
    await criar_faixa_padrao(db, recurso)
    inicio, fim = horario_futuro(dias=7)

    db.add(
        Reserva(
            recurso_id=recurso.id,
            inicio=inicio,
            fim=fim,
            status=ReservaStatus.confirmada,
            origem=ReservaOrigem.balcao,
            valor_centavos=0,
        )
    )
    await db.flush()

    resp = await client.post(
        "/api/v1/reservas",
        json={
            "recurso_id": recurso.id,
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
        },
        headers=cliente_logado["headers"],
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "slot_ocupado"


# --- corrida real: IntegrityError da constraint EXCLUDE -> SlotOcupadoError -


async def test_corrida_simulada_converte_integrity_error(db, monkeypatch):
    """Simula a corrida entre duas requisições concorrentes: a checagem
    otimista (`esta_livre`) por si só não bastaria (é só uma leitura antes
    do insert) — quem garante a exclusão mútua de verdade é a constraint
    EXCLUDE do banco (Task T2). Aqui forçamos a segunda tentativa a passar
    pela checagem otimista (como se a primeira ainda não tivesse sido
    "vista" por ela, replicando a janela de corrida) para exercitar
    especificamente a conversão `IntegrityError` -> `SlotOcupadoError` no
    INSERT em si."""
    recurso = await criar_recurso(db)
    await criar_faixa_padrao(db, recurso)
    cliente_a = await criar_cliente(db, nome="Cliente Corrida A")
    cliente_b = await criar_cliente(db, nome="Cliente Corrida B")
    inicio, fim = horario_futuro(dias=8)

    # "Sessão" 1: primeira requisição, slot livre de verdade -> sucesso.
    primeira = await reservas_service.criar_online(db, cliente_a, recurso.id, inicio, fim)
    assert primeira.status == ReservaStatus.pendente_pagamento

    # "Sessão" 2: chega "ao mesmo tempo" que a primeira, então sua checagem
    # otimista também enxergaria o slot livre -- simulado aqui forçando
    # `esta_livre` a sempre responder True para esta chamada.
    async def _sempre_livre(*args, **kwargs):
        return True

    monkeypatch.setattr(reservas_service, "esta_livre", _sempre_livre)

    with pytest.raises(reservas_service.SlotOcupadoError):
        await reservas_service.criar_online(db, cliente_b, recurso.id, inicio, fim)

    # A sessão continua utilizável após o rollback do savepoint do INSERT
    # que falhou -- confirma que `_inserir` não derruba a transação inteira.
    total = (
        await db.execute(
            select(Reserva).where(
                Reserva.recurso_id == recurso.id, Reserva.inicio == inicio
            )
        )
    ).scalars().all()
    assert len(total) == 1


# --- balcão: nasce confirmada + Pagamento pago -------------------------------


async def test_criar_balcao_confirmada_com_pagamento(db):
    recurso = await criar_recurso(db)
    await criar_faixa_padrao(db, recurso)
    from app.models.entities import Staff
    from app.models.enums import PapelStaff

    staff = Staff(
        nome="Atendente T6",
        email="atendente-t6@arenacacerense.com.br",
        senha_hash="x",
        papel=PapelStaff.atendente,
        ativo=True,
    )
    db.add(staff)
    await db.flush()

    from app.schemas.reservas import ReservaBalcaoCriar

    inicio, fim = horario_futuro(dias=9)
    dados = ReservaBalcaoCriar(
        recurso_id=recurso.id,
        inicio=inicio,
        fim=fim,
        nome_avulso="Fulano Avulso",
        celular_avulso="65988887777",
        metodo=MetodoPagamento.dinheiro,
    )

    reserva = await reservas_service.criar_balcao(db, staff, dados)

    assert reserva.status == ReservaStatus.confirmada
    assert reserva.origem == ReservaOrigem.balcao
    assert reserva.valor_centavos == PRECO_PADRAO_CENTAVOS

    pagamento = (
        await db.execute(select(Pagamento).where(Pagamento.reserva_id == reserva.id))
    ).scalar_one()
    assert pagamento.metodo == MetodoPagamento.dinheiro
    assert pagamento.status == PagamentoStatus.pago
    assert pagamento.registrado_por_staff_id == staff.id


async def test_rota_balcao(client, db, staff_admin_logado):
    recurso = await criar_recurso(db, nome="Campo T6 Balcao Rota")
    await criar_faixa_padrao(db, recurso)
    inicio, fim = horario_futuro(dias=10)

    resp = await client.post(
        "/api/v1/reservas/balcao",
        json={
            "recurso_id": recurso.id,
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
            "nome_avulso": "Cliente Balcao",
            "celular_avulso": "65977776666",
            "metodo": "dinheiro",
        },
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "confirmada"


# --- cancelamento cliente: dentro/fora da janela -----------------------------


async def test_cancelar_cliente_dentro_da_janela(db):
    cliente = await criar_cliente(db)
    recurso = await criar_recurso(db, nome="Campo T6 Cancelar OK")
    inicio = datetime.now(timezone.utc) + timedelta(hours=settings.cancelamento_horas + 5)
    fim = inicio + timedelta(hours=1)

    reserva = Reserva(
        recurso_id=recurso.id,
        cliente_id=cliente.id,
        inicio=inicio,
        fim=fim,
        status=ReservaStatus.pendente_pagamento,
        origem=ReservaOrigem.online,
        valor_centavos=PRECO_PADRAO_CENTAVOS,
    )
    db.add(reserva)
    await db.flush()

    resultado = await reservas_service.cancelar_cliente(db, cliente, reserva.id)
    assert resultado.status == ReservaStatus.cancelada


async def test_cancelar_cliente_fora_da_janela_levanta_erro(db):
    cliente = await criar_cliente(db)
    recurso = await criar_recurso(db, nome="Campo T6 Cancelar Fora")
    inicio = datetime.now(timezone.utc) + timedelta(hours=1)  # < cancelamento_horas
    fim = inicio + timedelta(hours=1)

    reserva = Reserva(
        recurso_id=recurso.id,
        cliente_id=cliente.id,
        inicio=inicio,
        fim=fim,
        status=ReservaStatus.pendente_pagamento,
        origem=ReservaOrigem.online,
        valor_centavos=PRECO_PADRAO_CENTAVOS,
    )
    db.add(reserva)
    await db.flush()

    with pytest.raises(reservas_service.ForaDaJanelaError):
        await reservas_service.cancelar_cliente(db, cliente, reserva.id)


async def test_rota_cancelar_fora_da_janela_422(client, db, cliente_logado):
    recurso = await criar_recurso(db, nome="Campo T6 Cancelar Rota 422")
    inicio = datetime.now(timezone.utc) + timedelta(hours=1)
    fim = inicio + timedelta(hours=1)

    reserva = Reserva(
        recurso_id=recurso.id,
        cliente_id=cliente_logado["cliente"].id,
        inicio=inicio,
        fim=fim,
        status=ReservaStatus.pendente_pagamento,
        origem=ReservaOrigem.online,
        valor_centavos=PRECO_PADRAO_CENTAVOS,
    )
    db.add(reserva)
    await db.flush()

    resp = await client.post(
        f"/api/v1/reservas/{reserva.id}/cancelar", headers=cliente_logado["headers"]
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "fora_da_janela"


async def test_rota_cancelar_dentro_da_janela_200(client, db, cliente_logado):
    recurso = await criar_recurso(db, nome="Campo T6 Cancelar Rota 200")
    inicio = datetime.now(timezone.utc) + timedelta(hours=settings.cancelamento_horas + 5)
    fim = inicio + timedelta(hours=1)

    reserva = Reserva(
        recurso_id=recurso.id,
        cliente_id=cliente_logado["cliente"].id,
        inicio=inicio,
        fim=fim,
        status=ReservaStatus.pendente_pagamento,
        origem=ReservaOrigem.online,
        valor_centavos=PRECO_PADRAO_CENTAVOS,
    )
    db.add(reserva)
    await db.flush()

    resp = await client.post(
        f"/api/v1/reservas/{reserva.id}/cancelar", headers=cliente_logado["headers"]
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelada"


# --- cancelamento admin -------------------------------------------------------


async def test_rota_cancelar_admin(client, db, staff_admin_logado):
    recurso = await criar_recurso(db, nome="Campo T6 Cancelar Admin")
    inicio, fim = horario_futuro(dias=11)

    reserva = Reserva(
        recurso_id=recurso.id,
        inicio=inicio,
        fim=fim,
        status=ReservaStatus.confirmada,
        origem=ReservaOrigem.balcao,
        valor_centavos=PRECO_PADRAO_CENTAVOS,
    )
    db.add(reserva)
    await db.flush()

    resp = await client.post(
        f"/api/v1/reservas/{reserva.id}/cancelar-admin",
        json={"estornar": False},
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelada"


# --- GET /reservas (staff), paginada -----------------------------------------


async def test_rota_listar_staff_paginada(client, db, staff_admin_logado):
    recurso = await criar_recurso(db, nome="Campo T6 Listar Staff")
    base = datetime.now(timezone.utc) + timedelta(days=20)
    for i in range(3):
        db.add(
            Reserva(
                recurso_id=recurso.id,
                inicio=base + timedelta(hours=i),
                fim=base + timedelta(hours=i + 1),
                status=ReservaStatus.confirmada,
                origem=ReservaOrigem.balcao,
                valor_centavos=PRECO_PADRAO_CENTAVOS,
            )
        )
    await db.flush()

    resp = await client.get(
        f"/api/v1/reservas?recurso_id={recurso.id}&limit=2&offset=0",
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["total"] == 3
    assert len(corpo["itens"]) == 2


async def test_rota_listar_staff_filtra_por_cliente_id(client, db, staff_admin_logado):
    """Achado de code review (privacidade): `GET /reservas?cliente_id=X` deve
    devolver SÓ as reservas do cliente X — sem esse filtro, a tela "Histórico
    do cliente" do admin vazava reservas de outros clientes (o backend
    ignorava silenciosamente o parâmetro desconhecido e devolvia a lista
    geral paginada)."""
    recurso = await criar_recurso(db, nome="Campo T6 Cliente Filtro")
    cliente_a = await criar_cliente(db, nome="Cliente Filtro A")
    cliente_b = await criar_cliente(db, nome="Cliente Filtro B")
    base = datetime.now(timezone.utc) + timedelta(days=21)

    db.add(
        Reserva(
            recurso_id=recurso.id,
            cliente_id=cliente_a.id,
            inicio=base,
            fim=base + timedelta(hours=1),
            status=ReservaStatus.confirmada,
            origem=ReservaOrigem.online,
            valor_centavos=PRECO_PADRAO_CENTAVOS,
        )
    )
    db.add(
        Reserva(
            recurso_id=recurso.id,
            cliente_id=cliente_b.id,
            inicio=base + timedelta(hours=2),
            fim=base + timedelta(hours=3),
            status=ReservaStatus.confirmada,
            origem=ReservaOrigem.online,
            valor_centavos=PRECO_PADRAO_CENTAVOS,
        )
    )
    await db.flush()

    resp = await client.get(
        f"/api/v1/reservas?cliente_id={cliente_a.id}",
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["total"] == 1
    assert len(corpo["itens"]) == 1
    # `ReservaOut` não expõe `cliente_id` diretamente, mas o horário de início
    # identifica de forma inequívoca qual das duas reservas voltou: só a do
    # cliente A (`base`), nunca a do cliente B (`base + 2h`) — é exatamente
    # o vazamento que este teste existe para prevenir.
    assert datetime.fromisoformat(corpo["itens"][0]["inicio"]) == base

    # Confere também pelo lado do cliente B, para não passar "por acaso"
    # caso o filtro esteja invertido ou não fazendo nada.
    resp_b = await client.get(
        f"/api/v1/reservas?cliente_id={cliente_b.id}",
        headers=staff_admin_logado["headers"],
    )
    assert resp_b.status_code == 200, resp_b.text
    corpo_b = resp_b.json()
    assert corpo_b["total"] == 1
    assert datetime.fromisoformat(corpo_b["itens"][0]["inicio"]) == base + timedelta(hours=2)
