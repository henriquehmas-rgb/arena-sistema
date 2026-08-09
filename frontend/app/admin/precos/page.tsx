"use client";

// Admin — Tabela de preços por recurso. Task T12 Step 2.
//
// Convenção de dia da semana: 0=Domingo, 1=Segunda, ... 6=Sábado
// (Date.getDay()), exibida em ordem seg→dom via DIAS_ORDEM_EXIBICAO.

import { useEffect, useState, type CSSProperties } from "react";
import { api } from "@/lib/api";
import { mensagemErro } from "@/lib/auth";
import { Botao, BotaoSecundario, Campo, Card, Titulo, Aviso } from "@/components/ui";
import { centavos } from "@/lib/format";

type Recurso = { id: number; nome: string; tipo: string; ativo: boolean };
type Preco = {
  id: number;
  recurso_id: number;
  dias_semana: number[];
  hora_inicio: string;
  hora_fim: string;
  preco_centavos: number;
};

const DIAS_ABREV = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
const DIAS_ORDEM_EXIBICAO = [1, 2, 3, 4, 5, 6, 0]; // seg -> dom

function reaisParaCentavos(valorStr: string): number {
  let s = valorStr.trim();
  if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
  const n = parseFloat(s);
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

function centavosParaReais(c: number): string {
  return (c / 100).toFixed(2).replace(".", ",");
}

const chipStyle = (ativo: boolean): CSSProperties => ({
  padding: "6px 10px",
  borderRadius: 8,
  border: `1.5px solid ${ativo ? "var(--azul)" : "#d7dbe6"}`,
  background: ativo ? "var(--azul)" : "var(--branco)",
  color: ativo ? "var(--branco)" : "var(--tinta)",
  cursor: "pointer",
  fontWeight: 600,
  fontSize: "0.82rem",
});

const tableStyle: CSSProperties = { width: "100%", borderCollapse: "collapse", marginTop: 4 };
const thStyle: CSSProperties = {
  textAlign: "left",
  padding: "8px 10px",
  borderBottom: "2px solid #e7e9f0",
  fontSize: "0.78rem",
  color: "var(--cinza)",
  textTransform: "uppercase",
};
const tdStyle: CSSProperties = { padding: "10px", borderBottom: "1px solid #eef0f5", verticalAlign: "middle" };

function FormularioPreco({
  inicial,
  onSalvar,
  onCancelar,
  salvando,
}: {
  inicial?: Preco;
  onSalvar: (dados: { dias_semana: number[]; hora_inicio: string; hora_fim: string; preco_centavos: number }) => void;
  onCancelar?: () => void;
  salvando: boolean;
}) {
  const [dias, setDias] = useState<number[]>(inicial?.dias_semana ?? []);
  const [horaInicio, setHoraInicio] = useState(inicial?.hora_inicio ?? "08:00");
  const [horaFim, setHoraFim] = useState(inicial?.hora_fim ?? "09:00");
  const [valorReais, setValorReais] = useState(inicial ? centavosParaReais(inicial.preco_centavos) : "");
  const [erro, setErro] = useState<string | null>(null);

  function alternarDia(d: number) {
    setDias((prev) => (prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]));
  }

  function submeter(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    if (dias.length === 0) {
      setErro("Selecione ao menos um dia da semana.");
      return;
    }
    onSalvar({ dias_semana: dias, hora_inicio: horaInicio, hora_fim: horaFim, preco_centavos: reaisParaCentavos(valorReais) });
  }

  return (
    <form onSubmit={submeter} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {erro && <Aviso tipo="erro">{erro}</Aviso>}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {DIAS_ORDEM_EXIBICAO.map((d) => (
          <button type="button" key={d} style={chipStyle(dias.includes(d))} onClick={() => alternarDia(d)}>
            {DIAS_ABREV[d]}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        <Campo
          label="Início"
          type="time"
          value={horaInicio}
          onChange={(e) => setHoraInicio(e.target.value)}
          required
        />
        <Campo label="Fim" type="time" value={horaFim} onChange={(e) => setHoraFim(e.target.value)} required />
        <Campo
          label="Valor (R$)"
          value={valorReais}
          onChange={(e) => setValorReais(e.target.value)}
          placeholder="80,00"
          required
        />
        <div style={{ marginBottom: 14, display: "flex", gap: 8 }}>
          <Botao type="submit" disabled={salvando}>
            {salvando ? "Salvando..." : "Salvar"}
          </Botao>
          {onCancelar && (
            <BotaoSecundario type="button" onClick={onCancelar}>
              Cancelar
            </BotaoSecundario>
          )}
        </div>
      </div>
    </form>
  );
}

export default function PrecosPage() {
  const [recursos, setRecursos] = useState<Recurso[]>([]);
  const [precos, setPrecos] = useState<Preco[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [editando, setEditando] = useState<number | null>(null);
  const [novoPara, setNovoPara] = useState<number | null>(null);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    carregar();
  }, []);

  async function carregar() {
    setErro(null);
    try {
      const [r, p] = await Promise.all([api.recursos(), api.precos.listar()]);
      setRecursos(r);
      setPrecos(p as Preco[]);
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível carregar a tabela de preços."));
    }
  }

  async function criar(recursoId: number, dados: { dias_semana: number[]; hora_inicio: string; hora_fim: string; preco_centavos: number }) {
    setSalvando(true);
    setErro(null);
    try {
      await api.precos.criar({ recurso_id: recursoId, ...dados });
      setNovoPara(null);
      await carregar();
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível criar a regra de preço."));
    } finally {
      setSalvando(false);
    }
  }

  async function atualizar(id: number, dados: { dias_semana: number[]; hora_inicio: string; hora_fim: string; preco_centavos: number }) {
    setSalvando(true);
    setErro(null);
    try {
      await api.precos.atualizar(id, dados);
      setEditando(null);
      await carregar();
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível atualizar a regra de preço."));
    } finally {
      setSalvando(false);
    }
  }

  async function remover(id: number) {
    if (!window.confirm("Remover esta regra de preço?")) return;
    setErro(null);
    try {
      await api.precos.remover(id);
      await carregar();
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível remover a regra de preço."));
    }
  }

  if (precos === null && !erro) return <p>Carregando...</p>;

  return (
    <>
      <Titulo>Preços</Titulo>
      {erro && <Aviso tipo="erro">{erro}</Aviso>}

      {recursos.map((r) => {
        const regras = (precos ?? []).filter((p) => p.recurso_id === r.id);
        return (
          <Card key={r.id} style={{ marginBottom: 20 }}>
            <Titulo as="h2">{r.nome}</Titulo>

            {regras.length === 0 && <p>Nenhuma regra de preço cadastrada.</p>}

            {regras.length > 0 && (
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyle}>Dias</th>
                    <th style={thStyle}>Horário</th>
                    <th style={thStyle}>Valor</th>
                    <th style={thStyle}>Ações</th>
                  </tr>
                </thead>
                <tbody>
                  {regras.map((p) =>
                    editando === p.id ? (
                      <tr key={p.id}>
                        <td colSpan={4} style={tdStyle}>
                          <FormularioPreco
                            inicial={p}
                            salvando={salvando}
                            onSalvar={(dados) => atualizar(p.id, dados)}
                            onCancelar={() => setEditando(null)}
                          />
                        </td>
                      </tr>
                    ) : (
                      <tr key={p.id}>
                        <td style={tdStyle}>
                          {p.dias_semana
                            .slice()
                            .sort((a, b) => DIAS_ORDEM_EXIBICAO.indexOf(a) - DIAS_ORDEM_EXIBICAO.indexOf(b))
                            .map((d) => DIAS_ABREV[d])
                            .join(", ")}
                        </td>
                        <td style={tdStyle}>
                          {p.hora_inicio} – {p.hora_fim}
                        </td>
                        <td style={tdStyle}>{centavos(p.preco_centavos)}</td>
                        <td style={tdStyle}>
                          <div style={{ display: "flex", gap: 8 }}>
                            <BotaoSecundario onClick={() => setEditando(p.id)}>Editar</BotaoSecundario>
                            <BotaoSecundario onClick={() => remover(p.id)}>Remover</BotaoSecundario>
                          </div>
                        </td>
                      </tr>
                    )
                  )}
                </tbody>
              </table>
            )}

            <div style={{ marginTop: 16 }}>
              {novoPara === r.id ? (
                <FormularioPreco
                  salvando={salvando}
                  onSalvar={(dados) => criar(r.id, dados)}
                  onCancelar={() => setNovoPara(null)}
                />
              ) : (
                <BotaoSecundario onClick={() => setNovoPara(r.id)}>+ Nova regra de preço</BotaoSecundario>
              )}
            </div>
          </Card>
        );
      })}
    </>
  );
}
