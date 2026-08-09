"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { cadastrar, mensagemErro } from "@/lib/auth";
import { Botao, Campo, Card, Titulo, Aviso } from "@/components/ui";

// Celular BR: 10 ou 11 dígitos (com DDD), aceitando formatação livre no input.
const CELULAR_REGEX = /^\d{10,11}$/;

function FormularioCadastro() {
  const router = useRouter();
  const params = useSearchParams();
  const volta = params.get("volta") || "/conta";

  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [celular, setCelular] = useState("");
  const [senha, setSenha] = useState("");
  const [erros, setErros] = useState<Record<string, string>>({});
  const [erroApi, setErroApi] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  function validar(): boolean {
    const e: Record<string, string> = {};
    if (!nome.trim()) e.nome = "Informe seu nome.";
    if (!email.trim()) e.email = "Informe seu e-mail.";
    if (senha.length < 8) e.senha = "A senha deve ter pelo menos 8 caracteres.";
    const celularLimpo = celular.replace(/\D/g, "");
    if (!CELULAR_REGEX.test(celularLimpo)) e.celular = "Informe um celular válido com DDD.";
    setErros(e);
    return Object.keys(e).length === 0;
  }

  async function onSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    setErroApi(null);
    if (!validar()) return;
    setEnviando(true);
    try {
      await cadastrar({ nome, email, senha, celular: celular.replace(/\D/g, "") });
      router.push(volta);
    } catch (err) {
      setErroApi(mensagemErro(err, "Não foi possível criar sua conta."));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <Card style={{ maxWidth: 420, margin: "0 auto" }}>
      <Titulo as="h2">Criar conta</Titulo>
      {erroApi && <Aviso tipo="erro">{erroApi}</Aviso>}
      <form onSubmit={onSubmit}>
        <Campo label="Nome" value={nome} onChange={(e) => setNome(e.target.value)} erro={erros.nome} required />
        <Campo
          label="E-mail"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          erro={erros.email}
          required
        />
        <Campo
          label="Celular (com DDD)"
          type="tel"
          placeholder="65999998888"
          value={celular}
          onChange={(e) => setCelular(e.target.value)}
          erro={erros.celular}
          required
        />
        <Campo
          label="Senha"
          type="password"
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
          erro={erros.senha}
          required
        />
        <Botao type="submit" disabled={enviando}>
          {enviando ? "Criando conta..." : "Criar conta"}
        </Botao>
      </form>
      <p style={{ marginTop: 16 }}>
        Já tem conta? <Link href={`/entrar?volta=${encodeURIComponent(volta)}`}>Entrar</Link>
      </p>
    </Card>
  );
}

export default function CadastroPage() {
  return (
    <Suspense fallback={<p>Carregando...</p>}>
      <FormularioCadastro />
    </Suspense>
  );
}
