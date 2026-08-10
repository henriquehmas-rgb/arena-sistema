from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://arena:arena@localhost:5432/arena"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-inseguro-trocar"
    jwt_access_min: int = 15
    jwt_refresh_dias: int = 30
    reserva_ttl_min: int = 15
    cancelamento_horas: int = 24
    janela_campo_dias: int = 14
    janela_quiosque_dias: int = 60
    pagarme_mode: str = "simulado"          # simulado|sandbox|producao
    pagarme_api_key: str = ""
    pagarme_webhook_secret: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    # Endereço que aparece em "De:" — separado de `smtp_user` porque em
    # provedores como o Resend o usuário de autenticação SMTP é uma
    # constante do provedor ("resend"), não um e-mail; usar `smtp_user`
    # também como remetente (como este serviço fazia antes) gerava um
    # cabeçalho "From" inválido. Cai de volta pra `smtp_user` se não
    # configurado, pra não quebrar um `.env` que já usava um usuário SMTP
    # que também é um e-mail válido (ex.: Gmail/SES com usuário = e-mail).
    smtp_from: str = ""
    frontend_url: str = "http://localhost:3000"
    tz_local: str = "America/Cuiaba"

    class Config:
        env_file = ".env"


settings = Settings()
