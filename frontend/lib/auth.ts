"use client";

// Helpers de autenticação do cliente. Envolve `api.ts` (contrato congelado) e
// guarda o token via api.setToken/getToken (localStorage "at").
//
// `/auth/recuperar` e `/auth/redefinir` não são expostos por lib/api.ts (fora
// do escopo consumido pelo T10 original), então fazemos fetch direto aqui,
// espelhando a mesma convenção de base URL usada em api.ts.

import { api, getToken, setToken } from "./api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export type ErroApi = Error & { status?: number; body?: { detail?: string } | null };

export function estaAutenticado(): boolean {
  return !!getToken();
}

export async function cadastrar(dados: { nome: string; email: string; senha: string; celular: string }) {
  const r = await api.cadastro(dados);
  setToken(r.access_token);
  return r;
}

export async function entrar(dados: { email: string; senha: string }) {
  const r = await api.loginCliente(dados);
  setToken(r.access_token);
  return r;
}

export function sair() {
  setToken(null);
}

async function postSemAuth(path: string, body: object): Promise<void> {
  const r = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const payload = await r.json().catch(() => null);
    throw Object.assign(new Error(String(r.status)), { status: r.status, body: payload }) as ErroApi;
  }
}

export function solicitarRecuperacao(email: string) {
  return postSemAuth("/auth/recuperar", { email });
}

export function redefinirSenha(token: string, senha: string) {
  return postSemAuth("/auth/redefinir", { token, senha });
}

/** Extrai uma mensagem amigável de um erro lançado por lib/api.ts */
export function mensagemErro(e: unknown, fallback = "Algo deu errado. Tente novamente."): string {
  const err = e as ErroApi;
  return err?.body?.detail || fallback;
}
