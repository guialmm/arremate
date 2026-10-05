from app.core.config import settings
from app.llm.base import LLM, LLMErro, LLMIndisponivel, Resposta, Uso

__all__ = ["LLM", "LLMErro", "LLMIndisponivel", "Resposta", "Uso", "get_llm"]


def get_llm() -> LLM:
    from app.llm.gemini import GeminiLLM

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY ausente no .env")
    return GeminiLLM(settings.gemini_api_key, settings.gemini_modelos)
