from datetime import datetime
from pydantic import BaseModel, model_validator
from app.models.enums import MetodoPagamento, PagamentoStatus, ReservaOrigem, ReservaStatus


class ReservaCriar(BaseModel):
    recurso_id: int
    inicio: datetime
    fim: datetime

    @model_validator(mode="after")
    def _fim_apos_inicio(self) -> "ReservaCriar":
        if self.fim <= self.inicio:
            raise ValueError("fim deve ser depois de inicio")
        return self


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
    cliente_nome: str | None = None
    cliente_celular: str | None = None
    cliente_email: str | None = None
    pagamento_metodo: MetodoPagamento | None = None
    pagamento_status: PagamentoStatus | None = None
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


class ReservaListaOut(BaseModel):
    """Shape da listagem paginada `GET /reservas` (staff) — o contrato só diz
    "lista paginada" sem detalhar o formato; `itens` + `total` (em vez de só
    a lista crua) permite ao frontend montar paginação sem um segundo
    request de contagem."""

    itens: list[ReservaOut]
    total: int
