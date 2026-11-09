import httpx
import pytest

from app.main import app
from app.models import AnaliseEdital, Documento, Pagina, StatusDocumento, Triagem
from tests.test_triagem import licitacao, perfil


@pytest.fixture
async def api():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def cenario(session):
    p = await perfil(session)
    analisada = licitacao(1, "Aquisição de canetas")
    triada = licitacao(2, "Aquisição de papel sulfite")
    descartada = licitacao(3, "Reforma de escola")
    session.add_all([analisada, triada, descartada])
    await session.flush()
    session.add_all(
        [
            Triagem(perfil_id=p.id, licitacao_id=analisada.id, nota=70, relevante=True, motivo="canetas", modelo="m"),
            Triagem(perfil_id=p.id, licitacao_id=triada.id, nota=90, relevante=True, motivo="papel", modelo="m"),
            Triagem(perfil_id=p.id, licitacao_id=descartada.id, nota=5, relevante=False, motivo="obra", modelo="m"),
        ]
    )
    doc = Documento(
        licitacao_id=analisada.id, sequencial=1, titulo="Edital", url="https://x/1",
        status=StatusDocumento.ok, total_paginas=1,
    )
    session.add(doc)
    await session.flush()
    session.add(Pagina(documento_id=doc.id, numero=1, pagina_no_arquivo=1, texto="5.1 Exclusiva para ME/EPP."))
    session.add(
        AnaliseEdital(
            perfil_id=p.id, licitacao_id=analisada.id, resultado={"resumo": "Canetas."},
            recomendacao="participar", modelo="m", paginas_lidas=1, tokens_entrada=1,
            tokens_saida=1, segundos=1.0, citacoes_total=3, citacoes_verificadas=3,
        )
    )
    await session.commit()
    return p, analisada, doc


async def test_lista_analisadas_primeiro_e_esconde_descartadas(api, session):
    p, analisada, _ = await cenario(session)
    r = await api.get(f"/api/perfis/{p.id}/licitacoes")
    assert r.status_code == 200
    lista = r.json()
    assert [x["licitacao"]["objeto"] for x in lista] == ["Aquisição de canetas", "Aquisição de papel sulfite"]
    assert lista[0]["recomendacao"] == "participar" and lista[0]["citacoes_verificadas"] == 3
    assert lista[1]["recomendacao"] is None

    todas = (await api.get(f"/api/perfis/{p.id}/licitacoes", params={"todas": True})).json()
    assert len(todas) == 3


async def test_id_do_pncp_com_barra_na_rota(api, session):
    p, analisada, _ = await cenario(session)
    assert "/" in analisada.id
    r = await api.get(f"/api/licitacoes/{analisada.id}")
    assert r.status_code == 200
    assert r.json()["documentos"][0]["titulo"] == "Edital"

    r = await api.get(f"/api/licitacoes/{analisada.id}/analise", params={"perfil_id": p.id})
    assert r.status_code == 200
    assert r.json()["resultado"]["resumo"] == "Canetas."


async def test_pagina_citada_e_404s(api, session):
    p, analisada, doc = await cenario(session)
    r = await api.get(f"/api/documentos/{doc.id}/paginas/1")
    assert r.json()["texto"] == "5.1 Exclusiva para ME/EPP."
    assert (await api.get(f"/api/documentos/{doc.id}/paginas/9")).status_code == 404
    assert (await api.get("/api/licitacoes/nao-existe")).status_code == 404
    assert (await api.get("/api/perfis/999/licitacoes")).status_code == 404
    sem_analise = licitacao(4, "x").id
    r = await api.get(f"/api/licitacoes/{sem_analise}/analise", params={"perfil_id": p.id})
    assert r.status_code == 404
