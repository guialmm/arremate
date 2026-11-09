from app.core.config import settings
from app.llm.base import (
    LLM,
    AgenteLLM,
    Chamada,
    Ferramenta,
    LLMErro,
    LLMIndisponivel,
    Mensagem,
    Resposta,
    RespostaAgente,
    Uso,
)

__all__ = [
    "LLM", "AgenteLLM", "Chamada", "Ferramenta", "LLMErro", "LLMIndisponivel", "Mensagem",
    "Resposta", "RespostaAgente", "Uso", "get_llm",
]


def get_llm():  # GeminiLLM: implements both LLM and AgenteLLM
    from app.llm.gemini import FORA_DE_USO, GeminiLLM

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY ausente no .env")
    return GeminiLLM(settings.gemini_api_key, settings.gemini_modelos, fora_de_uso=FORA_DE_USO)
