// Fontes do design system, isoladas num módulo sem "use client" — next/font
// exige que o componente que lê `.variable`/`.className` não seja consumido
// como referência de client-component a partir de um server component
// (layout.tsx é server component e precisa ler kanit.variable diretamente).

import { Kanit, Saira } from "next/font/google";

export const kanit = Kanit({
  subsets: ["latin"],
  weight: ["400", "600", "700", "800", "900"],
  style: ["normal", "italic"],
  variable: "--font-kanit",
  display: "swap",
});

export const saira = Saira({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-saira",
  display: "swap",
});
