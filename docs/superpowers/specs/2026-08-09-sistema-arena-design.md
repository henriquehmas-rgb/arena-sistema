# Sistema de Gestão Arena Cacerense — Design

**Data:** 2026-08-09 · **Status:** aprovado pelo Henrique (seções 1–5 em conversa)
**Repo:** `arena-sistema` (GitHub henriquehmas-rgb, **PÚBLICO**)

## 1. Objetivo e escopo (v1)

Sistema de reservas e gestão da Arena Cacerense (Cáceres-MT): 2 campos society + quiosque.

Inclui na v1:
- Portal público de reservas com conta de cliente (e-mail + senha)
- Reserva avulsa paga na hora via Pagar.me (PIX ou cartão); horário expira se não pagar
- Mensalistas (horário fixo semanal) via assinatura recorrente Pagar.me
- Quiosque por período (manhã/tarde/noite/dia inteiro) e pacote campo+quiosque
- Painel admin: agenda, reservas, clientes, mensalistas, preços por faixa, bloqueios, caixa balcão, relatórios, gestão de equipe com papéis
- Preço por faixa de horário/dia, editável no painel

Fora da v1: escolinha (mensalidade de alunos), cozinha/comandas, app mobile, integração POS Stone.

## 2. Arquitetura

```
arenacacerense.com.br          → site estático atual (inalterado; botões RESERVAR passam a linkar pro portal)
reservas.arenacacerense.com.br → Next.js App Router (portal cliente + /admin)
api.arenacacerense.com.br      → FastAPI (REST /api/v1)
```

- **VPS** (191.96.251.71): `/docker/arena-sistema/` com Docker Compose: `postgres:16-alpine`, `redis:7-alpine`, `api` (FastAPI), `web` (Next standalone). Traefik global roteia + emite certificados (mesmo padrão lave-e-seeg).
- **Monorepo**: `backend/`, `frontend/`, `infra/`, `docs/`.
- **Backend**: FastAPI + SQLAlchemy async + Alembic. Estrutura `app/{routers,services,models,schemas}` espelhando lave-e-seeg. APScheduler no processo da API para jobs (expiração, materialização de mensalistas, reconciliação Pagar.me).
- **Frontend**: Next.js App Router, identidade visual do site (Kanit itálico, Saira, `#0B63D8`/`#00AFEF`/`#171335`, cards claros). Mobile-first no portal.
- **Auth**: JWT próprio (access 15 min + refresh 30 d em cookie httpOnly). Contas `staff` (papéis `admin`/`atendente`) e `clientes` separadas.

## 3. Modelo de dados (Postgres)

| Tabela | Campos-chave | Notas |
|---|---|---|
| `clientes` | nome, email UNIQUE, senha_hash, celular, cpf, pagarme_customer_id, criado_em | CPF exigido no 1º pagamento (requisito Pagar.me) |
| `staff` | nome, email UNIQUE, senha_hash, papel `admin\|atendente`, ativo | |
| `recursos` | nome, tipo `campo\|quiosque`, ativo, ordem | seeds: Campo 1, Campo 2, Quiosque |
| `faixas_preco` | recurso_id, dias_semana int[], hora_inicio, hora_fim, preco_centavos | quiosque: faixas = períodos |
| `reservas` | recurso_id, cliente_id NULL, nome_avulso, celular_avulso, inicio timestamptz, fim timestamptz, status, origem `online\|balcao\|mensalista`, valor_centavos, assinatura_id NULL, pacote_grupo_id NULL, criado_em | status: `pendente_pagamento\|confirmada\|concluida\|cancelada\|expirada` |
| `bloqueios` | recurso_id, inicio, fim, motivo, staff_id | |
| `assinaturas` | cliente_id, recurso_id, dia_semana, hora_inicio, hora_fim, valor_mensal_centavos, status `ativa\|pausada\|inadimplente\|cancelada`, pagarme_subscription_id, proxima_cobranca | |
| `pagamentos` | reserva_id NULL, assinatura_id NULL, metodo `pix\|cartao\|dinheiro\|pix_manual`, valor_centavos, status `pendente\|pago\|falhou\|estornado`, pagarme_order_id, pagarme_charge_id, pago_em, registrado_por_staff_id NULL | balcão: metodo manual + staff |
| `auditoria` | staff_id, acao, entidade, entidade_id, dados jsonb, criado_em | toda ação de staff |

**Anti-double-booking:** constraint `EXCLUDE USING gist (recurso_id WITH =, tstzrange(inicio, fim) WITH &&)` sobre reservas ativas (status em `pendente_pagamento/confirmada`) e bloqueios (mesma técnica em tabela própria; disponibilidade consulta as duas). O banco é a fonte de verdade contra corrida de slot.

- `pacote_grupo_id`: UUID que liga as 2 reservas de um pacote campo+quiosque (um pagamento só).
- Valores sempre em centavos (int).

## 4. Fluxos

### 4.1 Reserva avulsa online
1. Grade real por recurso/dia: livre = sem reserva `pendente/confirmada`, sem bloqueio, sem slot de assinatura ativa.
2. Cliente escolhe slot → loga/cria conta → `POST /reservas` cria `pendente_pagamento` (TTL 15 min; segura o slot pela constraint).
3. Checkout: PIX (QR + copia-e-cola, polling de status) ou cartão. Backend recalcula o valor pela faixa — nunca aceita preço do front.
4. Webhook Pagar.me `order.paid` → pagamento `pago`, reserva `confirmada`, e-mail de confirmação.
5. Job por minuto expira `pendente_pagamento` além do TTL → `expirada` (slot volta).

### 4.2 Mensalista
1. Admin cria (ou aprova pedido do cliente): recurso + dia_semana + horário + valor mensal.
2. Cria subscription na Pagar.me (cartão recorrente ou PIX/boleto mensal). Webhooks de fatura mantêm o status.
3. Job semanal materializa reservas das próximas 5 semanas (origem `mensalista`, já `confirmada`).
4. Fatura falha → `inadimplente` + alerta no admin; 2 falhas seguidas → para de materializar novas semanas.
5. Cancelou → cancela subscription na Pagar.me e remove reservas futuras não iniciadas.

### 4.3 Quiosque e pacote
- Quiosque reserva por período; antecedência configurável.
- Pacote campo+quiosque: 2 reservas com mesmo `pacote_grupo_id`, checkout único; falha/expiração desfaz as duas.

### 4.4 Balcão (atendente)
- Cria reserva direto `confirmada`, pagamento `dinheiro`/`pix_manual` registrado com staff_id. Entra no caixa do dia.
- Pode criar cliente na hora (sem senha; cliente define senha depois por link, opcional).

### 4.5 Cancelamento e estorno
- Cliente cancela até X horas antes (config, default 24 h) → estorno automático Pagar.me.
- Dentro da janela, só admin cancela (estorno manual opcional).
- Estorno falhou → retry em fila + alerta admin.

## 5. Integração Pagar.me

- SDK REST v5 (orders + subscriptions). Serviço `services/pagarme.py` adaptado do lave-e-seeg.
- **Modo simulado por env** (`PAGARME_MODE=simulado|sandbox|producao`) até o Henrique cadastrar as chaves — pagamentos simulados confirmam sozinhos após ~5 s em dev.
- Webhook `POST /api/v1/webhooks/pagarme`: valida assinatura (`X-Hub-Signature`), idempotente por `event_id` (Redis SETNX), processa `order.paid`, `order.payment_failed`, `charge.refunded`, `subscription.*`.
- **Reconciliação**: job a cada 10 min consulta orders `pendentes` com >5 min direto na API Pagar.me (webhook perdido ≠ dinheiro perdido).

## 6. Telas

### Portal cliente (mobile-first)
- **Grade** (home): tabs Campo 1/Campo 2/Quiosque + seletor de dia; slots com preço; CTA reservar.
- **Checkout**: resumo, métodos PIX/cartão, contador 15 min, status ao vivo.
- **Minha conta**: próximas reservas, histórico, cancelar, dados/cartões.
- **Auth**: login, cadastro, recuperar senha (e-mail via SMTP, serviço `email.py` padrão da casa).

### Admin (`/admin`)
| Tela | Papel | Conteúdo |
|---|---|---|
| Agenda | ambos | dia/semana, 3 recursos lado a lado, cores por status; clique em slot vazio = reserva balcão; bloquear períodos |
| Reservas | ambos | lista/filtros, detalhe, cancelar/estornar |
| Clientes | ambos | CRUD, busca, histórico |
| Mensalistas | ambos (criar: admin) | assinaturas, status cobrança, inadimplência destacada |
| Preços | admin | faixas por recurso |
| Caixa & Relatórios | caixa: ambos; relatórios: admin | caixa do dia; faturamento por período/método; ocupação por campo/horário |
| Equipe | admin | staff CRUD, papéis |

## 7. Segurança

- Repo público: **zero segredos no código/histórico**; `.env` só na VPS; `.env.example` completo.
- bcrypt; JWT httpOnly; rate-limit login/cadastro (Redis).
- Webhook assinado + idempotente. Valores recalculados no backend. CORS restrito. Auditoria de staff.

## 8. Erros

- Corrida de slot → constraint viola → 409 + front recarrega grade.
- Pagamento falhou → cliente tenta outro método dentro do TTL.
- Webhook atrasado/perdido → reconciliação (5.4).
- Estorno falhou → retry + alerta.

## 9. Testes e CI

- pytest: unit (preços, disponibilidade, expiração, materialização) + integração de rotas com Postgres efêmero. Fluxos de dinheiro com cobertura obrigatória: webhook, expiração, estorno, corrida de slot, idempotência.
- Playwright: reservar+pagar (simulado), balcão, bloqueio.
- GitHub Actions: lint (ruff/eslint) + testes em cada push.

## 10. Implantação

- `/docker/arena-sistema/` na VPS; DNS `reservas` e `api` (registros A na zona Hostinger → 191.96.251.71); Traefik emite certs.
- Backup diário do Postgres (script padrão da casa, cron na VPS).
- Site estático: trocar links RESERVAR para o portal quando o sistema estiver no ar.
