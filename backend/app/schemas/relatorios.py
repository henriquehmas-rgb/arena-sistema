from pydantic import BaseModel


class CaixaItem(BaseModel):
    id: int
    metodo: str
    valor_centavos: int
    recurso_nome: str | None = None
    cliente_nome: str | None = None


class CaixaOut(BaseModel):
    itens: list[CaixaItem]
    total_centavos: int
    por_metodo: dict[str, int]


class FaturamentoPorDia(BaseModel):
    data: str
    total_centavos: int


class FaturamentoOut(BaseModel):
    total_centavos: int
    por_metodo: dict[str, int]
    por_recurso: dict[str, int]
    por_dia: list[FaturamentoPorDia]


class OcupacaoRecurso(BaseModel):
    recurso: str
    horas_vendidas: float
    horas_disponiveis: float
    taxa: float


class OcupacaoOut(BaseModel):
    por_recurso: list[OcupacaoRecurso]
