# Agenda Admin — Cards de Cliente/Pagamento + Notificação por E-mail — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesenhar a Agenda do admin (`components/AgendaAdmin.tsx`) pra mostrar cards com nome do cliente e status de pagamento em cada agendamento, com um modal de detalhe (nome, celular, e-mail, método/status de pagamento) e um botão de notificação por e-mail.

**Architecture:** Backend enriquece `ReservaOut` (contrato de `GET /reservas`) com dados de cliente e pagamento mais recente, sem exigir migração de banco (tudo computado na serialização a partir de relações já existentes). Novo endpoint `POST /reservas/{id}/notificar` dispara um e-mail fixo via o módulo `email_templates` já existente. Frontend troca o preenchimento sólido das células por cards brancos com barra lateral colorida, e o painel lateral de detalhe por um modal central (mesmo padrão visual de `ModalBloqueio`).

**Tech Stack:** FastAPI + SQLAlchemy2 async (backend), Next.js 14 App Router + TypeScript (frontend), Postgres (sem migração nesta feature), pytest (testes backend), verificação manual no navegador (não há suíte de teste de frontend neste projeto).

## Global Constraints

- Escopo só a Agenda do admin (`/admin`, `components/AgendaAdmin.tsx`) — nenhuma outra tela muda.
- Sem migração de banco: os campos novos em `ReservaOut` são computados na serialização, não colunas novas.
- Botão de notificar sempre manda o e-mail fixo de lembrete (sem campo de texto livre).
- `POST /reservas/{id}/notificar` exige autenticação de staff (qualquer papel), mesmo padrão de `POST /reservas/balcao`.
- Diferente dos e-mails automáticos do sistema (best-effort/silenciosos), a falha de `notificar_cliente` **propaga** — é uma ação disparada de propósito pelo staff.
- Modal de detalhe = modal central (`position:fixed; alignItems:center; justifyContent:center`), mesmo padrão visual de `ModalBloqueio` em `components/AgendaAdmin.tsx`.
- Suíte completa do backend (129 testes + os novos) deve passar verde, e `ruff check backend` limpo, antes de considerar qualquer task concluída.
- Verificação de frontend é manual no navegador local (login staff → abrir agenda → interagir), documentada passo a passo em cada task — não existe suíte de teste de frontend neste projeto hoje.

---

### Task 1: Backend — enriquecer `ReservaOut` com dados de cliente

**Files:**
- Modify: `backend/app/models/entities.py:84` (adiciona relationship `cliente` em `Reserva`, logo após `recurso`)
- Modify: `backend/app/schemas/reservas.py:1-35` (import `PagamentoStatus`, novos campos em `ReservaOut`)
- Modify: `backend/app/routers/reservas.py:69-83` (`_para_out` preenche os campos novos a partir de `reserva.cliente`/avulso)
- Modify: `backend/app/services/reservas.py:112-121` (`criar_online`: atribui `reserva.cliente = cliente`)
- Modify: `backend/app/services/reservas.py:151-163` (`criar_balcao`: atribui `reserva.cliente = cliente` quando `dados.cliente_id` não é `None`)
- Test: `backend/tests/test_reservas.py` (novo teste no final do arquivo)

**Interfaces:**
- Consumes: nada de tasks anteriores (task inicial).
- Produces: `ReservaOut` com `cliente_nome: str | None`, `cliente_celular: str | None`, `cliente_email: str | None` — Task 2 e Task 6 (frontend) dependem desses três nomes exatos.

- [ ] **Step 1: Adicionar a relationship `cliente` em `Reserva`**

Em `backend/app/models/entities.py`, linha 84 (logo após `recurso = relationship("Recurso", lazy="joined")` dentro de `class Reserva`):

```python
    recurso = relationship("Recurso", lazy="joined")
    cliente = relationship("Cliente", lazy="joined")
```

- [ ] **Step 2: Escrever o teste que falha primeiro**

Adicionar ao final de `backend/tests/test_reservas.py`:

```python
# --- enriquecimento de ReservaOut com dados de cliente (agenda admin) -------


async def test_rota_criar_reserva_inclui_dados_do_cliente(client, db, cliente_logado):
    recurso = await criar_recurso(db, nome="Campo T6 Cliente Nome")
    await criar_faixa_padrao(db, recurso)
    inicio, fim = horario_futuro(dias=6)

    resp = await client.post(
        "/api/v1/reservas",
        json={
            "recurso_id": recurso.id,
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
        },
        headers=cliente_logado["headers"],
    )
    assert resp.status_code == 201, resp.text
    corpo = resp.json()
    assert corpo["cliente_nome"] == cliente_logado["cliente"].nome
    assert corpo["cliente_celular"] == cliente_logado["cliente"].celular
    assert corpo["cliente_email"] == cliente_logado["cliente"].email


async def test_rota_criar_balcao_avulso_sem_email(client, db, staff_admin_logado):
    recurso = await criar_recurso(db, nome="Campo T6 Balcao Avulso")
    await criar_faixa_padrao(db, recurso)
    inicio, fim = horario_futuro(dias=7)

    resp = await client.post(
        "/api/v1/reservas/balcao",
        json={
            "recurso_id": recurso.id,
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
            "nome_avulso": "Cliente Avulso Teste",
            "celular_avulso": "65988887777",
            "metodo": "dinheiro",
        },
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 201, resp.text
    corpo = resp.json()
    assert corpo["cliente_nome"] == "Cliente Avulso Teste"
    assert corpo["cliente_celular"] == "65988887777"
    assert corpo["cliente_email"] is None
```

- [ ] **Step 3: Rodar os testes e confirmar que falham**

Run (com `DATABASE_URL`/`TEST_DATABASE_URL`/`REDIS_URL` apontando pro Postgres/Redis de teste, ver `tests/conftest.py`):

```bash
cd backend
python -m pytest tests/test_reservas.py::test_rota_criar_reserva_inclui_dados_do_cliente tests/test_reservas.py::test_rota_criar_balcao_avulso_sem_email -v
```

Expected: FAIL — `KeyError: 'cliente_nome'` (o campo ainda não existe na resposta).

- [ ] **Step 4: Adicionar `PagamentoStatus` ao import e os campos novos em `ReservaOut`**

Em `backend/app/schemas/reservas.py`, linha 3:

```python
from app.models.enums import MetodoPagamento, PagamentoStatus, ReservaOrigem, ReservaStatus
```

Linhas 25-35 (`class ReservaOut`) — substituir por:

```python
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
    cliente_nome: str | None = None
    cliente_celular: str | None = None
    cliente_email: str | None = None
    pagamento_metodo: MetodoPagamento | None = None
    pagamento_status: PagamentoStatus | None = None
    model_config = {"from_attributes": True}
```

- [ ] **Step 5: Atualizar `_para_out` em `backend/app/routers/reservas.py`**

Substituir as linhas 69-83 (`def _para_out(reserva: Reserva) -> ReservaOut:`) por:

```python
def _para_out(reserva: Reserva) -> ReservaOut:
    expira_em = None
    if reserva.status == ReservaStatus.pendente_pagamento:
        expira_em = reserva.criado_em + timedelta(minutes=settings.reserva_ttl_min)

    if reserva.cliente_id is not None:
        cliente_nome = reserva.cliente.nome
        cliente_celular = reserva.cliente.celular
        cliente_email = reserva.cliente.email
    else:
        cliente_nome = reserva.nome_avulso
        cliente_celular = reserva.celular_avulso
        cliente_email = None

    return ReservaOut(
        id=reserva.id,
        recurso_id=reserva.recurso_id,
        recurso_nome=reserva.recurso.nome,
        inicio=reserva.inicio,
        fim=reserva.fim,
        status=reserva.status,
        origem=reserva.origem,
        valor_centavos=reserva.valor_centavos,
        expira_em=expira_em,
        cliente_nome=cliente_nome,
        cliente_celular=cliente_celular,
        cliente_email=cliente_email,
    )
```

(`pagamento_metodo`/`pagamento_status` ficam de fora por enquanto — usam o
default `None` do schema. Task 2 adiciona um parâmetro `pagamento` a esta
função.)

- [ ] **Step 6: Atribuir `reserva.cliente` explicitamente em `criar_online`**

Em `backend/app/services/reservas.py`, dentro de `criar_online` (por volta
da linha 121), logo após `reserva.recurso = recurso`:

```python
    reserva.recurso = recurso
    # Atribuir o objeto (não só cliente_id) preenche a relationship em
    # memória — sem isso, `_para_out` acessando `reserva.cliente` logo
    # depois do insert dispara `MissingGreenlet` (mesma classe de bug já
    # corrigida nesta sessão para `Assinatura.cliente`/`.recurso`: um
    # objeto recém-inserido, nunca reconsultado via SELECT, não tem a
    # relationship carregada mesmo com `lazy="joined"` — esse `lazy` só
    # afeta como um SELECT futuro carregaria o objeto).
    reserva.cliente = cliente
    return await _inserir(db, reserva)
```

- [ ] **Step 7: Atribuir `reserva.cliente` explicitamente em `criar_balcao` (quando houver cliente cadastrado)**

Ainda em `backend/app/services/reservas.py`, dentro de `criar_balcao` (por
volta da linha 162), logo após `reserva.recurso = recurso`:

```python
    reserva.recurso = recurso
    if dados.cliente_id is not None:
        # Mesmo motivo do comentário em `criar_online` — evita
        # MissingGreenlet ao acessar `reserva.cliente` em `_para_out`.
        reserva.cliente = cliente
    reserva = await _inserir(db, reserva)
```

- [ ] **Step 8: Rodar os testes de novo e confirmar que passam**

```bash
cd backend
python -m pytest tests/test_reservas.py -v
```

Expected: PASS em todos os testes de `test_reservas.py` (os 2 novos +
todos os existentes, sem regressão).

- [ ] **Step 9: Rodar a suíte completa e o ruff**

```bash
cd backend
ruff check .
python -m pytest -q
```

Expected: `All checks passed!` e todos os testes passando (129 + 2 novos =
131).

- [ ] **Step 10: Commit**

```bash
git add backend/app/models/entities.py backend/app/schemas/reservas.py backend/app/routers/reservas.py backend/app/services/reservas.py backend/tests/test_reservas.py
git commit -m "feat: ReservaOut inclui nome/celular/e-mail do cliente (ou avulso)"
```

---

### Task 2: Backend — enriquecer `ReservaOut` com método/status de pagamento

**Files:**
- Modify: `backend/app/services/reservas.py` (nova função `pagamentos_mais_recentes`, logo após `listar_staff`)
- Modify: `backend/app/routers/reservas.py:69-90` (`_para_out` ganha parâmetro `pagamento`), `:140-163` (`listar_reservas_staff` busca e passa os pagamentos)
- Test: `backend/tests/test_reservas.py`

**Interfaces:**
- Consumes: `ReservaOut.pagamento_metodo`/`.pagamento_status` já existem no schema (Task 1, default `None`); `reservas_service.listar_staff` já existe e devolve `(list[Reserva], int)`.
- Produces: `reservas_service.pagamentos_mais_recentes(db, reserva_ids: list[int]) -> dict[int, Pagamento]` — usado só por `listar_reservas_staff` nesta feature, mas fica público no serviço.

- [ ] **Step 1: Escrever o teste que falha primeiro**

Adicionar ao final de `backend/tests/test_reservas.py`:

```python
async def test_rota_listar_staff_inclui_pagamento_mais_recente(client, db, staff_admin_logado):
    recurso = await criar_recurso(db, nome="Campo T6 Pagamento Recente")
    inicio, fim = horario_futuro(dias=8)

    reserva_com_pagamento = Reserva(
        recurso_id=recurso.id,
        inicio=inicio,
        fim=fim,
        status=ReservaStatus.confirmada,
        origem=ReservaOrigem.balcao,
        valor_centavos=PRECO_PADRAO_CENTAVOS,
    )
    db.add(reserva_com_pagamento)
    await db.flush()

    # Dois pagamentos pra confirmar que pega o MAIS RECENTE (pago), não o
    # primeiro que tentou e falhou.
    db.add(
        Pagamento(
            reserva_id=reserva_com_pagamento.id,
            metodo=MetodoPagamento.pix,
            valor_centavos=PRECO_PADRAO_CENTAVOS,
            status=PagamentoStatus.falhou,
            criado_em=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    db.add(
        Pagamento(
            reserva_id=reserva_com_pagamento.id,
            metodo=MetodoPagamento.dinheiro,
            valor_centavos=PRECO_PADRAO_CENTAVOS,
            status=PagamentoStatus.pago,
            pago_em=datetime.now(timezone.utc),
        )
    )

    reserva_sem_pagamento = Reserva(
        recurso_id=recurso.id,
        inicio=inicio + timedelta(hours=1),
        fim=fim + timedelta(hours=1),
        status=ReservaStatus.pendente_pagamento,
        origem=ReservaOrigem.online,
        valor_centavos=PRECO_PADRAO_CENTAVOS,
    )
    db.add(reserva_sem_pagamento)
    await db.flush()

    resp = await client.get(
        f"/api/v1/reservas?recurso_id={recurso.id}",
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 200, resp.text
    por_id = {item["id"]: item for item in resp.json()["itens"]}

    assert por_id[reserva_com_pagamento.id]["pagamento_metodo"] == "dinheiro"
    assert por_id[reserva_com_pagamento.id]["pagamento_status"] == "pago"
    assert por_id[reserva_sem_pagamento.id]["pagamento_metodo"] is None
    assert por_id[reserva_sem_pagamento.id]["pagamento_status"] is None
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

```bash
cd backend
python -m pytest tests/test_reservas.py::test_rota_listar_staff_inclui_pagamento_mais_recente -v
```

Expected: FAIL — os dois itens vêm com `pagamento_metodo`/`pagamento_status` `None` (a rota ainda não busca pagamentos).

- [ ] **Step 3: Adicionar `pagamentos_mais_recentes` em `backend/app/services/reservas.py`**

Logo após a função `listar_staff` (que termina retornando `itens, total`):

```python
async def pagamentos_mais_recentes(
    db: AsyncSession, reserva_ids: list[int]
) -> dict[int, Pagamento]:
    """Retorna o `Pagamento` mais recente (por `criado_em`) de cada reserva
    em `reserva_ids`, indexado por `reserva_id` — usado pela listagem da
    agenda do staff pra mostrar método/status de pagamento em cada card
    sem emitir uma query por reserva (evita N+1). Uma reserva pode ter mais
    de um `Pagamento` (ex.: uma tentativa que falhou seguida de outra que
    pagou) — o mais recente é o que reflete o estado atual."""
    if not reserva_ids:
        return {}
    resultado = await db.execute(
        select(Pagamento)
        .where(Pagamento.reserva_id.in_(reserva_ids))
        .order_by(Pagamento.reserva_id, Pagamento.criado_em.desc())
    )
    mais_recentes: dict[int, Pagamento] = {}
    for pagamento in resultado.scalars().all():
        if pagamento.reserva_id not in mais_recentes:
            mais_recentes[pagamento.reserva_id] = pagamento
    return mais_recentes
```

- [ ] **Step 4: Atualizar `_para_out` pra aceitar `pagamento` opcional**

Em `backend/app/routers/reservas.py`, mudar a assinatura de `_para_out`
(escrita na Task 1, Step 5) de `def _para_out(reserva: Reserva) -> ReservaOut:`
para:

```python
def _para_out(reserva: Reserva, pagamento: Pagamento | None = None) -> ReservaOut:
```

E adicionar `pagamento_metodo`/`pagamento_status` na construção do
`ReservaOut` (mesma função, últimas duas linhas antes do `)` final):

```python
        cliente_nome=cliente_nome,
        cliente_celular=cliente_celular,
        cliente_email=cliente_email,
        pagamento_metodo=pagamento.metodo if pagamento else None,
        pagamento_status=pagamento.status if pagamento else None,
    )
```

Adicionar `Pagamento` ao import de `app.models.entities` no topo do
arquivo (linha 27, já importa `Cliente, Reserva, Staff` — vira
`Cliente, Pagamento, Reserva, Staff`).

- [ ] **Step 5: Passar os pagamentos em `listar_reservas_staff`**

Substituir o corpo da função `listar_reservas_staff` (linhas 151-163) por:

```python
    inicio_utc, fim_utc = _limites_periodo_utc(de, ate)
    itens, total = await reservas_service.listar_staff(
        db,
        recurso_id=recurso_id,
        de=inicio_utc,
        ate=fim_utc,
        status_=status_filtro,
        cliente_id=cliente_id,
        limit=limit,
        offset=offset,
    )
    pagamentos_por_reserva = await reservas_service.pagamentos_mais_recentes(
        db, [item.id for item in itens]
    )
    return ReservaListaOut(
        itens=[_para_out(item, pagamentos_por_reserva.get(item.id)) for item in itens],
        total=total,
    )
```

- [ ] **Step 6: Rodar o teste de novo e confirmar que passa**

```bash
cd backend
python -m pytest tests/test_reservas.py -v
```

Expected: PASS em todos os testes.

- [ ] **Step 7: Rodar a suíte completa e o ruff**

```bash
cd backend
ruff check .
python -m pytest -q
```

Expected: `All checks passed!` e 132 testes passando.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/reservas.py backend/app/routers/reservas.py backend/tests/test_reservas.py
git commit -m "feat: GET /reservas (staff) inclui método/status do pagamento mais recente"
```

---

### Task 3: Backend — endpoint de notificação por e-mail

**Files:**
- Modify: `backend/app/services/email_templates.py` (novo builder `lembrete_reserva_email`, novo helper `_centavos_para_reais`)
- Modify: `backend/app/schemas/reservas.py` (novo schema `NotificarOut`)
- Modify: `backend/app/services/reservas.py` (nova exceção `SemEmailError`, nova função `notificar_cliente`)
- Modify: `backend/app/routers/reservas.py` (novo endpoint `POST /reservas/{id}/notificar`)
- Test: `backend/tests/test_reservas.py`

**Interfaces:**
- Consumes: `email_templates._base`/`_botao` (já existem); `email.enviar(para, assunto, html)` (já existe); `auditoria.registrar(db, staff_id, acao, entidade, entidade_id, dados)` (já existe); `reservas_service._buscar_reserva_ou_404` (já existe).
- Produces: `POST /reservas/{id}/notificar` → `NotificarOut{status: "enviado"}` (200) — consumido pelo frontend na Task 6 via `api.notificarReserva`.

- [ ] **Step 1: Escrever os testes que falham primeiro**

Adicionar ao final de `backend/tests/test_reservas.py`:

```python
# --- POST /reservas/{id}/notificar ------------------------------------------


async def test_rota_notificar_envia_email(client, db, staff_admin_logado, monkeypatch):
    recurso = await criar_recurso(db, nome="Campo T6 Notificar")
    cliente = await criar_cliente(db, nome="Cliente Notificar")
    inicio, fim = horario_futuro(dias=9)

    reserva = Reserva(
        recurso_id=recurso.id,
        cliente_id=cliente.id,
        inicio=inicio,
        fim=fim,
        status=ReservaStatus.confirmada,
        origem=ReservaOrigem.online,
        valor_centavos=PRECO_PADRAO_CENTAVOS,
    )
    db.add(reserva)
    await db.flush()

    capturado = {}

    async def _enviar_fake(para, assunto, html):
        capturado["para"] = para
        capturado["assunto"] = assunto
        capturado["html"] = html

    monkeypatch.setattr("app.services.reservas.email.enviar", _enviar_fake)

    resp = await client.post(
        f"/api/v1/reservas/{reserva.id}/notificar",
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "enviado"}
    assert capturado["para"] == cliente.email
    assert "lembrete" in capturado["assunto"].lower() or "reserva" in capturado["assunto"].lower()

    registro = (
        await db.execute(
            select(Auditoria).where(
                Auditoria.entidade == "reserva",
                Auditoria.entidade_id == reserva.id,
                Auditoria.acao == "notificar",
            )
        )
    ).scalar_one()
    assert registro.staff_id == staff_admin_logado["staff"].id


async def test_rota_notificar_reserva_avulsa_sem_email_422(client, db, staff_admin_logado):
    recurso = await criar_recurso(db, nome="Campo T6 Notificar Avulso")
    inicio, fim = horario_futuro(dias=10)

    reserva = Reserva(
        recurso_id=recurso.id,
        nome_avulso="Avulso Sem Email",
        celular_avulso="65977776666",
        inicio=inicio,
        fim=fim,
        status=ReservaStatus.confirmada,
        origem=ReservaOrigem.balcao,
        valor_centavos=PRECO_PADRAO_CENTAVOS,
    )
    db.add(reserva)
    await db.flush()

    resp = await client.post(
        f"/api/v1/reservas/{reserva.id}/notificar",
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "sem_email"


async def test_rota_notificar_reserva_inexistente_404(client, staff_admin_logado):
    resp = await client.post(
        "/api/v1/reservas/999999/notificar",
        headers=staff_admin_logado["headers"],
    )
    assert resp.status_code == 404


async def test_rota_notificar_exige_staff(client, db):
    recurso = await criar_recurso(db, nome="Campo T6 Notificar Sem Auth")
    cliente = await criar_cliente(db, nome="Cliente Sem Auth")
    inicio, fim = horario_futuro(dias=12)
    reserva = Reserva(
        recurso_id=recurso.id,
        cliente_id=cliente.id,
        inicio=inicio,
        fim=fim,
        status=ReservaStatus.confirmada,
        origem=ReservaOrigem.online,
        valor_centavos=PRECO_PADRAO_CENTAVOS,
    )
    db.add(reserva)
    await db.flush()

    resp = await client.post(f"/api/v1/reservas/{reserva.id}/notificar")
    assert resp.status_code == 401
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

```bash
cd backend
python -m pytest tests/test_reservas.py -k notificar -v
```

Expected: FAIL com `404 Not Found` em todos (a rota `/notificar` ainda não
existe).

- [ ] **Step 3: Adicionar `_centavos_para_reais` e `lembrete_reserva_email` em `email_templates.py`**

Logo após a constante `_LOGO_URL` (topo do arquivo, antes de `def _base`):

```python
def _centavos_para_reais(centavos: int) -> str:
    return f"R$ {centavos / 100:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
```

Ao final do arquivo (depois de `cancelamento_reserva_email`):

```python
def lembrete_reserva_email(
    nome: str, recurso_nome: str, inicio_str: str, valor_centavos: int
) -> tuple[str, str]:
    corpo = (
        f"<p>Olá {nome},</p>"
        "<p>Este é um lembrete da sua reserva na Arena Cacerense:</p>"
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        f'style="margin:16px 0; font-size:14px; background-color:{_FUNDO}; border-radius:8px;">'
        f'<tr><td style="padding:14px 18px;">'
        f"<strong>Local:</strong> {recurso_nome}<br>"
        f"<strong>Data/hora:</strong> {inicio_str}<br>"
        f"<strong>Valor:</strong> {_centavos_para_reais(valor_centavos)}"
        "</td></tr></table>"
        "<p>Te esperamos na Arena Cacerense!</p>"
    )
    return "Lembrete de reserva — Arena Cacerense", _base("Lembrete de reserva", corpo)
```

- [ ] **Step 4: Adicionar `NotificarOut` em `schemas/reservas.py`**

Ao final do arquivo:

```python
class NotificarOut(BaseModel):
    status: str
```

- [ ] **Step 5: Adicionar `SemEmailError` e `notificar_cliente` em `services/reservas.py`**

Logo após a classe `SlotOcupadoError` (perto do topo do arquivo, onde já
vivem as outras exceções do módulo — `SlotInvalidoError`,
`ForaDaJanelaError`):

```python
class SemEmailError(Exception):
    """Reserva não tem e-mail associado (cliente avulso sem cadastro) —
    usado por `notificar_cliente` pra a rota responder 422 claro em vez de
    silenciosamente não mandar nada."""
```

Ao final do arquivo (depois de `pagamentos_mais_recentes`, escrita na
Task 2):

```python
async def notificar_cliente(db: AsyncSession, reserva_id: int) -> None:
    """Envia um e-mail de lembrete pro cliente da reserva, sob demanda do
    staff (botão "Notificar por e-mail" na agenda). Diferente dos e-mails
    automáticos do sistema (pagamento confirmado, cancelamento — ambos
    best-effort), este NÃO engole falha: se `email.enviar` levantar, a
    exceção sobe pra rota responder erro, porque é uma ação que o staff
    disparou de propósito e precisa saber se funcionou."""
    reserva = await _buscar_reserva_ou_404(db, reserva_id)
    if reserva.cliente_id is None:
        raise SemEmailError()
    cliente = await db.get(Cliente, reserva.cliente_id)
    if cliente is None:
        raise SemEmailError()
    assunto, html = email_templates.lembrete_reserva_email(
        cliente.nome,
        reserva.recurso.nome,
        f"{reserva.inicio:%d/%m/%Y %H:%M}",
        reserva.valor_centavos,
    )
    await email.enviar(cliente.email, assunto, html)
```

- [ ] **Step 6: Adicionar o endpoint em `routers/reservas.py`**

Adicionar `NotificarOut` ao bloco de import de `app.schemas.reservas`
(linhas 29-36, junto de `ReservaOut`, `StatusOut` etc).

Adicionar a rota ao final do arquivo:

```python
@router.post("/{reserva_id}/notificar", response_model=NotificarOut)
async def notificar_reserva(
    reserva_id: int,
    staff: Staff = Depends(get_staff_atual),
    db: AsyncSession = Depends(get_db),
) -> NotificarOut:
    try:
        await reservas_service.notificar_cliente(db, reserva_id)
    except reservas_service.SemEmailError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="sem_email"
        ) from None
    await auditoria.registrar(
        db,
        staff_id=staff.id,
        acao="notificar",
        entidade="reserva",
        entidade_id=reserva_id,
        dados=None,
    )
    return NotificarOut(status="enviado")
```

- [ ] **Step 7: Rodar os testes e confirmar que passam**

```bash
cd backend
python -m pytest tests/test_reservas.py -v
```

Expected: PASS em todos.

- [ ] **Step 8: Rodar a suíte completa e o ruff**

```bash
cd backend
ruff check .
python -m pytest -q
```

Expected: `All checks passed!` e 136 testes passando (132 + 4 novos).

- [ ] **Step 9: Verificar manualmente que o e-mail renderiza certo**

```bash
cd backend
python -c "
from app.services import email_templates as t
_, html = t.lembrete_reserva_email('Teste', 'Campo 1', '15/08/2026 18:00', 15000)
open(r'C:\Users\henri\AppData\Local\Temp\claude\preview_lembrete.html', 'w', encoding='utf-8').write(html)
print('ok')
"
```

Abrir o arquivo gerado no navegador e confirmar visualmente que segue o
mesmo estilo dos outros e-mails (cabeçalho azul-marinho com logo, faixa
azul, corpo, rodapé).

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/email_templates.py backend/app/schemas/reservas.py backend/app/services/reservas.py backend/app/routers/reservas.py backend/tests/test_reservas.py
git commit -m "feat: endpoint POST /reservas/{id}/notificar (lembrete por e-mail)"
```

---

### Task 4: Frontend — tipos e API client

**Files:**
- Modify: `frontend/lib/api.ts:5` (tipo `Reserva` ganha os 5 campos novos)
- Modify: `frontend/lib/api.ts:37-39` (novo método `notificarReserva`)

**Interfaces:**
- Consumes: contrato de `ReservaOut` da Task 1-3 (`cliente_nome`, `cliente_celular`, `cliente_email`, `pagamento_metodo`, `pagamento_status`) e `POST /reservas/{id}/notificar` → `{status: string}`.
- Produces: `Reserva` (tipo TS) com os campos novos, e `api.notificarReserva(id: number): Promise<{status: string}>` — Task 5 e Task 6 usam esse tipo e essa função.

- [ ] **Step 1: Atualizar o tipo `Reserva`**

Em `frontend/lib/api.ts`, linha 5, substituir:

```typescript
export type Reserva = { id: number; recurso_id: number; recurso_nome: string; inicio: string; fim: string; status: string; origem: string; valor_centavos: number; expira_em?: string };
```

por:

```typescript
export type Reserva = {
  id: number; recurso_id: number; recurso_nome: string; inicio: string; fim: string;
  status: string; origem: string; valor_centavos: number; expira_em?: string;
  cliente_nome?: string | null; cliente_celular?: string | null; cliente_email?: string | null;
  pagamento_metodo?: string | null; pagamento_status?: string | null;
};
```

- [ ] **Step 2: Adicionar `notificarReserva` ao objeto `api`**

Em `frontend/lib/api.ts`, linha 39 (logo após `cancelarAdmin`), adicionar:

```typescript
  notificarReserva: (id: number) => req<{ status: string }>(`/reservas/${id}/notificar`, { method: "POST" }),
```

- [ ] **Step 3: Verificar que o frontend ainda compila**

```bash
cd frontend
npm run build
```

Expected: build conclui sem erro (`✓ Compiled successfully` /
`Generating static pages (17/17)`), sem nenhum uso quebrado do tipo
`Reserva` em outros arquivos (`app/conta/page.tsx`,
`components/ModalBalcao.tsx` etc. — os campos novos são todos opcionais,
então nenhum consumidor existente deveria quebrar).

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat: tipo Reserva e api.notificarReserva pros dados novos da agenda"
```

---

### Task 5: Frontend — cards com nome do cliente + status de pagamento na grade

**Files:**
- Modify: `frontend/components/AgendaAdmin.tsx:47-60` (`corCelula` — troca cor de fundo por cor de borda lateral)
- Modify: `frontend/components/AgendaAdmin.tsx:216-244` (renderização da célula — card branco com borda colorida + nome do cliente + status)

**Interfaces:**
- Consumes: `Reserva.cliente_nome`, `.pagamento_status` (Task 4).
- Produces: nada consumido por outra task — mudança visual isolada.

- [ ] **Step 1: Trocar `corCelula` pra devolver cor de borda em vez de fundo**

Em `frontend/components/AgendaAdmin.tsx`, substituir as linhas 47-60
(função `corCelula`) por:

```typescript
function corCelula(tipo: CelulaTipo): { borda: string; texto: string } {
  switch (tipo) {
    case "confirmada":
      return { borda: "#1c9a5b", texto: "var(--verde)" };
    case "pendente":
      return { borda: "#d97706", texto: "#92660b" };
    case "mensalista":
      return { borda: "var(--azul)", texto: "var(--azul)" };
    case "bloqueio":
      return { borda: "var(--cinza)", texto: "var(--cinza)" };
    default:
      return { borda: "transparent", texto: "var(--tinta)" };
  }
}

function nomeCliente(celula: Celula): string {
  if (celula.tipo === "bloqueio") return celula.bloqueio?.motivo || "Bloqueado";
  return celula.reserva?.cliente_nome || "—";
}

function statusResumo(celula: Celula): string {
  if (celula.tipo === "bloqueio") return "Bloqueado";
  if (celula.tipo === "mensalista") return "Mensalista";
  const statusPagamento = celula.reserva?.pagamento_status;
  if (statusPagamento === "pago") return "✓ Pago";
  if (statusPagamento === "pendente" || celula.tipo === "pendente") return "⏳ Pendente";
  return celula.tipo === "confirmada" ? "Confirmada" : "";
}
```

- [ ] **Step 2: Trocar a renderização da célula**

Substituir as linhas 216-244 (o bloco `const { bg, texto } = corCelula(...)`
até o `</td>` correspondente) por:

```typescript
                    if (celula.tipo === "livre") {
                      return (
                        <td key={r.id} style={{ padding: 4 }}>
                          <button
                            type="button"
                            onClick={() => clicarCelula(r, celula)}
                            style={{
                              width: "100%",
                              textAlign: "left",
                              padding: "8px 10px",
                              borderRadius: 8,
                              border: "1.5px solid #d7dbe6",
                              background: "var(--branco)",
                              color: "var(--tinta)",
                              cursor: "pointer",
                              fontFamily: "inherit",
                              fontWeight: 600,
                              fontSize: "0.85rem",
                            }}
                          >
                            {centavos(celula.slot.preco_centavos)}
                          </button>
                        </td>
                      );
                    }
                    const { borda, texto } = corCelula(celula.tipo);
                    return (
                      <td key={r.id} style={{ padding: 4 }}>
                        <button
                          type="button"
                          onClick={() => clicarCelula(r, celula)}
                          disabled={celula.tipo === "bloqueio"}
                          style={{
                            width: "100%",
                            textAlign: "left",
                            padding: "8px 10px",
                            borderRadius: 8,
                            border: "1px solid #e5e7eb",
                            borderLeft: `4px solid ${borda}`,
                            background: "var(--branco)",
                            boxShadow: "0 1px 3px rgba(23,19,53,.06)",
                            cursor: celula.tipo === "bloqueio" ? "not-allowed" : "pointer",
                            fontFamily: "inherit",
                            fontSize: "0.82rem",
                          }}
                        >
                          <span style={{ display: "block", fontWeight: 700, color: "var(--tinta)", marginBottom: 2 }}>
                            {nomeCliente(celula)}
                          </span>
                          <span style={{ fontSize: "0.72rem", color: texto }}>{statusResumo(celula)}</span>
                        </button>
                      </td>
                    );
```

- [ ] **Step 3: Atualizar a legenda**

Nas linhas 251-257 (bloco `<Legenda .../>`), trocar as cores de fundo
sólidas pelas mesmas cores de borda usadas nos cards, pra legenda continuar
condizente:

```typescript
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 16, fontSize: "0.82rem" }}>
            <Legenda cor="#1c9a5b" texto="Confirmada" />
            <Legenda cor="#d97706" texto="Pendente" />
            <Legenda cor="var(--azul)" texto="Mensalista" />
            <Legenda cor="var(--cinza)" texto="Bloqueio" />
            <Legenda cor="#ffffff" texto="Livre" borda />
          </div>
```

- [ ] **Step 4: Verificar visualmente no navegador**

```bash
cd backend
export DATABASE_URL="postgresql+asyncpg://arena:arena@localhost:15499/arena"
export REDIS_URL="redis://localhost:16380/0"
export PAGARME_MODE="simulado"
export FRONTEND_URL="http://localhost:3900"
python -m uvicorn app.main:app --port 8010 &
```

```bash
cd frontend
export NEXT_PUBLIC_API_URL="http://localhost:8010/api/v1"
npx next dev -p 3900 &
```

Abrir `http://localhost:3900/admin/entrar`, logar como
`admin@arenacacerense.com.br` / `trocar123`, ir em Agenda. Confirmar:
- Células com reserva confirmada aparecem brancas com barra verde à
  esquerda, mostrando o nome do cliente e "✓ Pago" ou "Confirmada".
- Células livres continuam como antes (preço, sem borda colorida).
- A legenda embaixo da tabela mostra as cores certas.

Parar os dois processos (`kill %1 %2` ou matar os PIDs) depois de
verificar.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/AgendaAdmin.tsx
git commit -m "feat: cards com nome do cliente na grade da agenda (estilo B do brainstorm)"
```

---

### Task 6: Frontend — modal de detalhe com dados completos + notificar por e-mail

**Files:**
- Modify: `frontend/components/AgendaAdmin.tsx:274-283` (troca `<PainelDetalhe .../>` por `<ModalDetalheReserva .../>`)
- Modify: `frontend/components/AgendaAdmin.tsx:318-387` (substitui a função `PainelDetalhe` inteira por `ModalDetalheReserva` + helper `LinhaDetalhe`)

**Interfaces:**
- Consumes: `api.notificarReserva` (Task 4), `Reserva.cliente_nome/.cliente_celular/.cliente_email/.pagamento_metodo/.pagamento_status` (Task 1-2).
- Produces: nada consumido por outra task — última task da feature.

- [ ] **Step 1: Substituir a chamada do componente**

Em `frontend/components/AgendaAdmin.tsx`, linhas 274-283:

```typescript
      {detalhe && (
        <ModalDetalheReserva
          celula={detalhe}
          onFechar={() => setDetalhe(null)}
          onCancelado={() => {
            setDetalhe(null);
            carregar();
          }}
        />
      )}
```

- [ ] **Step 2: Substituir a função `PainelDetalhe` por `ModalDetalheReserva`**

Substituir as linhas 318-387 (função `PainelDetalhe` inteira, do
`function PainelDetalhe({` até o `}` de fechamento antes de
`function ModalBloqueio`) por:

```typescript
function ModalDetalheReserva({
  celula,
  onFechar,
  onCancelado,
}: {
  celula: Celula & { recurso: Recurso };
  onFechar: () => void;
  onCancelado: () => void;
}) {
  const [estornar, setEstornar] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [cancelando, setCancelando] = useState(false);
  const [notificando, setNotificando] = useState(false);
  const [notificado, setNotificado] = useState(false);
  const [erroNotificar, setErroNotificar] = useState<string | null>(null);
  const reserva = celula.reserva!;

  async function cancelar() {
    if (!window.confirm("Cancelar esta reserva?")) return;
    setCancelando(true);
    setErro(null);
    try {
      await api.cancelarAdmin(reserva.id, estornar);
      onCancelado();
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível cancelar a reserva."));
    } finally {
      setCancelando(false);
    }
  }

  async function notificar() {
    setNotificando(true);
    setErroNotificar(null);
    setNotificado(false);
    try {
      await api.notificarReserva(reserva.id);
      setNotificado(true);
    } catch (e) {
      setErroNotificar(mensagemErro(e, "Não foi possível enviar o e-mail."));
    } finally {
      setNotificando(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{ position: "fixed", inset: 0, background: "rgba(23,19,53,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50, padding: 16 }}
      onClick={onFechar}
    >
      <div onClick={(e) => e.stopPropagation()} style={{ width: "100%", maxWidth: 420 }}>
        <Card>
          <Titulo as="h2">Detalhes da reserva</Titulo>
          {erro && <Aviso tipo="erro">{erro}</Aviso>}
          <p>
            <Badge status={reserva.status} /> <strong>{celula.recurso.nome}</strong>
          </p>
          <p>
            {horaLocal(reserva.inicio)} às {horaLocal(reserva.fim)}
          </p>

          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6, fontSize: "0.9rem" }}>
            <LinhaDetalhe rotulo="Cliente" valor={reserva.cliente_nome || "—"} />
            <LinhaDetalhe rotulo="Celular" valor={reserva.cliente_celular || "—"} />
            <LinhaDetalhe rotulo="E-mail" valor={reserva.cliente_email || "—"} />
            <LinhaDetalhe rotulo="Valor" valor={centavos(reserva.valor_centavos)} />
            <LinhaDetalhe
              rotulo="Pagamento"
              valor={reserva.pagamento_metodo ? `${reserva.pagamento_metodo} · ${reserva.pagamento_status}` : "—"}
            />
          </div>

          <div style={{ marginTop: 16 }}>
            {erroNotificar && <Aviso tipo="erro">{erroNotificar}</Aviso>}
            {notificado && <Aviso tipo="sucesso">E-mail enviado ✓</Aviso>}
            <BotaoSecundario
              type="button"
              onClick={notificar}
              disabled={notificando || !reserva.cliente_email}
              title={!reserva.cliente_email ? "Cliente sem e-mail cadastrado" : undefined}
              style={{ width: "100%" }}
            >
              {notificando ? "Enviando..." : "✉ Notificar por e-mail"}
            </BotaoSecundario>
          </div>

          {reserva.status !== "cancelada" && (
            <>
              <label style={{ display: "flex", gap: 8, alignItems: "center", margin: "16px 0" }}>
                <input type="checkbox" checked={estornar} onChange={(e) => setEstornar(e.target.checked)} />
                Estornar pagamento ao cancelar
              </label>
              <Botao type="button" onClick={cancelar} disabled={cancelando}>
                {cancelando ? "Cancelando..." : "Cancelar reserva"}
              </Botao>
            </>
          )}

          <div style={{ marginTop: 24 }}>
            <BotaoSecundario type="button" onClick={onFechar}>
              Fechar
            </BotaoSecundario>
          </div>
        </Card>
      </div>
    </div>
  );
}

function LinhaDetalhe({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #f0f1f5", paddingBottom: 4 }}>
      <span style={{ color: "var(--cinza)" }}>{rotulo}</span>
      <span style={{ fontWeight: 600, color: "var(--tinta)" }}>{valor}</span>
    </div>
  );
}
```

- [ ] **Step 3: Verificar que o frontend compila e faz lint**

```bash
cd frontend
npm run lint
npm run build
```

Expected: sem erros novos (o warning pré-existente de `<img>` em
`PixCheckout.tsx` continua, é esperado); build conclui com
`Generating static pages (17/17)`.

- [ ] **Step 4: Verificar o fluxo completo no navegador**

Repetir o setup do Step 4 da Task 5 (backend na porta 8010, frontend na
3900). No navegador, logado como admin:

1. Ir em Agenda, clicar num card de reserva confirmada (com cliente
   cadastrado — se não houver nenhuma, criar uma reserva de balcão pra um
   cliente com e-mail primeiro, pelo botão "Bloquear"→cancelar e usar o
   fluxo normal de reserva de balcão num slot livre).
2. Confirmar que o modal abre centralizado (não mais deslizando da
   direita) e mostra Cliente/Celular/E-mail/Valor/Pagamento corretos.
3. Clicar em "Notificar por e-mail" — confirmar que aparece "Enviando...",
   depois "E-mail enviado ✓" (com `SMTP_HOST` vazio localmente, o envio é
   um no-op silencioso no backend, mas a rota ainda responde 200 — checar
   isso é o suficiente pra confirmar o fluxo do frontend).
4. Clicar num card de reserva de balcão avulsa (sem cliente cadastrado, só
   nome/celular avulso) — confirmar que o botão "Notificar por e-mail"
   aparece desabilitado.
5. Confirmar que "Cancelar reserva" ainda funciona (não foi quebrado pela
   troca de painel lateral pra modal).

Parar os processos depois.

- [ ] **Step 5: Rodar a suíte completa do backend uma última vez**

```bash
cd backend
python -m pytest -q
```

Expected: 136 testes passando, nenhuma regressão.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/AgendaAdmin.tsx
git commit -m "feat: modal central de detalhe da reserva com notificação por e-mail"
```

---

## Depois de todas as tasks

- [ ] Rodar `ruff check backend` e `cd frontend && npm run build` uma
      última vez pra garantir que nada ficou quebrado entre tasks.
- [ ] Push pro GitHub e confirmar que a CI (backend + frontend + e2e) fica
      verde.
- [ ] Deploy na VPS (`git pull && docker compose ... up -d --build`) e
      verificação de saúde (`/api/v1/health`, abrir `/admin` em produção).
