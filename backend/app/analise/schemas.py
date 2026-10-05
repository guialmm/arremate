"""What the model must return for an edital. Every claim carries a citation."""

from typing import Literal

from pydantic import BaseModel, Field


class Citacao(BaseModel):
    pagina: int = Field(description="Número da página, exatamente como marcado em [p. N]")
    trecho: str = Field(
        description="Cópia literal, sem resumir nem corrigir, de uma a três frases do edital "
        "que comprovam a afirmação"
    )


class Requisito(BaseModel):
    categoria: Literal[
        "habilitacao_juridica",
        "regularidade_fiscal_trabalhista",
        "qualificacao_economico_financeira",
        "qualificacao_tecnica",
        "outra",
    ]
    exigencia: str = Field(description="O documento ou condição exigida, em uma frase")
    situacao: Literal["atende", "falta", "verificar"] = Field(
        description="atende: algum documento da empresa cobre; falta: nenhum cobre; "
        "verificar: depende de detalhe que a lista da empresa não esclarece"
    )
    documento_da_empresa: str | None = Field(
        description="Nome do documento da lista da empresa que atende, ou null"
    )
    citacao: Citacao


class Prazo(BaseModel):
    evento: str = Field(description="Ex.: abertura da sessão, envio da proposta, impugnação")
    quando: str = Field(description="Data/hora ou prazo, como está no edital")
    citacao: Citacao


class Condicao(BaseModel):
    tipo: Literal["entrega", "amostra", "garantia", "pagamento", "vigencia", "outra"]
    descricao: str
    citacao: Citacao


class Risco(BaseModel):
    descricao: str = Field(description="O que pode desclassificar, multar ou dar prejuízo")
    gravidade: Literal["baixa", "media", "alta"]
    citacao: Citacao


class Analise(BaseModel):
    resumo: str = Field(description="Duas ou três frases: o que se compra, para quem, como disputa")
    exclusiva_me_epp: Literal["sim", "nao", "parcial", "nao_informado"] = Field(
        description="sim: toda a licitação é exclusiva para ME/EPP; parcial: só alguns "
        "itens/lotes ou cota reservada"
    )
    me_epp_citacao: Citacao | None
    criterio_julgamento: str = Field(description="Ex.: menor preço por item, por lote, global")
    prazos: list[Prazo]
    requisitos: list[Requisito]
    condicoes: list[Condicao]
    riscos: list[Risco]
    recomendacao: Literal["participar", "avaliar", "nao_participar"]
    justificativa: str = Field(description="Por que a recomendação, citando o que falta se houver")
