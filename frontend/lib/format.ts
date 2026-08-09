// Formatação de valores monetários e datas/horas no fuso da Arena (America/Cuiaba).
// Valores monetários sempre chegam do backend em centavos (int).

const TZ = "America/Cuiaba";

/** 15000 -> "R$ 150,00" */
export function centavos(n: number): string {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(n / 100);
}

/** ISO datetime -> "14:00" (hora local America/Cuiaba) */
export function horaLocal(iso: string): string {
  return new Intl.DateTimeFormat("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: TZ,
  }).format(new Date(iso));
}

/** ISO datetime -> "09/08/2026" (data local America/Cuiaba) */
export function dataLocal(iso: string): string {
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: TZ,
  }).format(new Date(iso));
}

/** ISO datetime -> "dom, 09/08" (usado no seletor de 7 dias) */
export function diaCurto(iso: string): string {
  return new Intl.DateTimeFormat("pt-BR", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    timeZone: TZ,
  }).format(new Date(iso));
}

/** Date -> "2026-08-09" (chave usada em api.disponibilidade) */
export function paraDataISO(d: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: TZ,
  }).format(d);
}

/** mm:ss a partir de segundos restantes, para o contador do checkout */
export function contagem(segundos: number): string {
  const s = Math.max(0, Math.floor(segundos));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}
