"use client";

// Guarda de rota do painel admin/staff + sidebar filtrada por papel + logout.
//
// Decisão (T11): NÃO reusamos `lib/auth.ts` como está — aquele módulo é
// específico do portal de cliente (cadastro/login/recuperação de senha via
// `/auth/cliente/*`). O login de staff usa `/auth/staff/login`, que devolve
// `papel` junto do token (`api.loginStaff`, já em lib/api.ts). Como só este
// arquivo (layout) e a página de login precisam dessa lógica, mantemos tudo
// local aqui em vez de criar um novo módulo em lib/ fora da lista de arquivos
// desta task — evita tocar em arquivos fora do escopo da T11.
//
// Sessão staff: token em `lib/api.ts` (localStorage "at", via setToken/getToken
// — mesmo mecanismo do portal público) + `papel` em localStorage separado
// ("papel_staff") porque o contrato só devolve `papel` no login de staff.

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { getToken, setToken } from "@/lib/api";

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

type ItemMenu = { href: string; rotulo: string; papeis: PapelStaff[] };

const ITENS_MENU: ItemMenu[] = [
  { href: "/admin", rotulo: "Agenda", papeis: ["admin", "atendente"] },
  { href: "/admin/reservas", rotulo: "Reservas", papeis: ["admin", "atendente"] },
  { href: "/admin/clientes", rotulo: "Clientes", papeis: ["admin", "atendente"] },
  { href: "/admin/caixa", rotulo: "Caixa do dia", papeis: ["admin", "atendente"] },
  { href: "/admin/relatorios", rotulo: "Relatórios", papeis: ["admin"] },
  { href: "/admin/precos", rotulo: "Preços", papeis: ["admin"] },
  { href: "/admin/assinaturas", rotulo: "Assinaturas", papeis: ["admin"] },
  { href: "/admin/equipe", rotulo: "Equipe", papeis: ["admin"] },
];

export default function AdminLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [pronto, setPronto] = useState(false);
  const [papel, setPapel] = useState<PapelStaff | null>(null);

  useEffect(() => {
    if (pathname === "/admin/entrar") {
      setPronto(true);
      return;
    }
    if (!estaAutenticadoStaff()) {
      router.push(`/admin/entrar?volta=${encodeURIComponent(pathname)}`);
      return;
    }
    setPapel(getPapelStaff());
    setPronto(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  // Página de login: sem sidebar/guarda, renderiza só o conteúdo.
  if (pathname === "/admin/entrar") {
    return <>{children}</>;
  }

  if (!pronto) return <p>Carregando...</p>;

  const itensVisiveis = ITENS_MENU.filter((item) => !papel || item.papeis.includes(papel));

  function handleSair() {
    sairStaff();
    router.push("/admin/entrar");
  }

  // Estilos do "chrome" admin (sidebar/shell) ficam inline aqui: não editamos
  // globals.css (frozen, T10) para não colidir com outras tracks da Wave 2.
  // Componentes de conteúdo (Card, Botao, Titulo, Badge...) continuam vindo
  // de components/ui.tsx normalmente.
  return (
    <div style={{ display: "flex", minHeight: "calc(100vh - 68px)", gap: 0 }}>
      <aside
        style={{
          width: 220,
          flex: "0 0 220px",
          background: "var(--tinta)",
          color: "var(--branco)",
          padding: "20px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        <p style={{ opacity: 0.7, fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.04em", margin: "0 0 12px" }}>
          {papel === "admin" ? "Administrador" : "Atendente"}
        </p>
        <nav style={{ display: "flex", flexDirection: "column", gap: 2, flex: 1 }}>
          {itensVisiveis.map((item) => {
            const ativo = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                style={{
                  padding: "10px 12px",
                  borderRadius: 8,
                  color: "var(--branco)",
                  textDecoration: "none",
                  fontWeight: ativo ? 700 : 500,
                  background: ativo ? "rgba(255,255,255,0.14)" : "transparent",
                }}
              >
                {item.rotulo}
              </Link>
            );
          })}
        </nav>
        <button
          onClick={handleSair}
          type="button"
          style={{
            marginTop: 16,
            padding: "10px 12px",
            borderRadius: 8,
            border: "1.5px solid rgba(255,255,255,0.35)",
            background: "transparent",
            color: "var(--branco)",
            cursor: "pointer",
            fontFamily: "inherit",
            fontWeight: 600,
          }}
        >
          Sair
        </button>
      </aside>
      <div style={{ flex: 1, padding: "24px 28px", maxWidth: 1200 }}>{children}</div>
    </div>
  );
}
