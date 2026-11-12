import type { Recomendacao } from "@/lib/api";

const ROTULO: Record<Recomendacao, string> = { participar: "Participar", avaliar: "Avaliar", nao_participar: "Não participar" };
// Petrol ink for a go, the red stamp only when the answer is no.
const COR: Record<Recomendacao, string> = {
  participar: "border-ok text-ok",
  avaliar: "border-tinta text-tinta",
  nao_participar: "border-carimbo text-carimbo",
};

/** The recommendation, stamped on the analysis like on a paper file. */
export function Carimbo({ recomendacao, pequeno = false }: { recomendacao: Recomendacao; pequeno?: boolean }) {
  return (
    <span
      className={`inline-block -rotate-6 border-[3px] bg-folha font-serif font-bold uppercase tracking-[0.12em] ${COR[recomendacao]} ${
        pequeno ? "px-2 py-0.5 text-xs" : "px-4 py-1 text-2xl"
      }`}
    >
      {ROTULO[recomendacao]}
    </span>
  );
}
