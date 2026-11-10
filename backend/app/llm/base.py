"""Provider-neutral interface: the analysis code never imports a vendor SDK.

Gemini's free tier runs the project at zero cost; a Claude adapter can be
added behind the same interface without touching triage or analysis.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

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


# --- Tool use -------------------------------------------------------------


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    parametros: dict  # JSON Schema of the arguments


@dataclass
class Chamada:
    nome: str
    argumentos: dict
    resultado: dict | None = None


@dataclass
class Mensagem:
    papel: Literal["usuario", "assistente"]
    texto: str


@dataclass
class RespostaAgente:
    final: dict  # arguments of the closing tool
    chamadas: list[Chamada]  # every tool call before it, in order
    uso: Uso


Executor = Callable[[str, dict], Awaitable[dict]]


class AgenteLLM(Protocol):
    async def agente(
        self,
        *,
        sistema: str,
        mensagens: list[Mensagem],
        ferramentas: list[Ferramenta],
        executar: Executor,
        final: str,
        max_passos: int = 10,
    ) -> RespostaAgente:
        """Let the model call tools until it calls `final`, whose arguments are the answer.
        `executar` must never raise: errors go back to the model as {"erro": ...}."""
        ...
