"""Achado na revisão final de branch: `JWT_SECRET` tem um default inseguro
conhecido (`dev-inseguro-trocar`, visível no repositório público) e nada
impedia subir em `sandbox`/`producao` com esse valor — um deploy que
esquecesse de gerar um segredo real aceitaria tokens forjados pra qualquer
cliente/staff sem erro nenhum. `_verificar_jwt_secret_producao` recusa
subir nesse cenário."""

from __future__ import annotations

import pytest

from app.config import settings
from app.main import JWT_SECRET_PADRAO_INSEGURO, _verificar_jwt_secret_producao


def test_recusa_subir_com_secret_padrao_em_producao(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", JWT_SECRET_PADRAO_INSEGURO)
    monkeypatch.setattr(settings, "pagarme_mode", "producao")

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        _verificar_jwt_secret_producao()


def test_recusa_subir_com_secret_padrao_em_sandbox(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", JWT_SECRET_PADRAO_INSEGURO)
    monkeypatch.setattr(settings, "pagarme_mode", "sandbox")

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        _verificar_jwt_secret_producao()


def test_permite_subir_com_secret_padrao_em_simulado(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", JWT_SECRET_PADRAO_INSEGURO)
    monkeypatch.setattr(settings, "pagarme_mode", "simulado")

    _verificar_jwt_secret_producao()  # não levanta


def test_permite_subir_com_secret_real_em_producao(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "um-segredo-gerado-de-verdade-bem-longo")
    monkeypatch.setattr(settings, "pagarme_mode", "producao")

    _verificar_jwt_secret_producao()  # não levanta
