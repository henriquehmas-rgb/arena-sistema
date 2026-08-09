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
    smtp_user: str = ""
    smtp_pass: str = ""
    frontend_url: str = "http://localhost:3000"
    tz_local: str = "America/Cuiaba"

    class Config:
        env_file = ".env"


settings = Settings()
