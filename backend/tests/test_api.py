import httpx
import pytest
from sqlalchemy import func, select

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


# --- Perguntas ao agente ----------------------------------------------------

from app.api import rotas  # noqa: E402
from app.llm import get_llm  # noqa: E402
from app.models import Pergunta  # noqa: E402
from tests.test_agente import AgenteFalso, cenario as cenario_agente  # noqa: E402


@pytest.fixture
def agente(monkeypatch):
    llm = AgenteFalso(
        [("buscar_trechos", {"consulta": "amostra"})],
        {"resposta": "Sim, em 3 dias úteis.", "citacoes": [{"pagina": 2, "trecho": "deverá apresentar amostra do item 4"}]},
    )
    llm.vezes = 0
    original = llm.agente

    async def contando(**kw):
        llm.vezes += 1
        return await original(**kw)

    llm.agente = contando
    app.dependency_overrides[get_llm] = lambda: llm
    monkeypatch.setattr(rotas, "limite_ip", rotas.Limite(2, janela_s=600))
    yield llm
    app.dependency_overrides.clear()


async def test_pergunta_responde_com_citacao_e_repetida_vem_do_cache(api, session, agente):
    lic, *_ = await cenario_agente(session)
    url = f"/api/licitacoes/{lic.id}/perguntar"
    r = await api.post(url, json={"pergunta": "Precisa de amostra?"})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["do_cache"] is False and corpo["citacoes"][0]["status"] == "verificada"

    # Same question, different case and punctuation: no LLM call.
    r = await api.post(url, json={"pergunta": "precisa de AMOSTRA"})
    assert r.json()["do_cache"] is True and r.json()["resposta"] == "Sim, em 3 dias úteis."
    assert agente.vezes == 1

    # A follow-up depends on the conversation: always asks the model.
    r = await api.post(url, json={"pergunta": "Precisa de amostra?", "historico": [{"papel": "usuario", "texto": "oi"}]})
    assert r.json()["do_cache"] is False and agente.vezes == 2


async def test_limites_por_ip_e_por_dia(api, session, agente, monkeypatch):
    lic, *_ = await cenario_agente(session)
    url = f"/api/licitacoes/{lic.id}/perguntar"
    assert (await api.post(url, json={"pergunta": "pergunta um"})).status_code == 200
    assert (await api.post(url, json={"pergunta": "pergunta dois"})).status_code == 200
    r = await api.post(url, json={"pergunta": "pergunta três"})
    assert r.status_code == 429 and "seguidas" in r.json()["detail"]
    # Another visitor still gets through, until the daily cap.
    outro = {"X-Forwarded-For": "200.1.1.1"}
    monkeypatch.setattr(rotas.settings, "perguntas_por_dia", 2)
    r = await api.post(url, json={"pergunta": "pergunta quatro"}, headers=outro)
    assert r.status_code == 429 and "diário" in r.json()["detail"]
    # Cached answers keep working after the cap.
    assert (await api.post(url, json={"pergunta": "pergunta um"}, headers=outro)).json()["do_cache"] is True
    assert await session.scalar(select(func.count()).select_from(Pergunta)) == 2


async def test_pergunta_invalida_ou_sem_texto(api, session, agente):
    lic, *_ = await cenario_agente(session)
    assert (await api.post(f"/api/licitacoes/{lic.id}/perguntar", json={"pergunta": "?"})).status_code == 422
    vazia = licitacao(9, "Sem documentos")
    session.add(vazia)
    await session.commit()
    assert (await api.post(f"/api/licitacoes/{vazia.id}/perguntar", json={"pergunta": "Tem amostra?"})).status_code == 409


async def test_cors_so_para_o_site(api):
    pre = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    ok = await api.options("/api/health", headers={"Origin": "http://localhost:3002", **pre})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3002"
    outro = await api.options("/api/health", headers={"Origin": "https://malicioso.example", **pre})
    assert "access-control-allow-origin" not in outro.headers
