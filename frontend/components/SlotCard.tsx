"use client";

import type { Slot } from "@/lib/api";
import { centavos, horaLocal } from "@/lib/format";

/** Um horário da grade: livre mostra preço + é clicável; ocupado aparece riscado. */
export default function SlotCard({ slot, onClick }: { slot: Slot; onClick: () => void }) {
  if (!slot.livre) {
    return (
      <button className="ac-slot ac-slot-ocupado" disabled type="button">
        <span className="ac-slot-hora">
          {horaLocal(slot.inicio)}–{horaLocal(slot.fim)}
        </span>
        <span>Ocupado</span>
      </button>
    );
  }

  return (
    <button className="ac-slot" onClick={onClick} type="button">
      <span className="ac-slot-hora">
        {horaLocal(slot.inicio)}–{horaLocal(slot.fim)}
      </span>
      <span className="ac-slot-preco">{centavos(slot.preco_centavos)}</span>
    </button>
  );
}
