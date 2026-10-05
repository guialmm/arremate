import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.llm import LLMIndisponivel, Resposta, Uso
from app.models import Licitacao, Perfil, Triagem
from app.triagem.service import AvaliacaoLote, candidatas, montar_conteudo, triar

AGORA = datetime.now(timezone.utc)


class FakeLLM:
    """Scores each listed tender with a rule; records every prompt."""

    def __init__(self, nota=lambda objeto: 90, falhar: int = 0, pular: set[int] = frozenset()):
        self.nota = nota
        self.falhar = falhar
        self.pular = pular
        self.chamadas: list[str] = []

    async def estruturado(self, *, sistema, conteudo, esquema):
        self.chamadas.append(conteudo)
        if self.falhar:
            self.falhar -= 1
            raise LLMIndisponivel("503")
        itens = re.findall(r"^(\d+)\. (.+)$", conteudo, re.M)
        dados = esquema.model_validate(
            {
                "avaliacoes": [
                    {"n": int(n), "nota": self.nota(obj), "motivo": f"avaliado: {obj[:20]}"}
                    for n, obj in itens
                    if int(n) not in self.pular
                ]
            }
        )
        return Resposta(dados, Uso("fake-flash", 100, 50, 0.1))


def licitacao(n: int, objeto: str, uf="PR", valor="50000", encerra=AGORA + timedelta(days=5)):
    return Licitacao(
        id=f"00000000000100-1-{n:06d}/2026",
        cnpj="00000000000100",
        ano=2026,
        sequencial=n,
        orgao=f"Prefeitura {n}",
        municipio="Curitiba",
        uf=uf,
        modalidade_id=6,
        modalidade="Pregão - Eletrônico",
        objeto=objeto,
        valor_estimado=Decimal(valor) if valor else None,
        situacao="Divulgada no PNCP",
        publicada_em=AGORA - timedelta(days=1),
        encerramento_propostas=encerra,
        raw={},
    )


async def perfil(session, **extra) -> Perfil:
    p = Perfil(
        nome="Papelaria",
        descricao="Vende material de escritório.",
        palavras_chave=["material de escritório", "caneta", "papel sulfite"],
        ufs=["PR", "SC"],
        valor_minimo=Decimal("1000"),
        valor_maximo=Decimal("100000"),
        documentos=[],
        **extra,
    )
    session.add(p)
    await session.commit()
    return p


async def ids(session, query) -> set[int]:
    return {lic.sequencial for lic in (await session.scalars(query)).all()}


async def test_prefilter_uses_stemming_phrases_state_value_and_deadline(session):
    session.add_all(
        [
            licitacao(1, "Aquisição de canetas esferográficas azuis"),  # plural via stemming
            licitacao(2, "Aquisição de MATERIAL DE ESCRITÓRIO para secretarias"),
            licitacao(3, "Material de limpeza e escritório"),  # words present, not the phrase
            licitacao(4, "Compra de canetas", uf="SP"),  # outside the states served
            licitacao(5, "Compra de canetas", valor="500"),  # below the minimum
            licitacao(6, "Compra de canetas", valor="900000"),  # above the maximum
            licitacao(7, "Compra de canetas", valor=None),  # undisclosed: kept
            licitacao(8, "Compra de canetas", encerra=AGORA - timedelta(hours=1)),  # closed
            licitacao(9, "Compra de canetas", encerra=None),  # no deadline published: kept
            licitacao(10, "Pavimentação asfáltica"),
        ]
    )
    await session.commit()
    p = await perfil(session)
    assert await ids(session, candidatas(p, 50)) == {1, 2, 7, 9}


async def test_profile_without_states_or_values_covers_brazil(session):
    session.add_all([licitacao(1, "Caneta", uf="AM", valor=None), licitacao(2, "Caneta", uf="SP")])
    await session.commit()
    p = await perfil(session)
    p.ufs, p.valor_minimo, p.valor_maximo = [], None, None
    assert await ids(session, candidatas(p, 50)) == {1, 2}


async def test_triage_scores_in_batches_and_marks_relevance(session):
    session.add_all([licitacao(n, f"Fornecimento de caneta lote {n}") for n in range(1, 26)])
    session.add(licitacao(99, "Fornecimento de caneta para manutenção de impressoras"))
    await session.commit()
    p = await perfil(session)
    llm = FakeLLM(nota=lambda obj: 20 if "manutenção" in obj else 85)

    r = await triar(session, llm, p)

    assert (r.candidatas, r.avaliadas, r.relevantes) == (26, 26, 25)
    assert len(llm.chamadas) == 2  # 20 + 6
    t = await session.scalar(select(Triagem).join(Licitacao).where(Licitacao.sequencial == 99))
    assert (t.nota, t.relevante, t.modelo) == (20, False, "fake-flash")


async def test_triaged_tenders_are_not_sent_again(session):
    session.add_all([licitacao(1, "Caneta azul"), licitacao(2, "Caneta preta")])
    await session.commit()
    p = await perfil(session)
    await triar(session, FakeLLM(), p)

    session.add(licitacao(3, "Caneta vermelha"))
    await session.commit()
    llm = FakeLLM()
    r = await triar(session, llm, p)
    assert r.avaliadas == 1 and "vermelha" in llm.chamadas[0] and "azul" not in llm.chamadas[0]


async def test_failed_batch_is_retried_on_the_next_run(session):
    session.add_all([licitacao(n, f"Caneta {n}") for n in range(1, 31)])
    await session.commit()
    p = await perfil(session)

    r = await triar(session, FakeLLM(falhar=1), p)
    assert (r.avaliadas, r.lotes_com_erro) == (10, 1)  # second batch saved, first lost

    r = await triar(session, FakeLLM(), p)
    assert r.avaliadas == 20


async def test_tender_the_model_skipped_is_not_guessed(session):
    session.add_all([licitacao(n, f"Caneta {n}") for n in range(1, 4)])
    await session.commit()
    p = await perfil(session)
    r = await triar(session, FakeLLM(pular={2}), p)
    assert r.avaliadas == 2
    assert await ids(session, candidatas(p, 50)) == {2}  # comes back next time


async def test_prompt_numbers_tenders_and_truncates_long_objects():
    p = Perfil(descricao="Vende canetas.", ufs=["PR"], palavras_chave=[], documentos=[])
    longo = "Aquisição de canetas " + "item " * 400
    texto = montar_conteudo(p, [licitacao(1, "Caneta azul", valor=None), licitacao(2, longo)])
    assert "1. Caneta azul" in texto and "Valor estimado: não informado" in texto
    assert "2. Aquisição de canetas" in texto and "…" in texto
    assert "Valor estimado: R$ 50.000,00" in texto
    assert "Atua em: PR" in texto


def test_schema_rejects_scores_out_of_range():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AvaliacaoLote.model_validate({"avaliacoes": [{"n": 1, "nota": 140, "motivo": "x"}]})
