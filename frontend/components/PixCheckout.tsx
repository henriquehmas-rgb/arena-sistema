"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Botao, Aviso } from "@/components/ui";
import { mensagemErro } from "@/lib/auth";

/**
 * Fluxo PIX: chama api.checkout ao montar, mostra QR/copia-e-cola e faz
 * polling de api.pagamento a cada 3s até status "pago" (ou "falhou").
 */
export default function PixCheckout({
  reservaId,
  onPago,
}: {
  reservaId: number;
  onPago: () => void;
}) {
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [qrCode, setQrCode] = useState<string | undefined>();
  const [copiaCola, setCopiaCola] = useState<string | undefined>();
  const [copiado, setCopiado] = useState(false);
  const pagamentoIdRef = useRef<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelado = false;

    async function iniciar() {
      setCarregando(true);
      setErro(null);
      try {
        const r = await api.checkout({ reserva_id: reservaId, metodo: "pix" });
        if (cancelado) return;
        pagamentoIdRef.current = r.pagamento_id;
        setQrCode(r.pix_qr_code);
        setCopiaCola(r.pix_copia_cola);

        if (r.status === "pago") {
          onPago();
          return;
        }

        intervalRef.current = setInterval(async () => {
          if (pagamentoIdRef.current == null) return;
          try {
            const status = await api.pagamento(pagamentoIdRef.current);
            if (status.status === "pago") {
              if (intervalRef.current) clearInterval(intervalRef.current);
              onPago();
            } else if (status.status === "falhou") {
              if (intervalRef.current) clearInterval(intervalRef.current);
              setErro("O pagamento falhou. Tente novamente ou escolha outro método.");
            }
          } catch {
            // erro de rede pontual no polling — tenta de novo no próximo tick
          }
        }, 3000);
      } catch (e) {
        if (!cancelado) setErro(mensagemErro(e, "Não foi possível gerar o PIX."));
      } finally {
        if (!cancelado) setCarregando(false);
      }
    }

    iniciar();

    return () => {
      cancelado = true;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reservaId]);

  async function copiar() {
    if (!copiaCola) return;
    await navigator.clipboard.writeText(copiaCola);
    setCopiado(true);
    setTimeout(() => setCopiado(false), 2000);
  }

  if (carregando) return <p>Gerando o PIX...</p>;
  if (erro) return <Aviso tipo="erro">{erro}</Aviso>;

  return (
    <div>
      {qrCode && (
        <div style={{ textAlign: "center", marginBottom: 16 }}>
          {/* pix_qr_code normalmente vem como imagem base64 (data URL) do backend */}
          <img src={qrCode} alt="QR Code PIX" style={{ maxWidth: 220 }} />
        </div>
      )}
      {copiaCola && (
        <div className="ac-copiar-box">
          <input className="ac-input" readOnly value={copiaCola} />
          <Botao type="button" onClick={copiar}>
            {copiado ? "Copiado!" : "Copiar"}
          </Botao>
        </div>
      )}
      <p style={{ marginTop: 16, color: "var(--cinza)" }}>
        Aguardando confirmação do pagamento — isso atualiza automaticamente.
      </p>
    </div>
  );
}
