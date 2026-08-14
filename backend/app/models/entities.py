from datetime import datetime

from sqlalchemy import ARRAY, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import (
    AssinaturaStatus,
    MetodoPagamento,
    PagamentoStatus,
    PapelStaff,
    ReservaOrigem,
    ReservaStatus,
    TipoRecurso,
)


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    senha_hash: Mapped[str | None] = mapped_column(String(100))  # None p/ cliente balcão sem senha
    celular: Mapped[str] = mapped_column(String(20))
    cpf: Mapped[str | None] = mapped_column(String(14))
    pagarme_customer_id: Mapped[str | None] = mapped_column(String(64))
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class Staff(Base):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(100))
    papel: Mapped[PapelStaff]
    ativo: Mapped[bool] = mapped_column(default=True)
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class Recurso(Base):
    __tablename__ = "recursos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80))
    tipo: Mapped[TipoRecurso]
    ativo: Mapped[bool] = mapped_column(default=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0)


class FaixaPreco(Base):
    __tablename__ = "faixas_preco"

    id: Mapped[int] = mapped_column(primary_key=True)
    recurso_id: Mapped[int] = mapped_column(ForeignKey("recursos.id"))
    dias_semana: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    hora_inicio: Mapped[int]
    hora_fim: Mapped[int]
    preco_centavos: Mapped[int]

    recurso = relationship("Recurso", lazy="joined")


class Reserva(Base):
    __tablename__ = "reservas"

    id: Mapped[int] = mapped_column(primary_key=True)
    recurso_id: Mapped[int] = mapped_column(ForeignKey("recursos.id"))
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"))
    nome_avulso: Mapped[str | None] = mapped_column(String(120))
    celular_avulso: Mapped[str | None] = mapped_column(String(20))
    inicio: Mapped[datetime]
    fim: Mapped[datetime]
    status: Mapped[ReservaStatus] = mapped_column(default=ReservaStatus.pendente_pagamento)
    origem: Mapped[ReservaOrigem]
    valor_centavos: Mapped[int]
    assinatura_id: Mapped[int | None] = mapped_column(ForeignKey("assinaturas.id"))
    pacote_grupo_id: Mapped[str | None] = mapped_column(String(36), index=True)
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())

    recurso = relationship("Recurso", lazy="joined")
    cliente = relationship("Cliente", lazy="joined")


class Bloqueio(Base):
    __tablename__ = "bloqueios"

    id: Mapped[int] = mapped_column(primary_key=True)
    recurso_id: Mapped[int] = mapped_column(ForeignKey("recursos.id"))
    inicio: Mapped[datetime]
    fim: Mapped[datetime]
    motivo: Mapped[str | None] = mapped_column(String(200))
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))

    recurso = relationship("Recurso", lazy="joined")


class Assinatura(Base):
    __tablename__ = "assinaturas"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    recurso_id: Mapped[int] = mapped_column(ForeignKey("recursos.id"))
    dia_semana: Mapped[int]
    hora_inicio: Mapped[int]
    hora_fim: Mapped[int]
    valor_mensal_centavos: Mapped[int]
    status: Mapped[AssinaturaStatus] = mapped_column(default=AssinaturaStatus.ativa)
    pagarme_subscription_id: Mapped[str | None] = mapped_column(String(64))
    proxima_cobranca: Mapped[datetime | None]

    cliente = relationship("Cliente", lazy="joined")
    recurso = relationship("Recurso", lazy="joined")


class Pagamento(Base):
    __tablename__ = "pagamentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    reserva_id: Mapped[int | None] = mapped_column(ForeignKey("reservas.id"))
    assinatura_id: Mapped[int | None] = mapped_column(ForeignKey("assinaturas.id"))
    metodo: Mapped[MetodoPagamento]
    valor_centavos: Mapped[int]
    status: Mapped[PagamentoStatus] = mapped_column(default=PagamentoStatus.pendente)
    pagarme_order_id: Mapped[str | None] = mapped_column(String(64))
    pagarme_charge_id: Mapped[str | None] = mapped_column(String(64))
    pago_em: Mapped[datetime | None]
    registrado_por_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class Auditoria(Base):
    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))
    acao: Mapped[str] = mapped_column(String(60))
    entidade: Mapped[str] = mapped_column(String(40))
    entidade_id: Mapped[int | None]
    dados: Mapped[dict | None] = mapped_column(JSONB)
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())
