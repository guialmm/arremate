import Link from "next/link";

import { Carimbo } from "@/components/Carimbo";
import { caminho, perfil, triadas } from "@/lib/api";
import { dataHora, lugar, nomeProprio, objeto, reais } from "@/lib/formato";

export default async function Inicio() {
  const [empresa, lista] = await Promise.all([perfil(), triadas()]);
  const analisadas = (lista ?? []).filter((t) => t.recomendacao).length;

  return (
    <div className="mx-auto max-w-7xl px-5 py-10 sm:px-10">
      <p className="text-sm uppercase tracking-[0.14em] text-apagado">Licitações para</p>
      <h1 className="mt-1 font-serif text-4xl font-bold leading-tight sm:text-5xl">{empresa?.nome ?? "Empresa de exemplo"}</h1>
      <p className="mt-3 max-w-3xl text-apagado">
        {empresa?.descricao} Pregões de {empresa?.ufs.join(", ")} que passaram na triagem: {lista?.length ?? 0} relevantes, {analisadas} com o
        edital lido e analisado.
      </p>

      <ul className="mt-10 border-t border-linha">
        {(lista ?? []).map((t) => (
          <li key={t.licitacao.id} className="border-b border-linha">
            <Link href={caminho(t.licitacao.id)} className="grid gap-x-8 gap-y-2 py-5 transition hover:bg-folha sm:grid-cols-[1fr_auto] sm:px-3">
              <div className="min-w-0">
                <p className="text-sm text-apagado">
                  {nomeProprio(t.licitacao.orgao)} · {lugar(t.licitacao.municipio, t.licitacao.uf)}
                </p>
                <p className="mt-1 line-clamp-2 font-serif text-xl font-bold leading-snug">{objeto(t.licitacao.objeto)}</p>
                <p className="mt-2 text-sm text-apagado">
                  {reais(t.licitacao.valor_estimado)} · encerra {dataHora(t.licitacao.encerramento_propostas)} · nota {t.nota} na triagem
                </p>
              </div>
              <div className="flex items-center gap-4 sm:flex-col sm:items-end sm:justify-center">
                {t.recomendacao ? (
                  <>
                    <Carimbo recomendacao={t.recomendacao} pequeno />
                    <span className="text-xs font-semibold text-ok">
                      ✓ {t.citacoes_verificadas}/{t.citacoes_total} citações conferidas
                    </span>
                  </>
                ) : (
                  <span className="text-xs uppercase tracking-[0.1em] text-apagado">Edital ainda não analisado</span>
                )}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
