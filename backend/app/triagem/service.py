"""Two-stage triage of the day's tenders for a company profile.

1. Postgres narrows ~1.500 tenders/day to a few dozen: Portuguese full-text
   search over the object, plus state, value range and an open deadline. Free.
2. The LLM scores the survivors in batches (one call reads ~20 summaries),
   which keeps the free tier's requests-per-minute budget for the editais.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import Select, and_, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import LLM, LLMErro
from app.models import Licitacao, Perfil, Triagem

log = logging.getLogger(__name__)

LOTE = 20
NOTA_RELEVANTE = 60
MAX_OBJETO = 700  # some objects paste the whole item list; the gist comes first

PORTUGUES = literal_column("'portuguese'::regconfig")


class Avaliacao(BaseModel):
    n: int = Field(description="Número da licitação na lista")
    nota: int = Field(ge=0, le=100, description="Aderência ao perfil, de 0 a 100")
    motivo: str = Field(description="Uma frase curta citando o que casa ou não casa com o perfil")


class AvaliacaoLote(BaseModel):
    avaliacoes: list[Avaliacao]


SISTEMA = f"""Você faz a triagem de licitações públicas brasileiras para uma empresa fornecedora.
Para cada licitação da lista, dê uma nota de aderência ao perfil da empresa:

- 80 a 100: o objeto principal é exatamente o que a empresa vende.
- {NOTA_RELEVANTE} a 79: uma parte relevante dos itens ou um lote inteiro está no ramo da empresa.
- 30 a 59: só itens marginais estão no ramo, ou o objeto é ambíguo.
- 0 a 29: fora do ramo (inclusive serviços quando a empresa só vende produtos, e vice-versa).

Julgue pelo que será comprado, não por palavras soltas: "manutenção de impressoras" não é
venda de papel, e "material de expediente" costuma ser material de escritório.
Avalie todas as licitações da lista, uma vez cada, usando o número dado."""


@dataclass
class ResultadoTriagem:
    candidatas: int = 0
    avaliadas: int = 0
    relevantes: int = 0
    lotes_com_erro: int = 0
    modelos: set[str] = field(default_factory=set)


def consulta_tsquery(palavras: Sequence[str]):
    """OR of phrase queries: "material de escritório" must appear as a phrase."""
    termos = [func.phraseto_tsquery(PORTUGUES, p) for p in palavras if p.strip()]
    query = termos[0]
    for termo in termos[1:]:
        query = query.op("||")(termo)
    return query


def candidatas(perfil: Perfil, limite: int) -> Select[tuple[Licitacao]]:
    """Open tenders matching the profile that it has not triaged yet."""
    query = consulta_tsquery(perfil.palavras_chave)
    filtros = [
        Licitacao.busca.op("@@")(query),
        or_(Licitacao.encerramento_propostas.is_(None), Licitacao.encerramento_propostas > func.now()),
        ~select(Triagem.id)
        .where(Triagem.perfil_id == perfil.id, Triagem.licitacao_id == Licitacao.id)
        .exists(),
    ]
    if perfil.ufs:
        filtros.append(Licitacao.uf.in_(perfil.ufs))
    # Undisclosed estimates (orçamento sigiloso) stay in: the value is unknown, not out of range.
    if perfil.valor_minimo is not None:
        filtros.append(
            or_(Licitacao.valor_estimado.is_(None), Licitacao.valor_estimado >= perfil.valor_minimo)
        )
    if perfil.valor_maximo is not None:
        filtros.append(
            or_(Licitacao.valor_estimado.is_(None), Licitacao.valor_estimado <= perfil.valor_maximo)
        )
    return (
        select(Licitacao)
        .where(and_(*filtros))
        .order_by(func.ts_rank(Licitacao.busca, query).desc(), Licitacao.encerramento_propostas)
        .limit(limite)
    )


def _valor(valor: Decimal | None) -> str:
    if valor is None or valor == 0:
        return "não informado"
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def montar_conteudo(perfil: Perfil, lote: Sequence[Licitacao]) -> str:
    linhas = [
        "PERFIL DA EMPRESA",
        perfil.descricao,
        f"Atua em: {', '.join(perfil.ufs) if perfil.ufs else 'todo o Brasil'}",
        "",
        "LICITAÇÕES",
    ]
    for n, lic in enumerate(lote, start=1):
        objeto = " ".join(lic.objeto.split())
        if len(objeto) > MAX_OBJETO:
            objeto = objeto[:MAX_OBJETO] + "…"
        linhas.append(
            f"{n}. {objeto}\n   Órgão: {lic.orgao} ({lic.municipio or '?'}/{lic.uf or '?'}) · "
            f"Valor estimado: {_valor(lic.valor_estimado)}"
        )
    return "\n".join(linhas)


async def triar(session: AsyncSession, llm: LLM, perfil: Perfil, limite: int = 200) -> ResultadoTriagem:
    lics = (await session.scalars(candidatas(perfil, limite))).all()
    resultado = ResultadoTriagem(candidatas=len(lics))
    for inicio in range(0, len(lics), LOTE):
        lote = lics[inicio : inicio + LOTE]
        try:
            resposta = await llm.estruturado(
                sistema=SISTEMA, conteudo=montar_conteudo(perfil, lote), esquema=AvaliacaoLote
            )
        except LLMErro as exc:
            # The batch stays untriaged and comes back on the next run.
            log.warning("lote de triagem falhou: %s", exc)
            resultado.lotes_com_erro += 1
            continue

        por_numero = {a.n: a for a in resposta.dados.avaliacoes}
        for n, lic in enumerate(lote, start=1):
            avaliacao = por_numero.get(n)
            if avaliacao is None:  # the model skipped it: retry next run rather than guess
                continue
            relevante = avaliacao.nota >= NOTA_RELEVANTE
            session.add(
                Triagem(
                    perfil_id=perfil.id,
                    licitacao_id=lic.id,
                    nota=avaliacao.nota,
                    relevante=relevante,
                    motivo=avaliacao.motivo.strip(),
                    modelo=resposta.uso.modelo,
                )
            )
            resultado.avaliadas += 1
            resultado.relevantes += relevante
        resultado.modelos.add(resposta.uso.modelo)
        await session.commit()  # each batch is kept even if a later one fails
    return resultado
