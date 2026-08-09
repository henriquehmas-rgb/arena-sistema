from datetime import datetime
from pydantic import BaseModel
from app.models.enums import TipoRecurso


class RecursoOut(BaseModel):
    id: int
    nome: str
    tipo: TipoRecurso
    ativo: bool
    model_config = {"from_attributes": True}


class FaixaPrecoIn(BaseModel):
    recurso_id: int
    dias_semana: list[int]
    hora_inicio: int
    hora_fim: int
    preco_centavos: int


class FaixaPrecoOut(BaseModel):
    id: int
    recurso_id: int
    dias_semana: list[int]
    hora_inicio: int
    hora_fim: int
    preco_centavos: int
    model_config = {"from_attributes": True}


class BloqueioIn(BaseModel):
    recurso_id: int
    inicio: datetime
    fim: datetime
    motivo: str


class BloqueioOut(BaseModel):
    id: int
    recurso_id: int
    inicio: datetime
    fim: datetime
    motivo: str
    model_config = {"from_attributes": True}
