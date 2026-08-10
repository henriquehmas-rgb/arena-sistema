"""Testes de autenticação (Task T4): cadastro/login de cliente, login de
staff + `/equipe` restrito a admin, rate-limit de login, refresh de token e
recuperação/redefinição de senha."""

from __future__ import annotations

import uuid

import pytest
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entities import Staff
from app.models.enums import PapelStaff
from app.services import auth as auth_service


def _email(prefixo: str = "teste") -> str:
    return f"{prefixo}-{uuid.uuid4().hex[:8]}@teste.com"


async def _limpar_rate_limit(prefixo: str, ip: str = "127.0.0.1") -> None:
    """`ASGITransport` (ver `conftest.client`) sempre reporta `request.client`
    como `("127.0.0.1", 123)` — os testes de rate-limit por IP (cadastro,
    recuperar) precisam limpar sua própria chave no Redis pra não vazar o
    contador pros outros testes deste arquivo, que rodam contra o mesmo
    Redis de teste e a mesma "IP" sintética."""
    client = aioredis.from_url(settings.redis_url)
    try:
        await client.delete(f"{prefixo}:{ip}")
    finally:
        await client.aclose()


@pytest.fixture(autouse=True)
async def _sem_rate_limit_residual():
    """`ASGITransport` sempre reporta a mesma "IP" sintética (127.0.0.1) —
    sem isso, o contador de `/cliente/cadastro` e `/recuperar` (por IP,
    janela de 1h) vazaria de um teste deste arquivo pro outro dependendo da
    ordem de execução."""
    await _limpar_rate_limit("cadastro")
    await _limpar_rate_limit("recuperar")


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


# Achado na revisão final de branch: só o login tinha rate-limit —
# `/cliente/cadastro` e `/recuperar` ficavam abertos a spam de contas / a um
# amplificador de custo de e-mail (uma vez que SMTP estiver configurado).


async def test_rate_limit_cadastro_11a_tentativa_429(client, monkeypatch):
    from app.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "LIMITE_CADASTRO", 10)
    await _limpar_rate_limit("cadastro")

    for _ in range(10):
        resp = await client.post(
            "/api/v1/auth/cliente/cadastro",
            json={
                "nome": "Fulano",
                "email": _email("ratelimit-cadastro"),
                "senha": "senha12345",
                "celular": "65999990000",
            },
        )
        assert resp.status_code == 201

    resp = await client.post(
        "/api/v1/auth/cliente/cadastro",
        json={
            "nome": "Fulano",
            "email": _email("ratelimit-cadastro"),
            "senha": "senha12345",
            "celular": "65999990000",
        },
    )
    assert resp.status_code == 429
    await _limpar_rate_limit("cadastro")


async def test_rate_limit_recuperar_6a_tentativa_429(client, monkeypatch):
    from app.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "LIMITE_RECUPERAR", 5)
    await _limpar_rate_limit("recuperar")

    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/recuperar", json={"email": _email("naoexiste-ratelimit")}
        )
        assert resp.status_code == 204

    resp = await client.post(
        "/api/v1/auth/recuperar", json={"email": _email("naoexiste-ratelimit")}
    )
    assert resp.status_code == 429
    await _limpar_rate_limit("recuperar")


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
    # Achado na revisão final de branch: o link apontava pra
    # `/redefinir-senha`, uma rota que não existe no frontend (a página real
    # é `/recuperar?token=...`) — todo link de recuperação de senha 404ava.
    assert "/recuperar?token=" in capturado["html"]
    assert "/redefinir-senha" not in capturado["html"]

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


# Achados na revisão final de branch: um link de recuperação funcionava
# repetidamente (replay) e redefinir a senha não invalidava sessões já
# abertas (refresh tokens emitidos antes da troca continuavam válidos).


async def test_redefinir_senha_token_replay_400(client, monkeypatch):
    email = _email("replay")
    resp = await client.post(
        "/api/v1/auth/cliente/cadastro",
        json={"nome": "Replay", "email": email, "senha": "senhaAntiga1", "celular": "65999990005"},
    )
    assert resp.status_code == 201

    capturado = {}

    async def _enviar_fake(para, assunto, html):
        capturado["html"] = html

    monkeypatch.setattr("app.routers.auth.email_service.enviar", _enviar_fake)
    resp = await client.post("/api/v1/auth/recuperar", json={"email": email})
    assert resp.status_code == 204
    token = capturado["html"].split("token=")[1].split('"')[0]

    resp = await client.post(
        "/api/v1/auth/redefinir", json={"token": token, "senha": "senhaNova1"}
    )
    assert resp.status_code == 204

    # Mesmo token, segunda vez: recusado, mesmo ainda dentro da validade de
    # 1h — um link de recuperação interceptado não pode ser reaproveitado.
    resp = await client.post(
        "/api/v1/auth/redefinir", json={"token": token, "senha": "senhaOutra1"}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "token_invalido"

    # A senha continua sendo a definida na 1ª (bem-sucedida) redefinição.
    resp = await client.post(
        "/api/v1/auth/cliente/login", json={"email": email, "senha": "senhaNova1"}
    )
    assert resp.status_code == 200


async def test_redefinir_senha_invalida_refresh_token_antigo(client, monkeypatch):
    email = _email("invalida-sessao")
    resp = await client.post(
        "/api/v1/auth/cliente/cadastro",
        json={
            "nome": "Invalida Sessao",
            "email": email,
            "senha": "senhaAntiga1",
            "celular": "65999990006",
        },
    )
    assert resp.status_code == 201
    refresh_token_antigo = resp.cookies["refresh_token"]

    capturado = {}

    async def _enviar_fake(para, assunto, html):
        capturado["html"] = html

    monkeypatch.setattr("app.routers.auth.email_service.enviar", _enviar_fake)
    resp = await client.post("/api/v1/auth/recuperar", json={"email": email})
    assert resp.status_code == 204
    token = capturado["html"].split("token=")[1].split('"')[0]

    resp = await client.post(
        "/api/v1/auth/redefinir", json={"token": token, "senha": "senhaNova1"}
    )
    assert resp.status_code == 204

    # O refresh token emitido no cadastro (antes da redefinição) não deve
    # continuar funcionando — sem isso, uma sessão já aberta (ex: refresh
    # token roubado) sobreviveria à vítima "recuperar" a conta.
    resp = await client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": refresh_token_antigo}
    )
    assert resp.status_code == 401

    # Um novo login gera um refresh token novo, que funciona normalmente.
    resp = await client.post(
        "/api/v1/auth/cliente/login", json={"email": email, "senha": "senhaNova1"}
    )
    assert resp.status_code == 200
    refresh_token_novo = resp.cookies["refresh_token"]
    resp = await client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": refresh_token_novo}
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


# Achado na revisão final de branch: `smtplib` é síncrono e bloqueava o
# event loop inteiro dentro de uma `async def` — `enviar` passou a rodar a
# conversa SMTP via `asyncio.to_thread`. Este teste (com `smtp_host`
# configurado, ao contrário do de cima) confirma que o caminho síncrono
# ainda monta e envia a mensagem certa, mesmo rodando numa thread separada.
async def test_email_com_smtp_configurado_envia_via_thread(monkeypatch):
    from app.services import email as email_service

    chamadas = {}

    class _SMTPFake:
        def __init__(self, host):
            chamadas["host"] = host

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            chamadas["starttls"] = True

        def login(self, user, senha):
            chamadas["login"] = (user, senha)

        def sendmail(self, remetente, destinatarios, corpo):
            chamadas["sendmail"] = (remetente, destinatarios, corpo)

    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.teste.local")
    monkeypatch.setattr(email_service.settings, "smtp_user", "arena@teste.com")
    monkeypatch.setattr(email_service.settings, "smtp_pass", "segredo")
    monkeypatch.setattr(email_service.smtplib, "SMTP", _SMTPFake)

    await email_service.enviar("cliente@teste.com", "Assunto Teste", "<p>oi</p>")

    assert chamadas["host"] == "smtp.teste.local"
    assert chamadas["starttls"] is True
    assert chamadas["login"] == ("arena@teste.com", "segredo")
    remetente, destinatarios, corpo = chamadas["sendmail"]
    assert remetente == "arena@teste.com"
    assert destinatarios == ["cliente@teste.com"]
    assert "Assunto Teste" in corpo


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
