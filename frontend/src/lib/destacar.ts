// Finds a quote inside a page so it can be marked. The model's quotes are literal but
// may skip parts with "..." and differ in line breaks or hyphenation: each fragment
// is matched on its words, with any whitespace (or a line-break hyphen) between them.
export type Pedaco = { texto: string; marcado: boolean };

const escapar = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function destacar(pagina: string, trecho: string): Pedaco[] {
  const fragmentos = trecho
    .split(/\.{3,}|…/)
    .map((f) => f.trim().replace(/^[\s.;,:"']+|[\s.;,:"']+$/g, ""))
    .filter((f) => f.length >= 12);
  const faixas: [number, number][] = [];
  for (const f of fragmentos) {
    const padrao = new RegExp(f.split(/\s+/).map(escapar).join("[\\s-]+"), "i");
    const m = padrao.exec(pagina);
    if (m) faixas.push([m.index, m.index + m[0].length]);
  }
  faixas.sort((a, b) => a[0] - b[0]);
  const pedacos: Pedaco[] = [];
  let pos = 0;
  for (const [ini, fim] of faixas) {
    if (ini < pos) continue;
    if (ini > pos) pedacos.push({ texto: pagina.slice(pos, ini), marcado: false });
    pedacos.push({ texto: pagina.slice(ini, fim), marcado: true });
    pos = fim;
  }
  if (pos < pagina.length) pedacos.push({ texto: pagina.slice(pos), marcado: false });
  return pedacos;
}
