"""Rotas públicas de recursos e disponibilidade.

`GET /recursos` mora aqui (em vez de um arquivo `routers/recursos.py`
próprio) para não criar arquivo fora do mapa do projeto (`_estrutura-
arquivos.md` não lista um router de recursos) — ver Task T5, Step 3.

Nota sobre o `prefix` deste router em `app/main.py`: para que as rotas
apareçam como `/api/v1/recursos` e `/api/v1/disponibilidade` (conforme o
contrato congelado, que trata os dois como recursos de topo separados, não
aninhados um sob o outro), `main.py` monta este router com
`prefix="/api/v1"` e os paths abaixo já incluem o segmento final
(`/recursos`, `/disponibilidade`) explicitamente.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db
from app.models.entities import Recurso
from app.models.enums import TipoRecurso
from app.schemas.recursos import RecursoOut
from app.schemas.reservas import DisponibilidadeOut, SlotOut
from app.services.disponibilidade import slots_do_dia

router = APIRouter()


@router.get("/recursos", response_model=list[RecursoOut])
async def listar_recursos(db: AsyncSession = Depends(get_db)) -> list[Recurso]:
    resultado = await db.execute(select(Recurso).order_by(Recurso.ordem))
    return list(resultado.scalars().all())


@router.get("/disponibilidade", response_model=DisponibilidadeOut)
async def disponibilidade(
    recurso_id: int = Query(...),
    data: date = Query(...),
    db: AsyncSession = Depends(get_db),
) -> DisponibilidadeOut:
    recurso = await db.get(Recurso, recurso_id)
    if recurso is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recurso_nao_encontrado")

    tz = ZoneInfo(settings.tz_local)
    hoje_local = datetime.now(tz).date()
    janela_dias = (
        settings.janela_campo_dias
        if recurso.tipo == TipoRecurso.campo
        else settings.janela_quiosque_dias
    )
    if (data - hoje_local).days > janela_dias:
        raise HTTPException(status_code=422, detail="janela_excedida")

    slots = await slots_do_dia(db, recurso, data)
    return DisponibilidadeOut(
        slots=[
            SlotOut(
                inicio=s.inicio,
                fim=s.fim,
                preco_centavos=s.preco_centavos,
                livre=s.livre,
            )
            for s in slots
        ]
    )
