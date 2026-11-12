// What the FastAPI backend returns (see backend/app/api/schemas.py).

export type Citacao = {
  pagina: number;
  trecho: string;
  status: "verificada" | "corrigida" | "aproximada" | "nao_encontrada";
  documento_id?: number;
  documento?: string;
  pagina_documento?: number;
  arquivo?: string | null;
  pagina_no_arquivo?: number;
};

export type Situacao = "atende" | "falta" | "verificar";
export type Recomendacao = "participar" | "avaliar" | "nao_participar";

export type Analise = {
  documentos_completos: boolean;
  resumo: string;
  exclusiva_me_epp: "sim" | "nao" | "parcial" | "nao_informado";
  me_epp_citacao: Citacao | null;
  criterio_julgamento: string;
  prazos: { evento: string; quando: string; citacao: Citacao }[];
  requisitos: { categoria: string; exigencia: string; situacao: Situacao; documento_da_empresa: string | null; citacao: Citacao }[];
  condicoes: { tipo: string; descricao: string; citacao: Citacao }[];
  riscos: { descricao: string; gravidade: "baixa" | "media" | "alta"; citacao: Citacao }[];
  recomendacao: Recomendacao;
  justificativa: string;
};

export type Licitacao = {
  id: string;
  orgao: string;
  municipio: string | null;
  uf: string | null;
  modalidade: string;
  objeto: string;
  valor_estimado: string | null;
  publicada_em: string;
  encerramento_propostas: string | null;
  link_origem: string | null;
};

export type Triada = {
  licitacao: Licitacao;
  nota: number;
  relevante: boolean;
  motivo: string;
  recomendacao: Recomendacao | null;
  citacoes_total: number | null;
  citacoes_verificadas: number | null;
};

export type Detalhe = Licitacao & {
  unidade: string | null;
  informacao_complementar: string | null;
  srp: boolean;
  situacao: string;
  abertura_propostas: string | null;
  itens: { numero: number; descricao: string; quantidade: string | null; unidade: string | null; valor_total: string | null; beneficio: string | null }[];
  documentos: { id: number; titulo: string; tipo: string | null; url: string; status: string; total_paginas: number | null }[];
};

export type AnaliseOut = {
  resultado: Analise;
  recomendacao: Recomendacao;
  modelo: string;
  paginas_lidas: number;
  citacoes_total: number;
  citacoes_verificadas: number;
  created_at: string;
};

export type Perfil = { id: number; nome: string; descricao: string; ufs: string[]; documentos: string[] };

// The demo has one profile; a multi-company version would put it in the URL or session.
export const PERFIL_ID = 1;
const API = process.env.API_URL ?? "http://localhost:8003";

async function pegar<T>(caminho: string): Promise<T | null> {
  const r = await fetch(`${API}${caminho}`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`API ${r.status} em ${caminho}`);
  return r.json();
}

export const perfil = async () => (await pegar<Perfil[]>("/api/perfis"))?.find((p) => p.id === PERFIL_ID) ?? null;
export const triadas = () => pegar<Triada[]>(`/api/perfis/${PERFIL_ID}/licitacoes`);
export const licitacao = (id: string) => pegar<Detalhe>(`/api/licitacoes/${id}`);
export const analise = (id: string) => pegar<AnaliseOut>(`/api/licitacoes/${id}/analise?perfil_id=${PERFIL_ID}`);

// numeroControlePNCP "83021808000182-1-000627/2026" ↔ path /licitacao/83021808000182-1-000627/2026
export const caminho = (id: string) => `/licitacao/${id}`;
