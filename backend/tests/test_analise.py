import pytest
from sqlalchemy import func, select

from app.analise.service import SemTexto, analisar
from app.llm import Resposta, Uso
from app.models import AnaliseEdital, Documento, Item, Pagina, Perfil, StatusDocumento
from tests.test_triagem import licitacao

EDITAL_P1 = "5.1 A participação é exclusiva para microempresas e empresas de pequeno porte."
EDITAL_P2 = "9.4 Atestado de capacidade técnica de fornecimento compatível com o objeto."
ANEXO_P1 = "O prazo de entrega será de 5 (cinco) dias úteis após a ordem de fornecimento."


def citacao(pagina, trecho):
    return {"pagina": pagina, "trecho": trecho}


def analise_modelo(**override) -> dict:
    base = {
        "documentos_completos": True,
        "resumo": "Compra de canetas.",
        "exclusiva_me_epp": "sim",
        "me_epp_citacao": citacao(1, "exclusiva para microempresas e empresas de pequeno porte"),
        "criterio_julgamento": "menor preço por item",
        "prazos": [],
        "requisitos": [
            {
                "categoria": "qualificacao_tecnica",
                "exigencia": "Atestado de fornecimento",
                "situacao": "atende",
                "documento_da_empresa": "Atestado de capacidade técnica",
                "citacao": citacao(2, "Atestado de capacidade técnica de fornecimento compatível"),
            },
            {
                "categoria": "qualificacao_economico_financeira",
                "exigencia": "Balanço com índice de liquidez maior que 1",
                "situacao": "verificar",
                "documento_da_empresa": None,
                "citacao": citacao(2, "índice de liquidez geral superior a 1,0"),  # not in the edital
            },
        ],
        "condicoes": [
            {
                "tipo": "entrega",
                "descricao": "5 dias úteis",
                "citacao": citacao(1, "prazo de entrega será de 5 (cinco) dias úteis"),  # wrong page
            }
        ],
        "riscos": [],
        "recomendacao": "avaliar",
        "justificativa": "Confirmar índice de liquidez.",
    }
    return base | override


class FakeLLM:
    def __init__(self, dados: dict):
        self.dados = dados
        self.conteudos: list[str] = []

    async def estruturado(self, *, sistema, conteudo, esquema):
        self.conteudos.append(conteudo)
        return Resposta(esquema.model_validate(self.dados), Uso("fake-flash", 30000, 2000, 1.0))


async def cenario(session):
    lic = licitacao(1, "Aquisição de canetas")
    perfil = Perfil(
        nome="P",
        descricao="Vende canetas.",
        palavras_chave=["caneta"],
        ufs=[],
        documentos=["Atestado de capacidade técnica", "Cartão CNPJ"],
    )
    session.add_all([lic, perfil])
    await session.flush()
    edital = Documento(licitacao_id=lic.id, sequencial=1, titulo="Edital", tipo="Edital", tipo_id=2,
                       url="u1", status=StatusDocumento.ok)
    anexo = Documento(licitacao_id=lic.id, sequencial=2, titulo="TR.zip", tipo="Termo de Referência",
                      tipo_id=4, url="u2", status=StatusDocumento.ok)
    ignorado = Documento(licitacao_id=lic.id, sequencial=3, titulo="Parecer", tipo="Outros", tipo_id=16,
                         url="u3", status=StatusDocumento.ok)
    session.add_all([edital, anexo, ignorado])
    await session.flush()
    session.add_all(
        [
            Pagina(documento_id=edital.id, numero=1, pagina_no_arquivo=1, texto=EDITAL_P1),
            Pagina(documento_id=edital.id, numero=2, pagina_no_arquivo=2, texto=EDITAL_P2),
            Pagina(documento_id=anexo.id, numero=1, arquivo="TR.pdf", pagina_no_arquivo=1, texto=ANEXO_P1),
            Pagina(documento_id=ignorado.id, numero=1, pagina_no_arquivo=1, texto="Parecer favorável."),
            Item(licitacao_id=lic.id, numero=1, descricao="Caneta azul", beneficio="Exclusiva para ME/EPP"),
        ]
    )
    await session.commit()
    return lic, perfil, anexo


async def test_citations_are_verified_and_linked_to_document_pages(session):
    lic, perfil, anexo = await cenario(session)
    llm = FakeLLM(analise_modelo())

    a = await analisar(session, llm, perfil, lic)

    assert (a.citacoes_total, a.citacoes_verificadas) == (4, 3)
    assert (a.paginas_lidas, a.recomendacao, a.modelo) == (3, "avaliar", "fake-flash")
    me_epp = a.resultado["me_epp_citacao"]
    assert me_epp["status"] == "verificada" and me_epp["pagina_documento"] == 1
    inventada = a.resultado["requisitos"][1]["citacao"]
    assert inventada["status"] == "nao_encontrada" and "documento_id" not in inventada
    entrega = a.resultado["condicoes"][0]["citacao"]
    # Quoted as page 1, actually page 3 of the prompt = page 1 of TR.pdf inside the annex.
    assert (entrega["status"], entrega["pagina"]) == ("corrigida", 3)
    assert (entrega["documento_id"], entrega["arquivo"], entrega["pagina_no_arquivo"]) == (anexo.id, "TR.pdf", 1)


async def test_prompt_has_profile_documents_items_and_tagged_pages_only_from_read_types(session):
    lic, perfil, _ = await cenario(session)
    llm = FakeLLM(analise_modelo())
    await analisar(session, llm, perfil, lic)

    prompt = llm.conteudos[0]
    assert "- Atestado de capacidade técnica" in prompt
    assert "Caneta azul" in prompt and "[Exclusiva para ME/EPP]" in prompt
    assert "[p. 1]\n" + EDITAL_P1 in prompt
    assert "[p. 3] (TR.pdf, pág. 1)" in prompt
    assert prompt.index("===== Edital: Edital") < prompt.index("===== Termo de Referência: TR.zip")
    assert "Parecer favorável" not in prompt


async def test_rerunning_replaces_the_previous_analysis(session):
    lic, perfil, _ = await cenario(session)
    await analisar(session, FakeLLM(analise_modelo()), perfil, lic)
    a = await analisar(session, FakeLLM(analise_modelo(recomendacao="participar")), perfil, lic)
    assert await session.scalar(select(func.count()).select_from(AnaliseEdital)) == 1
    assert a.recomendacao == "participar"


async def test_tender_without_readable_text_is_refused_before_calling_the_model(session):
    lic, perfil, _ = await cenario(session)
    for doc in await session.scalars(select(Documento)):
        doc.status = StatusDocumento.nao_suportado
    await session.commit()
    llm = FakeLLM(analise_modelo())
    with pytest.raises(SemTexto):
        await analisar(session, llm, perfil, lic)
    assert llm.conteudos == []
