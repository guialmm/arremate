from types import SimpleNamespace

import pytest

from app.agente.ferramentas import FerramentasEdital
from app.agente.service import perguntar
from app.analise.service import SemTexto, carregar_paginas
from app.llm import Chamada, LLMErro, Mensagem, RespostaAgente, Uso
from app.llm.gemini import GeminiLLM
from app.models import Documento, Item, Pagina, StatusDocumento
from tests.test_triagem import licitacao

P1 = "5.1 A participação é exclusiva para microempresas e empresas de pequeno porte."
P2 = "8.3 A licitante vencedora deverá apresentar amostra do item 4 no prazo de 3 dias úteis."
ANEXO = "O prazo de entrega será de 10 (dez) dias corridos após a emissão do empenho."


async def cenario(session):
    lic = licitacao(1, "Aquisição de canetas")
    session.add(lic)
    await session.flush()
    edital = Documento(licitacao_id=lic.id, sequencial=1, titulo="Edital", tipo_id=2, tipo="Edital",
                       url="https://x/1", status=StatusDocumento.ok, total_paginas=2)
    anexo = Documento(licitacao_id=lic.id, sequencial=2, titulo="TR", tipo_id=4, tipo="Termo de Referência",
                      url="https://x/2", status=StatusDocumento.ok, total_paginas=1)
    session.add_all([edital, anexo])
    await session.flush()
    session.add_all([
        Pagina(documento_id=edital.id, numero=1, pagina_no_arquivo=1, texto=P1),
        Pagina(documento_id=edital.id, numero=2, pagina_no_arquivo=2, texto=P2),
        Pagina(documento_id=anexo.id, numero=1, pagina_no_arquivo=1, texto=ANEXO),
        Item(licitacao_id=lic.id, numero=4, descricao="Caneta esferográfica azul", unidade="CX", beneficio="Exclusiva ME/EPP"),
    ])
    await session.commit()
    return lic, edital, anexo


async def test_busca_acha_pagina_com_todas_ou_alguma_palavra(session):
    lic, *_ = await cenario(session)
    f = FerramentasEdital(session, lic.id, await carregar_paginas(session, lic.id))
    r = await f.executar("buscar_trechos", {"consulta": "amostra prazo"})
    assert r["resultados"][0]["pagina"] == 2  # global page: edital p.2
    assert "«amostra»" in r["resultados"][0]["trecho"]
    # "entrega" + a word in no page: falls back to OR and still finds the annex (global p.3)
    r = await f.executar("buscar_trechos", {"consulta": "entrega helicóptero"})
    assert [x["pagina"] for x in r["resultados"]] == [3]
    assert (await f.executar("buscar_trechos", {"consulta": "helicóptero"}))["resultados"] == []


async def test_ferramentas_nunca_levantam_erro(session):
    lic, *_ = await cenario(session)
    f = FerramentasEdital(session, lic.id, await carregar_paginas(session, lic.id))
    assert "erro" in f.ler_pagina(99)
    assert "erro" in await f.executar("ler_pagina", {"pagina": "dois"})
    assert "erro" in await f.executar("apagar_tudo", {})
    assert "erro" in await f.executar("buscar_trechos", {"consulta": "  "})
    assert (await f.executar("listar_itens", {}))["itens"][0]["beneficio"] == "Exclusiva ME/EPP"


class AgenteFalso:
    """Plays a scripted tool session through the real executor, then answers."""

    def __init__(self, roteiro, final):
        self.roteiro, self.final = roteiro, final
        self.mensagens = None

    async def agente(self, *, sistema, mensagens, ferramentas, executar, final, max_passos=8):
        self.sistema, self.mensagens = sistema, mensagens
        chamadas = [Chamada(n, a, await executar(n, a)) for n, a in self.roteiro]
        return RespostaAgente(self.final, chamadas, Uso("falso", 10, 5, 1.0))


async def test_citacoes_verificadas_e_corrigidas(session):
    lic, edital, anexo = await cenario(session)
    llm = AgenteFalso(
        [("buscar_trechos", {"consulta": "amostra"}), ("ler_pagina", {"pagina": 2})],
        {
            "resposta": "Sim, amostra do item 4 em 3 dias úteis; entrega em 10 dias corridos.",
            "citacoes": [
                {"pagina": 2, "trecho": "deverá apresentar amostra do item 4 no prazo de 3 dias úteis"},
                {"pagina": 1, "trecho": "prazo de entrega será de 10 (dez) dias corridos"},  # wrong page
                {"pagina": 2, "trecho": "a amostra será analisada por comissão técnica"},  # invented
                {"pagina": "x"},  # malformed: dropped
            ],
        },
    )
    historico = [Mensagem("usuario", "É exclusiva ME?"), Mensagem("assistente", "Sim.")]
    r = await perguntar(session, llm, lic, "Precisa de amostra?", historico)

    assert [c["status"] for c in r.citacoes] == ["verificada", "corrigida", "nao_encontrada"]
    assert r.citacoes[1]["pagina"] == 3 and r.citacoes[1]["documento_id"] == anexo.id
    assert r.citacoes[0]["pagina_documento"] == 2 and r.citacoes[0]["documento_id"] == edital.id
    assert "documento_id" not in r.citacoes[2]
    assert [f["nome"] for f in r.ferramentas] == ["buscar_trechos", "ler_pagina"]
    assert llm.mensagens[-1] == Mensagem("usuario", "Precisa de amostra?") and len(llm.mensagens) == 3
    assert "3 páginas" in llm.sistema


async def test_sem_texto(session):
    lic = licitacao(2, "x")
    session.add(lic)
    await session.commit()
    with pytest.raises(SemTexto):
        await perguntar(session, AgenteFalso([], {}), lic, "?")


# --- Gemini tool loop -----------------------------------------------------


def turno(*chamadas):
    fcs = [SimpleNamespace(name=n, args=a, id=f"c{i}") for i, (n, a) in enumerate(chamadas)]
    uso = SimpleNamespace(prompt_token_count=100, candidates_token_count=10, thoughts_token_count=5)
    return SimpleNamespace(function_calls=fcs, candidates=[SimpleNamespace(content=f"turno {chamadas}")], usage_metadata=uso)


class GenaiRoteiro:
    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.contents = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._gerar))

    async def _gerar(self, *, model, contents, config):
        self.contents.append(list(contents))
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


async def test_laco_do_gemini_executa_ferramentas_ate_responder():
    from tests.test_llm import erro

    fake = GenaiRoteiro(
        turno(("buscar_trechos", {"consulta": "amostra"})),
        erro(503),  # first model overloaded mid-conversation: the next one continues
        turno(("ler_pagina", {"pagina": 2}), ("responder", {"resposta": "Sim.", "citacoes": []})),
    )
    feitas = []

    async def executar(nome, args):
        feitas.append(nome)
        return {"ok": True}

    async def sem_espera(_):
        pass

    g = GeminiLLM("k", ["novo", "estavel"], client=fake, sleep=sem_espera)
    r = await g.agente(sistema="s", mensagens=[Mensagem("usuario", "?")], ferramentas=[], executar=executar, final="responder")
    assert r.final == {"resposta": "Sim.", "citacoes": []}
    assert feitas == ["buscar_trechos", "ler_pagina"]
    assert [c.nome for c in r.chamadas] == ["buscar_trechos", "ler_pagina"]
    assert r.uso.modelo == "estavel" and r.uso.tokens_entrada == 200 and r.uso.tokens_saida == 30
    # The model's own turn is sent back before the tool results.
    assert fake.contents[-1][1] == "turno (('buscar_trechos', {'consulta': 'amostra'}),)"


async def test_laco_do_gemini_desiste_depois_de_max_passos():
    fake = GenaiRoteiro(*[turno(("buscar_trechos", {"consulta": "x"}))] * 3)

    async def executar(nome, args):
        return {}

    g = GeminiLLM("k", ["m"], client=fake)
    with pytest.raises(LLMErro):
        await g.agente(sistema="s", mensagens=[Mensagem("usuario", "?")], ferramentas=[], executar=executar,
                       final="responder", max_passos=3)
