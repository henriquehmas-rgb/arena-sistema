"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Botao, Campo, Aviso } from "@/components/ui";
import { mensagemErro } from "@/lib/auth";

declare global {
  interface Window {
    // Disponível em produção via tokenizecard.js da Pagar.me. Recebe os dados
    // do cartão e devolve (ou resolve, se async) o token pronto para envio.
    PagarmeTokenize?: (dados: {
      numero: string;
      validade: string;
      cvv: string;
    }) => string | Promise<string>;
  }
}

/**
 * Fluxo Cartão: coleta número/validade/cvv, tokeniza e envia via api.checkout.
 * Tokenização: em PAGARME_MODE=simulado não há chave real, então usamos o
 * token fixo "tok_simulado" documentado no brief. Se `window.PagarmeTokenize`
 * existir (script tokenizecard.js da Pagar.me carregado em produção), ele é
 * usado no lugar do valor fixo.
 */
export default function CartaoCheckout({
  reservaId,
  onPago,
}: {
  reservaId: number;
  onPago: () => void;
}) {
  const [numero, setNumero] = useState("");
  const [validade, setValidade] = useState("");
  const [cvv, setCvv] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [aguardandoConfirmacao, setAguardandoConfirmacao] = useState(false);
  const pagamentoIdRef = useRef<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  async function obterToken(): Promise<string> {
    if (typeof window !== "undefined" && window.PagarmeTokenize) {
      return window.PagarmeTokenize({ numero, validade, cvv });
    }
    return "tok_simulado";
  }

  function iniciarPolling() {
    intervalRef.current = setInterval(async () => {
      if (pagamentoIdRef.current == null) return;
      try {
        const status = await api.pagamento(pagamentoIdRef.current);
        if (status.status === "pago") {
          if (intervalRef.current) clearInterval(intervalRef.current);
          onPago();
        } else if (status.status === "falhou") {
          if (intervalRef.current) clearInterval(intervalRef.current);
          setAguardandoConfirmacao(false);
          setErro("O pagamento foi recusado. Verifique os dados do cartão ou tente outro método.");
        }
      } catch {
        // erro pontual no polling — tenta de novo no próximo tick
      }
    }, 3000);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    if (numero.replace(/\D/g, "").length < 13 || !validade || cvv.length < 3) {
      setErro("Confira os dados do cartão.");
      return;
    }
    setEnviando(true);
    try {
      const card_token = await obterToken();
      const r = await api.checkout({ reserva_id: reservaId, metodo: "cartao", card_token });
      pagamentoIdRef.current = r.pagamento_id;
      if (r.status === "pago") {
        onPago();
        return;
      }
      if (r.status === "falhou") {
        setErro("O pagamento foi recusado. Verifique os dados do cartão ou tente outro método.");
        return;
      }
      setAguardandoConfirmacao(true);
      iniciarPolling();
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível processar o pagamento."));
    } finally {
      setEnviando(false);
    }
  }

  if (aguardandoConfirmacao) {
    return <p>Confirmando pagamento...</p>;
  }

  return (
    <form onSubmit={onSubmit}>
      {erro && <Aviso tipo="erro">{erro}</Aviso>}
      <Campo
        label="Número do cartão"
        inputMode="numeric"
        placeholder="0000 0000 0000 0000"
        value={numero}
        onChange={(e) => setNumero(e.target.value)}
        required
      />
      <div style={{ display: "flex", gap: 12 }}>
        <Campo
          label="Validade (MM/AA)"
          placeholder="12/28"
          value={validade}
          onChange={(e) => setValidade(e.target.value)}
          required
        />
        <Campo
          label="CVV"
          inputMode="numeric"
          placeholder="123"
          value={cvv}
          onChange={(e) => setCvv(e.target.value)}
          required
        />
      </div>
      <Botao type="submit" disabled={enviando}>
        {enviando ? "Processando..." : "Pagar"}
      </Botao>
    </form>
  );
}
