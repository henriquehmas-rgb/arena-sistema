from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    assinaturas,
    auth,
    bloqueios,
    caixa,
    clientes,
    disponibilidade,
    equipe,
    health,
    pagamentos,
    precos,
    relatorios,
    reservas,
    webhooks,
)
from app.services import jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    jobs.iniciar(app)
    yield


app = FastAPI(title="Arena Cacerense API", lifespan=lifespan)

# CORS: origem do frontend (config, dev = localhost:3000) + domínios reais da
# arena (produção). Não usa "*" porque as rotas de auth trocam cookies/JWT
# com credentials.
origins = [
    settings.frontend_url,
    "https://reservas.arenacacerense.com.br",
    "https://api.arenacacerense.com.br",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers — implementações reais chegam a partir da Wave 1 (T4+); por
# enquanto a maioria é `APIRouter()` vazio (ver app/routers/*.py) só para o
# import aqui não quebrar.
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(clientes.router, prefix="/api/v1/clientes", tags=["clientes"])
app.include_router(
    # Task T5: expõe `GET /api/v1/recursos` e `GET /api/v1/disponibilidade`
    # (recursos de topo distintos no contrato congelado, não aninhados) — o
    # router já define os paths completos (`/recursos`, `/disponibilidade`),
    # então o prefixo aqui é só `/api/v1`. Era `/api/v1/disponibilidade`
    # (stub da Wave 0/T3); ajustado nesta task para bater com o contrato.
    disponibilidade.router, prefix="/api/v1", tags=["disponibilidade"]
)
app.include_router(reservas.router, prefix="/api/v1/reservas", tags=["reservas"])
app.include_router(bloqueios.router, prefix="/api/v1/bloqueios", tags=["bloqueios"])
app.include_router(precos.router, prefix="/api/v1/precos", tags=["precos"])
app.include_router(assinaturas.router, prefix="/api/v1/assinaturas", tags=["assinaturas"])
app.include_router(pagamentos.router, prefix="/api/v1/pagamentos", tags=["pagamentos"])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(caixa.router, prefix="/api/v1/caixa", tags=["caixa"])
app.include_router(relatorios.router, prefix="/api/v1/relatorios", tags=["relatorios"])
app.include_router(equipe.router, prefix="/api/v1/equipe", tags=["equipe"])
