"use client";

// Agenda do dia: colunas = recursos (campos/quiosque), linhas = horários do
// dia. Célula colorida por status (verde confirmada/concluída, âmbar
// pendente, azul mensalista, cinza bloqueio, branco livre).
//
// Fonte de dados por decisão (T11): `api.disponibilidade` dá a grade de
// horários (inicio/fim/preco/livre) por recurso, mas não diferencia POR QUE
// um horário está ocupado (reserva confirmada x pendente x mensalista x
// bloqueio). Para colorir corretamente cruzamos três chamadas por recurso/dia:
//   - api.disponibilidade(recursoId, data)      -> grade de slots + livre
//   - api.reservasAdmin(`recurso_id=&de=&ate=`)  -> reservas do dia (status)
//   - api.bloqueios.listar(`recurso_id=&de=&ate=`) -> bloqueios do dia
// e casamos pelo horário de início (ISO). O contrato não documenta o formato
// exato de `de`/`ate` nesses dois endpoints; usamos a mesma data (YYYY-MM-DD)
// passada duas vezes, espelhando `?data=` de /disponibilidade. Se o backend
// esperar datetimes completos, ajustar aqui é um ponto único de mudança.
//
// "Mensalista" não tem status próprio documentado em ReservaStatus
// (pendente_pagamento/confirmada/concluida/cancelada/expirada) — assumimos
// que reservas geradas por assinatura vêm com `origem === "assinatura"`
// (campo `origem` já existe em `Reserva`, ver lib/api.ts) e pintamos essas de
// azul mesmo que o status seja "confirmada".

import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Recurso, type Reserva, type Slot } from "@/lib/api";
import { Botao, BotaoSecundario, Campo, Card, Titulo, Aviso, Badge } from "@/components/ui";
import { centavos, horaLocal, paraDataISO } from "@/lib/format";
import ModalBalcao from "./ModalBalcao";

type Bloqueio = { id: number; recurso_id: number; inicio: string; fim: string; motivo: string };

type CelulaTipo = "livre" | "pendente" | "confirmada" | "mensalista" | "bloqueio";

type Celula = {
  tipo: CelulaTipo;
  slot: Slot;
  reserva?: Reserva;
  bloqueio?: Bloqueio;
};

function mensagemErro(e: unknown, fallback: string): string {
  const err = e as { body?: { detail?: string } | null };
  return err?.body?.detail || fallback;
}

function corCelula(tipo: CelulaTipo): { bg: string; texto: string } {
  switch (tipo) {
    case "confirmada":
      return { bg: "#e0f5e9", texto: "var(--verde)" };
    case "pendente":
      return { bg: "#fff4d6", texto: "#92660b" };
    case "mensalista":
      return { bg: "#e3f0fd", texto: "var(--azul)" };
    case "bloqueio":
      return { bg: "#e7e9f0", texto: "var(--cinza)" };
    default:
      return { bg: "var(--branco)", texto: "var(--tinta)" };
  }
}

export default function AgendaAdmin() {
  const [data, setData] = useState(() => paraDataISO(new Date()));
  const [recursos, setRecursos] = useState<Recurso[]>([]);
  // grade[recursoId][horaInicioISO] = Celula
  const [grade, setGrade] = useState<Record<number, Record<string, Celula>>>({});
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [modalSlot, setModalSlot] = useState<{ recurso: Recurso; slot: Slot } | null>(null);
  const [detalhe, setDetalhe] = useState<Celula & { recurso: Recurso } | null>(null);

  const [mostrarBloqueio, setMostrarBloqueio] = useState(false);

  // Guarda contra corrida entre requisições: trocar `data` rapidamente (ex:
  // efeito do mount buscando o dia default ainda em voo quando o usuário já
  // mudou pra outro dia) pode fazer uma resposta velha resolver DEPOIS da
  // nova e sobrescrever `grade` com os slots do dia errado — o usuário vê a
  // grade do dia selecionado no campo "Dia", mas os `slot.inicio`/`fim`
  // embutidos nas células são de outro dia, e a reserva de balcão criada a
  // partir de um clique acaba salva com a data errada. Cada chamada de
  // `carregar()` recebe um id incremental; só a resposta da requisição MAIS
  // RECENTE tem permissão de aplicar `setGrade`/`setRecursos`.
  const requisicaoAtual = useRef(0);

  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  async function carregar() {
    const idRequisicao = ++requisicaoAtual.current;
    const dataRequisitada = data;
    setCarregando(true);
    setErro(null);
    try {
      const listaRecursos = await api.recursos();
      const ativos = listaRecursos.filter((r) => r.ativo);

      const novaGrade: Record<number, Record<string, Celula>> = {};

      await Promise.all(
        ativos.map(async (recurso) => {
          const [disponibilidade, reservasResp, bloqueios] = await Promise.all([
            api.disponibilidade(recurso.id, dataRequisitada),
            api.reservasAdmin(`recurso_id=${recurso.id}&de=${dataRequisitada}&ate=${dataRequisitada}`),
            api.bloqueios.listar(`recurso_id=${recurso.id}&de=${dataRequisitada}&ate=${dataRequisitada}`) as Promise<Bloqueio[]>,
          ]);
          const reservas = reservasResp.itens;

          const porInicio: Record<string, Celula> = {};
          for (const slot of disponibilidade.slots) {
            let tipo: CelulaTipo = slot.livre ? "livre" : "confirmada";
            let reservaMatch: Reserva | undefined;
            let bloqueioMatch: Bloqueio | undefined;

            const reserva = reservas.find(
              (r) => r.inicio === slot.inicio && r.status !== "cancelada" && r.status !== "expirada"
            );
            if (reserva) {
              reservaMatch = reserva;
              const origem = (reserva as Reserva & { origem?: string }).origem;
              if (origem === "assinatura") tipo = "mensalista";
              else if (reserva.status === "pendente_pagamento" || reserva.status === "pendente") tipo = "pendente";
              else tipo = "confirmada";
            } else {
              const bloqueio = bloqueios.find((b) => b.inicio === slot.inicio || (b.inicio <= slot.inicio && b.fim > slot.inicio));
              if (bloqueio) {
                bloqueioMatch = bloqueio;
                tipo = "bloqueio";
              } else if (slot.livre) {
                tipo = "livre";
              }
            }

            porInicio[slot.inicio] = { tipo, slot, reserva: reservaMatch, bloqueio: bloqueioMatch };
          }
          novaGrade[recurso.id] = porInicio;
        })
      );

      if (requisicaoAtual.current !== idRequisicao) return; // resposta velha — descarta
      setRecursos(ativos);
      setGrade(novaGrade);
    } catch (e) {
      if (requisicaoAtual.current !== idRequisicao) return;
      setErro(mensagemErro(e, "Não foi possível carregar a agenda do dia."));
    } finally {
      if (requisicaoAtual.current === idRequisicao) setCarregando(false);
    }
  }

  const horarios = useMemo(() => {
    const set = new Set<string>();
    Object.values(grade).forEach((porInicio) => {
      Object.keys(porInicio).forEach((inicio) => set.add(inicio));
    });
    return Array.from(set).sort();
  }, [grade]);

  function clicarCelula(recurso: Recurso, celula: Celula) {
    if (celula.tipo === "livre") {
      setModalSlot({ recurso, slot: celula.slot });
      return;
    }
    if (celula.reserva) {
      setDetalhe({ ...celula, recurso });
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
        <Titulo>Agenda</Titulo>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
          <Campo
            label="Dia"
            type="date"
            value={data}
            onChange={(e) => setData(e.target.value)}
            style={{ marginBottom: 0 }}
          />
          <BotaoSecundario type="button" onClick={() => setMostrarBloqueio(true)}>
            Bloquear
          </BotaoSecundario>
        </div>
      </div>

      {erro && <Aviso tipo="erro">{erro}</Aviso>}
      {carregando && <p>Carregando agenda...</p>}

      {!carregando && recursos.length === 0 && !erro && <p>Nenhum recurso ativo cadastrado.</p>}

      {!carregando && recursos.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 560 }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "8px 10px", borderBottom: "2px solid #d7dbe6" }}>Horário</th>
                {recursos.map((r) => (
                  <th key={r.id} style={{ textAlign: "left", padding: "8px 10px", borderBottom: "2px solid #d7dbe6" }}>
                    {r.nome}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {horarios.map((inicio) => (
                <tr key={inicio}>
                  <td style={{ padding: "6px 10px", fontWeight: 600, whiteSpace: "nowrap" }}>{horaLocal(inicio)}</td>
                  {recursos.map((r) => {
                    const celula = grade[r.id]?.[inicio];
                    if (!celula) {
                      return <td key={r.id} style={{ padding: 4 }} />;
                    }
                    const { bg, texto } = corCelula(celula.tipo);
                    return (
                      <td key={r.id} style={{ padding: 4 }}>
                        <button
                          type="button"
                          onClick={() => clicarCelula(r, celula)}
                          disabled={celula.tipo === "bloqueio"}
                          style={{
                            width: "100%",
                            textAlign: "left",
                            padding: "8px 10px",
                            borderRadius: 8,
                            border: "1.5px solid #d7dbe6",
                            background: bg,
                            color: texto,
                            cursor: celula.tipo === "bloqueio" ? "not-allowed" : "pointer",
                            fontFamily: "inherit",
                            fontWeight: 600,
                            fontSize: "0.85rem",
                          }}
                        >
                          {celula.tipo === "livre" && centavos(celula.slot.preco_centavos)}
                          {celula.tipo === "pendente" && "Pendente"}
                          {celula.tipo === "confirmada" && (celula.reserva?.recurso_nome ? "Confirmada" : "Confirmada")}
                          {celula.tipo === "mensalista" && "Mensalista"}
                          {celula.tipo === "bloqueio" && (celula.bloqueio?.motivo || "Bloqueado")}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>

          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 16, fontSize: "0.82rem" }}>
            <Legenda cor="#e0f5e9" texto="Confirmada" />
            <Legenda cor="#fff4d6" texto="Pendente" />
            <Legenda cor="#e3f0fd" texto="Mensalista" />
            <Legenda cor="#e7e9f0" texto="Bloqueio" />
            <Legenda cor="#ffffff" texto="Livre" borda />
          </div>
        </div>
      )}

      {modalSlot && (
        <ModalBalcao
          recursoId={modalSlot.recurso.id}
          recursoNome={modalSlot.recurso.nome}
          slot={modalSlot.slot}
          onFechar={() => setModalSlot(null)}
          onCriado={() => {
            setModalSlot(null);
            carregar();
          }}
        />
      )}

      {detalhe && (
        <PainelDetalhe
          celula={detalhe}
          onFechar={() => setDetalhe(null)}
          onCancelado={() => {
            setDetalhe(null);
            carregar();
          }}
        />
      )}

      {mostrarBloqueio && (
        <ModalBloqueio
          recursos={recursos}
          data={data}
          onFechar={() => setMostrarBloqueio(false)}
          onCriado={() => {
            setMostrarBloqueio(false);
            carregar();
          }}
        />
      )}
    </div>
  );
}

function Legenda({ cor, texto, borda }: { cor: string; texto: string; borda?: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span
        style={{
          width: 14,
          height: 14,
          borderRadius: 4,
          background: cor,
          border: borda ? "1.5px solid #d7dbe6" : "none",
          display: "inline-block",
        }}
      />
      {texto}
    </span>
  );
}

function PainelDetalhe({
  celula,
  onFechar,
  onCancelado,
}: {
  celula: Celula & { recurso: Recurso };
  onFechar: () => void;
  onCancelado: () => void;
}) {
  const [estornar, setEstornar] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [cancelando, setCancelando] = useState(false);
  const reserva = celula.reserva!;

  async function cancelar() {
    if (!window.confirm("Cancelar esta reserva?")) return;
    setCancelando(true);
    setErro(null);
    try {
      await api.cancelarAdmin(reserva.id, estornar);
      onCancelado();
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível cancelar a reserva."));
    } finally {
      setCancelando(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{ position: "fixed", inset: 0, background: "rgba(23,19,53,0.45)", display: "flex", justifyContent: "flex-end", zIndex: 50 }}
      onClick={onFechar}
    >
      <div onClick={(e) => e.stopPropagation()} style={{ width: "100%", maxWidth: 380, height: "100%", overflowY: "auto" }}>
        <Card style={{ height: "100%", borderRadius: 0 }}>
          <Titulo as="h2">Detalhes da reserva</Titulo>
          {erro && <Aviso tipo="erro">{erro}</Aviso>}
          <p>
            <Badge status={reserva.status} /> <strong>{celula.recurso.nome}</strong>
          </p>
          <p>
            {horaLocal(reserva.inicio)} às {horaLocal(reserva.fim)}
          </p>
          <p>Valor: {centavos(reserva.valor_centavos)}</p>
          <p>Origem: {(reserva as Reserva & { origem?: string }).origem || "-"}</p>

          {reserva.status !== "cancelada" && (
            <>
              <label style={{ display: "flex", gap: 8, alignItems: "center", margin: "16px 0" }}>
                <input type="checkbox" checked={estornar} onChange={(e) => setEstornar(e.target.checked)} />
                Estornar pagamento ao cancelar
              </label>
              <Botao type="button" onClick={cancelar} disabled={cancelando}>
                {cancelando ? "Cancelando..." : "Cancelar reserva"}
              </Botao>
            </>
          )}

          <div style={{ marginTop: 24 }}>
            <BotaoSecundario type="button" onClick={onFechar}>
              Fechar
            </BotaoSecundario>
          </div>
        </Card>
      </div>
    </div>
  );
}

function ModalBloqueio({
  recursos,
  data,
  onFechar,
  onCriado,
}: {
  recursos: Recurso[];
  data: string;
  onFechar: () => void;
  onCriado: () => void;
}) {
  const [recursoId, setRecursoId] = useState<number | "">(recursos[0]?.id ?? "");
  const [horaInicio, setHoraInicio] = useState("08:00");
  const [horaFim, setHoraFim] = useState("09:00");
  const [motivo, setMotivo] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [conflitos, setConflitos] = useState<string[] | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function confirmar() {
    setErro(null);
    setConflitos(null);
    if (!recursoId) {
      setErro("Selecione um recurso.");
      return;
    }
    if (!motivo.trim()) {
      setErro("Informe o motivo do bloqueio.");
      return;
    }
    setEnviando(true);
    try {
      await api.bloqueios.criar({
        recurso_id: recursoId,
        inicio: `${data}T${horaInicio}:00`,
        fim: `${data}T${horaFim}:00`,
        motivo: motivo.trim(),
      });
      onCriado();
    } catch (e: unknown) {
      const err = e as { status?: number; body?: { detail?: unknown; conflitos?: unknown } | null };
      if (err?.status === 409) {
        const corpo = err.body;
        const lista =
          (Array.isArray(corpo?.conflitos) && corpo?.conflitos) ||
          (Array.isArray(corpo?.detail) && corpo?.detail) ||
          null;
        if (lista) {
          setConflitos(
            lista.map((c) =>
              typeof c === "string" ? c : JSON.stringify(c)
            )
          );
        } else {
          setErro("Conflito: já existe reserva ou bloqueio nesse período.");
        }
      } else {
        setErro(mensagemErro(e, "Não foi possível criar o bloqueio."));
      }
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{ position: "fixed", inset: 0, background: "rgba(23,19,53,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50, padding: 16 }}
      onClick={onFechar}
    >
      <div onClick={(e) => e.stopPropagation()} style={{ width: "100%", maxWidth: 420 }}>
        <Card>
          <Titulo as="h2">Bloquear horário</Titulo>
          {erro && <Aviso tipo="erro">{erro}</Aviso>}
          {conflitos && (
            <Aviso tipo="erro">
              Conflito com:
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                {conflitos.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </Aviso>
          )}

          <div className="ac-campo">
            <label>Recurso</label>
            <select
              className="ac-input"
              value={recursoId}
              onChange={(e) => setRecursoId(Number(e.target.value))}
            >
              {recursos.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.nome}
                </option>
              ))}
            </select>
          </div>

          <div style={{ display: "flex", gap: 12 }}>
            <Campo label="Início" type="time" value={horaInicio} onChange={(e) => setHoraInicio(e.target.value)} />
            <Campo label="Fim" type="time" value={horaFim} onChange={(e) => setHoraFim(e.target.value)} />
          </div>
          <Campo label="Motivo" value={motivo} onChange={(e) => setMotivo(e.target.value)} required />

          <div style={{ display: "flex", gap: 12, justifyContent: "flex-end" }}>
            <BotaoSecundario type="button" onClick={onFechar} disabled={enviando}>
              Cancelar
            </BotaoSecundario>
            <Botao type="button" onClick={confirmar} disabled={enviando}>
              {enviando ? "Salvando..." : "Bloquear"}
            </Botao>
          </div>
        </Card>
      </div>
    </div>
  );
}
