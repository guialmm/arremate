import type { Situacao as S } from "@/lib/api";

const ESTILO: Record<S, string> = { atende: "text-ok", verificar: "text-atencao", falta: "text-carimbo" };
const ROTULO: Record<S, string> = { atende: "Atende", verificar: "Verificar", falta: "Falta" };

export function Situacao({ situacao }: { situacao: S }) {
  return <span className={`text-xs font-semibold uppercase tracking-[0.08em] ${ESTILO[situacao]}`}>{ROTULO[situacao]}</span>;
}
