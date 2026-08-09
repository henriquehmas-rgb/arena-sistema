"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type Reserva } from "@/lib/api";
import { estaAutenticado, mensagemErro } from "@/lib/auth";
import { Badge, BotaoSecundario, Card, Titulo, Aviso } from "@/components/ui";
import { centavos, dataLocal, horaLocal } from "@/lib/format";

const STATUS_FUTUROS = new Set(["pendente_pagamento", "confirmada"]);

export default function ContaPage() {
  const router = useRouter();
  const [reservas, setReservas] = useState<Reserva[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [erroPorReserva, setErroPorReserva] = useState<Record<number, string>>({});
  const [cancelando, setCancelando] = useState<number | null>(null);

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
      const lista = await api.minhasReservas();
      setReservas(lista);
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível carregar suas reservas."));
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
      <Titulo>Minha conta</Titulo>
      {erro && <Aviso tipo="erro">{erro}</Aviso>}

      <Titulo as="h2">Próximas reservas</Titulo>
      {proximas.length === 0 && <p>Você não tem reservas futuras.</p>}
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
