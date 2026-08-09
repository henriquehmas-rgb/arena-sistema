"use client";

// Lista de reservas com filtros (recurso, status, período) usando
// `api.reservasAdmin` (GET /reservas?recurso_id&de&ate&status, staff).
//
// Paginação: o backend retorna o envelope `{itens, total}` (ver
// `backend/app/schemas/reservas.py`, `ReservaListaOut`), mas não expõe
// `limit`/`offset` como parâmetros de página "amigáveis" ao filtro desta
// tela. Paginamos no cliente sobre `itens` (fatiar em páginas de 20) até o
// contrato definir parâmetros de página server-side — documentado aqui como
// limitação conhecida.

import { useEffect, useMemo, useState } from "react";
import { api, type Recurso, type Reserva } from "@/lib/api";
import { Badge, BotaoSecundario, Campo, Card, Titulo, Aviso, Botao } from "@/components/ui";
import { centavos, dataLocal, horaLocal, paraDataISO } from "@/lib/format";

// Achado de code review (T11): o `useEffect` inicial buscava sem nenhum
// filtro de data, então toda abertura da página trazia o histórico INTEIRO
// de reservas da arena antes de paginar no client-side. Agora o estado
// inicial dos filtros já vem com um intervalo padrão (últimos 30 dias até
// hoje) — o staff ainda pode limpar/ajustar os campos "De"/"Até" e clicar em
// "Filtrar" normalmente.
function intervaloPadrao(): { de: string; ate: string } {
  const hoje = new Date();
  const trintaDiasAtras = new Date(hoje);
  trintaDiasAtras.setDate(trintaDiasAtras.getDate() - 30);
  return { de: paraDataISO(trintaDiasAtras), ate: paraDataISO(hoje) };
}

const STATUS_OPCOES = [
  { valor: "", rotulo: "Todos" },
  { valor: "pendente_pagamento", rotulo: "Pendente" },
  { valor: "confirmada", rotulo: "Confirmada" },
  { valor: "concluida", rotulo: "Concluída" },
  { valor: "cancelada", rotulo: "Cancelada" },
  { valor: "expirada", rotulo: "Expirada" },
];

const PAGINA_TAMANHO = 20;

function mensagemErro(e: unknown, fallback: string): string {
  const err = e as { body?: { detail?: string } | null };
  return err?.body?.detail || fallback;
}

export default function AdminReservasPage() {
  const [recursos, setRecursos] = useState<Recurso[]>([]);
  const [recursoId, setRecursoId] = useState("");
  const [status, setStatus] = useState("");
  const [{ de: deInicial, ate: ateInicial }] = useState(intervaloPadrao);
  const [de, setDe] = useState(deInicial);
  const [ate, setAte] = useState(ateInicial);

  const [reservas, setReservas] = useState<Reserva[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [pagina, setPagina] = useState(1);
  const [erroPorReserva, setErroPorReserva] = useState<Record<number, string>>({});
  const [cancelando, setCancelando] = useState<number | null>(null);

  useEffect(() => {
    api.recursos().then(setRecursos).catch(() => {});
  }, []);

  useEffect(() => {
    buscar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function buscar() {
    setCarregando(true);
    setErro(null);
    setPagina(1);
    try {
      const partes: string[] = [];
      if (recursoId) partes.push(`recurso_id=${recursoId}`);
      if (status) partes.push(`status=${status}`);
      if (de) partes.push(`de=${de}`);
      if (ate) partes.push(`ate=${ate}`);
      const resp = await api.reservasAdmin(partes.join("&"));
      setReservas(resp.itens);
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível carregar as reservas."));
    } finally {
      setCarregando(false);
    }
  }

  async function cancelar(id: number) {
    if (!window.confirm("Cancelar esta reserva e estornar o pagamento?")) return;
    setCancelando(id);
    setErroPorReserva((prev) => {
      const { [id]: _omit, ...resto } = prev;
      return resto;
    });
    try {
      await api.cancelarAdmin(id, true);
      await buscar();
    } catch (e) {
      setErroPorReserva((prev) => ({ ...prev, [id]: mensagemErro(e, "Não foi possível cancelar.") }));
    } finally {
      setCancelando(null);
    }
  }

  const totalPaginas = Math.max(1, Math.ceil((reservas?.length ?? 0) / PAGINA_TAMANHO));
  const paginaAtual = useMemo(() => {
    if (!reservas) return [];
    const inicio = (pagina - 1) * PAGINA_TAMANHO;
    return reservas.slice(inicio, inicio + PAGINA_TAMANHO);
  }, [reservas, pagina]);

  return (
    <div>
      <Titulo>Reservas</Titulo>

      <Card style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="ac-campo" style={{ marginBottom: 0 }}>
            <label>Recurso</label>
            <select className="ac-input" value={recursoId} onChange={(e) => setRecursoId(e.target.value)}>
              <option value="">Todos</option>
              {recursos.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.nome}
                </option>
              ))}
            </select>
          </div>
          <div className="ac-campo" style={{ marginBottom: 0 }}>
            <label>Status</label>
            <select className="ac-input" value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUS_OPCOES.map((o) => (
                <option key={o.valor} value={o.valor}>
                  {o.rotulo}
                </option>
              ))}
            </select>
          </div>
          <Campo label="De" type="date" value={de} onChange={(e) => setDe(e.target.value)} />
          <Campo label="Até" type="date" value={ate} onChange={(e) => setAte(e.target.value)} />
          <Botao type="button" onClick={buscar} disabled={carregando}>
            {carregando ? "Buscando..." : "Filtrar"}
          </Botao>
        </div>
      </Card>

      {erro && <Aviso tipo="erro">{erro}</Aviso>}

      {!carregando && reservas && reservas.length === 0 && <p>Nenhuma reserva encontrada.</p>}

      {reservas && reservas.length > 0 && (
        <>
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", width: "100%" }}>
              <thead>
                <tr>
                  {["Recurso", "Data", "Horário", "Status", "Valor", "Origem", ""].map((h) => (
                    <th key={h} style={{ textAlign: "left", padding: "8px 10px", borderBottom: "2px solid #d7dbe6" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paginaAtual.map((r) => (
                  <tr key={r.id}>
                    <td style={{ padding: "8px 10px" }}>{r.recurso_nome}</td>
                    <td style={{ padding: "8px 10px" }}>{dataLocal(r.inicio)}</td>
                    <td style={{ padding: "8px 10px" }}>
                      {horaLocal(r.inicio)}–{horaLocal(r.fim)}
                    </td>
                    <td style={{ padding: "8px 10px" }}>
                      <Badge status={r.status} />
                    </td>
                    <td style={{ padding: "8px 10px" }}>{centavos(r.valor_centavos)}</td>
                    <td style={{ padding: "8px 10px" }}>{r.origem}</td>
                    <td style={{ padding: "8px 10px" }}>
                      {r.status !== "cancelada" && r.status !== "expirada" && (
                        <BotaoSecundario type="button" onClick={() => cancelar(r.id)} disabled={cancelando === r.id}>
                          {cancelando === r.id ? "..." : "Cancelar"}
                        </BotaoSecundario>
                      )}
                      {erroPorReserva[r.id] && <Aviso tipo="erro">{erroPorReserva[r.id]}</Aviso>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 16 }}>
            <BotaoSecundario type="button" disabled={pagina <= 1} onClick={() => setPagina((p) => p - 1)}>
              Anterior
            </BotaoSecundario>
            <span>
              Página {pagina} de {totalPaginas}
            </span>
            <BotaoSecundario type="button" disabled={pagina >= totalPaginas} onClick={() => setPagina((p) => p + 1)}>
              Próxima
            </BotaoSecundario>
          </div>
        </>
      )}
    </div>
  );
}
