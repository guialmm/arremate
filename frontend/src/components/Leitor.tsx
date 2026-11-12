"use client";

import { useState } from "react";

import type { AnaliseOut, Citacao } from "@/lib/api";

import { Carimbo } from "./Carimbo";
import { Pagina } from "./Pagina";
import { Pergunte } from "./Pergunte";
import { Situacao } from "./Situacao";

const CATEGORIA: Record<string, string> = {
  habilitacao_juridica: "Jurídica",
  regularidade_fiscal_trabalhista: "Fiscal e trabalhista",
  qualificacao_economico_financeira: "Econômico-financeira",
  qualificacao_tecnica: "Técnica",
  outra: "Outra",
};
const GRAVIDADE = { alta: "Risco alto", media: "Risco médio", baixa: "Risco baixo" } as const;
const ME_EPP = { sim: "Exclusiva para ME/EPP", parcial: "Cota ou itens para ME/EPP", nao: "Ampla concorrência", nao_informado: "" } as const;

function Ref({ c, aberta, abrir }: { c: Citacao; aberta: Citacao | null; abrir: (c: Citacao) => void }) {
  const conferida = c.status !== "nao_encontrada";
  return (
    <button
      onClick={() => abrir(c)}
      title={conferida ? "Ver o trecho no edital" : "Trecho não encontrado no edital"}
      className={`shrink-0 text-sm underline underline-offset-4 ${aberta === c ? "font-semibold" : ""} ${conferida ? "" : "text-carimbo"}`}
    >
      p. {c.pagina_documento ?? c.pagina}
    </button>
  );
}

export function Leitor({ licitacaoId, analise }: { licitacaoId: string; analise: AnaliseOut | null }) {
  const [aberta, setAberta] = useState<Citacao | null>(null);
  const a = analise?.resultado;

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_440px]">
      <section className="min-w-0">
        {a && analise ? (
          <>
            <div className="relative border border-linha bg-folha px-7 py-6">
              <div className="absolute -top-5 right-6">
                <Carimbo recomendacao={a.recomendacao} />
              </div>
              <p className="text-sm font-semibold text-ok">
                ✓ {analise.citacoes_verificadas}/{analise.citacoes_total} citações conferidas no texto do edital
              </p>
              <p className="mt-3 leading-relaxed">{a.justificativa}</p>
              {!a.documentos_completos && (
                <p className="mt-3 text-sm text-carimbo">O órgão publicou só anexos: as regras de habilitação podem estar no edital que não veio.</p>
              )}
            </div>

            <p className="mt-6 leading-relaxed text-apagado">
              {a.resumo} {[ME_EPP[a.exclusiva_me_epp], a.criterio_julgamento].filter(Boolean).join(" · ")}
              {a.me_epp_citacao && (
                <>
                  {" "}
                  <Ref c={a.me_epp_citacao} aberta={aberta} abrir={setAberta} />
                </>
              )}
            </p>

            {!!a.prazos.length && (
              <>
                <h2 className="mt-10 border-b border-linha pb-2 font-serif text-2xl font-bold">Prazos</h2>
                <ul>
                  {a.prazos.map((p, i) => (
                    <li key={i} className="grid grid-cols-[1fr_auto] gap-4 border-b border-dotted border-linha py-3 sm:grid-cols-[220px_1fr_auto]">
                      <span className="font-medium">{p.evento}</span>
                      <span className="col-span-2 row-start-2 text-apagado sm:col-span-1 sm:row-start-auto">{p.quando}</span>
                      <Ref c={p.citacao} aberta={aberta} abrir={setAberta} />
                    </li>
                  ))}
                </ul>
              </>
            )}

            <h2 className="mt-10 border-b border-linha pb-2 font-serif text-2xl font-bold">Habilitação</h2>
            <ul>
              {a.requisitos.map((r, i) => (
                <li key={i} className="grid grid-cols-[90px_1fr_auto] items-start gap-4 border-b border-dotted border-linha py-3">
                  <span className="pt-0.5">
                    <Situacao situacao={r.situacao} />
                  </span>
                  <span>
                    {r.exigencia}
                    <span className="mt-0.5 block text-sm text-apagado">
                      {CATEGORIA[r.categoria] ?? r.categoria}
                      {r.documento_da_empresa ? ` · a empresa tem: ${r.documento_da_empresa}` : ""}
                    </span>
                  </span>
                  <Ref c={r.citacao} aberta={aberta} abrir={setAberta} />
                </li>
              ))}
            </ul>

            {!!a.condicoes.length && (
              <>
                <h2 className="mt-10 border-b border-linha pb-2 font-serif text-2xl font-bold">Condições</h2>
                <ul>
                  {a.condicoes.map((c, i) => (
                    <li key={i} className="grid grid-cols-[90px_1fr_auto] gap-4 border-b border-dotted border-linha py-3">
                      <span className="pt-0.5 text-xs font-semibold uppercase tracking-[0.08em] text-apagado">{c.tipo}</span>
                      <span>{c.descricao}</span>
                      <Ref c={c.citacao} aberta={aberta} abrir={setAberta} />
                    </li>
                  ))}
                </ul>
              </>
            )}

            {!!a.riscos.length && (
              <>
                <h2 className="mt-10 border-b border-linha pb-2 font-serif text-2xl font-bold">Riscos</h2>
                <ul className="mt-3 space-y-3">
                  {a.riscos.map((r, i) => (
                    <li
                      key={i}
                      className={`flex items-start justify-between gap-4 border-l-4 px-5 py-3 ${
                        r.gravidade === "alta" ? "border-carimbo bg-carimbo-suave text-[#5c1a14]" : "border-linha bg-folha"
                      }`}
                    >
                      <span>
                        <b className={`block text-xs uppercase tracking-[0.1em] ${r.gravidade === "alta" ? "text-carimbo" : "text-apagado"}`}>
                          {GRAVIDADE[r.gravidade]}
                        </b>
                        {r.descricao}
                      </span>
                      <Ref c={r.citacao} aberta={aberta} abrir={setAberta} />
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        ) : (
          <div className="border border-linha bg-folha px-7 py-6">
            <p className="font-serif text-xl font-bold">Edital ainda não analisado</p>
            <p className="mt-2 text-apagado">
              Esta licitação passou na triagem, mas a leitura completa do edital ainda não rodou. Dá para perguntar ao lado: o agente lê só as páginas que
              a pergunta precisa.
            </p>
          </div>
        )}
      </section>

      <aside className="space-y-8 lg:sticky lg:top-6 lg:self-start">
        <div>
          <h2 className="mb-3 border-b border-linha pb-2 font-serif text-2xl font-bold">No edital</h2>
          <Pagina citacao={aberta} />
        </div>
        <div>
          <h2 className="mb-3 border-b border-linha pb-2 font-serif text-2xl font-bold">Pergunte ao edital</h2>
          <Pergunte licitacaoId={licitacaoId} abrir={setAberta} />
        </div>
      </aside>
    </div>
  );
}
