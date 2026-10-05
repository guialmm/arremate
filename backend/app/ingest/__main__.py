"""Run the ingestion by hand.

    python -m app.ingest sync --dias 3          # publications of the last 3 days
    python -m app.ingest detalhes --limite 200  # items + document lists
    python -m app.ingest documentos <licitacao> # download and read one tender's editais
    python -m app.ingest relevantes --perfil 1  # details + editais of the triaged-in tenders
    python -m app.ingest status
"""

import argparse
import asyncio
import logging
import time
from datetime import date, timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.ingest.service import (
    buscar_detalhes,
    detalhes_pendentes,
    documentos_a_ler,
    ler_documento,
    sincronizar_dia,
)
from app.models import Documento, Etapa, Licitacao, Pagina, Triagem
from app.pncp.client import PncpClient


async def sync(client: PncpClient, dias: int) -> None:
    hoje = date.today()
    for delta in range(dias - 1, -1, -1):
        dia = hoje - timedelta(days=delta)
        for modalidade in settings.pncp_modalidades:
            inicio = time.monotonic()
            async with SessionLocal() as session:
                r = await sincronizar_dia(session, client, dia, modalidade)
            print(
                f"{dia} modalidade {modalidade}: {r.paginas} páginas, {r.novas} novas, "
                f"{r.atualizadas} atualizadas ({time.monotonic() - inicio:.0f}s)"
            )


async def detalhes(client: PncpClient, limite: int) -> None:
    async with SessionLocal() as session:
        ids = (await session.scalars(detalhes_pendentes(limite).with_only_columns(Licitacao.id))).all()
    semaforo = asyncio.Semaphore(settings.pncp_concurrency)
    ok = 0

    async def um(lic_id: str) -> None:
        nonlocal ok
        async with semaforo, SessionLocal() as session:
            sucesso = await buscar_detalhes(session, client, await session.get(Licitacao, lic_id))
        ok += sucesso  # not `ok += await ...`: that reads `ok` before awaiting

    inicio = time.monotonic()
    await asyncio.gather(*map(um, ids))
    print(f"detalhes: {ok}/{len(ids)} ok ({time.monotonic() - inicio:.0f}s)")


async def documentos(client: PncpClient, licitacao_id: str) -> None:
    async with SessionLocal() as session:
        for doc in (await session.scalars(documentos_a_ler(licitacao_id))).all():
            await ler_documento(session, client, doc)
            print(f"{doc.tipo} '{doc.titulo}': {doc.status.value} {doc.total_paginas or ''} {doc.erro or ''}")


async def relevantes(client: PncpClient, perfil_id: int) -> None:
    """Only tenders that passed triage get their slow endpoints and editais fetched."""
    async with SessionLocal() as session:
        ids = (
            await session.scalars(
                select(Triagem.licitacao_id)
                .where(Triagem.perfil_id == perfil_id, Triagem.relevante)
                .order_by(Triagem.nota.desc())
            )
        ).all()
    for lic_id in ids:
        async with SessionLocal() as session:
            lic = await session.get(Licitacao, lic_id)
            if lic.detalhes != Etapa.ok and not await buscar_detalhes(session, client, lic):
                print(f"{lic_id}: detalhes falharam ({lic.detalhes_erro})")
                continue
            for doc in (await session.scalars(documentos_a_ler(lic_id))).all():
                await ler_documento(session, client, doc)
                print(
                    f"{lic_id} · {doc.tipo} '{doc.titulo[:40]}': {doc.status.value} "
                    f"{doc.formato or ''} {doc.total_paginas or ''} {doc.erro or ''}"
                )


async def status() -> None:
    async with SessionLocal() as session:
        licitacoes = await session.execute(
            select(Licitacao.detalhes, func.count()).group_by(Licitacao.detalhes)
        )
        docs = await session.execute(
            select(Documento.status, func.count()).group_by(Documento.status)
        )
        paginas = await session.scalar(select(func.count()).select_from(Pagina))
    print("licitações por etapa:", {k.value: v for k, v in licitacoes})
    print("documentos por status:", {k.value: v for k, v in docs})
    print("páginas de texto:", paginas)


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.ingest")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("sync").add_argument("--dias", type=int, default=2)
    sub.add_parser("detalhes").add_argument("--limite", type=int, default=100)
    sub.add_parser("documentos").add_argument("licitacao")
    sub.add_parser("relevantes").add_argument("--perfil", type=int, default=1)
    sub.add_parser("status")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    try:
        if args.comando == "status":
            await status()
            return
        async with PncpClient.default_http() as http:
            client = PncpClient(http)
            if args.comando == "sync":
                await sync(client, args.dias)
            elif args.comando == "relevantes":
                await relevantes(client, args.perfil)
            elif args.comando == "detalhes":
                await detalhes(client, args.limite)
            else:
                await documentos(client, args.licitacao)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
