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
  // Porta 3900 (não 3000): nesta máquina de desenvolvimento já havia outro
  // processo (não relacionado a este projeto) ocupando localhost:3000 —
  // confirmado via `netstat`/`tasklist`, servindo HTML de uma ferramenta
  // completamente diferente ("OpaSuite Crisis Manager"). Rodar o `next dev`
  // numa porta alternativa evita a colisão. Ver .git/sdd/task-15-report.md.
  use: {
    baseURL: "http://localhost:3900",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
