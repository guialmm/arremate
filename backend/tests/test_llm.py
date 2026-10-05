from types import SimpleNamespace

import pytest
from google.genai import errors
from pydantic import BaseModel

from app.llm import LLMErro, LLMIndisponivel
from app.llm.gemini import GeminiLLM


class Nota(BaseModel):
    nota: int


def erro(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})


def ok(texto: str):
    uso = SimpleNamespace(prompt_token_count=120, candidates_token_count=8)
    return SimpleNamespace(text=texto, usage_metadata=uso)


class FakeGenai:
    """Mimics client.aio.models.generate_content with a script of outcomes."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.models_called: list[str] = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, *, model, contents, config):
        self.models_called.append(model)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def llm(fake, modelos=("novo", "estavel"), rodadas=3):
    sleeps = []

    async def sleep(s):
        sleeps.append(s)

    g = GeminiLLM("k", list(modelos), max_rodadas=rodadas, client=fake, sleep=sleep)
    g.sleeps = sleeps
    return g


async def test_returns_validated_data_and_usage():
    g = llm(FakeGenai(ok('{"nota": 87}')))
    r = await g.estruturado(sistema="s", conteudo="c", esquema=Nota)
    assert r.dados == Nota(nota=87)
    assert (r.uso.modelo, r.uso.tokens_entrada, r.uso.tokens_saida) == ("novo", 120, 8)


async def test_overloaded_model_falls_back_to_the_next_without_sleeping():
    fake = FakeGenai(erro(503), ok('{"nota": 10}'))
    g = llm(fake)
    r = await g.estruturado(sistema="s", conteudo="c", esquema=Nota)
    assert fake.models_called == ["novo", "estavel"]
    assert r.uso.modelo == "estavel" and g.sleeps == []


async def test_retired_model_is_skipped():
    fake = FakeGenai(erro(404), ok('{"nota": 1}'))
    assert (await llm(fake).estruturado(sistema="s", conteudo="c", esquema=Nota)).dados.nota == 1


async def test_sleeps_between_rounds_then_gives_up():
    fake = FakeGenai(*[erro(429)] * 6)
    g = llm(fake)
    with pytest.raises(LLMIndisponivel, match="estavel: 429"):
        await g.estruturado(sistema="s", conteudo="c", esquema=Nota)
    assert len(fake.models_called) == 6
    assert len(g.sleeps) == 2 and g.sleeps[1] > g.sleeps[0] - 3  # grows each round


async def test_recovers_in_a_later_round():
    fake = FakeGenai(erro(503), erro(503), ok('{"nota": 5}'))
    g = llm(fake)
    assert (await g.estruturado(sistema="s", conteudo="c", esquema=Nota)).dados.nota == 5
    assert len(g.sleeps) == 1


async def test_bad_request_is_not_retried():
    fake = FakeGenai(erro(400))
    with pytest.raises(LLMErro) as exc:
        await llm(fake).estruturado(sistema="s", conteudo="c", esquema=Nota)
    assert not isinstance(exc.value, LLMIndisponivel)
    assert fake.models_called == ["novo"]


async def test_answer_outside_the_schema_is_an_error():
    with pytest.raises(LLMErro, match="fora do esquema"):
        await llm(FakeGenai(ok('{"nota": "alta"}'))).estruturado(sistema="s", conteudo="c", esquema=Nota)
