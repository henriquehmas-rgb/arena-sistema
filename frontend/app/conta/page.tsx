"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, type MeuCadastro, type Reserva } from "@/lib/api";
import { estaAutenticado, mensagemErro } from "@/lib/auth";
import { Badge, Botao, BotaoSecundario, Campo, Card, Titulo, Aviso } from "@/components/ui";
import { centavos, dataLocal, horaLocal } from "@/lib/format";

const STATUS_FUTUROS = new Set(["pendente_pagamento", "confirmada"]);

export default function ContaPage() {
  const router = useRouter();
  const [reservas, setReservas] = useState<Reserva[] | null>(null);
  const [cadastro, setCadastro] = useState<MeuCadastro | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [erroPorReserva, setErroPorReserva] = useState<Record<number, string>>({});
  const [cancelando, setCancelando] = useState<number | null>(null);

  const [editando, setEditando] = useState(false);
  const [nomeForm, setNomeForm] = useState("");
  const [celularForm, setCelularForm] = useState("");
  const [errosForm, setErrosForm] = useState<Record<string, string>>({});
  const [erroForm, setErroForm] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    if (!estaAutenticado()) {
      router.push(`/entrar?volta=${encodeURIComponent("/conta")}`);
      return;
    }
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function carregar() {
    setErro(null);
    try {
      const [listaReservas, meuCadastro] = await Promise.all([
        api.minhasReservas(),
        api.meuCadastro(),
      ]);
      setReservas(listaReservas);
      setCadastro(meuCadastro);
      setNomeForm(meuCadastro.nome);
      setCelularForm(meuCadastro.celular);
    } catch (e: unknown) {
      const err = e as { status?: number };
      if (err?.status === 401) {
        // Sessão expirada e a renovação também falhou (ver lib/api.ts) —
        // manda pra tela de login em vez de deixar um card de erro sem saída.
        router.push(`/entrar?volta=${encodeURIComponent("/conta")}`);
        return;
      }
      setErro(mensagemErro(e, "Não foi possível carregar sua conta."));
    }
  }

  function iniciarEdicao() {
    if (!cadastro) return;
    setNomeForm(cadastro.nome);
    setCelularForm(cadastro.celular);
    setErrosForm({});
    setErroForm(null);
    setEditando(true);
  }

  async function salvarCadastro(ev: React.FormEvent) {
    ev.preventDefault();
    const e: Record<string, string> = {};
    if (!nomeForm.trim()) e.nome = "Informe seu nome.";
    const celularLimpo = celularForm.replace(/\D/g, "");
    if (!/^\d{10,11}$/.test(celularLimpo)) e.celular = "Informe um celular válido com DDD.";
    setErrosForm(e);
    if (Object.keys(e).length > 0) return;

    setSalvando(true);
    setErroForm(null);
    try {
      const atualizado = await api.atualizarMeuCadastro({ nome: nomeForm.trim(), celular: celularLimpo });
      setCadastro(atualizado);
      setEditando(false);
    } catch (err) {
      setErroForm(mensagemErro(err, "Não foi possível salvar seus dados."));
    } finally {
      setSalvando(false);
    }
  }

  async function cancelar(id: number) {
    if (!window.confirm("Tem certeza que deseja cancelar esta reserva?")) return;
    setCancelando(id);
    setErroPorReserva((prev) => {
      const { [id]: _omit, ...resto } = prev;
      return resto;
    });
    try {
      await api.cancelarReserva(id);
      await carregar();
    } catch (e: unknown) {
      const err = e as { status?: number };
      const msg =
        err?.status === 422
          ? "Essa reserva só pode ser cancelada até 24 horas antes do horário marcado."
          : mensagemErro(e, "Não foi possível cancelar a reserva.");
      setErroPorReserva((prev) => ({ ...prev, [id]: msg }));
    } finally {
      setCancelando(null);
    }
  }

  if (reservas === null && !erro) return <p>Carregando...</p>;

  const proximas = (reservas ?? []).filter((r) => STATUS_FUTUROS.has(r.status));
  const historico = (reservas ?? []).filter((r) => !STATUS_FUTUROS.has(r.status));

  return (
    <>
      <div className="ac-conta-topo">
        <div>
          <Titulo>Minha conta</Titulo>
          {cadastro && <p style={{ margin: "4px 0 0", color: "var(--cinza)" }}>Olá, {cadastro.nome.split(" ")[0]}!</p>}
        </div>
        <Link href="/">
          <Botao>Reservar horário →</Botao>
        </Link>
      </div>

      {erro && <Aviso tipo="erro">{erro}</Aviso>}

      <Card className="ac-conta-dados">
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
          <Titulo as="h2">Meus dados</Titulo>
          {!editando && cadastro && (
            <BotaoSecundario onClick={iniciarEdicao}>Editar</BotaoSecundario>
          )}
        </div>

        {editando ? (
          <form onSubmit={salvarCadastro}>
            {erroForm && <Aviso tipo="erro">{erroForm}</Aviso>}
            <Campo
              label="Nome"
              value={nomeForm}
              onChange={(e) => setNomeForm(e.target.value)}
              erro={errosForm.nome}
              required
            />
            <Campo
              label="Celular (com DDD)"
              type="tel"
              placeholder="65999998888"
              value={celularForm}
              onChange={(e) => setCelularForm(e.target.value)}
              erro={errosForm.celular}
              required
            />
            <p style={{ fontSize: "0.85rem", color: "var(--cinza)", margin: "0 0 14px" }}>
              E-mail: {cadastro?.email} — pra trocar o e-mail de login, fale com a gente pelo WhatsApp.
            </p>
            <div style={{ display: "flex", gap: 10 }}>
              <Botao type="submit" disabled={salvando}>
                {salvando ? "Salvando..." : "Salvar"}
              </Botao>
              <BotaoSecundario type="button" onClick={() => setEditando(false)} disabled={salvando}>
                Cancelar
              </BotaoSecundario>
            </div>
          </form>
        ) : (
          cadastro && (
            <dl className="ac-conta-dados-lista">
              <div>
                <dt>Nome</dt>
                <dd>{cadastro.nome}</dd>
              </div>
              <div>
                <dt>E-mail</dt>
                <dd>{cadastro.email}</dd>
              </div>
              <div>
                <dt>Celular</dt>
                <dd>{cadastro.celular}</dd>
              </div>
            </dl>
          )
        )}
      </Card>

      <Titulo as="h2">Próximas reservas</Titulo>
      {proximas.length === 0 && (
        <p>
          Você não tem reservas futuras. <Link href="/">Reservar um horário →</Link>
        </p>
      )}
      <div className="ac-lista-reservas">
        {proximas.map((r) => (
          <Card key={r.id} className="ac-reserva-linha">
            <div>
              <p style={{ margin: 0 }}>
                <Badge status={r.status} /> <strong>{r.recurso_nome}</strong>
              </p>
              <p style={{ margin: 0 }}>
                {dataLocal(r.inicio)} — {horaLocal(r.inicio)} às {horaLocal(r.fim)} — {centavos(r.valor_centavos)}
              </p>
              {erroPorReserva[r.id] && <Aviso tipo="erro">{erroPorReserva[r.id]}</Aviso>}
            </div>
            <BotaoSecundario onClick={() => cancelar(r.id)} disabled={cancelando === r.id}>
              {cancelando === r.id ? "Cancelando..." : "Cancelar"}
            </BotaoSecundario>
          </Card>
        ))}
      </div>

      <Titulo as="h2" className="ac-titulo-historico">
        Histórico
      </Titulo>
      {historico.length === 0 && <p>Nenhuma reserva no histórico.</p>}
      <div className="ac-lista-reservas">
        {historico.map((r) => (
          <Card key={r.id} className="ac-reserva-linha">
            <div>
              <p style={{ margin: 0 }}>
                <Badge status={r.status} /> <strong>{r.recurso_nome}</strong>
              </p>
              <p style={{ margin: 0 }}>
                {dataLocal(r.inicio)} — {horaLocal(r.inicio)} às {horaLocal(r.fim)} — {centavos(r.valor_centavos)}
              </p>
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
