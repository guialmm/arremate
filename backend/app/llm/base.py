"""Provider-neutral interface: the analysis code never imports a vendor SDK.

Gemini's free tier runs the project at zero cost; a Claude adapter can be
added behind the same interface without touching triage or analysis.
"""

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMErro(Exception):
    """The provider refused the request or returned something unusable."""


class LLMIndisponivel(LLMErro):
    """Every model stayed overloaded or rate-limited through every retry."""


@dataclass
class Uso:
    modelo: str
    tokens_entrada: int
    tokens_saida: int
    segundos: float


@dataclass
class Resposta(Generic[T]):
    dados: T
    uso: Uso


class LLM(Protocol):
    async def estruturado(self, *, sistema: str, conteudo: str, esquema: type[T]) -> Resposta[T]:
        """One call whose answer must validate against `esquema`."""
        ...
