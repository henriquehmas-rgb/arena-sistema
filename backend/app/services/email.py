"""Serviço de envio de e-mail transacional.

Se `settings.smtp_host` estiver vazio (padrão em dev/test), a função vira
um no-op que só loga — não é necessário um servidor SMTP real para rodar a
suíte de testes; os testes de recuperação/redefinição de senha capturam a
chamada via monkeypatch de `enviar`.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger("app.email")


async def enviar(para: str, assunto: str, html: str) -> None:
    if not settings.smtp_host:
        logger.info("email (SMTP não configurado, no-op) para=%s assunto=%s", para, assunto)
        return

    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = assunto
    msg["From"] = settings.smtp_user
    msg["To"] = para

    with smtplib.SMTP(settings.smtp_host) as smtp:
        if settings.smtp_user:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_pass)
        smtp.sendmail(settings.smtp_user, [para], msg.as_string())
    logger.info("email enviado para=%s assunto=%s", para, assunto)
