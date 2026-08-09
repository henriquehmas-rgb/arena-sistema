"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type Recurso, type Slot } from "@/lib/api";
import { estaAutenticado, mensagemErro } from "@/lib/auth";
import { Titulo, Aviso } from "@/components/ui";
import Grade from "@/components/Grade";
import { diaCurto, paraDataISO } from "@/lib/format";

function proximosDias(qtd: number): Date[] {
  const hoje = new Date();
  return Array.from({ length: qtd }, (_, i) => {
    const d = new Date(hoje);
    d.setDate(hoje.getDate() + i);
    return d;
  });
}

export default function Home() {
  const router = useRouter();
  const [recursos, setRecursos] = useState<Recurso[]>([]);
  const [recursoId, setRecursoId] = useState<number | null>(null);
  const dias = useMemo(() => proximosDias(7), []);
  const [diaSelecionado, setDiaSelecionado] = useState<string>(() => paraDataISO(new Date()));
  const [slots, setSlots] = useState<Slot[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  useEffect(() => {
    api
      .recursos()
      .then((lista) => {
        setRecursos(lista);
        const ativo = lista.find((r) => r.ativo) ?? lista[0];
        if (ativo) setRecursoId(ativo.id);
      })
      .catch((e) => setErro(mensagemErro(e, "Não foi possível carregar os recursos.")));
  }, []);

  async function buscarDisponibilidade() {
    if (recursoId == null) return;
    setCarregando(true);
    setErro(null);
    try {
      const { slots: s } = await api.disponibilidade(recursoId, diaSelecionado);
      setSlots(s);
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível carregar a disponibilidade."));
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => {
    buscarDisponibilidade();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recursoId, diaSelecionado]);

  async function selecionarSlot(slot: Slot) {
    if (recursoId == null) return;
    setAviso(null);

    if (!estaAutenticado()) {
      const volta = `/?recurso=${recursoId}&data=${diaSelecionado}`;
      router.push(`/entrar?volta=${encodeURIComponent(volta)}`);
      return;
    }

    try {
      const reserva = await api.criarReserva({ recurso_id: recursoId, inicio: slot.inicio, fim: slot.fim });
      router.push(`/checkout/${reserva.id}`);
    } catch (e: unknown) {
      const err = e as { status?: number };
      if (err?.status === 409) {
        setAviso("Esse horário acabou de sair — escolhe outro.");
        buscarDisponibilidade();
      } else {
        setErro(mensagemErro(e, "Não foi possível reservar. Tente novamente."));
      }
    }
  }

  return (
    <>
      <Titulo>Reserve seu horário</Titulo>

      {erro && <Aviso tipo="erro">{erro}</Aviso>}
      {aviso && <Aviso tipo="erro">{aviso}</Aviso>}

      <div className="ac-tabs">
        {recursos.map((r) => (
          <button
            key={r.id}
            className={`ac-tab ${r.id === recursoId ? "ativo" : ""}`}
            onClick={() => setRecursoId(r.id)}
            type="button"
          >
            {r.nome}
          </button>
        ))}
      </div>

      <div className="ac-dias">
        {dias.map((d) => {
          const iso = paraDataISO(d);
          return (
            <button
              key={iso}
              className={`ac-dia ${iso === diaSelecionado ? "ativo" : ""}`}
              onClick={() => setDiaSelecionado(iso)}
              type="button"
            >
              {diaCurto(d.toISOString())}
            </button>
          );
        })}
      </div>

      {carregando ? <p>Carregando horários...</p> : <Grade slots={slots} onSelecionar={selecionarSlot} />}
    </>
  );
}
