import enum


class TipoRecurso(str, enum.Enum):
    campo = "campo"
    quiosque = "quiosque"


class PapelStaff(str, enum.Enum):
    admin = "admin"
    atendente = "atendente"


class ReservaStatus(str, enum.Enum):
    pendente_pagamento = "pendente_pagamento"
    confirmada = "confirmada"
    concluida = "concluida"
    cancelada = "cancelada"
    expirada = "expirada"


class ReservaOrigem(str, enum.Enum):
    online = "online"
    balcao = "balcao"
    mensalista = "mensalista"


class MetodoPagamento(str, enum.Enum):
    pix = "pix"
    cartao = "cartao"
    dinheiro = "dinheiro"
    pix_manual = "pix_manual"


class PagamentoStatus(str, enum.Enum):
    pendente = "pendente"
    pago = "pago"
    falhou = "falhou"
    estornado = "estornado"


class AssinaturaStatus(str, enum.Enum):
    ativa = "ativa"
    pausada = "pausada"
    inadimplente = "inadimplente"
    cancelada = "cancelada"
