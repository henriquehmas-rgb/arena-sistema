"use client";

// Admin — Relatórios (admin). Task T12 Step 4.
// Gráfico de barras por dia feito em CSS puro (divs com altura proporcional),
// sem lib externa, conforme pedido no brief.

import { useEffect, useState, type CSSProperties } from "react";
import { api } from "@/lib/api";
import { mensagemErro } from "@/lib/auth";
import { Card, Titulo, Aviso, Campo, Botao } from "@/components/ui";
import { centavos, paraDataISO } from "@/lib/format";

type MapaCentavos = Record<string, number>;

type Faturamento = {
  total_centavos: number;
  por_metodo: MapaCentavos;
  por_recurso: MapaCentavos | { recurso: string; total_centavos: number }[];
  por_dia: MapaCentavos | { data: string; total_centavos: number }[];
};

type OcupacaoItem = { recurso: string; horas_vendidas: number; horas_disponiveis: number; taxa: number };
type Ocupacao = { por_recurso: OcupacaoItem[] };

const METODO_LABEL: Record<string, string> = { pix: "Pix", cartao: "Cartão", dinheiro: "Dinheiro" };

function normalizarPares(v: MapaCentavos | { [k: string]: unknown }[] | undefined, chaveLabel: string, chaveValor: string): { label: string; valor: number }[] {
  if (!v) return [];
  if (Array.isArray(v)) {
    return v.map((item) => ({
      label: String((item as Record<string, unknown>)[chaveLabel] ?? ""),
      valor: Number((item as Record<string, unknown>)[chaveValor] ?? 0),
    }));
  }
  return Object.entries(v).map(([label, valor]) => ({ label, valor: Number(valor) }));
}

function diaAbrev(dataStr: string): string {
  // dataStr esperado como "YYYY-MM-DD"; se não for, exibe como veio.
  const partes = dataStr.split("-");
  if (partes.length === 3) return `${partes[2]}/${partes[1]}`;
  return dataStr;
}

function taxaPct(taxa: number): string {
  const pct = taxa <= 1 ? taxa * 100 : taxa;
  return `${pct.toFixed(0)}%`;
}

const tableStyle: CSSProperties = { width: "100%", borderCollapse: "collapse", marginTop: 4 };
const thStyle: CSSProperties = {
  textAlign: "left",
  padding: "8px 10px",
  borderBottom: "2px solid #e7e9f0",
  fontSize: "0.78rem",
  color: "var(--cinza)",
  textTransform: "uppercase",
};
const tdStyle: CSSProperties = { padding: "10px", borderBottom: "1px solid #eef0f5" };

function GraficoBarras({ dados }: { dados: { label: string; valor: number }[] }) {
  const max = Math.max(1, ...dados.map((d) => d.valor));
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 180, marginTop: 12, overflowX: "auto" }}>
      {dados.map((d) => (
        <div
          key={d.label}
          style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: "0 0 auto", width: 44 }}
          title={`${d.label}: ${centavos(d.valor)}`}
        >
          <div
            style={{
              width: 28,
              height: Math.max(4, Math.round((d.valor / max) * 140)),
              background: "linear-gradient(180deg, var(--ciano), var(--azul))",
              borderRadius: "4px 4px 0 0",
            }}
          />
          <span style={{ fontSize: "0.7rem", color: "var(--cinza)", marginTop: 4 }}>{diaAbrev(d.label)}</span>
        </div>
      ))}
    </div>
  );
}

function periodoPadrao() {
  const hoje = new Date();
  const trintaAtras = new Date(hoje);
  trintaAtras.setDate(hoje.getDate() - 30);
  return { de: paraDataISO(trintaAtras), ate: paraDataISO(hoje) };
}

export default function RelatoriosPage() {
  const padrao = periodoPadrao();
  const [de, setDe] = useState(padrao.de);
  const [ate, setAte] = useState(padrao.ate);
  const [faturamento, setFaturamento] = useState<Faturamento | null>(null);
  const [ocupacao, setOcupacao] = useState<Ocupacao | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);

  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function carregar() {
    setCarregando(true);
    setErro(null);
    try {
      const [f, o] = await Promise.all([api.faturamento(de, ate), api.ocupacao(de, ate)]);
      setFaturamento(f as Faturamento);
      setOcupacao(o as Ocupacao);
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível carregar os relatórios."));
    } finally {
      setCarregando(false);
    }
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    carregar();
  }

  const porMetodo = normalizarPares(faturamento?.por_metodo, "metodo", "valor");
  const porRecurso = normalizarPares(faturamento?.por_recurso, "recurso", "total_centavos");
  const porDia = normalizarPares(faturamento?.por_dia, "data", "total_centavos").sort((a, b) =>
    a.label.localeCompare(b.label)
  );

  return (
    <>
      <Titulo>Relatórios</Titulo>
      {erro && <Aviso tipo="erro">{erro}</Aviso>}

      <Card style={{ marginBottom: 20 }}>
        <form onSubmit={onSubmit} style={{ display: "flex", gap: 16, alignItems: "flex-end", flexWrap: "wrap" }}>
          <Campo label="De" type="date" value={de} onChange={(e) => setDe(e.target.value)} />
          <Campo label="Até" type="date" value={ate} onChange={(e) => setAte(e.target.value)} />
          <div style={{ marginBottom: 14 }}>
            <Botao type="submit" disabled={carregando}>
              {carregando ? "Carregando..." : "Filtrar"}
            </Botao>
          </div>
        </form>
      </Card>

      {faturamento && (
        <>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 20 }}>
            <Card style={{ minWidth: 200 }}>
              <p style={{ margin: 0, color: "var(--cinza)", fontSize: "0.85rem" }}>Faturamento total</p>
              <p style={{ margin: 0, fontWeight: 700, fontSize: "1.4rem" }}>{centavos(faturamento.total_centavos)}</p>
            </Card>
            {porMetodo.map((m) => (
              <Card key={m.label} style={{ minWidth: 160 }}>
                <p style={{ margin: 0, color: "var(--cinza)", fontSize: "0.85rem" }}>
                  {METODO_LABEL[m.label] ?? m.label}
                </p>
                <p style={{ margin: 0, fontWeight: 700, fontSize: "1.2rem" }}>{centavos(m.valor)}</p>
              </Card>
            ))}
          </div>

          <Card style={{ marginBottom: 20 }}>
            <Titulo as="h2">Faturamento por recurso</Titulo>
            {porRecurso.length === 0 && <p>Sem dados no período.</p>}
            {porRecurso.length > 0 && (
              <div className="ac-tabela-wrap">
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyle}>Recurso</th>
                    <th style={thStyle}>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {porRecurso.map((r) => (
                    <tr key={r.label}>
                      <td style={tdStyle}>{r.label}</td>
                      <td style={tdStyle}>{centavos(r.valor)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </Card>

          <Card style={{ marginBottom: 20 }}>
            <Titulo as="h2">Faturamento por dia</Titulo>
            {porDia.length === 0 && <p>Sem dados no período.</p>}
            {porDia.length > 0 && <GraficoBarras dados={porDia} />}
          </Card>
        </>
      )}

      {ocupacao && (
        <Card>
          <Titulo as="h2">Ocupação por recurso</Titulo>
          {ocupacao.por_recurso.length === 0 && <p>Sem dados no período.</p>}
          {ocupacao.por_recurso.length > 0 && (
            <div className="ac-tabela-wrap">
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>Recurso</th>
                  <th style={thStyle}>Horas vendidas</th>
                  <th style={thStyle}>Horas disponíveis</th>
                  <th style={thStyle}>Taxa</th>
                </tr>
              </thead>
              <tbody>
                {ocupacao.por_recurso.map((o) => (
                  <tr key={o.recurso}>
                    <td style={tdStyle}>{o.recurso}</td>
                    <td style={tdStyle}>{o.horas_vendidas}</td>
                    <td style={tdStyle}>{o.horas_disponiveis}</td>
                    <td style={tdStyle}>{taxaPct(o.taxa)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </Card>
      )}
    </>
  );
}
