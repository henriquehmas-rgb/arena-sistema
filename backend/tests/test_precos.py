"""Testes de `app.services.precos` (Task T5, Step 1) e do CRUD admin
`GET/POST/PUT/DELETE /precos`.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.entities import Auditoria, FaixaPreco, Recurso
from app.models.enums import TipoRecurso
from app.services.precos import PrecoNaoConfigurado, preco_para


def cuiaba(*args) -> datetime:
    """Datetime aware no fuso local (`settings.tz_local` = America/Cuiaba)."""
    return datetime(*args, tzinfo=ZoneInfo(settings.tz_local))


async def criar_campo(db) -> Recurso:
    campo = Recurso(nome="Campo T5", tipo=TipoRecurso.campo, ativo=True, ordem=1)
    db.add(campo)
    await db.flush()
    return campo


async def criar_quiosque(db) -> Recurso:
    quiosque = Recurso(nome="Quiosque T5", tipo=TipoRecurso.quiosque, ativo=True, ordem=2)
    db.add(quiosque)
    await db.flush()
    return quiosque


async def test_preco_por_faixa(db):
    campo = await criar_campo(db)
    db.add(
        FaixaPreco(
            recurso_id=campo.id,
            dias_semana=[0, 1, 2, 3, 4],
            hora_inicio=8,
            hora_fim=18,
            preco_centavos=15000,
        )
    )
    db.add(
        FaixaPreco(
            recurso_id=campo.id,
            dias_semana=[0, 1, 2, 3, 4],
            hora_inicio=18,
            hora_fim=23,
            preco_centavos=18000,
        )
    )
    await db.flush()

    # segunda 19h (UTC-4 Cuiabá) → faixa noturna
    assert await preco_para(db, campo, cuiaba(2026, 8, 10, 19), cuiaba(2026, 8, 10, 20)) == 18000


async def test_preco_por_faixa_diurna(db):
    campo = await criar_campo(db)
    db.add(
        FaixaPreco(
            recurso_id=campo.id,
            dias_semana=[0, 1, 2, 3, 4],
            hora_inicio=8,
            hora_fim=18,
            preco_centavos=15000,
        )
    )
    db.add(
        FaixaPreco(
            recurso_id=campo.id,
            dias_semana=[0, 1, 2, 3, 4],
            hora_inicio=18,
            hora_fim=23,
            preco_centavos=18000,
        )
    )
    await db.flush()

    # segunda 9h → faixa diurna
    assert await preco_para(db, campo, cuiaba(2026, 8, 10, 9), cuiaba(2026, 8, 10, 10)) == 15000


async def test_preco_nao_configurado_levanta_excecao(db):
    campo = await criar_campo(db)
    # nenhuma FaixaPreco cadastrada pro recurso
    with pytest.raises(PrecoNaoConfigurado):
        await preco_para(db, campo, cuiaba(2026, 8, 10, 9), cuiaba(2026, 8, 10, 10))


async def test_preco_respeita_dia_da_semana(db):
    campo = await criar_campo(db)
    db.add(
        FaixaPreco(
            recurso_id=campo.id,
            dias_semana=[5, 6],  # só sábado/domingo
            hora_inicio=8,
            hora_fim=23,
            preco_centavos=18000,
        )
    )
    await db.flush()

    # 2026-08-10 é segunda-feira → não cai em [5, 6]
    with pytest.raises(PrecoNaoConfigurado):
        await preco_para(db, campo, cuiaba(2026, 8, 10, 9), cuiaba(2026, 8, 10, 10))


# --- CRUD admin `/precos` (contrato: GET/POST/PUT/DELETE /precos (admin)) ---


async def test_crud_precos_admin(client, db, staff_admin_logado):
    campo = await criar_campo(db)

    resp = await client.post(
        "/api/v1/precos",
        json={
            "recurso_id": campo.id,
            "dias_semana": [0, 1, 2, 3, 4],
            "hora_inicio": 8,
            "hora_fim": 18,
            "preco_centavos": 15000,
        },
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 201, resp.text
    faixa_id = resp.json()["id"]

    resp = await client.get(
        f"/api/v1/precos?recurso_id={campo.id}", headers=staff_admin_logado["headers"]
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = await client.put(
        f"/api/v1/precos/{faixa_id}",
        json={
            "recurso_id": campo.id,
            "dias_semana": [0, 1, 2, 3, 4],
            "hora_inicio": 8,
            "hora_fim": 18,
            "preco_centavos": 16000,
        },
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["preco_centavos"] == 16000

    resp = await client.delete(
        f"/api/v1/precos/{faixa_id}", headers=staff_admin_logado["headers"]
    )
    assert resp.status_code == 204

    resultado = await db.execute(select(FaixaPreco).where(FaixaPreco.id == faixa_id))
    assert resultado.scalar_one_or_none() is None

    # Achado na revisão final de branch: o CRUD de preços não registrava
    # nada em auditoria — as 3 ações (criar/atualizar/remover) devem gerar
    # um registro cada, todas atribuídas ao admin autenticado.
    registros = (
        await db.execute(
            select(Auditoria)
            .where(Auditoria.entidade == "faixa_preco", Auditoria.entidade_id == faixa_id)
            .order_by(Auditoria.id)
        )
    ).scalars().all()
    assert [r.acao for r in registros] == ["criar", "atualizar", "remover"]
    assert all(r.staff_id == staff_admin_logado["staff"].id for r in registros)


async def test_precos_exige_autenticacao(client):
    resp = await client.get("/api/v1/precos")
    assert resp.status_code == 401
