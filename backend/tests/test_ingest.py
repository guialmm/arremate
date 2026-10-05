import copy
from datetime import date

import httpx
from sqlalchemy import func, select

from app.ingest.service import (
    buscar_detalhes,
    detalhes_pendentes,
    documentos_a_ler,
    ler_documento,
    sincronizar_dia,
)
from app.models import Documento, Etapa, Item, Licitacao, Pagina, Sincronizacao, StatusDocumento
from tests.conftest import fixture, make_pdf, make_zip

BUSCA = "/consulta/v1/contratacoes/publicacao"
HOJE = date(2026, 10, 5)
ANTIGO = date(2026, 10, 1)
TEXTO = "Exige-se atestado de capacidade tecnica e certidao negativa de debitos trabalhistas. " * 3


def registros() -> list[dict]:
    return copy.deepcopy(fixture("publicacoes.json")["data"])


def pagina(regs: list[dict], total_paginas: int) -> httpx.Response:
    return httpx.Response(
        200, json={"data": regs, "totalPaginas": total_paginas, "totalRegistros": 10 * total_paginas}
    )


def by_page(pages: dict[int, httpx.Response]):
    return lambda request: pages[int(request.url.params["pagina"])]


async def contar(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def test_sync_walks_every_page_and_stores_tenders(session, client, pncp):
    regs = registros()
    pncp.on(BUSCA, by_page({1: pagina(regs[:5], 2), 2: pagina(regs[5:], 2)}))

    resultado = await sincronizar_dia(session, client, ANTIGO, 6, hoje=HOJE)

    assert (resultado.paginas, resultado.novas, resultado.atualizadas) == (2, 10, 0)
    assert await contar(session, Licitacao) == 10
    lic = await session.get(Licitacao, regs[0]["numeroControlePNCP"])
    assert lic.orgao == regs[0]["orgaoEntidade"]["razaoSocial"]
    assert lic.uf == regs[0]["unidadeOrgao"]["ufSigla"]
    assert lic.publicada_em.utcoffset() is not None  # stored with Brasília offset
    assert lic.detalhes == Etapa.pendente
    cursor = await session.get(Sincronizacao, (ANTIGO, 6))
    assert cursor.concluida and cursor.ultima_pagina == 2


async def test_closed_day_is_not_fetched_again(session, client, pncp):
    pncp.on(BUSCA, pagina(registros(), 1))
    await sincronizar_dia(session, client, ANTIGO, 6, hoje=HOJE)
    await sincronizar_dia(session, client, ANTIGO, 6, hoje=HOJE)
    assert len(pncp.calls) == 1


async def test_interrupted_sync_resumes_after_the_last_saved_page(session, client, pncp):
    regs = registros()
    pncp.on(BUSCA, by_page({1: pagina(regs[:5], 2), 2: httpx.Response(503)}))
    try:
        await sincronizar_dia(session, client, ANTIGO, 6, hoje=HOJE)
    except Exception:
        await session.rollback()
    assert await contar(session, Licitacao) == 5

    pncp.calls.clear()
    pncp.on(BUSCA, by_page({2: pagina(regs[5:], 2)}))
    resultado = await sincronizar_dia(session, client, ANTIGO, 6, hoje=HOJE)
    assert [c.url.params["pagina"] for c in pncp.calls] == ["2"]
    assert resultado.novas == 5
    assert await contar(session, Licitacao) == 10


async def test_today_is_swept_again_and_stays_open(session, client, pncp):
    pncp.on(BUSCA, pagina(registros(), 1))
    await sincronizar_dia(session, client, HOJE, 6, hoje=HOJE)
    resultado = await sincronizar_dia(session, client, HOJE, 6, hoje=HOJE)
    assert len(pncp.calls) == 2
    assert (resultado.novas, resultado.atualizadas) == (0, 10)
    assert not (await session.get(Sincronizacao, (HOJE, 6))).concluida


async def test_republished_tender_goes_back_to_the_details_queue(session, client, pncp):
    regs = registros()
    pncp.on(BUSCA, pagina(regs, 1))
    await sincronizar_dia(session, client, HOJE, 6, hoje=HOJE)
    alvo, intocado = regs[0]["numeroControlePNCP"], regs[1]["numeroControlePNCP"]
    for lic_id in (alvo, intocado):
        (await session.get(Licitacao, lic_id)).detalhes = Etapa.ok
    await session.commit()

    regs[0]["dataAtualizacaoGlobal"] = "2026-10-05T09:00:00"
    regs[0]["objetoCompra"] = "Objeto retificado"
    pncp.on(BUSCA, pagina(regs, 1))
    await sincronizar_dia(session, client, HOJE, 6, hoje=HOJE)

    session.expire_all()
    atualizada = await session.get(Licitacao, alvo)
    assert atualizada.detalhes == Etapa.pendente and atualizada.objeto == "Objeto retificado"
    assert (await session.get(Licitacao, intocado)).detalhes == Etapa.ok


async def sincronizada(session, client, pncp) -> Licitacao:
    pncp.on(BUSCA, pagina(registros()[:1], 1))
    await sincronizar_dia(session, client, HOJE, 6, hoje=HOJE)
    return (await session.scalars(select(Licitacao))).one()


async def test_details_store_items_and_documents(session, client, pncp):
    lic = await sincronizada(session, client, pncp)
    pncp.on("/itens", httpx.Response(200, json=fixture("itens.json")))
    pncp.on("/arquivos", httpx.Response(200, json=fixture("arquivos.json")))

    assert await buscar_detalhes(session, client, lic)

    itens = (await session.scalars(select(Item).order_by(Item.numero))).all()
    assert len(itens) == len(fixture("itens.json"))
    assert itens[0].descricao and itens[0].valor_unitario is not None
    docs = (await session.scalars(select(Documento).order_by(Documento.sequencial))).all()
    assert [d.tipo_id for d in docs] == [a["tipoDocumentoId"] for a in fixture("arquivos.json")]
    assert lic.detalhes == Etapa.ok
    # Only the edital, the termo de referência and the projeto básico are read.
    a_ler = (await session.scalars(documentos_a_ler(lic.id))).all()
    assert {d.tipo_id for d in a_ler} <= {2, 4, 6} and a_ler


async def test_details_failure_is_recorded_and_retried_later(session, client, pncp):
    lic = await sincronizada(session, client, pncp)
    pncp.on("/itens", httpx.Response(503))

    assert not await buscar_detalhes(session, client, lic)
    assert lic.detalhes == Etapa.falhou and lic.detalhes_tentativas == 1
    assert "503" in lic.detalhes_erro
    assert (await session.scalars(detalhes_pendentes(10))).all() == [lic]


async def test_replaced_file_is_read_again(session, client, pncp):
    lic = await sincronizada(session, client, pncp)
    arquivos = fixture("arquivos.json")
    pncp.on("/itens", httpx.Response(200, json=[]))
    pncp.on("/arquivos", httpx.Response(200, json=arquivos))
    await buscar_detalhes(session, client, lic)
    for d in await session.scalars(select(Documento)):
        d.status = StatusDocumento.ok
    await session.commit()

    arquivos[0]["url"] += "?v=2"
    removido = arquivos.pop()
    pncp.on("/arquivos", httpx.Response(200, json=arquivos))
    await buscar_detalhes(session, client, lic)

    session.expire_all()
    docs = {d.sequencial: d for d in await session.scalars(select(Documento))}
    assert docs[arquivos[0]["sequencialDocumento"]].status == StatusDocumento.pendente
    assert docs[arquivos[1]["sequencialDocumento"]].status == StatusDocumento.ok
    assert removido["sequencialDocumento"] not in docs


async def documento(session, lic, url="https://pncp.test/doc/1") -> Documento:
    doc = Documento(licitacao_id=lic.id, sequencial=1, titulo="Edital", tipo_id=2, url=url)
    session.add(doc)
    await session.commit()
    return doc


async def test_reading_a_zip_stores_pages_with_their_source_file(session, client, pncp):
    lic = await sincronizada(session, client, pncp)
    doc = await documento(session, lic)
    conteudo = make_zip({"Edital.pdf": make_pdf([TEXTO, TEXTO]), "Anexo I.pdf": make_pdf([TEXTO])})
    pncp.on(doc.url, httpx.Response(200, content=conteudo))

    await ler_documento(session, client, doc)

    assert doc.status == StatusDocumento.ok and doc.formato == "zip" and doc.total_paginas == 3
    paginas = (await session.scalars(select(Pagina).order_by(Pagina.numero))).all()
    assert [(p.numero, p.arquivo, p.pagina_no_arquivo) for p in paginas] == [
        (1, "Edital.pdf", 1),
        (2, "Edital.pdf", 2),
        (3, "Anexo I.pdf", 1),
    ]
    # Portuguese full-text search finds "atestados" through the stem of "atestado".
    achadas = await session.scalars(
        select(Pagina.numero).where(Pagina.busca.match("atestados", postgresql_regconfig="portuguese"))
    )
    assert achadas.all() == [1, 2, 3]


async def test_rereading_replaces_old_pages(session, client, pncp):
    lic = await sincronizada(session, client, pncp)
    doc = await documento(session, lic)
    pncp.on(doc.url, httpx.Response(200, content=make_pdf([TEXTO, TEXTO, TEXTO])))
    await ler_documento(session, client, doc)
    pncp.on(doc.url, httpx.Response(200, content=make_pdf([TEXTO])))
    await ler_documento(session, client, doc)
    assert await contar(session, Pagina) == 1


async def test_unsupported_and_failed_downloads_are_recorded(session, client, pncp):
    lic = await sincronizada(session, client, pncp)
    doc = await documento(session, lic)

    pncp.on(doc.url, httpx.Response(200, content=b"Rar!\x1a\x07\x00"))
    await ler_documento(session, client, doc)
    assert doc.status == StatusDocumento.nao_suportado and doc.erro == "formato rar"
    assert (await session.scalars(documentos_a_ler(lic.id))).all() == []

    doc.status = StatusDocumento.pendente
    pncp.on(doc.url, httpx.Response(503))
    await ler_documento(session, client, doc)
    assert doc.status == StatusDocumento.falhou and doc.tentativas == 2
    assert (await session.scalars(documentos_a_ler(lic.id))).all() == [doc]
