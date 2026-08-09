"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { redefinirSenha, solicitarRecuperacao, mensagemErro } from "@/lib/auth";
import { Botao, Campo, Card, Titulo, Aviso } from "@/components/ui";

// Página cobre os dois passos do fluxo:
//  - sem ?token= na URL: pede o e-mail e chama POST /auth/recuperar
//  - com ?token=...: mostra o formulário de nova senha e chama POST /auth/redefinir

function SolicitarLink() {
  const [email, setEmail] = useState("");
  const [enviado, setEnviado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      await solicitarRecuperacao(email);
      setEnviado(true);
    } catch (err) {
      setErro(mensagemErro(err, "Não foi possível enviar o link de recuperação."));
    } finally {
      setEnviando(false);
    }
  }

  if (enviado) {
    return (
      <Aviso tipo="sucesso">
        Se o e-mail informado estiver cadastrado, você vai receber um link para redefinir sua senha.
      </Aviso>
    );
  }

  return (
    <form onSubmit={onSubmit}>
      {erro && <Aviso tipo="erro">{erro}</Aviso>}
      <Campo label="E-mail" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
      <Botao type="submit" disabled={enviando}>
        {enviando ? "Enviando..." : "Enviar link de recuperação"}
      </Botao>
    </form>
  );
}

function RedefinirComToken({ token }: { token: string }) {
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [enviando, setEnviando] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    if (senha.length < 8) {
      setErro("A senha deve ter pelo menos 8 caracteres.");
      return;
    }
    setEnviando(true);
    try {
      await redefinirSenha(token, senha);
      setOk(true);
    } catch (err) {
      setErro(mensagemErro(err, "Não foi possível redefinir sua senha. O link pode ter expirado."));
    } finally {
      setEnviando(false);
    }
  }

  if (ok) {
    return <Aviso tipo="sucesso">Senha redefinida com sucesso. Você já pode entrar com a nova senha.</Aviso>;
  }

  return (
    <form onSubmit={onSubmit}>
      {erro && <Aviso tipo="erro">{erro}</Aviso>}
      <Campo
        label="Nova senha"
        type="password"
        value={senha}
        onChange={(e) => setSenha(e.target.value)}
        required
      />
      <Botao type="submit" disabled={enviando}>
        {enviando ? "Salvando..." : "Redefinir senha"}
      </Botao>
    </form>
  );
}

function ConteudoRecuperar() {
  const params = useSearchParams();
  const token = params.get("token");

  return (
    <Card style={{ maxWidth: 420, margin: "0 auto" }}>
      <Titulo as="h2">{token ? "Nova senha" : "Recuperar senha"}</Titulo>
      {token ? <RedefinirComToken token={token} /> : <SolicitarLink />}
    </Card>
  );
}

export default function RecuperarPage() {
  return (
    <Suspense fallback={<p>Carregando...</p>}>
      <ConteudoRecuperar />
    </Suspense>
  );
}
