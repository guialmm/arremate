import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.llm.base import LLMErro, LLMIndisponivel, Resposta, T, Uso

log = logging.getLogger(__name__)

# Free tier: newest models answer 503 "high demand" at peak hours, older
# aliases keep working. Rate limits answer 429. Both are worth another try.
TRANSITORIOS = {429, 500, 503, 504}


class GeminiLLM:
    def __init__(
        self,
        api_key: str,
        modelos: list[str],
        *,
        max_rodadas: int = 4,
        client: genai.Client | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        if not modelos:
            raise ValueError("at least one model")
        self.client = client or genai.Client(api_key=api_key)
        self.modelos = modelos
        self.max_rodadas = max_rodadas
        self.sleep = sleep

    async def estruturado(self, *, sistema: str, conteudo: str, esquema: type[T]) -> Resposta[T]:
        config = types.GenerateContentConfig(
            system_instruction=sistema,
            response_mime_type="application/json",
            response_schema=esquema,
            temperature=0,
            # No tools are passed; this only silences the SDK's AFC warning.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        ultimo = ""
        for rodada in range(self.max_rodadas):
            # Fall through the models in order of preference before sleeping.
            for modelo in self.modelos:
                inicio = time.monotonic()
                try:
                    r = await self.client.aio.models.generate_content(
                        model=modelo, contents=conteudo, config=config
                    )
                except errors.APIError as exc:
                    if exc.code in TRANSITORIOS or exc.code == 404:  # 404: model retired
                        ultimo = f"{modelo}: {exc.code}"
                        log.info("gemini %s indisponível (%s)", modelo, exc.code)
                        continue
                    raise LLMErro(f"{modelo}: {exc.code} {exc.message}") from exc
                try:
                    dados = esquema.model_validate_json(r.text or "")
                except ValidationError as exc:
                    raise LLMErro(f"{modelo} respondeu fora do esquema: {exc}") from exc
                u = r.usage_metadata
                return Resposta(
                    dados,
                    Uso(
                        modelo=modelo,
                        tokens_entrada=(u.prompt_token_count or 0) if u else 0,
                        tokens_saida=(u.candidates_token_count or 0) if u else 0,
                        segundos=time.monotonic() - inicio,
                    ),
                )
            if rodada + 1 < self.max_rodadas:
                await self.sleep(min(10 * 2**rodada, 90) + random.uniform(0, 3))
        raise LLMIndisponivel(f"todos os modelos falharam {self.max_rodadas}x (último: {ultimo})")
