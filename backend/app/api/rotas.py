from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    AnaliseOut,
    LicitacaoDetalhe,
    LicitacaoResumo,
    PaginaOut,
    PerfilOut,
    Triada,
)
from app.core.db import get_session
from app.models import AnaliseEdital, Documento, Licitacao, Pagina, Perfil, Triagem

router = APIRouter(prefix="/api")
Sessao = Annotated[AsyncSession, Depends(get_session)]


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
