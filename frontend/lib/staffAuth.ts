"use client";

// Sessão de staff (admin/atendente): token em `lib/api.ts` (localStorage
// "at", via setToken/getToken — mesmo mecanismo do portal público) + `papel`
// em localStorage separado ("papel_staff") porque o contrato só devolve
// `papel` no login de staff.
//
// Extraído de `app/admin/layout.tsx` (T11) porque um `layout.tsx` do App
// Router só pode ter exports reservados (default, metadata, etc.) — um
// export nomeado qualquer (`getPapelStaff`) quebra o build do Next
// ("is not a valid Layout export field"), erro que só aparece no `next
// build` real (type-checking de rotas), não no `tsc --noEmit` solto.

import { getToken, setToken } from "./api";

export type PapelStaff = "admin" | "atendente" | string;

const CHAVE_PAPEL = "papel_staff";

export function getPapelStaff(): PapelStaff | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(CHAVE_PAPEL);
}

export function setPapelStaff(papel: string | null) {
  if (typeof window === "undefined") return;
  papel ? localStorage.setItem(CHAVE_PAPEL, papel) : localStorage.removeItem(CHAVE_PAPEL);
}

export function estaAutenticadoStaff(): boolean {
  return !!getToken() && !!getPapelStaff();
}

export function sairStaff() {
  setToken(null);
  setPapelStaff(null);
}
