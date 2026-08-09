"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { entrar, mensagemErro } from "@/lib/auth";
import { Botao, Campo, Card, Titulo, Aviso } from "@/components/ui";

function FormularioEntrar() {
  const router = useRouter();
  const params = useSearchParams();
  const volta = params.get("volta") || "/conta";

  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      await entrar({ email, senha });
      router.push(volta);
    } catch (err) {
      setErro(mensagemErro(err, "E-mail ou senha inválidos."));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <Card className="ac-form-card" style={{ maxWidth: 420, margin: "0 auto" }}>
      <Titulo as="h2">Entrar</Titulo>
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
      <p style={{ marginTop: 16 }}>
        Não tem conta? <Link href={`/cadastro?volta=${encodeURIComponent(volta)}`}>Cadastre-se</Link>
      </p>
      <p>
        <Link href="/recuperar">Esqueci minha senha</Link>
      </p>
    </Card>
  );
}

export default function EntrarPage() {
  return (
    <Suspense fallback={<p>Carregando...</p>}>
      <FormularioEntrar />
    </Suspense>
  );
}
