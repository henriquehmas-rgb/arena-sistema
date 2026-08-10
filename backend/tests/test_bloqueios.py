"""Testes do CRUD `GET/POST/PUT/DELETE /bloqueios` (staff) — não existia
arquivo dedicado até a revisão final de branch encontrar que essas rotas
não registravam auditoria (achado corrigido junto com a criação deste
arquivo: as 3 ações mutáveis agora geram um registro cada)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.entities import Auditoria, Bloqueio, Recurso, Reserva
from app.models.enums import ReservaOrigem, ReservaStatus, TipoRecurso


async def _recurso(db, nome: str = "Campo Bloqueios") -> Recurso:
    r = Recurso(nome=nome, tipo=TipoRecurso.campo, ativo=True, ordem=1)
    db.add(r)
    await db.flush()
    return r


def _janela(dias: int = 10, horas: int = 1) -> tuple[str, str]:
    inicio = (datetime.now(timezone.utc) + timedelta(days=dias)).replace(
        minute=0, second=0, microsecond=0
    )
    fim = inicio + timedelta(hours=horas)
    return inicio.isoformat(), fim.isoformat()


async def test_crud_bloqueios_registra_auditoria(client, db, staff_admin_logado):
    recurso = await _recurso(db)
    headers = staff_admin_logado["headers"]
    inicio, fim = _janela()

    resp = await client.post(
        "/api/v1/bloqueios",
        json={"recurso_id": recurso.id, "inicio": inicio, "fim": fim, "motivo": "Manutenção"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    bloqueio_id = resp.json()["id"]

    inicio2, fim2 = _janela(dias=11)
    resp = await client.put(
        f"/api/v1/bloqueios/{bloqueio_id}",
        json={"recurso_id": recurso.id, "inicio": inicio2, "fim": fim2, "motivo": "Reforma"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["motivo"] == "Reforma"

    resp = await client.delete(f"/api/v1/bloqueios/{bloqueio_id}", headers=headers)
    assert resp.status_code == 204

    resultado = await db.execute(select(Bloqueio).where(Bloqueio.id == bloqueio_id))
    assert resultado.scalar_one_or_none() is None

    registros = (
        await db.execute(
            select(Auditoria)
            .where(Auditoria.entidade == "bloqueio", Auditoria.entidade_id == bloqueio_id)
            .order_by(Auditoria.id)
        )
    ).scalars().all()
    assert [r.acao for r in registros] == ["criar", "atualizar", "remover"]
    assert all(r.staff_id == staff_admin_logado["staff"].id for r in registros)


async def test_criar_bloqueio_conflito_com_reserva_confirmada_409(client, db, staff_admin_logado):
    recurso = await _recurso(db, nome="Campo Bloqueio Conflito")
    inicio, fim = _janela(dias=12)
    db.add(
        Reserva(
            recurso_id=recurso.id,
            inicio=datetime.fromisoformat(inicio),
            fim=datetime.fromisoformat(fim),
            status=ReservaStatus.confirmada,
            origem=ReservaOrigem.balcao,
            valor_centavos=10000,
        )
    )
    await db.flush()

    resp = await client.post(
        "/api/v1/bloqueios",
        json={"recurso_id": recurso.id, "inicio": inicio, "fim": fim, "motivo": "Manutenção"},
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 409
