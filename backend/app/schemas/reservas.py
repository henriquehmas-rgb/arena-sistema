from datetime import datetime
from pydantic import BaseModel
from app.models.enums import ReservaStatus, ReservaOrigem, MetodoPagamento


class ReservaCriar(BaseModel):
    recurso_id: int
    inicio: datetime
    fim: datetime


class ReservaBalcaoCriar(ReservaCriar):
    cliente_id: int | None = None
    nome_avulso: str | None = None
    celular_avulso: str | None = None
    metodo: MetodoPagamento  # dinheiro | pix_manual


class ReservaOut(BaseModel):
    id: int
    recurso_id: int
    recurso_nome: str
    inicio: datetime
    fim: datetime
    status: ReservaStatus
    origem: ReservaOrigem
    valor_centavos: int
    expira_em: datetime | None = None
    model_config = {"from_attributes": True}


class SlotOut(BaseModel):
    inicio: datetime
    fim: datetime
    preco_centavos: int
    livre: bool


class DisponibilidadeOut(BaseModel):
    slots: list[SlotOut]


# --- Além do bloco literal do brief: inferidas do contrato de API (rotas
# POST /reservas/{id}/cancelar-admin e respostas genéricas {status}) ---

class CancelarAdminIn(BaseModel):
    estornar: bool


class StatusOut(BaseModel):
    status: ReservaStatus
