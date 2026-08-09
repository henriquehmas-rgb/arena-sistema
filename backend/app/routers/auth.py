"""Rotas de autenticação: cadastro/login de cliente, login de staff,
refresh de token, recuperação e redefinição de senha."""

from __future__ import annotations

import logging

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db
from app.models.entities import Cliente, Staff
from app.schemas.auth import (
    ClienteCadastro,
    ClienteCadastroOut,
    ClienteCadastroResumo,
    Login,
    RecuperarIn,
    RedefinirIn,
    TokenOut,
)
from app.services import auth as auth_service
from app.services import email as email_service
from app.services import ratelimit

logger = logging.getLogger("app.auth")

router = APIRouter()

REFRESH_COOKIE = "refresh_token"


def _ip_do_cliente(request: Request) -> str:
    return request.client.host if request.client else "desconhecido"


def _definir_cookie_refresh(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.jwt_refresh_dias * 24 * 60 * 60,
        path="/api/v1/auth",
    )


@router.post(
    "/cliente/cadastro", response_model=ClienteCadastroOut, status_code=status.HTTP_201_CREATED
)
async def cadastro_cliente(
    dados: ClienteCadastro, response: Response, db: AsyncSession = Depends(get_db)
) -> ClienteCadastroOut:
    existente = await db.scalar(select(Cliente).where(Cliente.email == dados.email))
    if existente is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email_ja_cadastrado")

    cliente = Cliente(
        nome=dados.nome,
        email=dados.email,
        senha_hash=auth_service.hash_senha(dados.senha),
        celular=dados.celular,
    )
    db.add(cliente)
    await db.flush()

    access, refresh = auth_service.criar_tokens(str(cliente.id), "cliente")
    _definir_cookie_refresh(response, refresh)

    return ClienteCadastroOut(
        cliente=ClienteCadastroResumo.model_validate(cliente),
        access_token=access,
    )


@router.post("/cliente/login", response_model=TokenOut)
async def login_cliente(
    dados: Login, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenOut:
    ip = _ip_do_cliente(request)
    if await ratelimit.excedeu_limite(dados.email, ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="muitas_tentativas_login"
        )

    cliente = await db.scalar(select(Cliente).where(Cliente.email == dados.email))
    if cliente is None or not auth_service.verificar_senha(dados.senha, cliente.senha_hash):
        await ratelimit.registrar_falha(dados.email, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="credenciais_invalidas"
        )

    await ratelimit.limpar(dados.email, ip)
    access, refresh = auth_service.criar_tokens(str(cliente.id), "cliente")
    _definir_cookie_refresh(response, refresh)
    return TokenOut(access_token=access)


@router.post("/staff/login", response_model=TokenOut)
async def login_staff(
    dados: Login, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenOut:
    ip = _ip_do_cliente(request)
    if await ratelimit.excedeu_limite(dados.email, ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="muitas_tentativas_login"
        )

    staff = await db.scalar(select(Staff).where(Staff.email == dados.email))
    if (
        staff is None
        or not staff.ativo
        or not auth_service.verificar_senha(dados.senha, staff.senha_hash)
    ):
        await ratelimit.registrar_falha(dados.email, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="credenciais_invalidas"
        )

    await ratelimit.limpar(dados.email, ip)
    access, refresh = auth_service.criar_tokens(str(staff.id), "staff")
    _definir_cookie_refresh(response, refresh)
    return TokenOut(access_token=access, papel=staff.papel.value)


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="sem_refresh_token")

    try:
        payload = auth_service.decodificar_token(refresh_token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh_token_invalido"
        ) from None

    tipo = payload.get("tipo")
    if tipo not in ("cliente", "staff"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh_token_invalido"
        )

    # Exige escopo="refresh": sem isso, um access token vazado (mais exposto
    # que o cookie httpOnly do refresh) poderia ser usado aqui para gerar
    # novos access tokens indefinidamente.
    if payload.get("escopo") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh_token_invalido"
        )

    try:
        sub_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh_token_invalido"
        ) from None

    if tipo == "cliente":
        entidade = await db.get(Cliente, sub_id)
    else:
        entidade = await db.get(Staff, sub_id)
        if entidade is not None and not entidade.ativo:
            entidade = None

    if entidade is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh_token_invalido"
        )

    novo_access = auth_service.criar_access_token(str(sub_id), tipo)
    papel = entidade.papel.value if tipo == "staff" else None
    return TokenOut(access_token=novo_access, papel=papel)


@router.post("/recuperar", status_code=status.HTTP_204_NO_CONTENT)
async def recuperar_senha(dados: RecuperarIn, db: AsyncSession = Depends(get_db)) -> None:
    cliente = await db.scalar(select(Cliente).where(Cliente.email == dados.email))
    if cliente is not None:
        token = auth_service.criar_token_redefinicao(cliente.id)
        link = f"{settings.frontend_url}/redefinir-senha?token={token}"
        html = (
            f"<p>Olá {cliente.nome},</p>"
            f"<p>Para redefinir sua senha da Arena Cacerense, acesse: "
            f'<a href="{link}">{link}</a></p>'
            "<p>Se você não solicitou, ignore este e-mail.</p>"
        )
        await email_service.enviar(cliente.email, "Redefinição de senha - Arena Cacerense", html)
    # Sempre 204, mesmo se o e-mail não existir, para não vazar quais
    # e-mails estão cadastrados.
    return None


@router.post("/redefinir", status_code=status.HTTP_204_NO_CONTENT)
async def redefinir_senha(dados: RedefinirIn, db: AsyncSession = Depends(get_db)) -> None:
    try:
        payload = auth_service.decodificar_token(dados.token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="token_invalido"
        ) from None

    if payload.get("tipo") != "redefinir_senha":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="token_invalido")

    try:
        cliente_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="token_invalido"
        ) from None

    cliente = await db.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="token_invalido")

    cliente.senha_hash = auth_service.hash_senha(dados.senha)
    await db.flush()
    return None
