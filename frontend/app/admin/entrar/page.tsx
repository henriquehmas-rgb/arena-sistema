"use client";

// Login de staff — rota própria `/admin/entrar`, separada de `/entrar` (portal
// de cliente). Decisão (T11): usar `/auth/staff/login` (devolve `access_token`
// + `papel`) em vez de reaproveitar o fluxo de cliente, já que o guard de
// `app/admin/layout.tsx` depende de `papel` para filtrar a sidebar.

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { setToken } from "@/lib/api";
import { setPapelStaff } from "../layout";
import { Botao, Campo, Card, Titulo, Aviso } from "@/components/ui";

function mensagemErro(e: unknown, fallback: string): string {
  const err = e as { body?: { detail?: string } | null };
  return err?.body?.detail || fallback;
}

function FormularioEntrarStaff() {
  const router = useRouter();
  const params = useSearchParams();
  const volta = params.get("volta") || "/admin";

  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      const r = await api.loginStaff({ email, senha });
      setToken(r.access_token);
      setPapelStaff(r.papel);
      router.push(volta);
    } catch (err) {
      setErro(mensagemErro(err, "E-mail ou senha inválidos."));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div style={{ maxWidth: 420, margin: "48px auto" }}>
      <Card className="ac-form-card">
        <Titulo as="h2">Painel Arena Cacerense</Titulo>
        {erro && <Aviso tipo="erro">{erro}</Aviso>}
        <form onSubmit={onSubmit}>
          <Campo
            label="E-mail"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <Campo
            label="Senha"
            type="password"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            required
          />
          <Botao type="submit" disabled={enviando}>
            {enviando ? "Entrando..." : "Entrar"}
          </Botao>
        </form>
      </Card>
    </div>
  );
}

export default function AdminEntrarPage() {
  return (
    <Suspense fallback={<p>Carregando...</p>}>
      <FormularioEntrarStaff />
    </Suspense>
  );
}
