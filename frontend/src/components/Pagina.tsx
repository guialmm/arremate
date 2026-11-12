"use client";

import { useEffect, useRef, useState } from "react";

import type { Citacao } from "@/lib/api";
import { destacar } from "@/lib/destacar";
import { nomeDocumento } from "@/lib/formato";

type Carregada = { documento: string; numero: number; total_paginas: number | null; arquivo: string | null; pagina_no_arquivo: number; texto: string };

/** The edital page a citation points to, with the quote marked, so the reader checks it in context. */
export function Pagina({ citacao }: { citacao: Citacao | null }) {
  const [pagina, setPagina] = useState<Carregada | null>(null);
  const [erro, setErro] = useState(false);
  const marca = useRef<HTMLElement>(null);
  const chave = citacao?.documento_id ? `${citacao.documento_id}/${citacao.pagina_documento}` : null;

  useEffect(() => {
    if (!chave) return;
    let vivo = true;
    fetch(`/api/documentos/${chave.replace("/", "/paginas/")}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((p) => vivo && (setPagina(p), setErro(false)))
      .catch(() => vivo && setErro(true));
    return () => {
      vivo = false;
    };
  }, [chave]);

  useEffect(() => {
    // Braces matter: scrollIntoView now returns a promise, and an effect may only return a cleanup.
    marca.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [pagina]);

  if (!citacao) {
    return <p className="text-sm text-apagado">Clique em uma página citada para ver o trecho no edital.</p>;
  }
  if (!chave) {
    return <p className="text-sm text-carimbo">Esse trecho não foi encontrado no texto do edital: não confie nele sem conferir o documento.</p>;
  }
  if (erro) return <p className="text-sm text-carimbo">Não deu para abrir a página agora.</p>;
  if (!pagina || `${pagina.numero}` !== `${citacao.pagina_documento}`) return <p className="text-sm text-apagado">Abrindo a página…</p>;

  const pedacos = destacar(pagina.texto, citacao.trecho);
  const primeiro = pedacos.findIndex((p) => p.marcado);
  return (
    <div className="surgir">
      <p className="mb-3 text-xs uppercase tracking-[0.12em] text-apagado">
        {nomeDocumento(pagina.documento)} · pág. {pagina.arquivo ? `${pagina.pagina_no_arquivo} de ${pagina.arquivo}` : `${pagina.numero}${pagina.total_paginas ? ` de ${pagina.total_paginas}` : ""}`}
      </p>
      <div className="max-h-[60vh] overflow-y-auto whitespace-pre-line border border-linha bg-folha px-6 py-5 font-serif text-[15px] leading-7 shadow-[0_12px_30px_-18px_rgba(31,58,74,0.4)]">
        {pedacos.map((p, i) =>
          p.marcado ? (
            <mark key={i} ref={i === primeiro ? marca : undefined}>
              {p.texto}
            </mark>
          ) : (
            <span key={i}>{p.texto}</span>
          ),
        )}
      </div>
    </div>
  );
}
