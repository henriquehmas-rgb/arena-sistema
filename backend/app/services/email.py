"""Serviço de envio de e-mail transacional.

Se `settings.smtp_host` estiver vazio (padrão em dev/test), a função vira
um no-op que só loga — não é necessário um servidor SMTP real para rodar a
suíte de testes; os testes de recuperação/redefinição de senha capturam a
chamada via monkeypatch de `enviar`.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger("app.email")


def _enviar_sincrono(para: str, assunto: str, html: str) -> None:
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = assunto
    msg["From"] = settings.smtp_user
    msg["To"] = para

    with smtplib.SMTP(settings.smtp_host) as smtp:
        if settings.smtp_user:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_pass)
        smtp.sendmail(settings.smtp_user, [para], msg.as_string())


async def enviar(para: str, assunto: str, html: str) -> None:
    if not settings.smtp_host:
        logger.info("email (SMTP não configurado, no-op) para=%s assunto=%s", para, assunto)
        return

    # Achado na revisão final de branch: `smtplib` é síncrono/bloqueante
    # (conexão TCP + STARTTLS + login + envio) — chamado direto dentro de
    # uma `async def`, ele trava a thread do event loop inteira (todas as
    # outras requisições concorrentes) pela duração da conversa SMTP.
    # `asyncio.to_thread` roda isso numa thread separada.
    await asyncio.to_thread(_enviar_sincrono, para, assunto, html)
    logger.info("email enviado para=%s assunto=%s", para, assunto)
