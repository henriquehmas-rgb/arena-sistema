"use client";

// Admin — Mensalistas (assinaturas recorrentes). Task T12 Step 1.
//
// Convenção de dia da semana usada na UI (mesma usada em app/admin/precos):
// 0=Domingo, 1=Segunda, ... 6=Sábado (convenção JS Date.getDay()), exibida
// visualmente em ordem seg→dom.
//
// O BACKEND usa outra convenção: datetime.weekday() — 0=Segunda, 1=Terça,
// ..., 5=Sábado, 6=Domingo. Todo valor de dia_semana lido do backend (pra
// exibir) ou enviado pro backend (ao criar/editar) precisa passar por uma
// das funções de conversão abaixo.

import { useEffect, useState, type CSSProperties } from "react";
import { api } from "@/lib/api";
import { mensagemErro } from "@/lib/auth";
import { Badge, Botao, BotaoSecundario, Campo, Card, Titulo, Aviso } from "@/components/ui";
import { centavos } from "@/lib/format";

type Recurso = { id: number; nome: string; tipo: string; ativo: boolean };
type Cliente = { id: number; nome: string; email?: string; celular?: string };

type Assinatura = {
  id: number;
  cliente_id?: number;
  cliente?: string | { id: number; nome: string };
  recurso_id?: number;
  recurso?: string | { id: number; nome: string };
  dia_semana: number;
  hora_inicio: string;
  hora_fim?: string;
  valor_centavos?: number;
  metodo?: string;
  status: string;
};

const DIAS_LABEL = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"];
const DIAS_ORDEM_EXIBICAO = [1, 2, 3, 4, 5, 6, 0]; // seg -> dom

// Backend usa 0=segunda..6=domingo (datetime.weekday()); JS Date usa 0=domingo..6=sábado.
function diaJsParaBackend(diaJs: number): number {
  return (diaJs + 6) % 7;
}
function diaBackendParaJs(diaBackend: number): number {
  return (diaBackend + 1) % 7;
}

const METODOS = [
  { valor: "pix", label: "Pix" },
  { valor: "cartao", label: "Cartão" },
  { valor: "dinheiro", label: "Dinheiro" },
];

function nomeDe(v?: string | { id: number; nome: string }): string {
  if (!v) return "—";
  return typeof v === "string" ? v : v.nome;
}

function reaisParaCentavos(valorStr: string): number {
  let s = valorStr.trim();
  if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
  const n = parseFloat(s);
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
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
const tdStyle: CSSProperties = { padding: "10px", borderBottom: "1px solid #eef0f5", verticalAlign: "middle" };

export default function MensalistasPage() {
  const [assinaturas, setAssinaturas] = useState<Assinatura[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [acaoEmAndamento, setAcaoEmAndamento] = useState<number | null>(null);

  const [recursos, setRecursos] = useState<Recurso[]>([]);
  const [mostrarForm, setMostrarForm] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erroForm, setErroForm] = useState<string | null>(null);

  const [buscaCliente, setBuscaCliente] = useState("");
  const [resultadosCliente, setResultadosCliente] = useState<Cliente[]>([]);
  const [clienteSelecionado, setClienteSelecionado] = useState<Cliente | null>(null);
  const [recursoId, setRecursoId] = useState<number | "">("");
  const [diaSemana, setDiaSemana] = useState<number>(1);
  const [horaInicio, setHoraInicio] = useState("08:00");
  const [valorReais, setValorReais] = useState("");
  const [metodo, setMetodo] = useState("pix");

  useEffect(() => {
    carregar();
    api
      .recursos()
      .then(setRecursos)
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function carregar() {
    setErro(null);
    try {
      const lista = (await api.assinaturas.listar()) as Assinatura[];
      setAssinaturas(lista);
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível carregar os mensalistas."));
    }
  }

  useEffect(() => {
    if (buscaCliente.trim().length < 2) {
      setResultadosCliente([]);
      return;
    }
    const t = setTimeout(() => {
      api.clientes
        .listar(buscaCliente.trim())
        .then((r) => setResultadosCliente(r as Cliente[]))
        .catch(() => setResultadosCliente([]));
    }, 300);
    return () => clearTimeout(t);
  }, [buscaCliente]);

  async function executarAcao(id: number, acao: "pausar" | "reativar" | "cancelar") {
    if (acao === "cancelar") {
      if (!window.confirm("Tem certeza que deseja cancelar esta assinatura?")) return;
      if (!window.confirm("Essa ação não pode ser desfeita. Confirmar cancelamento?")) return;
    }
    setAcaoEmAndamento(id);
    setErro(null);
    try {
      await api.assinaturas.acao(id, acao);
      await carregar();
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível concluir a ação."));
    } finally {
      setAcaoEmAndamento(null);
    }
  }

  function limparForm() {
    setBuscaCliente("");
    setResultadosCliente([]);
    setClienteSelecionado(null);
    setRecursoId("");
    setDiaSemana(1);
    setHoraInicio("08:00");
    setValorReais("");
    setMetodo("pix");
  }

  async function criarMensalista(e: React.FormEvent) {
    e.preventDefault();
    setErroForm(null);
    if (!clienteSelecionado) {
      setErroForm("Selecione um cliente.");
      return;
    }
    if (!recursoId) {
      setErroForm("Selecione um recurso.");
      return;
    }
    setEnviando(true);
    try {
      await api.assinaturas.criar({
        cliente_id: clienteSelecionado.id,
        recurso_id: recursoId,
        dia_semana: diaJsParaBackend(diaSemana),
        hora_inicio: horaInicio,
        valor_centavos: reaisParaCentavos(valorReais),
        metodo,
      });
      limparForm();
      setMostrarForm(false);
      await carregar();
    } catch (e) {
      setErroForm(mensagemErro(e, "Não foi possível criar o mensalista."));
    } finally {
      setEnviando(false);
    }
  }

  const lista = assinaturas ?? [];
  const inadimplentes = lista.filter((a) => a.status === "inadimplente");
  const outros = lista.filter((a) => a.status !== "inadimplente");
  const ordenados = [...inadimplentes, ...outros];

  return (
    <>
      <Titulo>Mensalistas</Titulo>
      {erro && <Aviso tipo="erro">{erro}</Aviso>}

      <div style={{ marginBottom: 16 }}>
        <Botao onClick={() => setMostrarForm((v) => !v)}>
          {mostrarForm ? "Fechar" : "+ Novo mensalista"}
        </Botao>
      </div>

      {mostrarForm && (
        <Card style={{ marginBottom: 24 }}>
          <Titulo as="h2">Novo mensalista</Titulo>
          {erroForm && <Aviso tipo="erro">{erroForm}</Aviso>}
          <form onSubmit={criarMensalista}>
            <Campo
              label="Buscar cliente (nome, e-mail ou celular)"
              value={clienteSelecionado ? clienteSelecionado.nome : buscaCliente}
              onChange={(e) => {
                setClienteSelecionado(null);
                setBuscaCliente(e.target.value);
              }}
              placeholder="Digite para buscar..."
            />
            {!clienteSelecionado && resultadosCliente.length > 0 && (
              <div style={{ marginTop: -8, marginBottom: 14 }}>
                {resultadosCliente.map((c) => (
                  <div
                    key={c.id}
                    style={{ padding: "8px 10px", cursor: "pointer", borderBottom: "1px solid #eef0f5" }}
                    onClick={() => {
                      setClienteSelecionado(c);
                      setBuscaCliente("");
                      setResultadosCliente([]);
                    }}
                  >
                    {c.nome} {c.email ? `— ${c.email}` : ""}
                  </div>
                ))}
              </div>
            )}
            {clienteSelecionado && (
              <p style={{ marginTop: -8, color: "var(--verde)", fontWeight: 600 }}>
                Cliente selecionado: {clienteSelecionado.nome}
              </p>
            )}

            <div className="ac-campo">
              <label>Recurso</label>
              <select
                className="ac-input"
                value={recursoId}
                onChange={(e) => setRecursoId(e.target.value ? Number(e.target.value) : "")}
              >
                <option value="">Selecione...</option>
                {recursos.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.nome}
                  </option>
                ))}
              </select>
            </div>

            <div className="ac-campo">
              <label>Dia da semana</label>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {DIAS_ORDEM_EXIBICAO.map((d) => (
                  <button
                    type="button"
                    key={d}
                    onClick={() => setDiaSemana(d)}
                    style={{
                      padding: "6px 12px",
                      borderRadius: 8,
                      border: `1.5px solid ${diaSemana === d ? "var(--azul)" : "#d7dbe6"}`,
                      background: diaSemana === d ? "var(--azul)" : "var(--branco)",
                      color: diaSemana === d ? "var(--branco)" : "var(--tinta)",
                      cursor: "pointer",
                      fontWeight: 600,
                      fontSize: "0.85rem",
                    }}
                  >
                    {DIAS_LABEL[d].slice(0, 3)}
                  </button>
                ))}
              </div>
            </div>

            <Campo
              label="Hora de início"
              type="time"
              value={horaInicio}
              onChange={(e) => setHoraInicio(e.target.value)}
              required
            />
            <Campo
              label="Valor mensal (R$)"
              value={valorReais}
              onChange={(e) => setValorReais(e.target.value)}
              placeholder="150,00"
              required
            />
            <div className="ac-campo">
              <label>Método de pagamento</label>
              <select className="ac-input" value={metodo} onChange={(e) => setMetodo(e.target.value)}>
                {METODOS.map((m) => (
                  <option key={m.valor} value={m.valor}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>

            <Botao type="submit" disabled={enviando}>
              {enviando ? "Salvando..." : "Criar mensalista"}
            </Botao>
          </form>
        </Card>
      )}

      {assinaturas === null && !erro && <p>Carregando...</p>}
      {assinaturas !== null && ordenados.length === 0 && <p>Nenhum mensalista cadastrado.</p>}

      {ordenados.length > 0 && (
        <Card>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Cliente</th>
                <th style={thStyle}>Recurso</th>
                <th style={thStyle}>Dia/Hora</th>
                <th style={thStyle}>Valor</th>
                <th style={thStyle}>Ações</th>
              </tr>
            </thead>
            <tbody>
              {ordenados.map((a) => (
                <tr
                  key={a.id}
                  style={a.status === "inadimplente" ? { background: "#fbe4e2" } : undefined}
                >
                  <td style={tdStyle}>
                    <Badge status={a.status} />
                  </td>
                  <td style={tdStyle}>{nomeDe(a.cliente)}</td>
                  <td style={tdStyle}>{nomeDe(a.recurso)}</td>
                  <td style={tdStyle}>
                    {DIAS_LABEL[diaBackendParaJs(a.dia_semana)] ?? a.dia_semana} — {a.hora_inicio}
                  </td>
                  <td style={tdStyle}>{a.valor_centavos != null ? centavos(a.valor_centavos) : "—"}</td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {a.status !== "pausada" && a.status !== "cancelada" && (
                        <BotaoSecundario
                          onClick={() => executarAcao(a.id, "pausar")}
                          disabled={acaoEmAndamento === a.id}
                        >
                          Pausar
                        </BotaoSecundario>
                      )}
                      {a.status === "pausada" && (
                        <BotaoSecundario
                          onClick={() => executarAcao(a.id, "reativar")}
                          disabled={acaoEmAndamento === a.id}
                        >
                          Reativar
                        </BotaoSecundario>
                      )}
                      {a.status !== "cancelada" && (
                        <BotaoSecundario
                          onClick={() => executarAcao(a.id, "cancelar")}
                          disabled={acaoEmAndamento === a.id}
                        >
                          Cancelar
                        </BotaoSecundario>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
