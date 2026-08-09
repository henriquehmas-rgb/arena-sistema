from datetime import datetime
from typing import Literal
from pydantic import BaseModel
from app.models.enums import AssinaturaStatus


class AssinaturaCriar(BaseModel):
    cliente_id: int
    recurso_id: int
    dia_semana: int
    hora_inicio: int
    hora_fim: int
    valor_mensal_centavos: int
    metodo: Literal["cartao", "pix"]
    card_token: str | None = None


class AssinaturaOut(BaseModel):
    id: int
    cliente_nome: str
    recurso_nome: str
    dia_semana: int
    hora_inicio: int
    hora_fim: int
    valor_mensal_centavos: int
    status: AssinaturaStatus
    proxima_cobranca: datetime | None = None
    model_config = {"from_attributes": True}
