"""Testes de autenticação (Task T4): cadastro/login de cliente, login de
staff + `/equipe` restrito a admin, rate-limit de login, refresh de token e
recuperação/redefinição de senha."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Staff
from app.models.enums import PapelStaff
from app.services import auth as auth_service


def _email(prefixo: str = "teste") -> str:
    return f"{prefixo}-{uuid.uuid4().hex[:8]}@teste.com"


# ---------------------------------------------------------------------------
# Cadastro + login de cliente + rota protegida
# ---------------------------------------------------------------------------


async def test_cadastro_cliente_201(client):
    email = _email("cadastro")
    resp = await client.post(
        "/api/v1/auth/cliente/cadastro",
        json={"nome": "Fulano", "email": email, "senha": "senha12345", "celular": "65999990000"},
    )
    assert resp.status_code == 201
    corpo = resp.json()
    assert corpo["cliente"]["email"] == email
    assert corpo["cliente"]["nome"] == "Fulano"
    assert corpo["access_token"]
    assert "refresh_token" in resp.cookies


async def test_login_cliente_200_e_acesso_reservas_minhas(client):
    email = _email("login")
    resp = await client.post(
        "/api/v1/auth/cliente/cadastro",
        json={"nome": "Ciclana", "email": email, "senha": "senha12345", "celular": "65999990001"},
    )
    assert resp.status_code == 201

    resp = await client.post(
        "/api/v1/auth/cliente/login", json={"email": email, "senha": "senha12345"}
    )
    assert resp.status_code == 200
    access_token = resp.json()["access_token"]
    assert access_token

    resp = await client.get(
        "/api/v1/reservas/minhas", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_reservas_minhas_sem_token_401(client):
    resp = await client.get("/api/v1/reservas/minhas")
    assert resp.status_code == 401


async def test_login_cliente_senha_errada_401(client):
    email = _email("senhaerrada")
    resp = await client.post(
        "/api/v1/auth/cliente/cadastro",
        json={"nome": "X", "email": email, "senha": "senha12345", "celular": "65999990002"},
    )
    assert resp.status_code == 201

    resp = await client.post(
        "/api/v1/auth/cliente/login", json={"email": email, "senha": "errada123"}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Login staff + /equipe exige admin
# ---------------------------------------------------------------------------


async def _criar_staff(db: AsyncSession, papel: PapelStaff, senha: str = "senha12345") -> Staff:
    staff = Staff(
        nome="Staff Teste",
        email=_email("staff"),
        senha_hash=auth_service.hash_senha(senha),
        papel=papel,
        ativo=True,
    )
    db.add(staff)
    await db.flush()
    return staff


async def test_login_staff_admin_e_acesso_equipe(client, db: AsyncSession):
    admin = await _criar_staff(db, PapelStaff.admin)

    resp = await client.post(
        "/api/v1/auth/staff/login", json={"email": admin.email, "senha": "senha12345"}
    )
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["papel"] == "admin"
    access_token = corpo["access_token"]

    resp = await client.get(
        "/api/v1/equipe", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resp.status_code == 200
    emails = [s["email"] for s in resp.json()]
    assert admin.email in emails


async def test_login_atendente_equipe_403(client, db: AsyncSession):
    atendente = await _criar_staff(db, PapelStaff.atendente)

    resp = await client.post(
        "/api/v1/auth/staff/login", json={"email": atendente.email, "senha": "senha12345"}
    )
    assert resp.status_code == 200
    access_token = resp.json()["access_token"]

    resp = await client.get(
        "/api/v1/equipe", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resp.status_code == 403


async def test_equipe_sem_token_401(client):
    resp = await client.get("/api/v1/equipe")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Rate-limit de login
# ---------------------------------------------------------------------------


async def test_rate_limit_login_6a_tentativa_429(client, db: AsyncSession):
    staff = await _criar_staff(db, PapelStaff.atendente)

    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/staff/login", json={"email": staff.email, "senha": "senha_errada"}
        )
        assert resp.status_code == 401

    resp = await client.post(
        "/api/v1/auth/staff/login", json={"email": staff.email, "senha": "senha_errada"}
    )
    assert resp.status_code == 429

    # mesmo com a senha certa, ainda bloqueado dentro da janela
    resp = await client.post(
        "/api/v1/auth/staff/login", json={"email": staff.email, "senha": "senha12345"}
    )
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Refresh de token
# ---------------------------------------------------------------------------


async def test_refresh_renova_access_token(client):
    email = _email("refresh")
    resp = await client.post(
        "/api/v1/auth/cliente/cadastro",
        json={"nome": "Refresh", "email": email, "senha": "senha12345", "celular": "65999990003"},
    )
    assert resp.status_code == 201
    refresh_token = resp.cookies["refresh_token"]

    resp = await client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": refresh_token}
    )
    assert resp.status_code == 200
    novo_access = resp.json()["access_token"]
    assert novo_access

    resp = await client.get(
        "/api/v1/reservas/minhas", headers={"Authorization": f"Bearer {novo_access}"}
    )
    assert resp.status_code == 200


async def test_refresh_sem_cookie_401(client):
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Recuperar / redefinir senha
# ---------------------------------------------------------------------------


async def test_recuperar_e_redefinir_senha(client, monkeypatch):
    email = _email("recuperar")
    resp = await client.post(
        "/api/v1/auth/cliente/cadastro",
        json={
            "nome": "Recupera",
            "email": email,
            "senha": "senhaAntiga1",
            "celular": "65999990004",
        },
    )
    assert resp.status_code == 201

    capturado = {}

    async def _enviar_fake(para, assunto, html):
        capturado["para"] = para
        capturado["assunto"] = assunto
        capturado["html"] = html

    monkeypatch.setattr("app.routers.auth.email_service.enviar", _enviar_fake)

    resp = await client.post("/api/v1/auth/recuperar", json={"email": email})
    assert resp.status_code == 204
    assert capturado["para"] == email
    assert "token=" in capturado["html"]

    token = capturado["html"].split("token=")[1].split('"')[0]

    resp = await client.post(
        "/api/v1/auth/redefinir", json={"token": token, "senha": "senhaNova1"}
    )
    assert resp.status_code == 204

    # login com a senha antiga deve falhar, com a nova deve funcionar
    resp = await client.post(
        "/api/v1/auth/cliente/login", json={"email": email, "senha": "senhaAntiga1"}
    )
    assert resp.status_code == 401

    resp = await client.post(
        "/api/v1/auth/cliente/login", json={"email": email, "senha": "senhaNova1"}
    )
    assert resp.status_code == 200


async def test_recuperar_email_inexistente_ainda_204(client, monkeypatch, caplog):
    chamou = {"sim": False}

    async def _enviar_fake(para, assunto, html):
        chamou["sim"] = True

    monkeypatch.setattr("app.routers.auth.email_service.enviar", _enviar_fake)

    resp = await client.post(
        "/api/v1/auth/recuperar", json={"email": _email("naoexiste")}
    )
    assert resp.status_code == 204
    assert chamou["sim"] is False


async def test_email_noop_loga_quando_smtp_vazio(caplog):
    """`services.email.enviar` deve ser no-op logando quando
    `settings.smtp_host` está vazio (padrão em dev/test)."""
    from app.services import email as email_service

    with caplog.at_level("INFO", logger="app.email"):
        await email_service.enviar("alguem@teste.com", "Assunto", "<p>oi</p>")

    assert any("no-op" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Fix pós-review de segurança: escopo access/refresh + rate-limit falha aberto
# ---------------------------------------------------------------------------


async def test_access_token_como_refresh_401(client):
    """Um access token válido não pode ser usado como refresh token em
    `/auth/refresh` — só tokens com claim `escopo="refresh"` (que só
    circulam via cookie httpOnly) podem gerar novos access tokens."""
    email = _email("escopo")
    resp = await client.post(
        "/api/v1/auth/cliente/cadastro",
        json={"nome": "Escopo", "email": email, "senha": "senha12345", "celular": "65999990005"},
    )
    assert resp.status_code == 201
    access_token = resp.json()["access_token"]

    resp = await client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": access_token}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "refresh_token_invalido"


async def test_rate_limit_redis_indisponivel_login_nao_500(client, db: AsyncSession, monkeypatch):
    """Se o Redis estiver inacessível, o login deve continuar funcionando
    (falha aberto) em vez de retornar 500."""
    import redis.exceptions

    from app.services import ratelimit

    async def _get_falha(*args, **kwargs):
        raise redis.exceptions.ConnectionError("redis indisponível (simulado)")

    monkeypatch.setattr(ratelimit.aioredis.Redis, "get", _get_falha)

    staff = await _criar_staff(db, PapelStaff.atendente)
    resp = await client.post(
        "/api/v1/auth/staff/login", json={"email": staff.email, "senha": "senha12345"}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]
