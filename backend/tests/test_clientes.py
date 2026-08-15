"""Testes de `/clientes/me` — auto-atendimento do cliente logado ver/editar
seu próprio cadastro (nome/celular). E-mail não é editável por aqui."""

from __future__ import annotations

import uuid


def _email(prefixo: str = "teste") -> str:
    return f"{prefixo}-{uuid.uuid4().hex[:8]}@teste.com"


async def _cadastrar_e_logar(client, nome="Fulano", celular="65999990000") -> str:
    email = _email("me")
    resp = await client.post(
        "/api/v1/auth/cliente/cadastro",
        json={"nome": nome, "email": email, "senha": "senha12345", "celular": celular},
    )
    assert resp.status_code == 201
    return resp.json()["access_token"]


async def test_meu_cadastro_200(client):
    token = await _cadastrar_e_logar(client, nome="Ciclana", celular="65999990002")
    resp = await client.get("/api/v1/clientes/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["nome"] == "Ciclana"
    assert corpo["celular"] == "65999990002"


async def test_meu_cadastro_sem_token_401(client):
    resp = await client.get("/api/v1/clientes/me")
    assert resp.status_code == 401


async def test_atualizar_meu_cadastro_200(client):
    token = await _cadastrar_e_logar(client, nome="Beltrano", celular="65999990003")
    resp = await client.put(
        "/api/v1/clientes/me",
        json={"nome": "Beltrano Editado", "celular": "65988887777"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["nome"] == "Beltrano Editado"
    assert corpo["celular"] == "65988887777"

    resp = await client.get("/api/v1/clientes/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.json()["nome"] == "Beltrano Editado"


async def test_atualizar_meu_cadastro_sem_token_401(client):
    resp = await client.put(
        "/api/v1/clientes/me", json={"nome": "X", "celular": "65999990000"}
    )
    assert resp.status_code == 401
