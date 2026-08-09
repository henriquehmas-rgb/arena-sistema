from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_cliente_atual, get_db
from app.models.entities import Cliente, Reserva
from app.schemas.reservas import ReservaOut

# Stub (Wave 0 / Task T3): só existe para o import em app/main.py não
# quebrar. Implementação real completa das rotas de reservas é da Task T5.
#
# Task T4 (auth): adiciona só GET /minhas, mínimo, para exercitar
# `deps.get_cliente_atual` fim-a-fim em `tests/test_auth.py` (o brief do T4
# pede explicitamente um teste de "acesso /reservas/minhas com token"). A
# Task T5 deve substituir por implementação completa (filtros, paginação
# etc conforme o contrato) — este handler não faz mais do que listar as
# reservas do cliente autenticado.
router = APIRouter()


@router.get("/minhas", response_model=list[ReservaOut])
async def minhas_reservas(
    cliente: Cliente = Depends(get_cliente_atual),
    db: AsyncSession = Depends(get_db),
) -> list[ReservaOut]:
    resultado = await db.execute(
        select(Reserva).where(Reserva.cliente_id == cliente.id).order_by(Reserva.inicio)
    )
    reservas = resultado.scalars().all()
    return [
        ReservaOut(
            id=r.id,
            recurso_id=r.recurso_id,
            recurso_nome=r.recurso.nome,
            inicio=r.inicio,
            fim=r.fim,
            status=r.status,
            origem=r.origem,
            valor_centavos=r.valor_centavos,
        )
        for r in reservas
    ]
