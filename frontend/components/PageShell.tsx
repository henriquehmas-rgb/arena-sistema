"use client";

// `<main>` global do app. Rotas do portal público usam `.ac-container`
// (max-width 1080px, padding, centralizado) — rotas /admin NÃO usam: o
// painel administrativo é um app-shell próprio (`.ac-admin-shell` em
// admin/layout.tsx) que precisa ocupar a largura/altura reais da tela,
// encostado no header. Aplicar o container do portal também no admin
// deixava a sidebar com um respiro de 24px/16px acima e nas laterais —
// a barra lateral parecia "flutuando", desalinhada do header.

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

export default function PageShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isAdmin = pathname?.startsWith("/admin") ?? false;
  return <main className={isAdmin ? "" : "ac-container"}>{children}</main>;
}
