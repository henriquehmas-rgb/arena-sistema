import { test, expect, type Page } from "@playwright/test";

// Task T15 — E2E: fluxo de balcão do painel admin/staff.
//
// login staff -> reserva balcão em slot livre -> aparece na agenda
// confirmada -> caixa do dia soma -> bloquear horário -> slot some do portal
// público.
//
// Usa o admin seedado por `app/seed.py` (e-mail fixo `admin@arenacacerense.com.br`,
// senha `SEED_ADMIN_SENHA` — default de dev `trocar123`, confirmado via
// `POST /auth/staff/login` antes de escrever este spec). Roda contra a mesma
// stack local do reserva.spec.ts (ver .git/sdd/task-15-report.md).
//
// Recursos/dia usados aqui ("Campo 2" para a reserva de balcão, "Quiosque"
// para o bloqueio, hoje + 4) são diferentes dos usados em reserva.spec.ts
// ("Campo 1", hoje + 2) para não disputar o mesmo horário quando os dois
// specs rodam na mesma sessão de testes.
const ADMIN_EMAIL = "admin@arenacacerense.com.br";
const ADMIN_SENHA = process.env.SEED_ADMIN_SENHA || "trocar123";
const DIA_OFFSET = 4;
const RECURSO_BALCAO = "Campo 2";
const RECURSO_BLOQUEIO = "Quiosque";

/** Mesma lógica de `lib/format.ts#paraDataISO` (fuso America/Cuiaba), pra bater com a data que a UI usa internamente. */
function dataISO(diasAPartirDeHoje: number): string {
  const d = new Date(Date.now() + diasAPartirDeHoje * 24 * 60 * 60 * 1000);
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "America/Cuiaba",
  }).format(d);
}

/** Acha e clica no primeiro slot livre (botão com texto "R$...", não desabilitado) da coluna `nomeRecurso` na tabela da agenda. Retorna {hora, preco}. */
async function clicarPrimeiroSlotLivre(
  page: Page,
  nomeRecurso: string
): Promise<{ hora: string; preco: string }> {
  const headers = page.locator("table thead th");
  const total = await headers.count();
  let col = -1;
  for (let i = 0; i < total; i++) {
    const texto = (await headers.nth(i).innerText()).trim();
    if (texto === nomeRecurso) {
      col = i;
      break;
    }
  }
  if (col === -1) throw new Error(`Coluna "${nomeRecurso}" não encontrada na agenda.`);

  const linhas = page.locator("table tbody tr");
  const totalLinhas = await linhas.count();
  for (let r = 0; r < totalLinhas; r++) {
    const celula = linhas.nth(r).locator("td").nth(col);
    const botao = celula.locator("button");
    if ((await botao.count()) === 0) continue;
    const desabilitado = await botao.isDisabled();
    const texto = (await botao.innerText()).trim();
    if (!desabilitado && texto.startsWith("R$")) {
      const hora = (await linhas.nth(r).locator("td").first().innerText()).trim();
      await botao.click();
      return { hora, preco: texto };
    }
  }
  throw new Error(`Nenhum slot livre encontrado para "${nomeRecurso}" no dia selecionado.`);
}

test("login staff -> reserva balcão -> agenda confirmada -> caixa soma -> bloqueio -> some do portal", async ({
  page,
}) => {
  const dataAlvo = dataISO(DIA_OFFSET);
  const nomeAvulso = `Balcão E2E ${Date.now()}`;

  // 1. Login staff
  await page.goto("/admin/entrar");
  await page.getByLabel("E-mail").fill(ADMIN_EMAIL);
  await page.getByLabel("Senha").fill(ADMIN_SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();

  await expect(page).toHaveURL(/\/admin$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Agenda" })).toBeVisible();

  // 2. Seleciona o dia alvo na agenda
  await page.locator("#campo-dia").fill(dataAlvo);
  await expect(page.getByText("Carregando agenda...")).toHaveCount(0, { timeout: 15_000 });

  // 3. Reserva de balcão num slot livre de "Campo 2"
  const { hora, preco } = await clicarPrimeiroSlotLivre(page, RECURSO_BALCAO);

  const modalBalcao = page.getByRole("dialog").filter({ hasText: "Reserva de balcão" });
  await expect(modalBalcao).toBeVisible();
  await modalBalcao.getByRole("button", { name: "Avulso" }).click();
  await modalBalcao.getByLabel("Nome").fill(nomeAvulso);
  // Método "Dinheiro" já vem selecionado por padrão.
  await modalBalcao.getByRole("button", { name: "Confirmar reserva" }).click();
  await expect(modalBalcao).toBeHidden({ timeout: 15_000 });

  // 4. Confirma que a reserva aparece na agenda como confirmada
  await expect(page.getByText("Carregando agenda...")).toHaveCount(0, { timeout: 15_000 });
  const linhaHorario = page.locator("table tbody tr").filter({ hasText: hora });
  const headersPos = page.locator("table thead th");
  let colBalcao = -1;
  for (let i = 0; i < (await headersPos.count()); i++) {
    if ((await headersPos.nth(i).innerText()).trim() === RECURSO_BALCAO) {
      colBalcao = i;
      break;
    }
  }
  // Task 5 (redesign da agenda): a célula não mostra mais "Confirmada" — é
  // um card com o nome do cliente + indicador curto de pagamento.
  const celulaConfirmada = linhaHorario.locator("td").nth(colBalcao);
  await expect(celulaConfirmada).toContainText(nomeAvulso, { timeout: 15_000 });
  await expect(celulaConfirmada).toContainText("Pago", { timeout: 15_000 });

  // 5. Caixa do dia: soma inclui o lançamento recém-criado.
  // Nota: `GET /caixa` soma por `Pagamento.pago_em` (quando o dinheiro foi
  // efetivamente recebido no balcão, "hoje"), não pela data da reserva
  // (`dataAlvo`, hoje+4) — confirmado lendo `backend/app/routers/caixa.py`
  // e batendo direto na API (`GET /caixa?data=hoje` retorna o item;
  // `GET /caixa?data=dataAlvo` vem vazio). Usar `dataAlvo` aqui era um bug
  // no teste, não no app: o fechamento de caixa é por data de recebimento.
  const dataHoje = dataISO(0);
  await page.goto("/admin/caixa");
  await page.locator("#caixa-data").fill(dataHoje);
  await expect(page.getByText("Carregando...")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Itens do dia" })).toBeVisible();

  // A coluna "Hora" do caixa mostra quando o pagamento foi recebido (agora),
  // não o horário do slot reservado (`hora`, hoje+4) — então filtramos pelo
  // nome do cliente avulso (único por execução) em vez de `hora`.
  const linhaCaixa = page.locator("table tbody tr").filter({ hasText: nomeAvulso }).filter({ hasText: preco });
  await expect(linhaCaixa).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Total do dia")).toBeVisible();

  // 6. Bloquear horário — recurso diferente ("Quiosque") para não colidir
  // com a reserva de balcão criada acima.
  await page.goto("/admin");
  await page.locator("#campo-dia").fill(dataAlvo);
  await expect(page.getByText("Carregando agenda...")).toHaveCount(0, { timeout: 15_000 });

  await page.getByRole("button", { name: "Bloquear" }).click();
  const modalBloqueio = page.getByRole("dialog").filter({ hasText: "Bloquear horário" });
  await expect(modalBloqueio).toBeVisible();
  await modalBloqueio.locator("select").selectOption({ label: RECURSO_BLOQUEIO });
  const motivo = `Manutenção E2E ${Date.now()}`;
  await modalBloqueio.getByLabel("Motivo").fill(motivo);
  await modalBloqueio.getByRole("button", { name: "Bloquear" }).click();
  await expect(modalBloqueio).toBeHidden({ timeout: 15_000 });

  // 7. Confirma que o horário aparece como bloqueio na agenda (célula
  // desabilitada, cinza, com o motivo).
  await expect(page.getByText("Carregando agenda...")).toHaveCount(0, { timeout: 15_000 });
  const headersBloqueio = page.locator("table thead th");
  let colQuiosque = -1;
  for (let i = 0; i < (await headersBloqueio.count()); i++) {
    if ((await headersBloqueio.nth(i).innerText()).trim() === RECURSO_BLOQUEIO) {
      colQuiosque = i;
      break;
    }
  }
  const linhaBloqueio8h = page.locator("table tbody tr").filter({ hasText: "08:00" });
  const celulaBloqueada = linhaBloqueio8h.locator("td").nth(colQuiosque);
  await expect(celulaBloqueada).toContainText(motivo, { timeout: 15_000 });
  await expect(celulaBloqueada.locator("button")).toBeDisabled();

  // 8. Confirma que o horário some do portal público (fica indisponível):
  // GET /disponibilidade passa a devolver livre=false pro slot bloqueado, e
  // o SlotCard renderiza "Ocupado" (desabilitado) em vez do preço.
  await page.goto("/");
  await page.getByRole("button", { name: RECURSO_BLOQUEIO }).click();
  const diaBotao = page.locator(".ac-dia").nth(DIA_OFFSET);
  await diaBotao.click();
  await expect(page.getByText("Carregando horários...")).toHaveCount(0, { timeout: 15_000 });

  // O período "08:00–12:00" é usado (em vez de só "08:00") porque o
  // quiosque tem outro período que também começa às 08:00 ("08:00–22:00",
  // o período "dia") — texto completo evita ambiguidade no locator.
  const slotBloqueado = page.locator(".ac-slot").filter({ hasText: "08:00–12:00" });
  await expect(slotBloqueado).toContainText("Ocupado", { timeout: 15_000 });
  await expect(slotBloqueado).toBeDisabled();
});
