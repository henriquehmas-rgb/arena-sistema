"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, type Reserva } from "@/lib/api";
import { estaAutenticado, mensagemErro } from "@/lib/auth";
import { Botao, BotaoSecundario, Card, Titulo, Aviso, Badge } from "@/components/ui";
import { centavos, contagem, dataLocal, horaLocal } from "@/lib/format";
import PixCheckout from "@/components/PixCheckout";
import CartaoCheckout from "@/components/CartaoCheckout";

type Metodo = "pix" | "cartao";

export default function CheckoutPage({ params }: { params: { reservaId: string } }) {
  const router = useRouter();
  const reservaId = Number(params.reservaId);

  const [reserva, setReserva] = useState<Reserva | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [metodo, setMetodo] = useState<Metodo>("pix");
  const [segundosRestantes, setSegundosRestantes] = useState<number | null>(null);
  const [pago, setPago] = useState(false);

  useEffect(() => {
    if (!estaAutenticado()) {
      router.push(`/entrar?volta=${encodeURIComponent(`/checkout/${reservaId}`)}`);
      return;
    }

    api
      .minhasReservas()
      .then((lista) => {
        const r = lista.find((x) => x.id === reservaId);
        if (!r) {
          setErro("Reserva não encontrada.");
        } else {
          setReserva(r);
        }
      })
      .catch((e) => setErro(mensagemErro(e, "Não foi possível carregar a reserva.")))
      .finally(() => setCarregando(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reservaId]);

  useEffect(() => {
    if (!reserva?.expira_em) return;
    const expiraEm = new Date(reserva.expira_em).getTime();

    function tick() {
      setSegundosRestantes(Math.max(0, Math.floor((expiraEm - Date.now()) / 1000)));
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [reserva?.expira_em]);

  if (carregando) return <p>Carregando...</p>;

  if (erro) {
    return (
      <Card style={{ maxWidth: 480, margin: "0 auto" }}>
        <Aviso tipo="erro">{erro}</Aviso>
        <Link href="/">Voltar para a grade</Link>
      </Card>
    );
  }

  if (!reserva) return null;

  if (pago) {
    return (
      <Card style={{ maxWidth: 480, margin: "0 auto" }}>
        <Titulo as="h2">Pagamento confirmado!</Titulo>
        <Aviso tipo="sucesso">Sua reserva está garantida.</Aviso>
        <p>
          <strong>{reserva.recurso_nome}</strong>
        </p>
        <p>
          {dataLocal(reserva.inicio)} — {horaLocal(reserva.inicio)} às {horaLocal(reserva.fim)}
        </p>
        <p>Valor: {centavos(reserva.valor_centavos)}</p>
        <Link href="/conta">Ver minhas reservas</Link>
      </Card>
    );
  }

  const expirou = reserva.status !== "pendente_pagamento" || segundosRestantes === 0;

  if (expirou) {
    return (
      <Card style={{ maxWidth: 480, margin: "0 auto" }}>
        <Titulo as="h2">Reserva expirada</Titulo>
        <Aviso tipo="erro">
          O tempo para concluir o pagamento acabou e o horário foi liberado. Escolha outro horário para
          continuar.
        </Aviso>
        <Link href="/">Voltar para a grade</Link>
      </Card>
    );
  }

  return (
    <Card style={{ maxWidth: 480, margin: "0 auto" }}>
      <Titulo as="h2">Finalizar reserva</Titulo>
      <p>
        <Badge status={reserva.status} /> <strong>{reserva.recurso_nome}</strong>
      </p>
      <p>
        {dataLocal(reserva.inicio)} — {horaLocal(reserva.inicio)} às {horaLocal(reserva.fim)}
      </p>
      <p>Valor: {centavos(reserva.valor_centavos)}</p>

      {segundosRestantes != null && (
        <div className="ac-contador">Expira em {contagem(segundosRestantes)}</div>
      )}

      <div className="ac-metodos">
        <Botao
          type="button"
          onClick={() => setMetodo("pix")}
          style={metodo === "pix" ? {} : { opacity: 0.55 }}
        >
          PIX
        </Botao>
        <BotaoSecundario
          type="button"
          onClick={() => setMetodo("cartao")}
          style={metodo === "cartao" ? { background: "rgba(11,99,216,0.08)" } : {}}
        >
          Cartão
        </BotaoSecundario>
      </div>

      {metodo === "pix" ? (
        <PixCheckout reservaId={reserva.id} onPago={() => setPago(true)} />
      ) : (
        <CartaoCheckout reservaId={reserva.id} onPago={() => setPago(true)} />
      )}
    </Card>
  );
}
