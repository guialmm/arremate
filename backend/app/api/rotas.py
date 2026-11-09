import re
import unicodedata
from datetime import UTC, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agente.service import perguntar
from app.analise.service import SemTexto
from app.api.limite import Limite, ip
from app.api.schemas import (
    AnaliseOut,
    LicitacaoDetalhe,
    LicitacaoResumo,
    PaginaOut,
    PerfilOut,
    PerguntaIn,
    RespostaOut,
    Triada,
)
from app.core.config import settings
from app.core.db import get_session
from app.llm import LLMErro, LLMIndisponivel, Mensagem, get_llm
from app.models import AnaliseEdital, Documento, Licitacao, Pagina, Perfil, Pergunta, Triagem

router = APIRouter(prefix="/api")
Sessao = Annotated[AsyncSession, Depends(get_session)]
limite_ip = Limite(settings.perguntas_por_ip, janela_s=600)


def normalizar_pergunta(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^\w\s]", " ", sem_acento).split())


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.get("/perfis", response_model=list[PerfilOut])
async def perfis(session: Sessao):
    return (await session.scalars(select(Perfil).order_by(Perfil.id))).all()


@router.get("/perfis/{perfil_id}/licitacoes", response_model=list[Triada])
async def triadas(
    perfil_id: int,
    session: Sessao,
    todas: Annotated[bool, Query(description="inclui as descartadas pela triagem")] = False,
):
    """Tenders triaged for a profile, best first; analyzed ones carry the recommendation."""
    if await session.get(Perfil, perfil_id) is None:
        raise HTTPException(404, "perfil não encontrado")
    consulta = (
        select(Triagem, AnaliseEdital)
        .options(selectinload(Triagem.licitacao))
        .outerjoin(
            AnaliseEdital,
            (AnaliseEdital.perfil_id == Triagem.perfil_id)
            & (AnaliseEdital.licitacao_id == Triagem.licitacao_id),
        )
        .where(Triagem.perfil_id == perfil_id)
        .order_by(AnaliseEdital.id.is_(None), Triagem.nota.desc(), Triagem.licitacao_id)
    )
    if not todas:
        consulta = consulta.where(Triagem.relevante)
    linhas = (await session.execute(consulta)).all()
    return [
        Triada(
            licitacao=LicitacaoResumo.model_validate(t.licitacao),
            nota=t.nota,
            relevante=t.relevante,
            motivo=t.motivo,
            recomendacao=a.recomendacao if a else None,
            citacoes_total=a.citacoes_total if a else None,
            citacoes_verificadas=a.citacoes_verificadas if a else None,
        )
        for t, a in linhas
    ]


@router.post("/licitacoes/{licitacao_id:path}/perguntar", response_model=RespostaOut)
async def perguntar_ao_edital(
    licitacao_id: str, corpo: PerguntaIn, request: Request, session: Sessao, llm=Depends(get_llm)
):
    """Ask the agent about this tender. A first question already asked is answered from
    the log; new ones are capped per IP and per day (the free LLM tier is small)."""
    lic = await session.get(Licitacao, licitacao_id)
    if lic is None:
        raise HTTPException(404, "licitação não encontrada")
    normalizada = normalizar_pergunta(corpo.pergunta)
    if not corpo.historico:
        guardada = await session.scalar(
            select(Pergunta)
            .where(
                Pergunta.licitacao_id == lic.id,
                Pergunta.pergunta_normalizada == normalizada,
                Pergunta.com_historico.is_(False),
            )
            .order_by(Pergunta.id.desc())
            .limit(1)
        )
        if guardada:
            return RespostaOut(
                resposta=guardada.resposta, citacoes=guardada.citacoes, ferramentas=guardada.ferramentas,
                modelo=guardada.modelo, segundos=guardada.segundos, do_cache=True,
            )

    meia_noite = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    hoje = await session.scalar(select(func.count()).select_from(Pergunta).where(Pergunta.created_at >= meia_noite))
    if hoje >= settings.perguntas_por_dia:
        raise HTTPException(429, "O limite diário de perguntas da demonstração acabou. Volte amanhã.")
    if not limite_ip.permitir(ip(request)):
        raise HTTPException(429, "Muitas perguntas seguidas. Espere alguns minutos.")

    historico = [Mensagem(t.papel, t.texto) for t in corpo.historico]
    try:
        r = await perguntar(session, llm, lic, corpo.pergunta, historico)
    except SemTexto:
        raise HTTPException(409, "Os documentos desta licitação não puderam ser lidos.")
    except LLMIndisponivel:
        raise HTTPException(503, "O modelo gratuito está sobrecarregado agora. Tente em instantes.")
    except LLMErro:
        raise HTTPException(502, "O modelo não conseguiu responder. Tente reformular a pergunta.")

    session.add(
        Pergunta(
            licitacao_id=lic.id, pergunta=corpo.pergunta, pergunta_normalizada=normalizada,
            com_historico=bool(historico), resposta=r.resposta, citacoes=r.citacoes,
            ferramentas=r.ferramentas, modelo=r.modelo, tokens_entrada=r.tokens_entrada,
            tokens_saida=r.tokens_saida, segundos=r.segundos,
        )
    )
    await session.commit()
    return RespostaOut(
        resposta=r.resposta, citacoes=r.citacoes, ferramentas=r.ferramentas,
        modelo=r.modelo, segundos=r.segundos, do_cache=False,
    )


@router.get("/licitacoes/{licitacao_id:path}/analise", response_model=AnaliseOut)
async def analise(licitacao_id: str, perfil_id: int, session: Sessao):
    a = await session.scalar(
        select(AnaliseEdital).where(
            AnaliseEdital.licitacao_id == licitacao_id, AnaliseEdital.perfil_id == perfil_id
        )
    )
    if a is None:
        raise HTTPException(404, "edital ainda não analisado para este perfil")
    return a


@router.get("/licitacoes/{licitacao_id:path}", response_model=LicitacaoDetalhe)
async def licitacao(licitacao_id: str, session: Sessao):
    # numeroControlePNCP has a slash ("…-000627/2026"), hence the :path converter.
    lic = await session.scalar(
        select(Licitacao)
        .where(Licitacao.id == licitacao_id)
        .options(selectinload(Licitacao.itens), selectinload(Licitacao.documentos))
    )
    if lic is None:
        raise HTTPException(404, "licitação não encontrada")
    return lic


@router.get("/documentos/{documento_id}/paginas/{numero}", response_model=PaginaOut)
async def pagina(documento_id: int, numero: int, session: Sessao):
    """The page a citation points to, so the reader can check the quote in context."""
    linha = (
        await session.execute(
            select(Pagina, Documento)
            .join(Documento)
            .where(Pagina.documento_id == documento_id, Pagina.numero == numero)
        )
    ).first()
    if linha is None:
        raise HTTPException(404, "página não encontrada")
    p, d = linha
    return PaginaOut(
        documento_id=d.id,
        documento=d.titulo,
        numero=p.numero,
        total_paginas=d.total_paginas,
        arquivo=p.arquivo,
        pagina_no_arquivo=p.pagina_no_arquivo,
        texto=p.texto,
    )
