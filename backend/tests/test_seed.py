from sqlalchemy import func, select

from app.models.entities import FaixaPreco, Recurso, Staff
from app.seed import seed


async def test_seed_e_idempotente(db):
    await seed(db)
    n_recursos_1 = (await db.execute(select(func.count()).select_from(Recurso))).scalar_one()
    n_faixas_1 = (await db.execute(select(func.count()).select_from(FaixaPreco))).scalar_one()
    n_staff_1 = (await db.execute(select(func.count()).select_from(Staff))).scalar_one()

    await seed(db)
    n_recursos_2 = (await db.execute(select(func.count()).select_from(Recurso))).scalar_one()
    n_faixas_2 = (await db.execute(select(func.count()).select_from(FaixaPreco))).scalar_one()
    n_staff_2 = (await db.execute(select(func.count()).select_from(Staff))).scalar_one()

    assert n_recursos_1 == n_recursos_2 == 3
    assert n_faixas_1 == n_faixas_2 == 7
    assert n_staff_1 == n_staff_2 == 1
