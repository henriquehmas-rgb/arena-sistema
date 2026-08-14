const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export type Recurso = { id: number; nome: string; tipo: "campo" | "quiosque"; ativo: boolean };
export type Slot = { inicio: string; fim: string; preco_centavos: number; livre: boolean };
export type Reserva = {
  id: number; recurso_id: number; recurso_nome: string; inicio: string; fim: string;
  status: string; origem: string; valor_centavos: number; expira_em?: string;
  cliente_nome?: string | null; cliente_celular?: string | null; cliente_email?: string | null;
  pagamento_metodo?: string | null; pagamento_status?: string | null;
};
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
  reservasAdmin: (q: string) => req<{ itens: Reserva[]; total: number }>(`/reservas?${q}`),
  reservaBalcao: (b: object) => req<Reserva>("/reservas/balcao", { method: "POST", body: JSON.stringify(b) }),
  cancelarAdmin: (id: number, estornar: boolean) => req(`/reservas/${id}/cancelar-admin`, { method: "POST", body: JSON.stringify({ estornar }) }),
  notificarReserva: (id: number) => req<{ status: string }>(`/reservas/${id}/notificar`, { method: "POST" }),
  bloqueios: { listar: (q: string) => req<object[]>(`/bloqueios?${q}`), criar: (b: object) => req("/bloqueios", { method: "POST", body: JSON.stringify(b) }), remover: (id: number) => req(`/bloqueios/${id}`, { method: "DELETE" }) },
  precos: { listar: () => req<object[]>("/precos"), criar: (b: object) => req("/precos", { method: "POST", body: JSON.stringify(b) }), atualizar: (id: number, b: object) => req(`/precos/${id}`, { method: "PUT", body: JSON.stringify(b) }), remover: (id: number) => req(`/precos/${id}`, { method: "DELETE" }) },
  assinaturas: { listar: () => req<object[]>("/assinaturas"), criar: (b: object) => req("/assinaturas", { method: "POST", body: JSON.stringify(b) }), acao: (id: number, acao: string) => req(`/assinaturas/${id}/${acao}`, { method: "POST" }) },
  clientes: { listar: (busca: string) => req<object[]>(`/clientes?busca=${busca}`), criar: (b: object) => req("/clientes", { method: "POST", body: JSON.stringify(b) }) },
  caixa: (data: string) => req<object>(`/caixa?data=${data}`),
  faturamento: (de: string, ate: string) => req<object>(`/relatorios/faturamento?de=${de}&ate=${ate}`),
  ocupacao: (de: string, ate: string) => req<object>(`/relatorios/ocupacao?de=${de}&ate=${ate}`),
  equipe: { listar: () => req<object[]>("/equipe"), criar: (b: object) => req("/equipe", { method: "POST", body: JSON.stringify(b) }), atualizar: (id: number, b: object) => req(`/equipe/${id}`, { method: "PUT", body: JSON.stringify(b) }) },
};
