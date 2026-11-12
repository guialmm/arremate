"use client";

import { useState } from "react";

import type { Citacao } from "@/lib/api";

// Straight to the API, not through the /api rewrite: an answer can take a minute on the
// free LLM tier, and the rewrite proxy gives up after ~30 s.
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8003";

type Turno = { papel: "usuario" | "assistente"; texto: string; citacoes?: Citacao[]; erro?: boolean };

const SUGESTOES = ["Precisa apresentar amostra?", "Qual o prazo de entrega?", "Como é feito o pagamento?", "Que garantia é exigida?"];

/** Free questions about this tender's editais, answered by the agent with checked quotes. */
export function Pergunte({ licitacaoId, abrir }: { licitacaoId: string; abrir: (c: Citacao) => void }) {
  const [turnos, setTurnos] = useState<Turno[]>([]);
  const [texto, setTexto] = useState("");
  const [pensando, setPensando] = useState(false);

  async function perguntar(pergunta: string) {
    if (!pergunta.trim() || pensando) return;
    const historico = turnos.filter((t) => !t.erro).map(({ papel, texto }) => ({ papel, texto }));
    setTurnos((t) => [...t, { papel: "usuario", texto: pergunta }]);
    setTexto("");
    setPensando(true);
    try {
      const r = await fetch(`${API}/api/licitacoes/${licitacaoId}/perguntar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pergunta, historico }),
      });
      const corpo = await r.json().catch(() => null);
      if (!r.ok) throw new Error(corpo?.detail ?? "Não deu para responder agora.");
      setTurnos((t) => [...t, { papel: "assistente", texto: corpo.resposta, citacoes: corpo.citacoes }]);
    } catch (e) {
      setTurnos((t) => [...t, { papel: "assistente", texto: e instanceof Error ? e.message : "Não deu para responder agora.", erro: true }]);
    } finally {
      setPensando(false);
    }
  }

  return (
    <div className="border border-linha bg-folha">
      <div className="max-h-[50vh] space-y-4 overflow-y-auto px-5 py-4">
        {!turnos.length && (
          <div className="flex flex-wrap gap-2">
            {SUGESTOES.map((s) => (
              <button key={s} onClick={() => perguntar(s)} className="border border-linha px-3 py-1.5 text-sm transition hover:border-tinta">
                {s}
              </button>
            ))}
          </div>
        )}
        {turnos.map((t, i) =>
          t.papel === "usuario" ? (
            <p key={i} className="text-sm text-apagado">
              {t.texto}
            </p>
          ) : (
            <div key={i} className="surgir">
              <p className={`whitespace-pre-line text-[15px] leading-relaxed ${t.erro ? "text-carimbo" : ""}`}>{t.texto}</p>
              {!!t.citacoes?.length && (
                <p className="mt-2 flex flex-wrap gap-x-3 text-sm">
                  {t.citacoes.map((c, j) => (
                    <button key={j} onClick={() => abrir(c)} className={`underline underline-offset-4 ${c.status === "nao_encontrada" ? "text-carimbo" : ""}`}>
                      p. {c.pagina_documento ?? c.pagina}
                      {c.status === "nao_encontrada" ? " (não conferida)" : ""}
                    </button>
                  ))}
                </p>
              )}
            </div>
          ),
        )}
        {pensando && <p className="text-sm text-apagado">Lendo o edital… pode levar até um minuto no plano gratuito da IA.</p>}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          perguntar(texto);
        }}
        className="flex border-t border-linha"
      >
        <input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          maxLength={500}
          placeholder="Pergunte sobre este edital"
          className="min-w-0 flex-1 bg-transparent px-5 py-3 outline-none"
        />
        <button disabled={pensando || texto.trim().length < 3} className="px-5 font-semibold disabled:opacity-40">
          Perguntar
        </button>
      </form>
    </div>
  );
}
