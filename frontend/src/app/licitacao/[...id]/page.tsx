import Link from "next/link";
import { notFound } from "next/navigation";

import { Leitor } from "@/components/Leitor";
import { analise, licitacao } from "@/lib/api";
import { dataHora, lugar, nomeProprio, objeto, reais } from "@/lib/formato";

export default async function PaginaLicitacao({ params }: PageProps<"/licitacao/[...id]">) {
  // numeroControlePNCP carries a slash ("…-000627/2026"): it arrives as two segments.
  const id = (await params).id.map(decodeURIComponent).join("/");
  const [lic, an] = await Promise.all([licitacao(id), analise(id)]);
  if (!lic) notFound();
  const lidos = lic.documentos.filter((d) => d.status === "ok");

  return (
    <div className="mx-auto max-w-7xl px-5 py-10 sm:px-10">
      <Link href="/" className="text-sm text-apagado hover:text-tinta">
        ← Todas as licitações
      </Link>
      <p className="mt-6 text-apagado">
        {nomeProprio(lic.orgao)} · {lugar(lic.municipio, lic.uf)} · {lic.modalidade}
      </p>
      <h1 className="mt-2 max-w-4xl font-serif text-3xl font-bold leading-tight sm:text-4xl">{objeto(lic.objeto)}</h1>
      <p className="mt-3 text-apagado">
        Valor estimado <b className="text-tinta">{reais(lic.valor_estimado)}</b> · encerra {dataHora(lic.encerramento_propostas)} · {lic.itens.length}{" "}
        {lic.itens.length === 1 ? "item" : "itens"} · {lidos.length} de {lic.documentos.length} documentos lidos
        {lic.link_origem && (
          <>
            {" · "}
            <a href={lic.link_origem} className="underline underline-offset-4" target="_blank" rel="noreferrer">
              página do órgão
            </a>
          </>
        )}
      </p>
      <div className="mt-10">
        <Leitor licitacaoId={id} analise={an} />
      </div>
    </div>
  );
}
