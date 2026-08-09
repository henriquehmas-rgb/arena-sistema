from datetime import datetime
from typing import Literal
from pydantic import BaseModel
from app.models.enums import MetodoPagamento, PagamentoStatus


class CheckoutIn(BaseModel):
    reserva_id: int
    metodo: Literal["pix", "cartao"]
    card_token: str | None = None


class CheckoutOut(BaseModel):
    pagamento_id: int
    status: PagamentoStatus
    pix_qr_code: str | None = None
    pix_copia_cola: str | None = None


class PagamentoOut(BaseModel):
    id: int
    status: PagamentoStatus
    metodo: MetodoPagamento
    valor_centavos: int
    pago_em: datetime | None = None
    model_config = {"from_attributes": True}
