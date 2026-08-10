import { defineConfig, devices } from "@playwright/test";

// Config aponta para a stack local (backend uvicorn + frontend next dev)
// rodando manualmente, apontando para os bancos de teste remotos (Postgres/
// Redis via túnel SSH) com PAGARME_MODE=simulado. Ver Task T15 — sem Docker
// disponível nesta máquina, então backend e frontend rodam localmente sem
// Docker Compose (ver .git/sdd/task-15-report.md para os comandos exatos).
//
// `webServer` não é usado de propósito: backend e frontend já rodam em
// processos separados geridos manualmente (uvicorn + next dev), então deixar
// o Playwright também tentar geri-los seria redundante e menos controlável.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  // baseURL configurável via PLAYWRIGHT_BASE_URL — o job `e2e` do CI sobe o
  // `next dev` na porta padrão 3000, mas nesta máquina de desenvolvimento
  // local havia outro processo (não relacionado a este projeto) ocupando
  // localhost:3000 (confirmado via `netstat`/`tasklist`, servindo HTML de
  // uma ferramenta completamente diferente, "OpaSuite Crisis Manager") —
  // hardcoded como 3900 antes, o que quebrava silenciosamente no CI
  // (ERR_CONNECTION_REFUSED, já que lá o frontend real está em 3000). Ver
  // .git/sdd/task-15-report.md.
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
