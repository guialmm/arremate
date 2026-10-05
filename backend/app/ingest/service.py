"""Copy PNCP into our database, one resumable step at a time.

1. `sincronizar_dia`: sweep the search API for a day's publications (cheap, all of them).
2. `buscar_detalhes`: items and the document list of one tender (slow endpoints).
3. `ler_documento`: download an edital and store its text page by page (only for
   tenders worth analysing — downloading all ~1.500 a day would be wasteful).

Each step commits its own progress and records failures instead of raising,
so one dead tender or a PNCP outage never stalls the rest of the queue.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, delete, func, literal, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingest.extract import FormatoNaoSuportado, detectar_formato, extrair
from app.models import Documento, Etapa, Item, Licitacao, Pagina, Sincronizacao, StatusDocumento
from app.pncp import parse
from app.pncp.client import ArquivoGrande, PncpClient, PncpErro

log = logging.getLogger(__name__)

# Edital, Termo de Referência, Projeto Básico: where requirements, deadlines and
# specs live. Pareceres, ETPs and DFDs would only add tokens.
TIPOS_LIDOS = {2, 4, 6}
MAX_TENTATIVAS = 5


@dataclass
class ResultadoSync:
    paginas: int = 0
    novas: int = 0
    atualizadas: int = 0


async def sincronizar_dia(
    session: AsyncSession, client: PncpClient, dia: date, modalidade: int, hoje: date | None = None
) -> ResultadoSync:
    hoje = hoje or date.today()
    cursor = await session.get(Sincronizacao, (dia, modalidade))
    if cursor is None:
        cursor = Sincronizacao(dia=dia, modalidade_id=modalidade, ultima_pagina=0)
        session.add(cursor)
    if cursor.concluida:
        return ResultadoSync()
    # Agencies keep publishing with yesterday's date for a while, and new rows shift
    # the pages: recent days are swept from the start (the upsert makes it harmless).
    fechado = dia < hoje - timedelta(days=1)
    pagina = cursor.ultima_pagina + 1 if fechado else 1

    resultado = ResultadoSync()
    while True:
        busca = await client.publicacoes(dia, modalidade, pagina)
        novas = await upsert_licitacoes(session, busca.registros)
        resultado.paginas += 1
        resultado.novas += novas
        resultado.atualizadas += len(busca.registros) - novas
        cursor.ultima_pagina = pagina
        cursor.total_paginas = busca.total_paginas
        cursor.total_registros = busca.total_registros
        await session.commit()  # progress survives a crash on the next page
        if pagina >= busca.total_paginas:
            break
        pagina += 1

    cursor.concluida = fechado
    await session.commit()
    return resultado


async def upsert_licitacoes(session: AsyncSession, registros: list[dict]) -> int:
    """Insert or refresh tenders; returns how many were new."""
    if not registros:
        return 0
    linhas = {r["id"]: r for r in map(parse.licitacao, registros)}  # dedupe within a page
    stmt = insert(Licitacao).values(list(linhas.values()))
    atual = Licitacao.__table__.c
    mudou = atual.atualizada_no_pncp.is_distinct_from(stmt.excluded.atualizada_no_pncp)
    campos = {
        c: stmt.excluded[c]
        for c in linhas[next(iter(linhas))]
        if c not in ("id", "cnpj", "ano", "sequencial")
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            **campos,
            # A republished tender may carry a new edital: fetch its details again.
            "detalhes": case((mudou, literal(Etapa.pendente, atual.detalhes.type)), else_=atual.detalhes),
            "detalhes_tentativas": case((mudou, 0), else_=atual.detalhes_tentativas),
        },
    ).returning(literal_column("xmax = 0"))  # true when the row was inserted
    inseridas = (await session.execute(stmt)).scalars().all()
    return sum(inseridas)


async def buscar_detalhes(session: AsyncSession, client: PncpClient, licitacao: Licitacao) -> bool:
    try:
        itens = await client.itens(licitacao.cnpj, licitacao.ano, licitacao.sequencial)
        arquivos = await client.arquivos(licitacao.cnpj, licitacao.ano, licitacao.sequencial)
    except PncpErro as exc:
        licitacao.detalhes = Etapa.falhou
        licitacao.detalhes_tentativas += 1
        licitacao.detalhes_erro = str(exc)[:1000]
        await session.commit()
        log.warning("detalhes de %s falharam: %s", licitacao.id, exc)
        return False

    await session.execute(delete(Item).where(Item.licitacao_id == licitacao.id))
    linhas_itens = {i["numero"]: i for i in map(parse.item, itens)}
    if linhas_itens:
        await session.execute(
            insert(Item).values([{**i, "licitacao_id": licitacao.id} for i in linhas_itens.values()])
        )

    ativos = [parse.documento(a) for a in arquivos if a.get("statusAtivo", True)]
    if ativos:
        stmt = insert(Documento).values([{**d, "licitacao_id": licitacao.id} for d in ativos])
        atual = Documento.__table__.c
        # Same slot, different URL: the agency replaced the file, read it again.
        trocou = atual.url.is_distinct_from(stmt.excluded.url)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["licitacao_id", "sequencial"],
                set_={
                    "titulo": stmt.excluded.titulo,
                    "tipo_id": stmt.excluded.tipo_id,
                    "tipo": stmt.excluded.tipo,
                    "url": stmt.excluded.url,
                    "status": case(
                        (trocou, literal(StatusDocumento.pendente, atual.status.type)),
                        else_=atual.status,
                    ),
                    "tentativas": case((trocou, 0), else_=atual.tentativas),
                },
            )
        )
    sequenciais = [d["sequencial"] for d in ativos]
    await session.execute(
        delete(Documento).where(
            Documento.licitacao_id == licitacao.id, Documento.sequencial.not_in(sequenciais)
        )
    )

    licitacao.detalhes = Etapa.ok
    licitacao.detalhes_erro = None
    await session.commit()
    return True


async def ler_documento(session: AsyncSession, client: PncpClient, documento: Documento) -> None:
    documento.tentativas += 1
    try:
        baixado = await client.baixar(documento.url, settings.max_document_mb * 2**20)
    except ArquivoGrande as exc:
        await _finalizar(session, documento, StatusDocumento.nao_suportado, f"arquivo grande: {exc}")
        return
    except PncpErro as exc:
        await _finalizar(session, documento, StatusDocumento.falhou, str(exc))
        return

    documento.nome_arquivo = (baixado.nome_arquivo or "")[:300] or None
    documento.formato = detectar_formato(baixado.conteudo, baixado.nome_arquivo)
    documento.tamanho_bytes = len(baixado.conteudo)
    documento.sha256 = hashlib.sha256(baixado.conteudo).hexdigest()
    try:
        # pypdf is CPU-bound: keep the event loop (and other downloads) moving.
        paginas = await asyncio.to_thread(extrair, baixado.conteudo, baixado.nome_arquivo)
    except FormatoNaoSuportado as exc:
        await _finalizar(session, documento, StatusDocumento.nao_suportado, str(exc))
        return

    await session.execute(delete(Pagina).where(Pagina.documento_id == documento.id))
    session.add_all(
        Pagina(
            documento_id=documento.id,
            numero=n,
            arquivo=p.arquivo,
            pagina_no_arquivo=p.pagina_no_arquivo,
            texto=p.texto,
        )
        for n, p in enumerate(paginas, start=1)
    )
    documento.total_paginas = len(paginas)
    documento.baixado_em = datetime.now(timezone.utc)
    await _finalizar(session, documento, StatusDocumento.ok, None)


async def _finalizar(
    session: AsyncSession, documento: Documento, status: StatusDocumento, erro: str | None
) -> None:
    documento.status = status
    documento.erro = erro[:1000] if erro else None
    await session.commit()


def documentos_a_ler(licitacao_id: str):
    return select(Documento).where(
        Documento.licitacao_id == licitacao_id,
        Documento.tipo_id.in_(TIPOS_LIDOS),
        (Documento.status == StatusDocumento.pendente)
        | ((Documento.status == StatusDocumento.falhou) & (Documento.tentativas < MAX_TENTATIVAS)),
    )


def detalhes_pendentes(limite: int):
    return (
        select(Licitacao)
        .where(
            (Licitacao.detalhes == Etapa.pendente)
            | ((Licitacao.detalhes == Etapa.falhou) & (Licitacao.detalhes_tentativas < MAX_TENTATIVAS))
        )
        # Tenders closing soonest first: they are the ones a company can still bid on.
        .where(
            (Licitacao.encerramento_propostas.is_(None))
            | (Licitacao.encerramento_propostas > func.now())
        )
        .order_by(Licitacao.encerramento_propostas.asc().nulls_last())
        .limit(limite)
    )
