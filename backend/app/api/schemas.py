"""What the API returns. Read-only views over what ingestion, triage and analysis stored."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class Modelo(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PerfilOut(Modelo):
    id: int
    nome: str
    descricao: str
    palavras_chave: list[str]
    ufs: list[str]
    valor_minimo: Decimal | None
    valor_maximo: Decimal | None
    documentos: list[str]


class LicitacaoResumo(Modelo):
    id: str
    orgao: str
    municipio: str | None
    uf: str | None
    modalidade: str
    objeto: str
    valor_estimado: Decimal | None
    publicada_em: datetime
    encerramento_propostas: datetime | None
    link_origem: str | None


class Triada(BaseModel):
    """One tender as a profile sees it: triage verdict plus the analysis, if any."""

    licitacao: LicitacaoResumo
    nota: int
    relevante: bool
    motivo: str
    recomendacao: str | None  # set once the edital was analyzed
    citacoes_total: int | None
    citacoes_verificadas: int | None


class ItemOut(Modelo):
    numero: int
    descricao: str
    material_ou_servico: str | None
    quantidade: Decimal | None
    unidade: str | None
    valor_unitario: Decimal | None
    valor_total: Decimal | None
    beneficio: str | None
    criterio_julgamento: str | None


class DocumentoOut(Modelo):
    id: int
    sequencial: int
    titulo: str
    tipo: str | None
    url: str
    status: str
    formato: str | None
    total_paginas: int | None


class LicitacaoDetalhe(LicitacaoResumo):
    unidade: str | None
    informacao_complementar: str | None
    srp: bool
    situacao: str
    abertura_propostas: datetime | None
    itens: list[ItemOut]
    documentos: list[DocumentoOut]


class AnaliseOut(Modelo):
    licitacao_id: str
    perfil_id: int
    resultado: dict
    recomendacao: str
    modelo: str
    paginas_lidas: int
    citacoes_total: int
    citacoes_verificadas: int
    segundos: float
    created_at: datetime


class PaginaOut(Modelo):
    documento_id: int
    documento: str
    numero: int
    total_paginas: int | None
    arquivo: str | None
    pagina_no_arquivo: int
    texto: str
