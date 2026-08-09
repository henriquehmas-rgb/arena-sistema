"use client";

import type { Slot } from "@/lib/api";
import SlotCard from "./SlotCard";

/** Renderiza a lista de slots de um dia/recurso. Sem slots -> mensagem vazia. */
export default function Grade({
  slots,
  onSelecionar,
}: {
  slots: Slot[];
  onSelecionar: (slot: Slot) => void;
}) {
  if (slots.length === 0) {
    return <p>Nenhum horário disponível para este dia.</p>;
  }

  return (
    <div className="ac-grade">
      {slots.map((slot) => (
        <SlotCard key={slot.inicio} slot={slot} onClick={() => onSelecionar(slot)} />
      ))}
    </div>
  );
}
