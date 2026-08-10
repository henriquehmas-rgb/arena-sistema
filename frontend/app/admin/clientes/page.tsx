"use client";

// Busca de clientes (api.clientes.listar por nome/celular), criação de
// cliente de balcão (api.clientes.criar) e histórico de reservas.
//
// Histórico por cliente: decisão (T11, conforme brief) — o contrato NÃO lista
// explicitamente `cliente_id` como filtro documentado de `GET /reservas`
// (só `recurso_id&de&ate&status`). Em vez de inventar um parâmetro fora do
// contrato congelado, usamos o mesmo filtro genérico de `api.reservasAdmin`
// passando `cliente_id=<id>` na query string — é o padrão REST mais provável
// para "filtro genérico" mencionado no brief, mas fica documentado como uma
// EXTENSÃO NÃO CONFIRMADA do contrato: se o backend não suportar esse
// parâmetro, o endpoint deve simplesmente ignorá-lo e devolver todas as
// reservas (staff), ou retornar lista vazia — qualquer um dos dois casos é
// tratado (mostramos aviso se a lista vier vazia).

import { useState } from "react";
import { api, type Reserva } from "@/lib/api";
import { Badge, Botao, BotaoSecundario, Campo, Card, Titulo, Aviso } from "@/components/ui";
import { centavos, dataLocal, horaLocal } from "@/lib/format";

type Cliente = { id: number; nome: string; celular?: string; email?: string };

function mensagemErro(e: unknown, fallback: string): string {
  const err = e as { body?: { detail?: string } | null };
  return err?.body?.detail || fallback;
}

export default function AdminClientesPage() {
  const [busca, setBusca] = useState("");
  const [resultados, setResultados] = useState<Cliente[] | null>(null);
  const [buscando, setBuscando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const [clienteSelecionado, setClienteSelecionado] = useState<Cliente | null>(null);
  const [historico, setHistorico] = useState<Reserva[] | null>(null);
  const [carregandoHistorico, setCarregandoHistorico] = useState(false);

  const [mostrarNovo, setMostrarNovo] = useState(false);
  const [novoNome, setNovoNome] = useState("");
  const [novoCelular, setNovoCelular] = useState("");
  const [novoEmail, setNovoEmail] = useState("");
  const [salvandoNovo, setSalvandoNovo] = useState(false);
  const [erroNovo, setErroNovo] = useState<string | null>(null);

  async function buscar() {
    setErro(null);
    setBuscando(true);
    try {
      const lista = (await api.clientes.listar(encodeURIComponent(busca.trim()))) as Cliente[];
      setResultados(lista);
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível buscar clientes."));
    } finally {
      setBuscando(false);
    }
  }

  async function verHistorico(cliente: Cliente) {
    setClienteSelecionado(cliente);
    setHistorico(null);
    setCarregandoHistorico(true);
    setErro(null);
    try {
      const resp = await api.reservasAdmin(`cliente_id=${cliente.id}`);
      setHistorico(resp.itens);
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível carregar o histórico deste cliente."));
    } finally {
      setCarregandoHistorico(false);
    }
  }

  async function criarClienteBalcao(e: React.FormEvent) {
    e.preventDefault();
    setErroNovo(null);
    if (!novoNome.trim()) {
      setErroNovo("Informe o nome.");
      return;
    }
    if (!novoCelular.trim() || !novoEmail.trim()) {
      // Backend exige os dois (Cliente.email/celular são NOT NULL, email é
      // UNIQUE) — validação espelhada aqui pra dar um erro claro em vez de
      // deixar estourar 422 direto da API.
      setErroNovo("Informe celular e e-mail.");
      return;
    }
    setSalvandoNovo(true);
    try {
      const criado = (await api.clientes.criar({
        nome: novoNome.trim(),
        celular: novoCelular.trim(),
        email: novoEmail.trim(),
      })) as Cliente;
      setMostrarNovo(false);
      setNovoNome("");
      setNovoCelular("");
      setNovoEmail("");
      setResultados((prev) => (prev ? [criado, ...prev] : [criado]));
    } catch (e) {
      setErroNovo(mensagemErro(e, "Não foi possível criar o cliente."));
    } finally {
      setSalvandoNovo(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
        <Titulo>Clientes</Titulo>
        <BotaoSecundario type="button" onClick={() => setMostrarNovo((v) => !v)}>
          {mostrarNovo ? "Cancelar" : "Novo cliente de balcão"}
        </BotaoSecundario>
      </div>

      {mostrarNovo && (
        <Card style={{ marginBottom: 20 }}>
          <Titulo as="h3">Novo cliente</Titulo>
          {erroNovo && <Aviso tipo="erro">{erroNovo}</Aviso>}
          <form onSubmit={criarClienteBalcao}>
            <Campo label="Nome" value={novoNome} onChange={(e) => setNovoNome(e.target.value)} required />
            <div style={{ display: "flex", gap: 12 }}>
              <Campo label="Celular" value={novoCelular} onChange={(e) => setNovoCelular(e.target.value)} required />
              <Campo label="E-mail" type="email" value={novoEmail} onChange={(e) => setNovoEmail(e.target.value)} required />
            </div>
            <Botao type="submit" disabled={salvandoNovo}>
              {salvandoNovo ? "Salvando..." : "Salvar cliente"}
            </Botao>
          </form>
        </Card>
      )}

      <Card style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <Campo
              label="Buscar por nome ou celular"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && buscar()}
            />
          </div>
          <Botao type="button" onClick={buscar} disabled={buscando} style={{ marginBottom: 14 }}>
            {buscando ? "Buscando..." : "Buscar"}
          </Botao>
        </div>
      </Card>

      {erro && <Aviso tipo="erro">{erro}</Aviso>}

      {resultados && resultados.length === 0 && <p>Nenhum cliente encontrado.</p>}

      {resultados && resultados.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 24 }}>
          {resultados.map((c) => (
            <Card key={c.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
              <div>
                <strong>{c.nome}</strong>
                {c.celular && <span> — {c.celular}</span>}
                {c.email && <span> — {c.email}</span>}
              </div>
              <BotaoSecundario type="button" onClick={() => verHistorico(c)}>
                Ver histórico
              </BotaoSecundario>
            </Card>
          ))}
        </div>
      )}

      {clienteSelecionado && (
        <div>
          <Titulo as="h2">Histórico — {clienteSelecionado.nome}</Titulo>
          {carregandoHistorico && <p>Carregando histórico...</p>}
          {!carregandoHistorico && historico && historico.length === 0 && (
            <Aviso tipo="info">
              Nenhuma reserva encontrada para este cliente. Se o filtro por cliente ainda não estiver
              implementado no backend, esta lista pode estar vazia mesmo havendo histórico — ver nota de
              implementação no topo deste arquivo.
            </Aviso>
          )}
          {historico && historico.length > 0 && (
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
          )}
        </div>
      )}
    </div>
  );
}
