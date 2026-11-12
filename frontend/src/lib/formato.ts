const fuso = { timeZone: "America/Sao_Paulo" } as const;

export const reais = (v: string | number | null) =>
  v == null ? "—" : new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(v));

export const dataHora = (iso: string | null) =>
  iso ? new Intl.DateTimeFormat("pt-BR", { ...fuso, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(iso)).replace(",", " às") : "—";

export const lugar = (municipio: string | null, uf: string | null) => [municipio, uf].filter(Boolean).join("/");

// PNCP objects come in every case and spacing; first letter up, extra spaces out.
export const objeto = (texto: string) => {
  const t = texto.replace(/\s+/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

// "MUNICIPIO DE PALHOCA" → "Municipio de Palhoca" (the PNCP drops the accents, we can't guess them).
const MINUSCULAS = new Set(["de", "da", "do", "das", "dos", "e"]);
export const nomeProprio = (texto: string) =>
  texto
    .toLowerCase()
    .split(/\s+/)
    .map((p, i) => (i > 0 && MINUSCULAS.has(p) ? p : p.charAt(0).toUpperCase() + p.slice(1)))
    .join(" ");

// "Edital: 8---EDITAL-DE-PREGAO-ELETRONICO-N_-021-2026.pdf" → "Edital: Edital de pregão…": file names as titles.
export const nomeDocumento = (texto: string) => {
  const [tipo, ...resto] = texto.split(": ");
  const titulo = resto.join(": ").replace(/\.(pdf|docx?|zip)$/i, "").replace(/[-_]+/g, " ").replace(/\s+/g, " ").trim();
  if (!titulo) return tipo;
  const limpo = /^[A-Z0-9 ]+$/.test(titulo) ? nomeProprio(titulo) : titulo;
  return `${tipo}: ${limpo.replace(/^\d+\s+/, "")}`;
};
