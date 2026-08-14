# Agenda do admin — cards com dados do cliente/pagamento + notificação por e-mail

Data: 2026-08-10

## Contexto

A Agenda do painel admin (`/admin`, componente `AgendaAdmin.tsx`) mostra uma
grade Horário × Recurso com células coloridas por status (verde=confirmada,
âmbar=pendente, azul=mensalista, cinza=bloqueio, branco=livre). O staff pediu
pra modernizar o visual (inspirado no Next Fit) e, principalmente, pra dar
mais informação em cada célula: quem reservou, como pagou, se já pagou, e um
jeito de notificar o cliente por e-mail direto da agenda.

## Escopo

Só a Agenda do admin (staff). Não mexe no portal público do cliente nem nas
outras telas do admin (Reservas, Caixa, etc.) — essas continuam como estão.

## Decisões de design (validadas com o usuário via mockups)

1. **Layout**: mantém a grade atual (linhas=horário, colunas=recurso). Cada
   célula ocupada vira um card compacto clicável; livre continua como hoje
   (preço + botão).
2. **Estilo do card compacto**: branco com barra lateral colorida (verde=pago,
   âmbar=pendente) — não o preenchimento sólido que existe hoje. Mostra só
   nome do cliente + um indicador curto de pagamento (✓ Pago / ⏳ Pendente).
3. **Card expandido**: modal central (mesmo padrão visual dos modais já
   existentes — `ModalBloqueio`, `ModalBalcao`), aberto ao clicar no card
   compacto. Mostra: nome completo, celular, e-mail (se houver), campo,
   horário, método+valor do pagamento, e um botão "Notificar por e-mail".
4. **Notificação por e-mail**: um clique, sem campo de texto livre — dispara
   um e-mail fixo de "lembrete de reserva" (resumo do agendamento), usando o
   template branded já existente (`app/services/email_templates.py`).
5. **Reservas de mensalista e bloqueios** também viram cards no novo estilo
   (cores atuais: azul, cinza), mas bloqueio não tem botão de notificar (não
   tem cliente associado).

## Mudanças de backend

### 1. Enriquecer `GET /reservas` (staff) com dados de cliente + pagamento

`ReservaOut` (`backend/app/schemas/reservas.py`) ganha campos novos,
opcionais, calculados na serialização (`_para_out` em
`backend/app/routers/reservas.py`):

- `cliente_nome: str | None` — `cliente.nome` se `cliente_id` setado, senão
  `nome_avulso`.
- `cliente_celular: str | None` — mesmo padrão, `cliente.celular` ou
  `celular_avulso`.
- `cliente_email: str | None` — só existe pra cliente cadastrado
  (`cliente.email`); reserva de balcão avulsa nunca tem e-mail.
- `pagamento_metodo: MetodoPagamento | None`
- `pagamento_status: PagamentoStatus | None`

Fonte: join com `Pagamento` por `reserva_id` (pega o pagamento mais recente,
se houver mais de um por causa de tentativa+reconciliação) e com `Cliente`
(já é `lazy="joined"` implicitamente via query — se não for, adiciona
`selectinload`/`joinedload` explícito pra não reintroduzir o bug de
`MissingGreenlet` já corrigido nesta sessão para `Reserva.recurso`).

Este campo é só leitura — não afeta `POST/PUT` de reserva.

### 2. Novo endpoint: `POST /reservas/{id}/notificar`

- Auth: staff (qualquer papel, mesmo padrão de `POST /reservas/balcao`).
- 404 se a reserva não existe.
- 422 (`sem_email`) se a reserva não tem e-mail associado (avulso sem
  cadastro) — o frontend usa isso pra desabilitar o botão preventivamente,
  mas a validação também vive no backend (defesa em profundidade).
- Monta o e-mail via um novo builder em `email_templates.py`
  (`lembrete_reserva_email(nome, recurso_nome, inicio_str, valor_centavos)`)
  e chama `email.enviar(...)` — **não** é best-effort/silencioso como os
  outros e-mails do sistema: se `email.enviar` falhar, a rota propaga 500
  (o frontend mostra erro), porque essa é uma ação que o staff disparou de
  propósito e precisa saber se funcionou ou não.
- Registra em auditoria (`app.services.auditoria`, mesmo padrão já usado em
  outras rotas de staff) — ação `reserva.notificar`.

## Mudanças de frontend

### `components/AgendaAdmin.tsx`

- Troca o preenchimento sólido das células ocupadas por um card branco com
  `border-left` colorido (verde `#1c9a5b` pago / âmbar `#d97706` pendente /
  azul mensalista / cinza bloqueio), mostrando nome do cliente + indicador
  curto de status.
- `onClick` do card abre um novo componente `ModalDetalheReserva` (modal
  central, mesmo padrão dos outros modais do arquivo) em vez do comportamento
  atual (que só abre detalhe pra reserva confirmada via `setDetalhe`).
- `ModalDetalheReserva`: renderiza os campos (nome, celular, e-mail, campo,
  horário, pagamento) e o botão "Notificar por e-mail":
  - Desabilitado (com `title` explicando) se `cliente_email` for `null`.
  - Ao clicar: chama `api.notificarReserva(id)`, mostra estado de loading,
    e no retorno mostra "E-mail enviado ✓" (sucesso) ou um `<Aviso tipo="erro">`
    com a mensagem de erro (falha).
- Bloqueios continuam sem botão de notificar (não têm `cliente_email`).

### `lib/api.ts`

- `notificarReserva: (id: number) => req<{status: string}>(`/reservas/${id}/notificar`, {method: "POST"})`.
- Tipo `Reserva` ganha os 5 campos novos (todos opcionais).

## Tratamento de erro (resumo)

| Cenário | Comportamento |
|---|---|
| Cliente avulso sem e-mail | Botão desabilitado + dica explicando por quê |
| Falha ao enviar (SMTP fora do ar, etc.) | Erro visível no modal, ação **não** é silenciosa |
| Envio OK | Confirmação visível no modal |
| Reserva/bloqueio sem cliente (bloqueio) | Modal não mostra o botão de notificar |

## Testes

- **Backend**: novos testes em `tests/test_reservas.py` (ou arquivo dedicado)
  para `POST /reservas/{id}/notificar` — sucesso (verifica chamada a
  `email.enviar` via monkeypatch, como os testes de e-mail já existentes),
  404, 422 sem e-mail, exige auth de staff. Mais um teste confirmando que
  `GET /reservas` agora inclui os campos novos corretamente para reserva
  cadastrada vs avulsa.
- **Frontend**: verificação manual real no navegador local (login staff,
  ver os cards com as cores certas, abrir o modal, conferir os dados,
  disparar uma notificação de teste e confirmar recebimento via log do
  Resend) — mesmo rigor usado no resto desta sessão. Não há suíte de teste
  de frontend neste projeto (confirmado no código existente); Playwright
  e2e pode ganhar uma asserção extra cobrindo o clique no card, mas isso é
  opcional, não bloqueia a entrega.
- Suíte completa do backend (129 + novos) roda verde antes do commit final,
  igual ao padrão já seguido nesta sessão.

## Fora de escopo (explicitamente)

- Portal público do cliente — sem mudanças.
- Outras telas do admin (Reservas, Caixa, Relatórios) — sem mudanças.
- Campo de texto livre para a notificação — é sempre o template fixo.
- Histórico de notificações enviadas (fica só no log de auditoria, sem UI
  dedicada pra isso por enquanto).
