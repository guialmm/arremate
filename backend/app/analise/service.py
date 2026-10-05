"""Read a tender's editais with the LLM and check what it claims.

The whole text goes in one call (Flash models take ~1M tokens; the largest
edital so far is ~70k), each page tagged [p. N] with a number that is global
across the tender's documents, so a citation is a single integer the
verifier can map back to (document, page, file inside the ZIP).
"""

import logging
import time
from collections.abc import Iterator

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analise.schemas import Analise
from app.analise.verificador import PaginaRef, Verificador
from app.ingest.service import TIPOS_LIDOS
from app.llm import LLM
from app.models import AnaliseEdital, Documento, Item, Licitacao, Perfil, StatusDocumento

log = logging.getLogger(__name__)

MAX_ITENS_NO_PROMPT = 40
VERIFICADAS = {"verificada", "corrigida", "aproximada"}

SISTEMA = """Você é um analista de licitações que ajuda pequenas empresas a decidir se participam
de um pregão. Leia o edital e os anexos fornecidos e preencha a análise.

Regras:
- Use somente o que está escrito nos documentos. Se algo não aparece, não invente: deixe a
  lista vazia ou use "nao_informado".
- Toda citação deve copiar o texto do documento literalmente (mesmas palavras, mesma ordem)
  e indicar a página [p. N] onde o trecho está. Prefira trechos curtos e específicos.
  Para pular partes de uma frase longa, use "...".
- Requisitos: liste cada documento de habilitação exigido (jurídica, fiscal e trabalhista,
  econômico-financeira, técnica). Compare com a lista de documentos da empresa:
  "atende" só quando um documento da lista cobre a exigência; "falta" quando nenhum cobre;
  "verificar" quando depende de um detalhe que a lista não diz (ex.: índice mínimo do
  balanço, quantidade mínima no atestado, validade).
- Prazos: datas da sessão, envio de propostas, impugnação e esclarecimentos, entrega.
- Condições: prazo e local de entrega, amostras, garantia, pagamento, vigência da ata.
- Riscos: o que desclassifica ou pune (amostra reprovada, multa, prazo curto, exigência
  incomum, marca específica). Gravidade alta para o que pode tirar a empresa da disputa.
- Recomendação: "participar" se o objeto é do ramo e não falta documento; "avaliar" se há
  pendências contornáveis; "nao_participar" se falta algo que a empresa não consegue obter
  a tempo ou o objeto não é do ramo.
Escreva em português do Brasil."""


class SemTexto(Exception):
    """None of the tender's editais could be read (scanned, RAR, not downloaded)."""


async def carregar_paginas(session: AsyncSession, licitacao_id: str) -> list[PaginaRef]:
    documentos = (
        await session.scalars(
            select(Documento)
            .where(
                Documento.licitacao_id == licitacao_id,
                Documento.tipo_id.in_(TIPOS_LIDOS),
                Documento.status == StatusDocumento.ok,
            )
            .options(selectinload(Documento.paginas))
            .order_by(Documento.tipo_id, Documento.sequencial)  # edital before annexes
        )
    ).all()
    refs: list[PaginaRef] = []
    for doc in documentos:
        for p in doc.paginas:
            refs.append(
                PaginaRef(
                    global_n=len(refs) + 1,
                    documento_id=doc.id,
                    documento=f"{doc.tipo}: {doc.titulo}",
                    numero=p.numero,
                    arquivo=p.arquivo,
                    pagina_no_arquivo=p.pagina_no_arquivo,
                    texto=p.texto,
                )
            )
    return refs


def montar_conteudo(perfil: Perfil, lic: Licitacao, itens: list[Item], paginas: list[PaginaRef]) -> str:
    partes = [
        "EMPRESA",
        perfil.descricao,
        "Documentos que a empresa já possui:",
        *[f"- {d}" for d in perfil.documentos],
        "",
        "LICITAÇÃO (dados do PNCP)",
        f"Órgão: {lic.orgao} ({lic.municipio}/{lic.uf})",
        f"Objeto: {' '.join(lic.objeto.split())}",
    ]
    if itens:
        partes.append(f"Itens ({len(itens)} no total):")
        for item in itens[:MAX_ITENS_NO_PROMPT]:
            beneficio = f" [{item.beneficio}]" if item.beneficio else ""
            partes.append(
                f"- {item.numero}. {' '.join(item.descricao.split())[:160]} "
                f"({item.quantidade or '?'} {item.unidade or ''}){beneficio}"
            )
        if len(itens) > MAX_ITENS_NO_PROMPT:
            partes.append(f"- ... e mais {len(itens) - MAX_ITENS_NO_PROMPT} itens")
    partes += ["", "DOCUMENTOS"]
    atual = None
    for p in paginas:
        if p.documento != atual:
            atual = p.documento
            partes.append(f"\n===== {p.documento} =====")
        origem = f" ({p.arquivo}, pág. {p.pagina_no_arquivo})" if p.arquivo else ""
        partes.append(f"[p. {p.global_n}]{origem}\n{p.texto}")
    return "\n".join(partes)


def _citacoes(resultado: dict) -> Iterator[dict]:
    if resultado.get("me_epp_citacao"):
        yield resultado["me_epp_citacao"]
    for lista in ("prazos", "requisitos", "condicoes", "riscos"):
        for entrada in resultado.get(lista, []):
            yield entrada["citacao"]


def verificar_citacoes(resultado: dict, paginas: list[PaginaRef]) -> tuple[int, int]:
    """Annotate each citation in place; returns (total, verified)."""
    verificador = Verificador(paginas)
    por_numero = {p.global_n: p for p in paginas}
    total = verificadas = 0
    for citacao in _citacoes(resultado):
        v = verificador.verificar(citacao["pagina"], citacao["trecho"])
        total += 1
        verificadas += v.status in VERIFICADAS
        citacao["status"] = v.status
        if v.pagina is not None:
            citacao["pagina"] = v.pagina
            ref = por_numero[v.pagina]
            citacao.update(
                documento_id=ref.documento_id,
                documento=ref.documento,
                pagina_documento=ref.numero,
                arquivo=ref.arquivo,
                pagina_no_arquivo=ref.pagina_no_arquivo,
            )
    return total, verificadas


async def analisar(session: AsyncSession, llm: LLM, perfil: Perfil, lic: Licitacao) -> AnaliseEdital:
    paginas = await carregar_paginas(session, lic.id)
    if not paginas:
        raise SemTexto(lic.id)
    itens = (await session.scalars(select(Item).where(Item.licitacao_id == lic.id).order_by(Item.numero))).all()

    inicio = time.monotonic()
    resposta = await llm.estruturado(
        sistema=SISTEMA, conteudo=montar_conteudo(perfil, lic, list(itens), paginas), esquema=Analise
    )
    resultado = resposta.dados.model_dump()
    total, verificadas = verificar_citacoes(resultado, paginas)

    await session.execute(
        delete(AnaliseEdital).where(
            AnaliseEdital.perfil_id == perfil.id, AnaliseEdital.licitacao_id == lic.id
        )
    )
    analise = AnaliseEdital(
        perfil_id=perfil.id,
        licitacao_id=lic.id,
        resultado=resultado,
        recomendacao=resultado["recomendacao"],
        modelo=resposta.uso.modelo,
        paginas_lidas=len(paginas),
        tokens_entrada=resposta.uso.tokens_entrada,
        tokens_saida=resposta.uso.tokens_saida,
        segundos=round(time.monotonic() - inicio, 1),
        citacoes_total=total,
        citacoes_verificadas=verificadas,
    )
    session.add(analise)
    await session.commit()
    return analise
