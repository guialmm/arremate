from datetime import date

import httpx
import pytest

from app.pncp.client import ArquivoGrande, PncpErro, PncpIndisponivel
from tests.conftest import fixture

BUSCA = "/consulta/v1/contratacoes/publicacao"


async def test_publicacoes_sends_the_day_and_parses_the_page(client, pncp):
    pncp.on(BUSCA, httpx.Response(200, json=fixture("publicacoes.json")))
    pagina = await client.publicacoes(date(2026, 10, 1), 6, 2)

    assert len(pagina.registros) == 10
    assert pagina.total_registros > 1000
    params = pncp.calls[0].url.params
    assert params["dataInicial"] == params["dataFinal"] == "20261001"
    assert params["pagina"] == "2" and params["tamanhoPagina"] == "50"


async def test_empty_day_is_204(client, pncp):
    pncp.on(BUSCA, httpx.Response(204))
    pagina = await client.publicacoes(date(2026, 10, 4), 6, 1)
    assert pagina.registros == [] and pagina.total_paginas == 0


async def test_retries_502_and_503_then_succeeds(client, pncp):
    pncp.on(
        BUSCA,
        httpx.Response(502),
        httpx.Response(503, headers={"Retry-After": "7"}),
        httpx.Response(200, json=fixture("publicacoes.json")),
    )
    pagina = await client.publicacoes(date(2026, 10, 1), 6, 1)

    assert len(pagina.registros) == 10
    assert len(pncp.calls) == 3
    assert client.sleeps[1] == 7  # Retry-After wins over the backoff


async def test_retries_timeouts(client, pncp):
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    pncp.on(BUSCA, timeout, httpx.Response(204))
    await client.publicacoes(date(2026, 10, 1), 6, 1)
    assert len(pncp.calls) == 2


async def test_gives_up_after_max_attempts(client, pncp):
    pncp.on(BUSCA, httpx.Response(503))
    with pytest.raises(PncpIndisponivel, match="HTTP 503 após 3 tentativas"):
        await client.publicacoes(date(2026, 10, 1), 6, 1)
    assert len(pncp.calls) == 3
    assert len(client.sleeps) == 2  # no pointless sleep after the last attempt


async def test_client_errors_are_not_retried(client, pncp):
    pncp.on(BUSCA, httpx.Response(400, json={"message": "Tamanho de página inválido"}))
    with pytest.raises(PncpErro, match="Tamanho de página inválido") as exc:
        await client.publicacoes(date(2026, 10, 1), 6, 1)
    assert not isinstance(exc.value, PncpIndisponivel)
    assert len(pncp.calls) == 1


async def test_itens_follow_pages_until_a_short_one(client, pncp):
    cheia = [{"numeroItem": i} for i in range(50)]
    pncp.on("/itens", httpx.Response(200, json=cheia), httpx.Response(200, json=[{"numeroItem": 50}]))
    itens = await client.itens("123", 2026, 7)
    assert len(itens) == 51
    assert [c.url.params["pagina"] for c in pncp.calls] == ["1", "2"]


async def test_download_returns_bytes_and_filename(client, pncp):
    pncp.on(
        "https://pncp.test/arquivo/1",
        httpx.Response(
            200,
            content=b"%PDF-conteudo",
            headers={"content-disposition": 'attachment; filename="904496.pdf"'},
        ),
    )
    baixado = await client.baixar("https://pncp.test/arquivo/1", 1000)
    assert baixado.conteudo == b"%PDF-conteudo"
    assert baixado.nome_arquivo == "904496.pdf"


async def test_download_refuses_files_over_the_limit(client, pncp):
    pncp.on("https://pncp.test/grande", httpx.Response(200, content=b"x" * 2000))
    with pytest.raises(ArquivoGrande):
        await client.baixar("https://pncp.test/grande", 1000)


async def test_download_retries_server_errors(client, pncp):
    pncp.on("https://pncp.test/a", httpx.Response(503), httpx.Response(200, content=b"ok"))
    assert (await client.baixar("https://pncp.test/a", 1000)).conteudo == b"ok"

    pncp.on("https://pncp.test/b", httpx.Response(503))
    with pytest.raises(PncpIndisponivel):
        await client.baixar("https://pncp.test/b", 1000)
