"""Ask a question about one tender's editais and get an answer with checked quotes.

Unlike the analysis, which reads every page in one call, the agent searches and
reads only what the question needs: cheaper, and it scales to editais that
would not fit a prompt. Its quotes go through the same verifier.
"""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.agente.ferramentas import DECLARACOES, FerramentasEdital
from app.analise.service import SemTexto, carregar_paginas
from app.analise.verificador import Verificador
from app.llm import AgenteLLM, Mensagem
from app.models import Licitacao

MAX_HISTORICO = 6  # earlier turns sent back for follow-up questions

SISTEMA = """Você responde perguntas sobre UMA licitação pública, com base nos documentos dela
(edital, termo de referência, anexos), para uma pequena empresa que pensa em participar.

Como trabalhar:
- Procure com buscar_trechos e leia as páginas relevantes com ler_pagina antes de responder.
  Se a primeira busca não achar, tente outras palavras (sinônimos, termos técnicos de edital).
- Responda só com o que está nos documentos. Se não estiver, diga claramente que os
  documentos não informam, sem supor.
- Toda afirmação importante leva uma citação: a página [p. N] e o trecho copiado
  literalmente da página lida (mesmas palavras, mesma ordem; use "..." para pular partes).
- Termine sempre chamando responder, uma única vez.

Licitação: {objeto}
Órgão: {orgao} ({municipio}/{uf})
Os documentos têm {paginas} páginas no total."""


@dataclass
class RespostaPergunta:
    resposta: str
    citacoes: list[dict]
    ferramentas: list[dict] = field(default_factory=list)  # what the agent searched/read
    modelo: str = ""
    tokens_entrada: int = 0
    tokens_saida: int = 0
    segundos: float = 0.0


async def perguntar(
    session: AsyncSession,
    llm: AgenteLLM,
    lic: Licitacao,
    pergunta: str,
    historico: list[Mensagem] | None = None,
) -> RespostaPergunta:
    paginas = await carregar_paginas(session, lic.id)
    if not paginas:
        raise SemTexto(lic.id)
    ferramentas = FerramentasEdital(session, lic.id, paginas)
    sistema = SISTEMA.format(
        objeto=" ".join(lic.objeto.split()),
        orgao=lic.orgao,
        municipio=lic.municipio or "?",
        uf=lic.uf or "?",
        paginas=len(paginas),
    )
    mensagens = [*(historico or [])[-MAX_HISTORICO:], Mensagem("usuario", pergunta)]
    r = await llm.agente(
        sistema=sistema,
        mensagens=mensagens,
        ferramentas=DECLARACOES,
        executar=ferramentas.executar,
        final="responder",
    )

    verificador = Verificador(paginas)
    citacoes = []
    for c in r.final.get("citacoes") or []:
        try:
            pagina, trecho = int(c["pagina"]), str(c["trecho"])
        except (KeyError, TypeError, ValueError):
            continue
        v = verificador.verificar(pagina, trecho)
        citacao = {"pagina": v.pagina or pagina, "trecho": trecho, "status": v.status}
        if v.pagina is not None:
            ref = ferramentas.paginas[v.pagina]
            citacao |= {
                "documento_id": ref.documento_id,
                "documento": ref.documento,
                "pagina_documento": ref.numero,
                "arquivo": ref.arquivo,
                "pagina_no_arquivo": ref.pagina_no_arquivo,
            }
        citacoes.append(citacao)

    return RespostaPergunta(
        resposta=str(r.final.get("resposta", "")).strip(),
        citacoes=citacoes,
        ferramentas=[{"nome": c.nome, "argumentos": c.argumentos} for c in r.chamadas],
        modelo=r.uso.modelo,
        tokens_entrada=r.uso.tokens_entrada,
        tokens_saida=r.uso.tokens_saida,
        segundos=round(r.uso.segundos, 1),
    )
