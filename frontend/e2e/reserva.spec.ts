import { test, expect } from "@playwright/test";

// Task T15 — E2E: fluxo de reserva online completo (cliente).
//
// cadastro (email único, timestamp) -> grade -> escolher slot -> checkout PIX
// -> aguardar confirmação (polling, PAGARME_MODE=simulado confirma sozinho
// depois de ~5s) -> "Pagamento confirmado!" -> reserva aparece em Minha conta.
//
// Roda contra a stack local (uvicorn + next dev, sem Docker — ver
// .git/sdd/task-15-report.md) com bancos de teste remotos (Postgres/Redis via
// túnel SSH). O banco é compartilhado com outras tasks, então usamos um
// e-mail de cliente único por execução e escolhemos dinamicamente o primeiro
// slot livre (em vez de um horário fixo) para não colidir com dados
// pré-existentes.
//
// Recurso usado: "Campo 1", dia = hoje + 2 (índice 2 dos 7 dias exibidos na
// grade). admin.spec.ts usa "Campo 2"/"Quiosque" em hoje + 4, para não
// disputar o mesmo horário quando os specs rodam na mesma sessão.
const DIA_INDEX = 2;
const RECURSO = "Campo 1";

test("cadastro -> reserva online -> checkout PIX -> confirmação -> Minha conta", async ({ page }) => {
  const timestamp = Date.now();
  const email = `teste-e2e-${timestamp}@example.com`;
  const nome = `Cliente E2E ${timestamp}`;
  const celular = "65999998888";
  const senha = "senha12345";

  // 1. Cadastro
  await page.goto("/cadastro");
  await page.getByLabel("Nome").fill(nome);
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Celular (com DDD)").fill(celular);
  await page.getByLabel("Senha").fill(senha);
  await page.getByRole("button", { name: "Criar conta" }).click();

  // Cadastro sem `volta` explícito -> redireciona para /conta.
  await expect(page).toHaveURL(/\/conta$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Minha conta" })).toBeVisible();

  // 2. Grade: escolhe o recurso e o dia
  await page.goto("/");
  await page.getByRole("button", { name: RECURSO }).click();
  const diaBotao = page.locator(".ac-dia").nth(DIA_INDEX);
  await diaBotao.click();

  // Aguarda a grade carregar (mostra "Carregando horários..." enquanto busca).
  await expect(page.getByText("Carregando horários...")).toHaveCount(0, { timeout: 15_000 });

  // 3. Escolhe o primeiro slot livre disponível
  const slotLivre = page.locator(".ac-slot:not(.ac-slot-ocupado)").first();
  await expect(slotLivre).toBeVisible({ timeout: 15_000 });
  const horaSlot = (await slotLivre.locator(".ac-slot-hora").innerText()).trim();
  await slotLivre.click();

  // 4. Checkout: vai para /checkout/{id}
  await expect(page).toHaveURL(/\/checkout\/\d+$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Finalizar reserva" })).toBeVisible();
  await expect(page.getByText(RECURSO)).toBeVisible();

  // Método PIX já vem selecionado por padrão — aguarda o QR/copia-e-cola
  // (chamada a POST /pagamentos/checkout).
  await expect(page.getByText("Aguardando confirmação do pagamento")).toBeVisible({ timeout: 15_000 });

  // 5. Aguarda a confirmação: PixCheckout faz polling de GET /pagamentos/{id}
  // a cada 3s; PAGARME_MODE=simulado confirma o pagamento sozinho depois de
  // ~5s. Timeout generoso (20s) para dar folga ao polling.
  await expect(page.getByRole("heading", { name: "Pagamento confirmado!" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Sua reserva está garantida.")).toBeVisible();

  // 6. Vai para Minha conta e confirma que a reserva aparece confirmada
  await page.getByRole("link", { name: "Ver minhas reservas" }).click();
  await expect(page).toHaveURL(/\/conta$/);
  await expect(page.getByRole("heading", { name: "Próximas reservas" })).toBeVisible();

  const linhaReserva = page.locator(".ac-reserva-linha").filter({ hasText: RECURSO }).filter({ hasText: horaSlot });
  await expect(linhaReserva).toBeVisible();
  await expect(linhaReserva.getByText("Confirmada")).toBeVisible();
});
