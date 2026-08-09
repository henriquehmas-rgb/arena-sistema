"use client";

// Nav do header — client component porque depende do token salvo em localStorage
// (ver lib/api.ts:getToken). Reavalia no mount e após navegação.

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { estaAutenticado, sair } from "@/lib/auth";

export default function HeaderNav() {
  const [logado, setLogado] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    setLogado(estaAutenticado());
  }, [pathname]);

  function handleSair() {
    sair();
    setLogado(false);
    router.push("/");
  }

  return (
    <nav className="ac-nav">
      {logado ? (
        <>
          <Link href="/conta">Minha conta</Link>
          <button onClick={handleSair}>Sair</button>
        </>
      ) : (
        <Link href="/entrar">Entrar</Link>
      )}
    </nav>
  );
}
