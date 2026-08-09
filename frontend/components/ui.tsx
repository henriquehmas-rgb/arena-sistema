"use client";

// Design system compartilhado do portal (Wave 2, T10 Step 1).
// B2/B3 (Grade admin/relatórios etc.) DEVEM importar daqui, não redefinir estilo.
//
// Cores (CSS custom properties, ver globals.css):
//   --azul:#0B63D8  --ciano:#00AFEF  --tinta:#171335  --fundo:#F6F8FC
// Fontes: Kanit (títulos, itálico 900 uppercase) e Saira (corpo), via next/font/google.

import type { ButtonHTMLAttributes, CSSProperties, InputHTMLAttributes, ReactNode } from "react";

// Fontes (Kanit/Saira) vivem em lib/fonts.ts — layout.tsx (server component)
// importa de lá diretamente, pois não é possível ler propriedades (.variable)
// de um objeto exportado por um módulo "use client" a partir de um server
// component. Reexportamos aqui só por conveniência para quem já importa de ui.tsx.
export { kanit, saira } from "@/lib/fonts";

/** Botão primário — fundo azul/ciano. `<Botao onClick={...}>Reservar</Botao>` */
export function Botao({
  children,
  className = "",
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode }) {
  return (
    <button
      className={`ac-botao ${className}`}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}

/** Botão secundário — contorno, fundo transparente. Mesma API do <Botao>. */
export function BotaoSecundario({
  children,
  className = "",
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode }) {
  return (
    <button className={`ac-botao-secundario ${className}`} disabled={disabled} {...props}>
      {children}
    </button>
  );
}

/** Cartão com fundo branco, cantos arredondados e sombra leve. */
export function Card({
  children,
  className = "",
  style,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div className={`ac-card ${className}`} style={style}>
      {children}
    </div>
  );
}

/** Campo de formulário: label + input + mensagem de erro opcional.
 * `<Campo label="E-mail" type="email" value={v} onChange={...} erro={erros.email} />` */
export function Campo({
  label,
  erro,
  className = "",
  id,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; erro?: string }) {
  const inputId = id || `campo-${label.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <div className={`ac-campo ${className}`}>
      <label htmlFor={inputId}>{label}</label>
      <input id={inputId} className={erro ? "ac-input ac-input-erro" : "ac-input"} {...props} />
      {erro && <span className="ac-campo-erro">{erro}</span>}
    </div>
  );
}

/** Título Kanit itálico 900 uppercase. `as` escolhe a tag (default h1). */
export function Titulo({
  children,
  as: Tag = "h1",
  className = "",
}: {
  children: ReactNode;
  as?: "h1" | "h2" | "h3";
  className?: string;
}) {
  return <Tag className={`ac-titulo ${className}`}>{children}</Tag>;
}

export type StatusReserva =
  | "pendente"
  | "confirmada"
  | "cancelada"
  | "expirada"
  | "paga"
  | "pago"
  | "falhou"
  | string;

const STATUS_LABEL: Record<string, string> = {
  pendente: "Pendente",
  confirmada: "Confirmada",
  cancelada: "Cancelada",
  expirada: "Expirada",
  paga: "Paga",
  pago: "Pago",
  falhou: "Falhou",
};

const STATUS_CLASSE: Record<string, string> = {
  pendente: "ac-badge-pendente",
  confirmada: "ac-badge-confirmada",
  cancelada: "ac-badge-cancelada",
  expirada: "ac-badge-cancelada",
  paga: "ac-badge-confirmada",
  pago: "ac-badge-confirmada",
  falhou: "ac-badge-cancelada",
};

/** Selo colorido de status. `<Badge status="confirmada" />` */
export function Badge({ status, className = "" }: { status: StatusReserva; className?: string }) {
  const classe = STATUS_CLASSE[status] ?? "ac-badge-neutro";
  const rotulo = STATUS_LABEL[status] ?? status;
  return <span className={`ac-badge ${classe} ${className}`}>{rotulo}</span>;
}

/** Faixa de aviso/erro simples, usada como "toast" inline no topo da página. */
export function Aviso({ children, tipo = "erro" }: { children: ReactNode; tipo?: "erro" | "info" | "sucesso" }) {
  return <div className={`ac-aviso ac-aviso-${tipo}`}>{children}</div>;
}
