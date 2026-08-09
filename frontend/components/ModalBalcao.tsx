"use client";

// Modal de reserva de balcão: aberto ao clicar num slot livre da AgendaAdmin.
// Busca cliente cadastrado (nome/celular) via api.clientes.listar, ou cria a
// reserva como "avulso" (nome_avulso/celular_avulso) para quem não tem
// cadastro. Método de pagamento: dinheiro ou pix_manual (recebido na hora,
// sem integração Pagar.me — condiz com o fluxo de balcão do contrato).

import { useState } from "react";
import { api, type Slot } from "@/lib/api";
import { Botao, BotaoSecundario, Campo, Card, Titulo, Aviso } from "@/components/ui";
import { centavos, dataLocal, horaLocal } from "@/lib/format";

type Cliente = { id: number; nome: string; celular?: string; email?: string };
type Metodo = "dinheiro" | "pix_manual";

function mensagemErro(e: unknown, fallback: string): string {
  const err = e as { body?: { detail?: string } | null };
  return err?.body?.detail || fallback;
}

export default function ModalBalcao({
  recursoId,
  recursoNome,
  slot,
  onFechar,
  onCriado,
}: {
  recursoId: number;
  recursoNome: string;
  slot: Slot;
  onFechar: () => void;
  onCriado: () => void;
}) {
  const [modo, setModo] = useState<"cadastrado" | "avulso">("cadastrado");
  const [busca, setBusca] = useState("");
  const [resultados, setResultados] = useState<Cliente[]>([]);
  const [clienteSelecionado, setClienteSelecionado] = useState<Cliente | null>(null);
  const [buscando, setBuscando] = useState(false);

  const [nomeAvulso, setNomeAvulso] = useState("");
  const [celularAvulso, setCelularAvulso] = useState("");

  const [metodo, setMetodo] = useState<Metodo>("dinheiro");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function buscarClientes() {
    if (!busca.trim()) return;
    setBuscando(true);
    setErro(null);
    try {
      const lista = (await api.clientes.listar(encodeURIComponent(busca.trim()))) as Cliente[];
      setResultados(lista);
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível buscar clientes."));
    } finally {
      setBuscando(false);
    }
  }

  async function confirmar() {
    setErro(null);
    if (modo === "cadastrado" && !clienteSelecionado) {
      setErro("Selecione um cliente na busca, ou use \"Avulso\".");
      return;
    }
    if (modo === "avulso" && !nomeAvulso.trim()) {
      setErro("Informe o nome do cliente avulso.");
      return;
    }
    setEnviando(true);
    try {
      await api.reservaBalcao({
        recurso_id: recursoId,
        inicio: slot.inicio,
        fim: slot.fim,
        ...(modo === "cadastrado"
          ? { cliente_id: clienteSelecionado!.id }
          : { nome_avulso: nomeAvulso.trim(), celular_avulso: celularAvulso.trim() || undefined }),
        metodo,
      });
      onCriado();
    } catch (e: unknown) {
      const err = e as { status?: number };
      const msg =
        err?.status === 409
          ? "Esse horário acabou de ser ocupado. Feche e atualize a agenda."
          : mensagemErro(e, "Não foi possível criar a reserva de balcão.");
      setErro(msg);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(23,19,53,0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
        padding: 16,
      }}
      onClick={onFechar}
    >
      <div onClick={(e) => e.stopPropagation()} style={{ width: "100%", maxWidth: 480 }}>
        <Card>
          <Titulo as="h2">Reserva de balcão</Titulo>
          <p style={{ marginTop: -8 }}>
            <strong>{recursoNome}</strong> — {dataLocal(slot.inicio)} · {horaLocal(slot.inicio)} às{" "}
            {horaLocal(slot.fim)} — {centavos(slot.preco_centavos)}
          </p>

          {erro && <Aviso tipo="erro">{erro}</Aviso>}

          <div className="ac-tabs">
            <button
              type="button"
              className={`ac-tab ${modo === "cadastrado" ? "ativo" : ""}`}
              onClick={() => setModo("cadastrado")}
            >
              Cliente cadastrado
            </button>
            <button
              type="button"
              className={`ac-tab ${modo === "avulso" ? "ativo" : ""}`}
              onClick={() => setModo("avulso")}
            >
              Avulso
            </button>
          </div>

          {modo === "cadastrado" ? (
            <>
              <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
                <div style={{ flex: 1 }}>
                  <Campo
                    label="Buscar por nome ou celular"
                    value={busca}
                    onChange={(e) => setBusca(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && buscarClientes()}
                  />
                </div>
                <BotaoSecundario type="button" onClick={buscarClientes} disabled={buscando} style={{ marginBottom: 14 }}>
                  {buscando ? "Buscando..." : "Buscar"}
                </BotaoSecundario>
              </div>

              {resultados.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 14 }}>
                  {resultados.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => setClienteSelecionado(c)}
                      style={{
                        textAlign: "left",
                        padding: "8px 12px",
                        borderRadius: 8,
                        border: "1.5px solid " + (clienteSelecionado?.id === c.id ? "var(--azul)" : "#d7dbe6"),
                        background: clienteSelecionado?.id === c.id ? "rgba(11,99,216,0.08)" : "var(--branco)",
                        cursor: "pointer",
                        fontFamily: "inherit",
                      }}
                    >
                      <strong>{c.nome}</strong> {c.celular ? `— ${c.celular}` : ""}
                    </button>
                  ))}
                </div>
              )}
              {clienteSelecionado && (
                <p>
                  Selecionado: <strong>{clienteSelecionado.nome}</strong>
                </p>
              )}
            </>
          ) : (
            <>
              <Campo label="Nome" value={nomeAvulso} onChange={(e) => setNomeAvulso(e.target.value)} required />
              <Campo
                label="Celular (opcional)"
                value={celularAvulso}
                onChange={(e) => setCelularAvulso(e.target.value)}
              />
            </>
          )}

          <div className="ac-campo">
            <label>Método de pagamento</label>
            <div className="ac-metodos">
              <Botao
                type="button"
                onClick={() => setMetodo("dinheiro")}
                style={metodo === "dinheiro" ? {} : { opacity: 0.55 }}
              >
                Dinheiro
              </Botao>
              <BotaoSecundario
                type="button"
                onClick={() => setMetodo("pix_manual")}
                style={metodo === "pix_manual" ? { background: "rgba(11,99,216,0.08)" } : {}}
              >
                Pix (manual)
              </BotaoSecundario>
            </div>
          </div>

          <div style={{ display: "flex", gap: 12, justifyContent: "flex-end" }}>
            <BotaoSecundario type="button" onClick={onFechar} disabled={enviando}>
              Cancelar
            </BotaoSecundario>
            <Botao type="button" onClick={confirmar} disabled={enviando}>
              {enviando ? "Salvando..." : "Confirmar reserva"}
            </Botao>
          </div>
        </Card>
      </div>
    </div>
  );
}
