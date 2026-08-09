# Mapa de Agentes — Arena Sistema

Fonte: `docs/superpowers/plans/2026-08-09-arena-sistema.md` (plano completo, self-review incluído).

## Ondas de execução (paralelismo)

| Wave | Agentes | Trechos | Depende de |
|---|---|---|---|
| **0** | 1 | T1 scaffold+contratos, T2 modelos+migração, T3 compose dev | — |
| **1** | 4 em paralelo | A1: T4 auth+equipe · A2: T5 preços/disponibilidade + T6 reservas/bloqueios/expiração · A3: T7 pagarme + T8 checkout/webhook/reconciliação · A4: T9 assinaturas/materialização (+ T9b caixa/relatórios) | Wave 0 |
| **2** | 4 em paralelo | B1: T10 portal público · B2: T11 admin agenda/reservas/clientes · B3: T12 admin mensalistas/preços/caixa/relatórios/equipe · B4: T13 CI + T14 deploy VPS | Wave 1 (B1–B3 usam a API real rodando) |
| **3** | 1 | T15 E2E Playwright + T16 integração site estático + go-live | Wave 2 |

## Regras de paralelismo

- Agentes da mesma wave **não editam os mesmos arquivos**.
- **Contratos são congelados na Wave 0**: schemas Pydantic (`backend/app/schemas/*.py`), client TypeScript (`frontend/lib/api.ts`) e o CONTRATO DE API abaixo. Waves 1–2 **importam e consomem**, mas **não alteram** esses contratos.
- Mudança de contrato (novo campo, nova rota, tipo diferente) exige voltar ao orquestrador — não é decisão de um agente de wave individual.
- `app/models/enums.py` e `app/models/entities.py` são produzidos pela Task T2 (também Wave 0); os schemas de T1 já importam desses módulos assumindo os símbolos definidos no plano.

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
GET  /relatorios/ocupacao?de&ate                                (admin)   → {por_recurso:[{recurso,horas_vendidas,horas_disponiveis,taxa}]}
GET/POST/PUT /equipe                                           (admin)
```
