"""Templates HTML dos e-mails transacionais, com a identidade visual do
site (cores/fontes de `frontend/app/globals.css`). Layout em tabelas com CSS
inline — não dá pra confiar em `<style>`/classes em clientes de e-mail
(Gmail, Outlook etc. removem ou ignoram boa parte disso).

Cada função `*_email` monta e retorna `(assunto, html)`; quem chama só
precisa passar isso pra `app.services.email.enviar`.
"""

from __future__ import annotations

_AZUL = "#0B63D8"
_TINTA = "#171335"
_FUNDO = "#F6F8FC"
_CINZA = "#6b7280"
_VERDE = "#1c9a5b"
_VERMELHO = "#d92d20"
_FONTE = (
    "'Saira', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
)
_LOGO_URL = "https://arenacacerense.com.br/assets/logo-horiz-white.png"


def _base(titulo: str, corpo_html: str, cor_destaque: str = _AZUL) -> str:
    return f"""\
<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0; padding:0; background-color:{_FUNDO}; font-family:{_FONTE};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{_FUNDO}; padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px; width:100%; background-color:#ffffff; border-radius:12px; overflow:hidden; border:1px solid #e5e7eb;">
          <tr>
            <td style="background-color:{_TINTA}; padding:28px 32px;" align="center">
              <img src="{_LOGO_URL}" alt="Arena Cacerense" height="32" style="display:block; height:32px;">
            </td>
          </tr>
          <tr>
            <td style="padding:4px 32px 0 32px; border-top:4px solid {cor_destaque};"></td>
          </tr>
          <tr>
            <td style="padding:32px;">
              <h1 style="margin:0 0 16px 0; font-family:{_FONTE}; font-size:20px; color:{_TINTA};">{titulo}</h1>
              <div style="font-size:15px; line-height:1.6; color:#374151;">
                {corpo_html}
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px; background-color:{_FUNDO}; border-top:1px solid #e5e7eb;" align="center">
              <p style="margin:0; font-size:12px; color:{_CINZA};">Arena Cacerense &middot; arenacacerense.com.br</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _botao(texto: str, link: str, cor: str = _AZUL) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0;">'
        f"<tr><td style=\"border-radius:8px; background-color:{cor};\">"
        f'<a href="{link}" style="display:inline-block; padding:12px 24px; font-family:{_FONTE}; '
        f'font-size:15px; font-weight:600; color:#ffffff; text-decoration:none; border-radius:8px;">'
        f"{texto}</a></td></tr></table>"
    )


def redefinicao_senha_email(nome: str, link: str) -> tuple[str, str]:
    corpo = (
        f"<p>Olá {nome},</p>"
        "<p>Recebemos um pedido para redefinir a senha da sua conta na Arena Cacerense.</p>"
        f"{_botao('Redefinir senha', link)}"
        f'<p style="font-size:13px; color:{_CINZA};">Se o botão não funcionar, copie e cole este '
        f'link no navegador: <a href="{link}" style="color:{_AZUL};">{link}</a></p>'
        "<p>Se você não solicitou essa alteração, ignore este e-mail — sua senha continua a mesma.</p>"
    )
    return "Redefinição de senha - Arena Cacerense", _base("Redefinição de senha", corpo)


def pagamento_confirmado_email(
    nome: str, reserva_id: int, recurso_nome: str, inicio_str: str
) -> tuple[str, str]:
    corpo = (
        f"<p>Olá {nome},</p>"
        f"<p>Seu pagamento foi confirmado! Aqui estão os detalhes da sua reserva:</p>"
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        f'style="margin:16px 0; font-size:14px; background-color:{_FUNDO}; border-radius:8px;">'
        f'<tr><td style="padding:14px 18px;">'
        f"<strong>Reserva:</strong> #{reserva_id}<br>"
        f"<strong>Local:</strong> {recurso_nome}<br>"
        f"<strong>Data/hora:</strong> {inicio_str}"
        "</td></tr></table>"
        "<p>Te esperamos na Arena Cacerense!</p>"
    )
    return "Pagamento confirmado — Arena Cacerense", _base("Pagamento confirmado", corpo, cor_destaque=_VERDE)


def boas_vindas_email(nome: str) -> tuple[str, str]:
    corpo = (
        f"<p>Olá {nome},</p>"
        "<p>Sua conta na Arena Cacerense foi criada com sucesso! Agora você já pode reservar "
        "campos e quiosques direto pelo site, acompanhar suas reservas e gerenciar seus pagamentos.</p>"
        f"{_botao('Acessar minha conta', 'https://reservas.arenacacerense.com.br')}"
        "<p>Qualquer dúvida, é só responder este e-mail.</p>"
    )
    return "Bem-vindo à Arena Cacerense!", _base("Bem-vindo(a)!", corpo, cor_destaque=_VERDE)


def cobranca_falhou_email(nome: str) -> tuple[str, str]:
    corpo = (
        f"<p>Olá {nome},</p>"
        "<p>Não conseguimos processar a cobrança da sua mensalidade na Arena Cacerense. "
        "Sua assinatura foi marcada como <strong>inadimplente</strong> e as próximas reservas "
        "automáticas do seu horário ficam suspensas até a regularização.</p>"
        "<p>Entre em contato conosco ou acesse sua conta para atualizar a forma de pagamento "
        "e reativar sua assinatura.</p>"
        f"{_botao('Ver minha assinatura', 'https://reservas.arenacacerense.com.br', cor=_VERMELHO)}"
    )
    return "Cobrança não processada — Arena Cacerense", _base(
        "Cobrança não processada", corpo, cor_destaque=_VERMELHO
    )


def cancelamento_reserva_email(
    nome: str, reserva_id: int, recurso_nome: str, inicio_str: str
) -> tuple[str, str]:
    corpo = (
        f"<p>Olá {nome},</p>"
        "<p>Sua reserva foi cancelada. Segue o resumo:</p>"
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        f'style="margin:16px 0; font-size:14px; background-color:{_FUNDO}; border-radius:8px;">'
        f'<tr><td style="padding:14px 18px;">'
        f"<strong>Reserva:</strong> #{reserva_id}<br>"
        f"<strong>Local:</strong> {recurso_nome}<br>"
        f"<strong>Data/hora:</strong> {inicio_str}"
        "</td></tr></table>"
        "<p>Se você não solicitou este cancelamento ou tiver dúvidas, entre em contato conosco.</p>"
    )
    return "Reserva cancelada — Arena Cacerense", _base("Reserva cancelada", corpo, cor_destaque=_VERMELHO)
