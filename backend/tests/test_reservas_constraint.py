from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.entities import Recurso, Reserva
from app.models.enums import ReservaOrigem, ReservaStatus, TipoRecurso


def dt(*args):
    return datetime(*args)


async def test_constraint_impede_sobreposicao(db):
    r = Recurso(nome="Campo T", tipo=TipoRecurso.campo, ativo=True, ordem=1)
    db.add(r)
    await db.flush()

    db.add(
        Reserva(
            recurso_id=r.id,
            inicio=dt(2026, 8, 10, 18),
            fim=dt(2026, 8, 10, 19),
            status=ReservaStatus.confirmada,
            origem=ReservaOrigem.balcao,
            valor_centavos=0,
        )
    )
    await db.flush()

    db.add(
        Reserva(
            recurso_id=r.id,
            inicio=dt(2026, 8, 10, 18),
            fim=dt(2026, 8, 10, 19),
            status=ReservaStatus.pendente_pagamento,
            origem=ReservaOrigem.online,
            valor_centavos=0,
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_constraint_permite_horarios_diferentes(db):
    r = Recurso(nome="Campo T2", tipo=TipoRecurso.campo, ativo=True, ordem=1)
    db.add(r)
    await db.flush()

    db.add(
        Reserva(
            recurso_id=r.id,
            inicio=dt(2026, 8, 10, 18),
            fim=dt(2026, 8, 10, 19),
            status=ReservaStatus.confirmada,
            origem=ReservaOrigem.balcao,
            valor_centavos=0,
        )
    )
    await db.flush()

    db.add(
        Reserva(
            recurso_id=r.id,
            inicio=dt(2026, 8, 10, 19),
            fim=dt(2026, 8, 10, 20),
            status=ReservaStatus.confirmada,
            origem=ReservaOrigem.balcao,
            valor_centavos=0,
        )
    )
    await db.flush()


async def test_constraint_permite_sobreposicao_se_cancelada(db):
    r = Recurso(nome="Campo T3", tipo=TipoRecurso.campo, ativo=True, ordem=1)
    db.add(r)
    await db.flush()

    db.add(
        Reserva(
            recurso_id=r.id,
            inicio=dt(2026, 8, 10, 18),
            fim=dt(2026, 8, 10, 19),
            status=ReservaStatus.cancelada,
            origem=ReservaOrigem.balcao,
            valor_centavos=0,
        )
    )
    await db.flush()

    db.add(
        Reserva(
            recurso_id=r.id,
            inicio=dt(2026, 8, 10, 18),
            fim=dt(2026, 8, 10, 19),
            status=ReservaStatus.confirmada,
            origem=ReservaOrigem.balcao,
            valor_centavos=0,
        )
    )
    await db.flush()
