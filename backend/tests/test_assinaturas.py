"""Testes de `app.services.assinaturas` (Task T9).

Sobre o `FakePagarmeClient`: `app/services/pagarme.py` é responsabilidade da
Task T7, rodando em paralelo com esta (T9). Para não acoplar este arquivo ao
momento em que aquela task termina de implementar o módulo real, os testes
aqui usam um fake local que implementa a mesma interface combinada (ver
docstring de `app/services/assinaturas.py`) e o injetam via
`monkeypatch.setattr(assinaturas_service, "get_pagarme", ...)`. Isso
funciona independente de `app/services/pagarme.py` existir ou não nesta
run — quando a Task T7 terminar, o import real (`from app.services.pagarme
import get_pagarme`) passa a funcionar em produção sem qualquer mudança
aqui, já que estes testes nunca dependem do valor *padrão* de
`get_pagarme`, sempre o substituem.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.entities import Auditoria, Cliente, Recurso, Reserva, Staff
from app.models.enums import (
    AssinaturaStatus,
    PapelStaff,
    ReservaOrigem,
    ReservaStatus,
    TipoRecurso,
)
from app.schemas.assinaturas import AssinaturaCriar
from app.services import assinaturas as assinaturas_service


@dataclass
class FakeSubResult:
    subscription_id: str
    status: str


class FakePagarmeClient:
    """Fake local da interface combinada de `app.services.pagarme`
    (contrato congelado na Wave 0, implementação real é da Task T7)."""

    def __init__(self) -> None:
        self.subscriptions_criadas: list[str] = []
        self.subscriptions_canceladas: list[str] = []
        self._contador = 0

    async def criar_order_pix(self, cliente, valor_centavos, descricao):  # pragma: no cover
        raise NotImplementedError

    async def criar_order_cartao(
        self, cliente, valor_centavos, descricao, card_token
    ):  # pragma: no cover
        raise NotImplementedError

    async def consultar_order(self, order_id):  # pragma: no cover
        raise NotImplementedError

    async def estornar_charge(self, charge_id):  # pragma: no cover
        raise NotImplementedError

    async def criar_subscription(
        self, cliente, valor_centavos, dia_cobranca, metodo, card_token=None
    ) -> FakeSubResult:
        self._contador += 1
        sub_id = f"sub_fake_{self._contador}"
        self.subscriptions_criadas.append(sub_id)
        return FakeSubResult(subscription_id=sub_id, status="ativa")

    async def cancelar_subscription(self, sub_id) -> bool:
        self.subscriptions_canceladas.append(sub_id)
        return True


@pytest.fixture
def fake_pagarme(monkeypatch):
    fake = FakePagarmeClient()
    monkeypatch.setattr(assinaturas_service, "get_pagarme", lambda: fake)
    return fake


async def _recurso(db, nome="Campo Assinaturas") -> Recurso:
    r = Recurso(nome=nome, tipo=TipoRecurso.campo, ativo=True, ordem=1)
    db.add(r)
    await db.flush()
    return r


async def _cliente(db, sufixo="a") -> Cliente:
    c = Cliente(
        nome=f"Cliente {sufixo}",
        email=f"assinante-{sufixo}@teste.com",
        celular="65999990000",
    )
    db.add(c)
    await db.flush()
    return c


async def _staff(db) -> Staff:
    s = Staff(
        nome="Staff Teste",
        email="staff-assinaturas@teste.com",
        senha_hash="x",
        papel=PapelStaff.atendente,
        ativo=True,
    )
    db.add(s)
    await db.flush()
    return s


def _dados(
    recurso_id: int,
    cliente_id: int,
    dia_semana: int = 0,  # segunda
    hora_inicio: int = 19,
    hora_fim: int = 20,
    valor: int = 15000,
) -> AssinaturaCriar:
    return AssinaturaCriar(
        cliente_id=cliente_id,
        recurso_id=recurso_id,
        dia_semana=dia_semana,
        hora_inicio=hora_inicio,
        hora_fim=hora_fim,
        valor_mensal_centavos=valor,
        metodo="pix",
    )


async def test_criar_assinatura_gera_subscription_no_client_simulado(db, fake_pagarme):
    recurso = await _recurso(db)
    cliente = await _cliente(db)
    staff = await _staff(db)

    assinatura = await assinaturas_service.criar(db, staff, _dados(recurso.id, cliente.id))

    assert assinatura.id is not None
    assert assinatura.status == AssinaturaStatus.ativa
    assert assinatura.pagarme_subscription_id in fake_pagarme.subscriptions_criadas
    assert len(fake_pagarme.subscriptions_criadas) == 1


# Achado na revisão final de branch: a subscription já existe (e já cobra)
# na Pagar.me antes do commit local — se o commit falhar, ficaria uma
# cobrança recorrente real sem nenhum registro local pra encontrá-la depois.
async def test_criar_falha_apos_subscription_compensa_com_cancelamento(
    db, fake_pagarme, monkeypatch
):
    recurso = await _recurso(db)
    cliente = await _cliente(db)
    staff = await _staff(db)

    async def _flush_com_falha():
        raise RuntimeError("falha simulada de commit local")

    monkeypatch.setattr(db, "flush", _flush_com_falha)

    with pytest.raises(RuntimeError, match="falha simulada"):
        await assinaturas_service.criar(db, staff, _dados(recurso.id, cliente.id))

    assert len(fake_pagarme.subscriptions_criadas) == 1
    assert fake_pagarme.subscriptions_criadas[0] in fake_pagarme.subscriptions_canceladas


async def test_criar_conflito_com_outra_assinatura_ativa_409(db, fake_pagarme):
    recurso = await _recurso(db)
    cliente1 = await _cliente(db, "1")
    cliente2 = await _cliente(db, "2")
    staff = await _staff(db)

    await assinaturas_service.criar(db, staff, _dados(recurso.id, cliente1.id))

    with pytest.raises(HTTPException) as exc_info:
        await assinaturas_service.criar(db, staff, _dados(recurso.id, cliente2.id))
    assert exc_info.value.status_code == 409


async def test_criar_conflito_com_bloqueio_existente_409(db, fake_pagarme):
    from app.models.entities import Bloqueio
    from app.services.assinaturas import _ocorrencia_semanal

    recurso = await _recurso(db)
    cliente = await _cliente(db)
    staff = await _staff(db)

    inicio_utc, fim_utc = _ocorrencia_semanal(dia_semana=0, hora_inicio=19, hora_fim=20)
    db.add(Bloqueio(recurso_id=recurso.id, inicio=inicio_utc, fim=fim_utc, motivo="manutencao"))
    await db.flush()

    with pytest.raises(HTTPException) as exc_info:
        await assinaturas_service.criar(db, staff, _dados(recurso.id, cliente.id))
    assert exc_info.value.status_code == 409


async def test_materializar_cria_exatamente_5_e_e_idempotente(db, fake_pagarme):
    recurso = await _recurso(db)
    cliente = await _cliente(db)
    staff = await _staff(db)
    assinatura = await assinaturas_service.criar(db, staff, _dados(recurso.id, cliente.id))

    criadas_1 = await assinaturas_service.materializar(db, semanas=5)
    assert criadas_1 == 5

    reservas = (
        await db.execute(select(Reserva).where(Reserva.assinatura_id == assinatura.id))
    ).scalars().all()
    assert len(reservas) == 5
    assert all(r.status == ReservaStatus.confirmada for r in reservas)
    assert all(r.origem == ReservaOrigem.mensalista for r in reservas)
    assert all(r.assinatura_id == assinatura.id for r in reservas)

    # Idempotente: rodar de novo não cria reservas duplicadas.
    criadas_2 = await assinaturas_service.materializar(db, semanas=5)
    assert criadas_2 == 0

    reservas_depois = (
        await db.execute(select(Reserva).where(Reserva.assinatura_id == assinatura.id))
    ).scalars().all()
    assert len(reservas_depois) == 5


async def test_materializar_pula_conflito_com_bloqueio_sem_quebrar(db, fake_pagarme, caplog):
    from app.models.entities import Bloqueio
    from app.services.assinaturas import _ocorrencia_semanal

    recurso = await _recurso(db)
    cliente = await _cliente(db)
    staff = await _staff(db)
    assinatura = await assinaturas_service.criar(db, staff, _dados(recurso.id, cliente.id))

    # Bloqueia a 3a ocorrência futura (semana=2).
    inicio_bloqueado, fim_bloqueado = _ocorrencia_semanal(
        dia_semana=0, hora_inicio=19, hora_fim=20, semanas_a_frente=2
    )
    db.add(
        Bloqueio(
            recurso_id=recurso.id,
            inicio=inicio_bloqueado,
            fim=fim_bloqueado,
            motivo="manutencao",
        )
    )
    await db.flush()

    with caplog.at_level("WARNING"):
        criadas = await assinaturas_service.materializar(db, semanas=5)

    # 5 ocorrências pedidas, 1 bloqueada -> só 4 reservas criadas, sem exceção.
    assert criadas == 4
    reservas = (
        await db.execute(select(Reserva).where(Reserva.assinatura_id == assinatura.id))
    ).scalars().all()
    assert len(reservas) == 4
    assert not any(r.inicio == inicio_bloqueado for r in reservas)
    assert any("conflito com bloqueio" in m for m in caplog.messages)


async def test_processar_evento_2_falhas_consecutivas_marca_inadimplente_e_para_materializar(
    db, fake_pagarme
):
    recurso = await _recurso(db)
    cliente = await _cliente(db)
    staff = await _staff(db)
    assinatura = await assinaturas_service.criar(db, staff, _dados(recurso.id, cliente.id))
    sub_id = assinatura.pagarme_subscription_id

    await assinaturas_service.processar_evento_sub(
        db, {"type": "invoice.payment_failed", "subscription_id": sub_id}
    )
    await db.refresh(assinatura)
    assert assinatura.status == AssinaturaStatus.ativa  # 1a falha isolada ainda não derruba

    await assinaturas_service.processar_evento_sub(
        db, {"type": "invoice.payment_failed", "subscription_id": sub_id}
    )
    await db.refresh(assinatura)
    assert assinatura.status == AssinaturaStatus.inadimplente

    criadas = await assinaturas_service.materializar(db, semanas=5)
    assert criadas == 0


async def test_processar_evento_fatura_paga_reativa_e_zera_contador(db, fake_pagarme):
    recurso = await _recurso(db)
    cliente = await _cliente(db)
    staff = await _staff(db)
    assinatura = await assinaturas_service.criar(db, staff, _dados(recurso.id, cliente.id))
    sub_id = assinatura.pagarme_subscription_id

    await assinaturas_service.processar_evento_sub(
        db, {"type": "invoice.payment_failed", "subscription_id": sub_id}
    )
    await assinaturas_service.processar_evento_sub(
        db, {"type": "invoice.paid", "subscription_id": sub_id}
    )
    await db.refresh(assinatura)
    assert assinatura.status == AssinaturaStatus.ativa
    assert assinatura.proxima_cobranca is not None

    # Contador de falhas foi zerado: agora precisa de 2 falhas *novas* para
    # cair em inadimplente de novo, não 1.
    await assinaturas_service.processar_evento_sub(
        db, {"type": "invoice.payment_failed", "subscription_id": sub_id}
    )
    await db.refresh(assinatura)
    assert assinatura.status == AssinaturaStatus.ativa


async def test_cancelar_chama_pagarme_e_remove_reservas_futuras(db, fake_pagarme):
    recurso = await _recurso(db)
    cliente = await _cliente(db)
    staff = await _staff(db)
    assinatura = await assinaturas_service.criar(db, staff, _dados(recurso.id, cliente.id))
    sub_id = assinatura.pagarme_subscription_id

    await assinaturas_service.materializar(db, semanas=5)
    reservas_antes = (
        await db.execute(select(Reserva).where(Reserva.assinatura_id == assinatura.id))
    ).scalars().all()
    assert len(reservas_antes) == 5

    await assinaturas_service.cancelar(db, assinatura.id)

    assert sub_id in fake_pagarme.subscriptions_canceladas

    reservas_depois = (
        await db.execute(select(Reserva).where(Reserva.assinatura_id == assinatura.id))
    ).scalars().all()
    assert reservas_depois == []

    await db.refresh(assinatura)
    assert assinatura.status == AssinaturaStatus.cancelada


async def test_pausar_e_reativar(db, fake_pagarme):
    recurso = await _recurso(db)
    cliente = await _cliente(db)
    staff = await _staff(db)
    assinatura = await assinaturas_service.criar(db, staff, _dados(recurso.id, cliente.id))
    sub_original = assinatura.pagarme_subscription_id

    pausada = await assinaturas_service.pausar(db, assinatura.id)
    assert pausada.status == AssinaturaStatus.pausada
    # Achado na revisão final de branch: pausar só trocava o status local —
    # a cobrança real continuava rodando. Agora cancela a subscription de
    # verdade na Pagar.me e limpa o id local.
    assert sub_original in fake_pagarme.subscriptions_canceladas
    assert pausada.pagarme_subscription_id is None

    # Assinatura pausada não é materializada (só `ativa` conta).
    criadas = await assinaturas_service.materializar(db, semanas=5)
    assert criadas == 0

    reativada = await assinaturas_service.reativar(db, assinatura.id)
    assert reativada.status == AssinaturaStatus.ativa
    # Reativar cria uma subscription NOVA (a antiga foi cancelada de
    # verdade, não só "escondida" localmente) — nunca reaproveita o id
    # antigo nem fica sem nenhuma subscription associada.
    assert reativada.pagarme_subscription_id is not None
    assert reativada.pagarme_subscription_id != sub_original
    assert len(fake_pagarme.subscriptions_criadas) == 2

    criadas_depois = await assinaturas_service.materializar(db, semanas=5)
    assert criadas_depois == 5


# Achado na revisão final de branch: nenhuma rota de /assinaturas
# registrava auditoria — criar/pausar/reativar/cancelar devem gerar um
# registro cada, via HTTP (não chamando o service direto), pra cobrir o
# router de ponta a ponta.
async def test_rotas_assinaturas_registram_auditoria(
    client, db, staff_admin_logado, fake_pagarme
):
    recurso = await _recurso(db, nome="Campo Auditoria Assinatura")
    cliente = await _cliente(db, "auditoria")
    headers = staff_admin_logado["headers"]

    resp = await client.post(
        "/api/v1/assinaturas",
        json={
            "cliente_id": cliente.id,
            "recurso_id": recurso.id,
            "dia_semana": 0,
            "hora_inicio": 19,
            "hora_fim": 20,
            "valor_mensal_centavos": 15000,
            "metodo": "pix",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assinatura_id = resp.json()["id"]

    for acao in ("pausar", "reativar", "cancelar"):
        resp = await client.post(
            f"/api/v1/assinaturas/{assinatura_id}/{acao}", headers=headers
        )
        assert resp.status_code == 200, resp.text

    registros = (
        await db.execute(
            select(Auditoria)
            .where(Auditoria.entidade == "assinatura", Auditoria.entidade_id == assinatura_id)
            .order_by(Auditoria.id)
        )
    ).scalars().all()
    assert [r.acao for r in registros] == ["criar", "pausar", "reativar", "cancelar"]
    assert all(r.staff_id == staff_admin_logado["staff"].id for r in registros)
