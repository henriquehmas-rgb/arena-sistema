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

/** Deslocamento (minutos, local-menos-UTC) de `tz` no instante `data` — ex.:
 * -240 para America/Cuiaba (UTC-4). Usa o truque de reformatar `data` nesse
 * fuso e reinterpretar os campos como se fossem UTC; a diferença entre os
 * dois instantes é o deslocamento. Não hardcoda o offset (apesar do Brasil
 * não observar horário de verão desde 2019) para não quebrar em silêncio
 * se isso mudar de novo. */
function offsetMinutos(tz: string, data: Date): number {
  const partes = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
    .formatToParts(data)
    .reduce<Record<string, string>>((acc, p) => {
      acc[p.type] = p.value;
      return acc;
    }, {});
  const comoUTC = Date.UTC(
    Number(partes.year),
    Number(partes.month) - 1,
    Number(partes.day),
    Number(partes.hour) === 24 ? 0 : Number(partes.hour),
    Number(partes.minute),
    Number(partes.second)
  );
  return (comoUTC - data.getTime()) / 60000;
}

/** `data` ("2026-08-14") + `hora` ("08:00") interpretados como horário
 * LOCAL do fuso da Arena (America/Cuiaba) -> ISO UTC ("...Z") pronto pra
 * mandar pro backend. Necessário porque o navegador de quem está usando o
 * admin pode estar em qualquer fuso — sem isso, `new Date(`${data}T${hora}`)`
 * (ou mandar a string local direto pro backend) interpreta o horário no
 * fuso de QUEM ESTÁ CLICANDO, não no fuso da arena, e o valor acaba salvo
 * deslocado em relação à grade (que sempre mostra horário local da arena). */
export function localParaUTC(data: string, hora: string): string {
  const [ano, mes, dia] = data.split("-").map(Number);
  const [h, m] = hora.split(":").map(Number);
  const chuteUTC = Date.UTC(ano, mes - 1, dia, h, m, 0);
  const offset = offsetMinutos(TZ, new Date(chuteUTC));
  return new Date(chuteUTC - offset * 60000).toISOString();
}

/** mm:ss a partir de segundos restantes, para o contador do checkout */
export function contagem(segundos: number): string {
  const s = Math.max(0, Math.floor(segundos));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}
