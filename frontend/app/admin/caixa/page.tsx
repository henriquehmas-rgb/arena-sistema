"use client";

// Admin — Caixa do dia. Task T12 Step 3.

import { useEffect, useState, type CSSProperties } from "react";
import { api } from "@/lib/api";
import { mensagemErro } from "@/lib/auth";
import { Card, Titulo, Aviso } from "@/components/ui";
import { centavos, horaLocal, paraDataISO } from "@/lib/format";

type ItemCaixa = {
  id?: number;
  descricao?: string;
  recurso?: string;
  recurso_nome?: string;
  cliente?: string;
  cliente_nome?: string;
  inicio?: string;
  hora?: string;
  metodo?: string;
  origem?: string;
  valor_centavos?: number;
};

type Caixa = {
  itens: ItemCaixa[];
  total_centavos: number;
  por_metodo: Record<string, number>;
};

const METODO_LABEL: Record<string, string> = {
  pix: "Pix",
  cartao: "Cartão",
  dinheiro: "Dinheiro",
};

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

function itemDescricao(item: ItemCaixa): string {
  return item.descricao || item.recurso_nome || item.recurso || "Item";
}

function itemHora(item: ItemCaixa): string {
  if (item.inicio) return horaLocal(item.inicio);
  return item.hora ?? "—";
}

export default function CaixaPage() {
  const [data, setData] = useState(() => paraDataISO(new Date()));
  const [caixa, setCaixa] = useState<Caixa | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);

  useEffect(() => {
    carregar(data);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  async function carregar(d: string) {
    setCarregando(true);
    setErro(null);
    try {
      const r = (await api.caixa(d)) as Caixa;
      setCaixa(r);
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível carregar o caixa."));
      setCaixa(null);
    } finally {
      setCarregando(false);
    }
  }

  const itens = caixa?.itens ?? [];
  const porMetodo = Object.entries(caixa?.por_metodo ?? {});

  return (
    <>
      <Titulo>Caixa</Titulo>
      {erro && <Aviso tipo="erro">{erro}</Aviso>}

      <Card style={{ marginBottom: 20, maxWidth: 280 }}>
        <div className="ac-campo" style={{ marginBottom: 0 }}>
          <label htmlFor="caixa-data">Data</label>
          <input
            id="caixa-data"
            type="date"
            className="ac-input"
            value={data}
            onChange={(e) => setData(e.target.value)}
          />
        </div>
      </Card>

      {carregando && <p>Carregando...</p>}

      {!carregando && caixa && (
        <>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 20 }}>
            <Card style={{ minWidth: 180 }}>
              <p style={{ margin: 0, color: "var(--cinza)", fontSize: "0.85rem" }}>Total do dia</p>
              <p style={{ margin: 0, fontWeight: 700, fontSize: "1.4rem" }}>{centavos(caixa.total_centavos)}</p>
            </Card>
            {porMetodo.map(([metodo, valor]) => (
              <Card key={metodo} style={{ minWidth: 160 }}>
                <p style={{ margin: 0, color: "var(--cinza)", fontSize: "0.85rem" }}>
                  {METODO_LABEL[metodo] ?? metodo}
                </p>
                <p style={{ margin: 0, fontWeight: 700, fontSize: "1.2rem" }}>{centavos(valor)}</p>
              </Card>
            ))}
          </div>

          <Card>
            <Titulo as="h2">Itens do dia</Titulo>
            {itens.length === 0 && <p>Nenhum lançamento nesta data.</p>}
            {itens.length > 0 && (
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyle}>Hora</th>
                    <th style={thStyle}>Descrição</th>
                    <th style={thStyle}>Cliente</th>
                    <th style={thStyle}>Método</th>
                    <th style={thStyle}>Valor</th>
                  </tr>
                </thead>
                <tbody>
                  {itens.map((item, i) => (
                    <tr key={item.id ?? i}>
                      <td style={tdStyle}>{itemHora(item)}</td>
                      <td style={tdStyle}>{itemDescricao(item)}</td>
                      <td style={tdStyle}>{item.cliente_nome || item.cliente || "—"}</td>
                      <td style={tdStyle}>{METODO_LABEL[item.metodo ?? ""] ?? item.metodo ?? "—"}</td>
                      <td style={tdStyle}>{item.valor_centavos != null ? centavos(item.valor_centavos) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </>
      )}
    </>
  );
}
