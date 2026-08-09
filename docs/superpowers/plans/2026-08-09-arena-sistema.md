# Arena Sistema — Plano de Implementação (Mapa de Agentes)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sistema de reservas e gestão da Arena Cacerense (2 campos + quiosque) com portal público, painel admin, cobrança Pagar.me (avulso + assinatura mensalista).

**Architecture:** Monorepo `backend/` (FastAPI + SQLAlchemy async + Alembic + APScheduler) e `frontend/` (Next.js App Router), Postgres 16 + Redis, Docker Compose atrás do Traefik global da VPS. Contratos (schemas + client tipado) definidos na Wave 0; ondas seguintes rodam em paralelo.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, asyncpg, Alembic, APScheduler, passlib[bcrypt], PyJWT, httpx, redis-py · Node 20, Next.js 14 App Router, TypeScript, Playwright · Postgres 16 (btree_gist), Redis 7.

**Spec:** `docs/superpowers/specs/2026-08-09-sistema-arena-design.md` — leia antes de qualquer tarefa.

## Global Constraints

- Repo GitHub **PÚBLICO**: nenhum segredo em código/commit; tudo sensível via env (`infra/.env` gitignored; `infra/.env.example` completo).
- Valores monetários **sempre em centavos (int)**; preço de reserva **sempre recalculado no backend**.
- Timestamps `timestamptz` UTC no banco; fuso de exibição `America/Cuiaba`.
- Idioma do domínio: português (tabelas, campos, rotas em pt-BR, como no spec).
- Slots campo: 1h fechada, 08:00–23:00 (último início 22:00). Quiosque: períodos `manha` 08–12, `tarde` 13–17, `noite` 18–22, `dia` 08–22.
- TTL reserva pendente: `RESERVA_TTL_MIN=15`. Janela online: campos 14 dias, quiosque 60 dias. Cancelamento com estorno: até `CANCELAMENTO_HORAS=24` antes.
- `PAGARME_MODE=simulado|sandbox|producao` — todo código de pagamento funciona em `simulado` sem chave.
- Convenções de código do lave-e-seeg (routers/services/models/schemas; commits `feat:|fix:|test:|docs:|chore:`).
- Modelo dos subagentes: **sonnet**.

---

## Estrutura de arquivos (mapa completo)

```
backend/
  Dockerfile  pyproject.toml  alembic.ini
  alembic/env.py  alembic/versions/0001_inicial.py
  app/main.py  app/config.py  app/db.py  app/deps.py  app/seed.py
  app/models/{__init__,base,enums,entities}.py
  app/schemas/{__init__,auth,clientes,recursos,reservas,assinaturas,pagamentos,relatorios}.py
  app/routers/{__init__,health,auth,clientes,disponibilidade,reservas,bloqueios,precos,assinaturas,pagamentos,webhooks,caixa,relatorios,equipe}.py
  app/services/{__init__,auth,precos,disponibilidade,reservas,assinaturas,pagarme,pagamentos,email,auditoria,ratelimit,jobs}.py
  tests/{conftest,test_auth,test_precos,test_disponibilidade,test_reservas,test_expiracao,test_pagamentos,test_webhook,test_assinaturas,test_caixa}.py
frontend/
  Dockerfile  package.json  next.config.mjs  tsconfig.json
  app/{layout,page}.tsx  app/globals.css
  app/entrar/page.tsx  app/cadastro/page.tsx  app/recuperar/page.tsx
  app/checkout/[reservaId]/page.tsx  app/conta/page.tsx
  app/admin/layout.tsx  app/admin/page.tsx
  app/admin/{reservas,clientes,mensalistas,precos,caixa,relatorios,equipe}/page.tsx
  lib/{api,auth,format}.ts
  components/{ui,Grade,SlotCard,PixCheckout,CartaoCheckout,AgendaAdmin,ModalBalcao}.tsx
  e2e/{reserva.spec.ts,admin.spec.ts}  playwright.config.ts
infra/
  docker-compose.yml  .env.example  backup-db.sh
.github/workflows/ci.yml
docs/MAPA-AGENTES.md
```

## Ondas de execução (paralelismo)

| Wave | Agentes | Trechos | Depende de |
|---|---|---|---|
| **0** | 1 | T1 scaffold+contratos, T2 modelos+migração, T3 compose dev | — |
| **1** | 4 em paralelo | A1: T4 auth+equipe · A2: T5 preços/disponibilidade + T6 reservas/bloqueios/expiração · A3: T7 pagarme + T8 checkout/webhook/reconciliação · A4: T9 assinaturas/materialização | Wave 0 |
| **2** | 4 em paralelo | B1: T10 portal público · B2: T11 admin agenda/reservas/clientes · B3: T12 admin mensalistas/preços/caixa/relatórios/equipe · B4: T13 CI + T14 deploy VPS | Wave 1 (B1–B3 usam a API real rodando) |
| **3** | 1 | T15 E2E Playwright + T16 integração site estático + go-live | Wave 2 |

Regra de paralelismo: agentes da mesma wave **não editam os mesmos arquivos**. Contratos (schemas, `lib/api.ts`, modelos) são congelados na Wave 0 — mudança de contrato exige voltar ao orquestrador.

---

## CONTRATO DE API (congelado na Wave 0 — fonte de verdade)

Prefixo `/api/v1`. Auth: `Authorization: Bearer <access>`; refresh em cookie httpOnly `refresh_token`.

```
POST /auth/cliente/cadastro   {nome,email,senha,celular}                 → 201 {cliente:{id,nome,email},access_token}
POST /auth/cliente/login      {email,senha}                              → 200 {access_token} (+cookie refresh)
POST /auth/staff/login        {email,senha}                              → 200 {access_token,papel}
POST /auth/refresh            (cookie)                                   → 200 {access_token}
POST /auth/recuperar          {email}                                    → 204
POST /auth/redefinir          {token,senha}                              → 204

GET  /recursos                                                           → [{id,nome,tipo,ativo}]
GET  /disponibilidade?recurso_id&data=YYYY-MM-DD                         → {slots:[{inicio,fim,preco_centavos,livre}]}

POST /reservas                {recurso_id,inicio,fim}          (cliente) → 201 {id,status,valor_centavos,expira_em} | 409 {detail:"slot_ocupado"}
GET  /reservas/minhas                                          (cliente) → [{id,recurso,inicio,fim,status,valor_centavos}]
POST /reservas/{id}/cancelar                                   (cliente) → 200 {status} | 422 {detail:"fora_da_janela"}
GET  /reservas?recurso_id&de&ate&status                        (staff)   → lista paginada
POST /reservas/balcao {recurso_id,inicio,fim,cliente_id?,nome_avulso?,celular_avulso?,metodo} (staff) → 201
POST /reservas/{id}/cancelar-admin {estornar:bool}             (staff)   → 200

GET/POST/PUT/DELETE /bloqueios  {recurso_id,inicio,fim,motivo} (staff)
GET/POST/PUT/DELETE /precos     {recurso_id,dias_semana,hora_inicio,hora_fim,preco_centavos} (admin)

POST /pagamentos/checkout     {reserva_id,metodo:'pix'|'cartao',card_token?} (cliente)
                                                                         → {pagamento_id,status,pix_qr_code?,pix_copia_cola?}
GET  /pagamentos/{id}                                          (cliente) → {status:'pendente'|'pago'|'falhou'}
POST /webhooks/pagarme        (assinado, sem auth)                       → 200

GET/POST /assinaturas          (staff; POST cria+subscription)           → {id,cliente,recurso,dia_semana,hora_inicio,status,...}
POST /assinaturas/{id}/pausar|reativar|cancelar               (staff)
GET  /caixa?data=YYYY-MM-DD                                    (staff)   → {itens:[...],total_centavos,por_metodo:{...}}
GET  /relatorios/faturamento?de&ate                            (admin)   → {total_centavos,por_metodo,por_recurso,por_dia}
GET  /relatorios/ocupacao?de&ate                               (admin)   → {por_recurso:[{recurso,horas_vendidas,horas_disponiveis,taxa}]}
GET/POST/PUT /equipe                                           (admin)
```

---

# WAVE 0 — Fundação (1 agente, sequencial)

### Task T1: Scaffold do monorepo + contratos congelados

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/main.py`, `backend/app/schemas/*.py` (todos), `frontend/lib/api.ts`, `docs/MAPA-AGENTES.md`, `.gitignore`

**Interfaces:**
- Produces: todos os Pydantic schemas e o client TS `lib/api.ts` (contrato acima, tipado 1:1). Waves 1–2 importam daqui e NÃO alteram.

- [ ] **Step 1: `.gitignore` raiz**

```gitignore
__pycache__/
*.pyc
.venv/
node_modules/
.next/
infra/.env
backend/.env
frontend/.env*.local
*.db
.pytest_cache/
playwright-report/
test-results/
```

- [ ] **Step 2: `backend/pyproject.toml`**

```toml
[project]
name = "arena-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115", "uvicorn[standard]>=0.30", "sqlalchemy[asyncio]>=2.0",
  "asyncpg>=0.29", "alembic>=1.13", "pydantic[email]>=2.7", "pydantic-settings>=2.2",
  "passlib[bcrypt]>=1.7", "pyjwt>=2.8", "httpx>=0.27", "redis>=5.0",
  "apscheduler>=3.10", "python-multipart>=0.0.9",
]
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "ruff>=0.4", "aiosqlite>=0.20"]
[tool.ruff]
line-length = 100
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 3: `backend/app/config.py`**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://arena:arena@localhost:5432/arena"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-inseguro-trocar"
    jwt_access_min: int = 15
    jwt_refresh_dias: int = 30
    reserva_ttl_min: int = 15
    cancelamento_horas: int = 24
    janela_campo_dias: int = 14
    janela_quiosque_dias: int = 60
    pagarme_mode: str = "simulado"          # simulado|sandbox|producao
    pagarme_api_key: str = ""
    pagarme_webhook_secret: str = ""
    smtp_host: str = ""
    smtp_user: str = ""
    smtp_pass: str = ""
    frontend_url: str = "http://localhost:3000"
    tz_local: str = "America/Cuiaba"

    class Config:
        env_file = ".env"

settings = Settings()
```

- [ ] **Step 4: Schemas Pydantic — criar TODOS conforme contrato.** Exemplo completo de `backend/app/schemas/reservas.py` (os demais seguem o contrato acima com a mesma disciplina de tipos):

```python
from datetime import datetime
from pydantic import BaseModel
from app.models.enums import ReservaStatus, ReservaOrigem, MetodoPagamento

class ReservaCriar(BaseModel):
    recurso_id: int
    inicio: datetime
    fim: datetime

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
    model_config = {"from_attributes": True}

class SlotOut(BaseModel):
    inicio: datetime
    fim: datetime
    preco_centavos: int
    livre: bool

class DisponibilidadeOut(BaseModel):
    slots: list[SlotOut]
```

`schemas/auth.py`: `ClienteCadastro{nome,email:EmailStr,senha:str(min 8),celular}`, `Login{email,senha}`, `TokenOut{access_token,papel:str|None}`, `RecuperarIn{email}`, `RedefinirIn{token,senha}`.
`schemas/clientes.py`: `ClienteOut{id,nome,email,celular,cpf|None}`, `ClienteAdminCriar{nome,email,celular,cpf|None}`.
`schemas/recursos.py`: `RecursoOut{id,nome,tipo,ativo}`, `FaixaPrecoIn/Out{id,recurso_id,dias_semana:list[int],hora_inicio:int,hora_fim:int,preco_centavos}`, `BloqueioIn/Out{id,recurso_id,inicio,fim,motivo}`.
`schemas/assinaturas.py`: `AssinaturaCriar{cliente_id,recurso_id,dia_semana:int,hora_inicio:int,hora_fim:int,valor_mensal_centavos,metodo:'cartao'|'pix',card_token|None}`, `AssinaturaOut{id,cliente_nome,recurso_nome,dia_semana,hora_inicio,hora_fim,valor_mensal_centavos,status,proxima_cobranca|None}`.
`schemas/pagamentos.py`: `CheckoutIn{reserva_id,metodo:'pix'|'cartao',card_token|None}`, `CheckoutOut{pagamento_id,status,pix_qr_code|None,pix_copia_cola|None}`, `PagamentoOut{id,status,metodo,valor_centavos,pago_em|None}`.
`schemas/relatorios.py`: `CaixaOut{itens:list[CaixaItem],total_centavos,por_metodo:dict[str,int]}`, `FaturamentoOut{total_centavos,por_metodo:dict[str,int],por_recurso:dict[str,int],por_dia:list[{data,total_centavos}]}`, `OcupacaoOut{por_recurso:list[{recurso,horas_vendidas,horas_disponiveis,taxa:float}]}`.

- [ ] **Step 5: `frontend/lib/api.ts` — client tipado 1:1 com o contrato**

```typescript
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export type Recurso = { id: number; nome: string; tipo: "campo" | "quiosque"; ativo: boolean };
export type Slot = { inicio: string; fim: string; preco_centavos: number; livre: boolean };
export type Reserva = { id: number; recurso_id: number; recurso_nome: string; inicio: string; fim: string; status: string; origem: string; valor_centavos: number; expira_em?: string };
export type Checkout = { pagamento_id: number; status: string; pix_qr_code?: string; pix_copia_cola?: string };

let accessToken: string | null = null;
export function setToken(t: string | null) { accessToken = t; if (typeof window !== "undefined") { t ? localStorage.setItem("at", t) : localStorage.removeItem("at"); } }
export function getToken() { if (!accessToken && typeof window !== "undefined") accessToken = localStorage.getItem("at"); return accessToken; }

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init, credentials: "include",
    headers: { "Content-Type": "application/json", ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}), ...init.headers },
  });
  if (r.status === 401 && path !== "/auth/refresh") {
    const rr = await fetch(`${API}/auth/refresh`, { method: "POST", credentials: "include" });
    if (rr.ok) { const { access_token } = await rr.json(); setToken(access_token); return req(path, init); }
  }
  if (!r.ok) throw Object.assign(new Error(`${r.status}`), { status: r.status, body: await r.json().catch(() => null) });
  return r.status === 204 ? (undefined as T) : r.json();
}

export const api = {
  cadastro: (b: { nome: string; email: string; senha: string; celular: string }) => req<{ access_token: string }>("/auth/cliente/cadastro", { method: "POST", body: JSON.stringify(b) }),
  loginCliente: (b: { email: string; senha: string }) => req<{ access_token: string }>("/auth/cliente/login", { method: "POST", body: JSON.stringify(b) }),
  loginStaff: (b: { email: string; senha: string }) => req<{ access_token: string; papel: string }>("/auth/staff/login", { method: "POST", body: JSON.stringify(b) }),
  recursos: () => req<Recurso[]>("/recursos"),
  disponibilidade: (recursoId: number, data: string) => req<{ slots: Slot[] }>(`/disponibilidade?recurso_id=${recursoId}&data=${data}`),
  criarReserva: (b: { recurso_id: number; inicio: string; fim: string }) => req<Reserva>("/reservas", { method: "POST", body: JSON.stringify(b) }),
  minhasReservas: () => req<Reserva[]>("/reservas/minhas"),
  cancelarReserva: (id: number) => req<{ status: string }>(`/reservas/${id}/cancelar`, { method: "POST" }),
  checkout: (b: { reserva_id: number; metodo: "pix" | "cartao"; card_token?: string }) => req<Checkout>("/pagamentos/checkout", { method: "POST", body: JSON.stringify(b) }),
  pagamento: (id: number) => req<{ status: string }>(`/pagamentos/${id}`),
  // admin
  reservasAdmin: (q: string) => req<Reserva[]>(`/reservas?${q}`),
  reservaBalcao: (b: object) => req<Reserva>("/reservas/balcao", { method: "POST", body: JSON.stringify(b) }),
  cancelarAdmin: (id: number, estornar: boolean) => req(`/reservas/${id}/cancelar-admin`, { method: "POST", body: JSON.stringify({ estornar }) }),
  bloqueios: { listar: (q: string) => req<object[]>(`/bloqueios?${q}`), criar: (b: object) => req("/bloqueios", { method: "POST", body: JSON.stringify(b) }), remover: (id: number) => req(`/bloqueios/${id}`, { method: "DELETE" }) },
  precos: { listar: () => req<object[]>("/precos"), criar: (b: object) => req("/precos", { method: "POST", body: JSON.stringify(b) }), atualizar: (id: number, b: object) => req(`/precos/${id}`, { method: "PUT", body: JSON.stringify(b) }), remover: (id: number) => req(`/precos/${id}`, { method: "DELETE" }) },
  assinaturas: { listar: () => req<object[]>("/assinaturas"), criar: (b: object) => req("/assinaturas", { method: "POST", body: JSON.stringify(b) }), acao: (id: number, acao: string) => req(`/assinaturas/${id}/${acao}`, { method: "POST" }) },
  clientes: { listar: (busca: string) => req<object[]>(`/clientes?busca=${busca}`), criar: (b: object) => req("/clientes", { method: "POST", body: JSON.stringify(b) }) },
  caixa: (data: string) => req<object>(`/caixa?data=${data}`),
  faturamento: (de: string, ate: string) => req<object>(`/relatorios/faturamento?de=${de}&ate=${ate}`),
  ocupacao: (de: string, ate: string) => req<object>(`/relatorios/ocupacao?de=${de}&ate=${ate}`),
  equipe: { listar: () => req<object[]>("/equipe"), criar: (b: object) => req("/equipe", { method: "POST", body: JSON.stringify(b) }), atualizar: (id: number, b: object) => req(`/equipe/${id}`, { method: "PUT", body: JSON.stringify(b) }) },
};
```

- [ ] **Step 6: `docs/MAPA-AGENTES.md`** — copiar a tabela de ondas deste plano + regra "mesma wave não toca no mesmo arquivo; contrato congelado".

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: scaffold monorepo + contratos congelados (schemas e client)"
```

### Task T2: Modelos SQLAlchemy + migração inicial (com EXCLUDE)

**Files:**
- Create: `backend/app/models/{base,enums,entities,__init__}.py`, `backend/app/db.py`, `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_inicial.py`, `backend/app/seed.py`, `backend/tests/conftest.py`

**Interfaces:**
- Produces: entidades ORM `Cliente, Staff, Recurso, FaixaPreco, Reserva, Bloqueio, Assinatura, Pagamento, Auditoria`; enums `ReservaStatus, ReservaOrigem, MetodoPagamento, PagamentoStatus, AssinaturaStatus, PapelStaff, TipoRecurso`; `get_db()` dependency; fixture pytest `db` + `client` (httpx AsyncClient com app).

- [ ] **Step 1: `app/models/enums.py`**

```python
import enum

class TipoRecurso(str, enum.Enum):
    campo = "campo"; quiosque = "quiosque"

class PapelStaff(str, enum.Enum):
    admin = "admin"; atendente = "atendente"

class ReservaStatus(str, enum.Enum):
    pendente_pagamento = "pendente_pagamento"; confirmada = "confirmada"
    concluida = "concluida"; cancelada = "cancelada"; expirada = "expirada"

class ReservaOrigem(str, enum.Enum):
    online = "online"; balcao = "balcao"; mensalista = "mensalista"

class MetodoPagamento(str, enum.Enum):
    pix = "pix"; cartao = "cartao"; dinheiro = "dinheiro"; pix_manual = "pix_manual"

class PagamentoStatus(str, enum.Enum):
    pendente = "pendente"; pago = "pago"; falhou = "falhou"; estornado = "estornado"

class AssinaturaStatus(str, enum.Enum):
    ativa = "ativa"; pausada = "pausada"; inadimplente = "inadimplente"; cancelada = "cancelada"
```

- [ ] **Step 2: `app/models/entities.py`** (colunas exatamente como no spec §3; mostrar aqui as não óbvias)

```python
from datetime import datetime
from sqlalchemy import ForeignKey, String, Text, func, Index, ARRAY, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.models.base import Base
from app.models.enums import *

class Cliente(Base):
    __tablename__ = "clientes"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    senha_hash: Mapped[str | None] = mapped_column(String(100))   # None p/ cliente balcão sem senha
    celular: Mapped[str] = mapped_column(String(20))
    cpf: Mapped[str | None] = mapped_column(String(14))
    pagarme_customer_id: Mapped[str | None] = mapped_column(String(64))
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())

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
```

(Demais entidades: `Staff{nome,email UNIQUE,senha_hash,papel,ativo=True}`, `Recurso{nome,tipo,ativo,ordem}`, `FaixaPreco{recurso_id FK, dias_semana ARRAY(Integer), hora_inicio int, hora_fim int, preco_centavos int}`, `Bloqueio{recurso_id,inicio,fim,motivo,staff_id FK}`, `Assinatura{cliente_id,recurso_id,dia_semana,hora_inicio,hora_fim,valor_mensal_centavos,status,pagarme_subscription_id|None,proxima_cobranca|None}`, `Pagamento{reserva_id FK|None,assinatura_id FK|None,metodo,valor_centavos,status,pagarme_order_id|None,pagarme_charge_id|None,pago_em|None,registrado_por_staff_id FK|None,criado_em}`, `Auditoria{staff_id,acao String(60),entidade String(40),entidade_id int|None,dados JSONB,criado_em}`.)

- [ ] **Step 3: Migração `0001_inicial.py`** — `alembic revision --autogenerate -m inicial` com `DATABASE_URL` de dev e **acrescentar manualmente** no `upgrade()`:

```python
op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
op.execute("""
  ALTER TABLE reservas ADD CONSTRAINT reservas_sem_sobreposicao
  EXCLUDE USING gist (recurso_id WITH =, tstzrange(inicio, fim) WITH &&)
  WHERE (status IN ('pendente_pagamento','confirmada'))
""")
op.execute("""
  ALTER TABLE bloqueios ADD CONSTRAINT bloqueios_sem_sobreposicao
  EXCLUDE USING gist (recurso_id WITH =, tstzrange(inicio, fim) WITH &&)
""")
```

- [ ] **Step 4: `app/seed.py`** — cria (idempotente, por nome/email): recursos `Campo 1`, `Campo 2` (tipo campo), `Quiosque`; staff admin `admin@arenacacerense.com.br` senha via env `SEED_ADMIN_SENHA` (default `trocar123` apenas em dev); faixas de preço exemplo: campos seg–sex 08–18 → 15000, seg–sex 18–23 → 18000, sáb–dom 08–23 → 18000; quiosque qualquer dia 08–22 → 25000/período.

- [ ] **Step 5: `tests/conftest.py`** — Postgres efêmero via env `TEST_DATABASE_URL` (CI sobe service); fixtures: `db` (sessão com rollback por teste), `client` (AsyncClient ASGI), `cliente_logado`, `staff_admin_logado` (criam usuário + retornam headers). Rodar `alembic upgrade head` no início da suíte.

- [ ] **Step 6: Teste de fumaça da constraint**

```python
async def test_constraint_impede_sobreposicao(db):
    r = Recurso(nome="Campo T", tipo=TipoRecurso.campo, ativo=True, ordem=1)
    db.add(r); await db.flush()
    db.add(Reserva(recurso_id=r.id, inicio=dt(2026,8,10,18), fim=dt(2026,8,10,19),
                   status=ReservaStatus.confirmada, origem=ReservaOrigem.balcao, valor_centavos=0))
    await db.flush()
    db.add(Reserva(recurso_id=r.id, inicio=dt(2026,8,10,18), fim=dt(2026,8,10,19),
                   status=ReservaStatus.pendente_pagamento, origem=ReservaOrigem.online, valor_centavos=0))
    with pytest.raises(IntegrityError):
        await db.flush()
```

Run: `pytest backend/tests/ -k constraint -v` → PASS (contra Postgres de dev do T3).

- [ ] **Step 7: Commit** `feat: modelos, migração com EXCLUDE anti-double-booking, seeds e fixtures`

### Task T3: Compose de desenvolvimento + Dockerfiles + main.py

**Files:**
- Create: `infra/docker-compose.yml`, `infra/.env.example`, `backend/Dockerfile`, `frontend/Dockerfile`, `backend/app/main.py`, `backend/app/routers/health.py`, `backend/app/deps.py`

**Interfaces:**
- Produces: `docker compose up` local sobe postgres+redis+api; `app.main:app` com CORS, routers registrados (stubs vazios ok até as waves preencherem), `deps.get_db/get_cliente_atual/get_staff_atual/require_admin` (implementação real de auth chega em T4 — aqui `deps.py` só define `get_db`; T4 completa).

- [ ] **Step 1:** `infra/docker-compose.yml` — copiar padrão lave-e-seeg (§ exploração): postgres16+healthcheck, redis7, api (build ../backend, env_file .env, depends healthy, networks app+traefik com labels `api.arenacacerense.com.br`), web (build ../frontend, labels `reservas.arenacacerense.com.br`). Em dev, portas 8000/3000 expostas; labels Traefik inofensivas fora da VPS.
- [ ] **Step 2:** `backend/Dockerfile` (python:3.12-slim, uv/pip install, uvicorn) e `frontend/Dockerfile` (node:20-alpine, build standalone, runner). Copiar dos equivalentes do lave-e-seeg.
- [ ] **Step 3:** `main.py`: FastAPI, CORS (origens = `settings.frontend_url` + domínios arena), `include_router` de todos os routers (criar arquivos router com `router = APIRouter()` vazio para não quebrar import), startup: iniciar scheduler de `services/jobs.py` (T6/T8/T9 registram jobs; aqui arquivo existe com `def iniciar(app): pass`).
- [ ] **Step 4:** `/api/v1/health` → `{"status":"ok","db":true,"redis":true}` testando conexões.
- [ ] **Step 5:** `infra/.env.example` com TODAS as vars de `config.py` comentadas.
- [ ] **Step 6:** Validar: `docker compose config -q`, subir, `curl localhost:8000/api/v1/health` → ok. Commit `feat: infra dev (compose, dockerfiles, health)`.

---

# WAVE 1 — Backend (4 agentes em paralelo)

### Task T4 (Agente A1): Auth completa + equipe + rate-limit

**Files:**
- Create: `app/services/auth.py`, `app/services/ratelimit.py`, `app/services/auditoria.py`, `app/services/email.py`, `app/routers/auth.py`, `app/routers/equipe.py`, `app/routers/clientes.py`, `tests/test_auth.py`
- Modify: `app/deps.py` (adicionar `get_cliente_atual`, `get_staff_atual`, `require_admin`)

**Interfaces:**
- Consumes: modelos T2, schemas T1.
- Produces: `deps.get_cliente_atual() -> Cliente`, `deps.get_staff_atual() -> Staff`, `deps.require_admin() -> Staff` (HTTPException 401/403); `services.auth.criar_tokens(sub:str, tipo:'cliente'|'staff') -> (access,refresh)`; `services.auditoria.registrar(db, staff_id, acao, entidade, entidade_id, dados)`; `services.email.enviar(para, assunto, html)` (no-op logando se SMTP vazio).

- [ ] **Step 1 (teste primeiro):** `test_auth.py`: cadastro cliente 201 + login 200 + acesso `/reservas/minhas` com token; login staff + `/equipe` exige admin (atendente → 403); rate-limit: 6ª tentativa de login errada em 1 min → 429; refresh renova access; recuperar/redefinir com token de e-mail (capturar via monkeypatch de `email.enviar`).
- [ ] **Step 2:** Implementar `services/auth.py` (bcrypt via passlib; PyJWT HS256 com `settings.jwt_secret`; claims `{sub, tipo, exp}`; refresh guardado como cookie httpOnly `Secure SameSite=Lax`, rota refresh valida tipo). `services/ratelimit.py`: `INCR`+`EXPIRE 60` por `login:{email}:{ip}`, limite 5.
- [ ] **Step 3:** Routers conforme contrato. `/clientes` (staff): GET busca por nome/email/celular, POST cria sem senha (`senha_hash=None`) + auditoria.
- [ ] **Step 4:** `pytest tests/test_auth.py -v` → PASS. Commit `feat: auth cliente/staff, equipe, rate-limit, auditoria`.

### Task T5 (Agente A2): Preços + disponibilidade

**Files:**
- Create: `app/services/precos.py`, `app/services/disponibilidade.py`, `app/routers/precos.py`, `app/routers/disponibilidade.py`, `app/routers/bloqueios.py` (GET público não; staff CRUD), `tests/test_precos.py`, `tests/test_disponibilidade.py`

**Interfaces:**
- Consumes: modelos T2; deps de T4 (import por nome — arquivo já existe).
- Produces: `precos.preco_para(db, recurso, inicio, fim) -> int` (levanta `PrecoNaoConfigurado`); `disponibilidade.slots_do_dia(db, recurso, data_local) -> list[Slot]` onde Slot = dataclass `{inicio,fim,preco_centavos,livre}`; `disponibilidade.esta_livre(db, recurso_id, inicio, fim) -> bool`.

- [ ] **Step 1 (testes):**

```python
async def test_preco_por_faixa(db):
    campo = await criar_campo(db)
    db.add(FaixaPreco(recurso_id=campo.id, dias_semana=[0,1,2,3,4], hora_inicio=8, hora_fim=18, preco_centavos=15000))
    db.add(FaixaPreco(recurso_id=campo.id, dias_semana=[0,1,2,3,4], hora_inicio=18, hora_fim=23, preco_centavos=18000))
    await db.flush()
    # segunda 19h (UTC-4 Cuiabá) → faixa noturna
    assert await preco_para(db, campo, cuiaba(2026,8,10,19), cuiaba(2026,8,10,20)) == 18000

async def test_slots_marcam_ocupado_por_reserva_bloqueio(db): ...
    # cria reserva confirmada 18-19 e bloqueio 20-21; slots do dia: 18h e 20h livres=False, demais True

async def test_quiosque_gera_periodos(db): ...
    # tipo quiosque → 4 slots: manha/tarde/noite/dia
```

- [ ] **Step 2:** Implementar. Regras: slots de campo = horas cheias 08→22 (fim 23); quiosque = períodos fixos (constantes módulo: `PERIODOS_QUIOSQUE = [(8,12),(13,17),(18,22),(8,22)]`); conversão fuso via `zoneinfo(settings.tz_local)`; `livre=False` se intersecta reserva `pendente|confirmada`, bloqueio, ou passou (`inicio < agora`); dias além da janela (`janela_campo_dias`/`janela_quiosque_dias`) → rota retorna 422 `janela_excedida`.
- [ ] **Step 3:** Routers: `GET /disponibilidade` (público), `GET /recursos` (público — adicionar em `routers/precos.py`? NÃO: criar em `routers/disponibilidade.py` a rota `/recursos` para não criar arquivo fora do mapa), CRUD `/precos` (admin) e `/bloqueios` (staff; POST valida sobreposição com reservas confirmadas → 409 com lista de conflitos).
- [ ] **Step 4:** `pytest tests/test_precos.py tests/test_disponibilidade.py -v` → PASS. Commit `feat: preços por faixa e disponibilidade (campos + quiosque)`.

### Task T6 (Agente A2): Motor de reservas + expiração

**Files:**
- Create: `app/services/reservas.py`, `app/routers/reservas.py`, `tests/test_reservas.py`, `tests/test_expiracao.py`
- Modify: `app/services/jobs.py` (registrar job expiração)

**Interfaces:**
- Consumes: `precos.preco_para`, `disponibilidade.esta_livre`, deps T4.
- Produces: `reservas.criar_online(db, cliente, recurso_id, inicio, fim) -> Reserva` (409 `SlotOcupadoError`); `reservas.criar_balcao(db, staff, dados) -> Reserva`; `reservas.cancelar_cliente(db, cliente, reserva_id) -> Reserva` (`ForaDaJanelaError`); `reservas.cancelar_admin(db, staff, reserva_id, estornar) -> Reserva`; `reservas.expirar_pendentes(db) -> int`. **Hook de estorno:** `cancelar_*` chama `pagamentos.estornar_se_pago(db, reserva)` — assinatura definida aqui, implementada em T8; até lá `services/pagamentos.py` já existe com a função levantando `NotImplementedError` apenas se `PAGARME_MODE!='simulado'` (em simulado marca estornado).

- [ ] **Step 1 (testes):** criar_online calcula valor no servidor (ignora payload de preço); slot ocupado → 409; corrida simulada (duas sessões, segunda recebe IntegrityError → SlotOcupadoError); balcão nasce `confirmada` + `Pagamento(metodo=dinheiro, status=pago, registrado_por)`; cancelar dentro da janela → `cancelada`; fora → 422; `expirar_pendentes` muda só as vencidas (`criado_em + TTL < now`) para `expirada`.
- [ ] **Step 2:** Implementar service (transação: recalcula preço → INSERT → captura `IntegrityError` da constraint → rollback → `SlotOcupadoError`). `expira_em = criado_em + timedelta(minutes=settings.reserva_ttl_min)` no schema Out.
- [ ] **Step 3:** Router conforme contrato (paginação admin `?limit=&offset=`, default 50).
- [ ] **Step 4:** `jobs.py`: APScheduler `AsyncIOScheduler`; `iniciar(app)` agenda `expirar_pendentes` a cada 60 s (sessão própria por execução).
- [ ] **Step 5:** `pytest tests/test_reservas.py tests/test_expiracao.py -v` → PASS. Commit `feat: motor de reservas (online/balcão), cancelamento e expiração`.

### Task T7 (Agente A3): Serviço Pagar.me (3 modos)

**Files:**
- Create: `app/services/pagarme.py`, `tests/test_pagamentos.py` (parte 1)

**Interfaces:**
- Produces (contrato interno, usado por T8/T9):

```python
class PagarmeClient:
    async def criar_order_pix(self, cliente, valor_centavos, descricao) -> OrderResult
    async def criar_order_cartao(self, cliente, valor_centavos, descricao, card_token) -> OrderResult
    async def consultar_order(self, order_id) -> str            # 'pendente'|'pago'|'falhou'
    async def estornar_charge(self, charge_id) -> bool
    async def criar_subscription(self, cliente, valor_centavos, dia_cobranca, metodo, card_token|None) -> SubResult
    async def cancelar_subscription(self, sub_id) -> bool
# OrderResult = dataclass(order_id, charge_id, status, pix_qr_code|None, pix_copia_cola|None)
# SubResult   = dataclass(subscription_id, status)
def get_pagarme() -> PagarmeClient   # escolhe impl pelo settings.pagarme_mode
```

- [ ] **Step 1 (testes, modo simulado):** order PIX retorna `pix_copia_cola` começando com `SIMULADO-`; `consultar_order` retorna `pendente` antes de 5 s e `pago` depois (armazenar `criado_em` em Redis `simulado:order:{id}`); estorno sempre `True`; subscription retorna id `sub_SIM...`.
- [ ] **Step 2:** Implementar `SimuladoClient` (Redis) e `HttpClient` (httpx, base `https://api.pagar.me/core/v5`, auth Basic `sk:`, endpoints `/orders`, `/charges/{id}/refund`, `/subscriptions`; sandbox e producao diferem só pela chave). Erros HTTP → `PagarmeError` com corpo logado **sem dados de cartão**.
- [ ] **Step 3:** `pytest tests/test_pagamentos.py -v` → PASS. Commit `feat: cliente Pagar.me com modo simulado/sandbox/produção`.

### Task T8 (Agente A3): Checkout + webhook + reconciliação + estorno

**Files:**
- Create: `app/services/pagamentos.py` (substitui stub), `app/routers/pagamentos.py`, `app/routers/webhooks.py`, `tests/test_webhook.py`, `tests/test_pagamentos.py` (parte 2)
- Modify: `app/services/jobs.py` (job reconciliação 10 min)

**Interfaces:**
- Consumes: `get_pagarme()` T7, reservas T6.
- Produces: `pagamentos.iniciar_checkout(db, cliente, reserva_id, metodo, card_token) -> Pagamento` (422 se reserva não é dele/não pendente/expirada); `pagamentos.confirmar_por_order(db, order_id) -> None` (idempotente); `pagamentos.estornar_se_pago(db, reserva) -> None`; `pagamentos.reconciliar_pendentes(db) -> int`.

- [ ] **Step 1 (testes):** checkout PIX cria `Pagamento pendente` com order; webhook `order.paid` assinado confirma pagamento+reserva; **mesmo evento 2× confirma 1×** (Redis SETNX `wh:{event_id}` TTL 24 h); assinatura inválida → 401; `order.payment_failed` marca pagamento falhou (reserva segue pendente até TTL); `charge.refunded` → estornado; reconciliar: pagamento pendente >5 min com `consultar_order`='pago' → confirma.
- [ ] **Step 2:** Implementar. Webhook: HMAC-SHA256 do corpo bruto com `pagarme_webhook_secret` comparado ao header `X-Hub-Signature` (formato `sha256=<hex>`); em `simulado`, aceitar sem assinatura apenas se `settings.pagarme_mode=='simulado'`. Confirmação dispara `email.enviar` (template inline simples com dados da reserva).
- [ ] **Step 3:** Job `reconciliar_pendentes` a cada 10 min em `jobs.py`.
- [ ] **Step 4:** `pytest tests/test_webhook.py -v` → PASS. Commit `feat: checkout, webhook idempotente, reconciliação e estorno`.

### Task T9 (Agente A4): Assinaturas (mensalistas) + materialização

**Files:**
- Create: `app/services/assinaturas.py`, `app/routers/assinaturas.py`, `tests/test_assinaturas.py`

**Interfaces:**
- Consumes: `get_pagarme()` (T7 — contrato já congelado, dá pra desenvolver em paralelo com modo simulado), reservas T6.
- Produces: `assinaturas.criar(db, staff, dados) -> Assinatura` (valida conflito do slot semanal com assinaturas ativas e bloqueios); `assinaturas.materializar(db, semanas=5) -> int` (cria reservas `confirmada/mensalista` futuras faltantes, pulando conflitos com bloqueio — loga aviso); `assinaturas.processar_evento_sub(db, evento) -> None` (fatura paga → `ativa` + `proxima_cobranca`; falha → `inadimplente`; 2ª falha consecutiva → para de materializar; usa contador Redis `sub:falhas:{id}`); `pausar/reativar/cancelar` (cancelar → Pagar.me + deleta reservas futuras `mensalista` não iniciadas).

- [ ] **Step 1 (testes):** criar assinatura seg 19–20 gera sub no client simulado; `materializar` cria exatamente 5 reservas futuras (idempotente: 2ª chamada cria 0); slot conflitante com outra assinatura → 409; evento fatura falha 2× → status `inadimplente` e materializar passa a criar 0; cancelar remove futuras.
- [ ] **Step 2:** Implementar; registrar job diário `materializar` (03:00 local) em `jobs.py`; conectar eventos `subscription.*`/`invoice.*` no dispatcher do webhook (T8 expõe dict `HANDLERS` — adicionar entradas aqui).
- [ ] **Step 3:** `pytest tests/test_assinaturas.py -v` → PASS. Commit `feat: assinaturas mensalistas com materialização automática`.

### Task T9b (Agente A4): Caixa + relatórios

**Files:**
- Create: `app/routers/caixa.py`, `app/routers/relatorios.py`, `tests/test_caixa.py`

**Interfaces:**
- Consumes: modelos.
- Produces: rotas do contrato. Faturamento = SUM pagamentos `pago` no período (por método/recurso/dia); ocupação = horas de reservas `confirmada|concluida` ÷ horas disponíveis (slots do período menos bloqueios).

- [ ] **Step 1 (teste):** semear pagamentos (2 pix pagos, 1 dinheiro, 1 pendente) → caixa do dia soma só pagos com método certo; faturamento por recurso bate.
- [ ] **Step 2:** Implementar com SQL agregado (func.sum/group_by).
- [ ] **Step 3:** PASS + Commit `feat: caixa do dia e relatórios de faturamento/ocupação`.

---

# WAVE 2 — Frontend + infra (4 agentes em paralelo)

Padrão visual (todos os agentes B1–B3): importar de `components/ui.tsx` — criar UMA vez em T10 Step 1 com: fontes Kanit/Saira (next/font), cores `--azul:#0B63D8 --ciano:#00AFEF --tinta:#171335 --fundo:#F6F8FC`, componentes `<Botao>`, `<BotaoSecundario>`, `<Card>`, `<Campo>` (input), `<Titulo>` (Kanit itálico 900 uppercase), `<Badge status>`. B2/B3 **importam** de lá, não redefinem estilo.

### Task T10 (Agente B1): Portal público

**Files:**
- Create: `frontend/{package.json,next.config.mjs,tsconfig.json}`, `app/{layout,page,globals.css}`, `app/entrar/page.tsx`, `app/cadastro/page.tsx`, `app/recuperar/page.tsx`, `app/checkout/[reservaId]/page.tsx`, `app/conta/page.tsx`, `components/{ui,Grade,SlotCard,PixCheckout,CartaoCheckout}.tsx`, `lib/{auth,format}.ts`

**Interfaces:**
- Consumes: `lib/api.ts` (T1, congelado).
- Produces: portal navegável. `lib/format.ts`: `centavos(n)->"R$ 150,00"`, `horaLocal(iso)`, `dataLocal(iso)`.

- [ ] **Step 1:** `ui.tsx` + `layout.tsx` (fontes, header com logo `mark.png` copiada do site, nav Entrar/Minha conta) + `globals.css`.
- [ ] **Step 2:** `page.tsx` (grade): tabs de recurso (api.recursos), seletor de 7 dias, `Grade` renderiza `SlotCard` (livre → preço + botão; ocupado → riscado). Clique: sem login → `/entrar?volta=...`; logado → `api.criarReserva` → push `/checkout/{id}`; 409 → toast "Esse horário acabou de sair — escolhe outro" + refetch.
- [ ] **Step 3:** Auth pages (cadastro valida senha ≥8 e celular; erros da API exibidos no formulário).
- [ ] **Step 4:** Checkout: contador regressivo até `expira_em`; escolha PIX (`PixCheckout`: chama `api.checkout`, mostra copia-e-cola + botão copiar, faz polling `api.pagamento` a cada 3 s → pago = tela de sucesso com detalhes) ou Cartão (`CartaoCheckout`: campos número/validade/cvv → tokenização: em `simulado`, enviar `card_token:"tok_simulado"`; em produção usar tokenizecard.js da Pagar.me — deixar o input pronto e o token vindo de `window.PagarmeTokenize` se presente). Expirou → aviso + voltar pra grade.
- [ ] **Step 5:** `conta/page.tsx`: próximas reservas (status badge), botão cancelar (confirma; 422 → mensagem da janela), histórico.
- [ ] **Step 6:** `npm run build` sem erro. Commit `feat: portal público (grade, auth, checkout pix/cartão, minha conta)`.

### Task T11 (Agente B2): Admin — agenda, reservas, clientes

**Files:**
- Create: `app/admin/layout.tsx`, `app/admin/page.tsx`, `app/admin/reservas/page.tsx`, `app/admin/clientes/page.tsx`, `components/{AgendaAdmin,ModalBalcao}.tsx`

**Interfaces:**
- Consumes: `lib/api.ts`, `components/ui.tsx` (T10 Step 1 — coordenar: B2/B3 só começam após commit do Step 1 de T10; orquestrador libera).
- Produces: `/admin` funcional p/ atendente.

- [ ] **Step 1:** `admin/layout.tsx`: guarda de rota (token staff; papel vindo do login guardado em localStorage `papel`), sidebar com itens filtrados por papel, logout.
- [ ] **Step 2:** `AgendaAdmin`: visão dia — 3 colunas (recursos) × linhas de slot; célula colorida por status (verde confirmada, âmbar pendente, azul mensalista, cinza bloqueio, branco livre); seletor de data; clique livre → `ModalBalcao` (buscar cliente por nome/celular ou avulso + método dinheiro/pix_manual) → `api.reservaBalcao` → refetch; clique em reserva → painel lateral com detalhes + cancelar (admin pode estornar). Botão "Bloquear" → mini-form início/fim/motivo → `api.bloqueios.criar`; 409 mostra conflitos.
- [ ] **Step 3:** `/admin/reservas`: filtros (recurso, status, período), tabela paginada, ações.
- [ ] **Step 4:** `/admin/clientes`: busca, criar cliente balcão, ver histórico (reutiliza `api.reservasAdmin('cliente_id=')` — adicionar query no contrato? **Não**: usar filtro existente `?busca` em clientes e detalhe carrega `/reservas?cliente_id=` que JÁ existe no contrato admin com filtros genéricos).
- [ ] **Step 5:** Build ok. Commit `feat: admin agenda interativa, reservas e clientes`.

### Task T12 (Agente B3): Admin — mensalistas, preços, caixa, relatórios, equipe

**Files:**
- Create: `app/admin/{mensalistas,precos,caixa,relatorios,equipe}/page.tsx`

**Interfaces:**
- Consumes: `lib/api.ts`, `ui.tsx`.

- [ ] **Step 1:** Mensalistas: lista com badge de status (inadimplente em vermelho no topo), criar (cliente + recurso + dia/hora + valor + método), ações pausar/reativar/cancelar (confirmação dupla no cancelar).
- [ ] **Step 2:** Preços: tabela editável por recurso (dias da semana como chips seg–dom, faixa hora início/fim, valor em reais convertido pra centavos no submit).
- [ ] **Step 3:** Caixa: seletor de data (default hoje), itens do dia, totais por método, total geral.
- [ ] **Step 4:** Relatórios (admin): período de/até, cards de faturamento total + por método, tabela por recurso, gráfico simples de barras por dia (CSS puro, sem lib), ocupação por recurso com taxa %.
- [ ] **Step 5:** Equipe (admin): CRUD staff, papel, ativar/desativar.
- [ ] **Step 6:** Build ok. Commit `feat: admin mensalistas, preços, caixa, relatórios e equipe`.

### Task T13 (Agente B4): CI GitHub Actions

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1:** Workflow com 2 jobs: `backend` (services postgres:16 + redis:7; `pip install -e backend[dev]`; `ruff check backend`; `alembic upgrade head`; `pytest backend/tests -q` com `TEST_DATABASE_URL`) e `frontend` (`npm ci && npm run lint && npm run build` em frontend/). Trigger push+PR.
- [ ] **Step 2:** Commit `chore: CI backend+frontend`; confirmar verde no Actions após push.

### Task T14 (Agente B4): Deploy na VPS + DNS

**Files:**
- Create: `infra/backup-db.sh`, `infra/DEPLOY.md`

- [ ] **Step 1:** Criar repo GitHub público `arena-sistema` (`ssh vps "gh repo create henriquehmas-rgb/arena-sistema --public ..."`), push main.
- [ ] **Step 2:** Na VPS: clone em `/docker/arena-sistema`, criar `infra/.env` real (senhas geradas `openssl rand -hex 24`; PAGARME_MODE=simulado até chaves reais), `docker compose up -d --build`, `alembic upgrade head` + seed no container api.
- [ ] **Step 3:** DNS (zona Hostinger, via painel): registros A `reservas` e `api` → `191.96.251.71`, TTL 300. Traefik emite certs.
- [ ] **Step 4:** `backup-db.sh` (pg_dump diário, rotação 14 dias) + linha no cron da VPS. `DEPLOY.md` documenta tudo.
- [ ] **Step 5:** Smoke: `curl https://api.arenacacerense.com.br/api/v1/health` ok; portal abre. Commit `chore: deploy VPS + backup`.

---

# WAVE 3 — Integração final (1 agente)

### Task T15: E2E Playwright

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/reserva.spec.ts`, `frontend/e2e/admin.spec.ts`

- [ ] **Step 1:** Config aponta pra stack local (compose) com `PAGARME_MODE=simulado`.
- [ ] **Step 2:** `reserva.spec.ts`: cadastro → grade → escolher slot → checkout PIX → aguardar polling confirmar (simulado ~5 s) → "Reserva confirmada" → aparece em Minha conta.
- [ ] **Step 3:** `admin.spec.ts`: login staff → reserva balcão em slot livre → aparece na agenda confirmada → caixa do dia soma → bloquear horário → slot some do portal público.
- [ ] **Step 4:** Rodar local verde; adicionar job `e2e` opcional (não bloqueante) no CI. Commit `test: e2e reserva online e fluxo balcão`.

### Task T16: Ligar o site estático + go-live

**Files:**
- Modify: site estático (`/docker/arena-cacerense/site/*.html` + fonte local `C:\Users\henri\.claude\Arena Cacerense\*.dc.html`): botões RESERVAR e slots da grade ilustrativa de `campos.dc.html` → `https://reservas.arenacacerense.com.br` (manter WhatsApp no rodapé/contato).

- [ ] **Step 1:** Editar os `.dc.html` locais (links dos CTAs), re-testar visual, `scp` pro VPS.
- [ ] **Step 2:** Teste manual guiado com o Henrique: reserva real em modo simulado ponta a ponta + balcão + relatório.
- [ ] **Step 3:** Checklist de produção: trocar `PAGARME_MODE` quando houver chaves; conferir `.env`; commit final.

---

## Self-review (feito)

1. **Cobertura do spec:** §1–§10 mapeados → T1–T16 (auth §2/§7→T4; modelo §3→T2; fluxos §4→T5/T6/T8/T9; Pagar.me §5→T7/T8; telas §6→T10–T12; segurança §7→T4/T8/global; erros §8→T6/T8; testes/CI §9→testes por task+T13/T15; deploy §10→T14/T16). Pacote campo+quiosque: coberto pelo modelo (`pacote_grupo_id` em T2) e checkout único — UI do pacote fica explícita em T10 Step 2 (grade do quiosque oferece "adicionar campo junto" criando 2 reservas com o mesmo grupo via 2 chamadas + checkout da 1ª; simplificação v1 registrada).
2. **Placeholders:** nenhum TBD; onde o código completo não está inline, o contrato exato de entrada/saída está no bloco Interfaces + CONTRATO DE API congelado.
3. **Consistência de tipos:** nomes conferidos entre contrato, schemas T1, services T5–T9 e client T1 (`preco_para`, `esta_livre`, `SlotOcupadoError`, `get_pagarme`, rotas).
