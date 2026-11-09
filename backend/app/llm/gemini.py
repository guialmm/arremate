import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.llm.base import (
    Chamada,
    Executor,
    Ferramenta,
    LLMErro,
    LLMIndisponivel,
    Mensagem,
    Resposta,
    RespostaAgente,
    T,
    Uso,
)

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
        # Free-tier models sometimes accept a request and never answer: give up and
        # fall through to the next model instead of hanging. A 70k-token edital takes ~1 min.
        timeout_s: float = 150,
        client: genai.Client | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        if not modelos:
            raise ValueError("at least one model")
        self.client = client or genai.Client(api_key=api_key)
        self.modelos = modelos
        self.max_rodadas = max_rodadas
        self.timeout_s = timeout_s
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
                    r = await asyncio.wait_for(
                        self.client.aio.models.generate_content(model=modelo, contents=conteudo, config=config),
                        self.timeout_s,
                    )
                except TimeoutError:
                    ultimo = f"{modelo}: sem resposta em {self.timeout_s:.0f}s"
                    log.info("gemini %s não respondeu a tempo", modelo)
                    continue
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

    # --- Tool use ---------------------------------------------------------

    async def _gerar(self, contents: list, config: types.GenerateContentConfig):
        """One call with model fallback; returns (response, model)."""
        ultimo = ""
        for rodada in range(self.max_rodadas):
            for modelo in self.modelos:
                try:
                    r = await asyncio.wait_for(
                        self.client.aio.models.generate_content(model=modelo, contents=contents, config=config),
                        self.timeout_s,
                    )
                    return r, modelo
                except TimeoutError:
                    ultimo = f"{modelo}: sem resposta em {self.timeout_s:.0f}s"
                    log.info("gemini %s não respondeu a tempo", modelo)
                    continue
                except errors.APIError as exc:
                    if exc.code in TRANSITORIOS or exc.code == 404:
                        ultimo = f"{modelo}: {exc.code}"
                        log.info("gemini %s indisponível (%s)", modelo, exc.code)
                        continue
                    raise LLMErro(f"{modelo}: {exc.code} {exc.message}") from exc
            if rodada + 1 < self.max_rodadas:
                await self.sleep(min(5 * 2**rodada, 40) + random.uniform(0, 2))
        raise LLMIndisponivel(f"todos os modelos falharam {self.max_rodadas}x (último: {ultimo})")

    async def agente(
        self,
        *,
        sistema: str,
        mensagens: list[Mensagem],
        ferramentas: list[Ferramenta],
        executar: Executor,
        final: str,
        max_passos: int = 8,
    ) -> RespostaAgente:
        config = types.GenerateContentConfig(
            system_instruction=sistema,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=f.nome, description=f.descricao, parameters_json_schema=f.parametros
                        )
                        for f in ferramentas
                    ]
                )
            ],
            # ANY: every turn is a tool call, so the answer always arrives through `final`.
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.ANY)
            ),
            temperature=0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = [
            types.Content(role="user" if m.papel == "usuario" else "model", parts=[types.Part(text=m.texto)])
            for m in mensagens
        ]
        chamadas: list[Chamada] = []
        entrada = saida = 0
        modelo = self.modelos[0]
        inicio = time.monotonic()
        for _ in range(max_passos):
            r, modelo = await self._gerar(contents, config)
            if u := r.usage_metadata:
                entrada += u.prompt_token_count or 0
                saida += (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
            pedidas = r.function_calls or []
            if not pedidas:
                raise LLMErro(f"{modelo} respondeu sem chamar ferramenta")
            # The model's own turn goes back as-is: Gemini 3 checks its thought signatures.
            contents.append(r.candidates[0].content)
            respostas = []
            for f in pedidas:
                args = dict(f.args or {})
                if f.name == final:
                    uso = Uso(modelo, entrada, saida, time.monotonic() - inicio)
                    return RespostaAgente(final=args, chamadas=chamadas, uso=uso)
                resultado = await executar(f.name, args)
                chamadas.append(Chamada(f.name, args, resultado))
                respostas.append(
                    types.Part(function_response=types.FunctionResponse(id=f.id, name=f.name, response=resultado))
                )
            contents.append(types.Content(role="user", parts=respostas))
        raise LLMErro(f"{modelo} não respondeu em {max_passos} passos")
