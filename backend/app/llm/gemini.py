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


# Models that just failed sit out for a while, shared by every request of the process:
# without it, each step of an agent conversation would wait on the same dead model again.
RESFRIAMENTO_S = 300
FORA_DE_USO: dict[str, float] = {}


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
        timeout_agente_s: float = 60,  # agent turns: a few pages of context at most
        fora_de_uso: dict[str, float] | None = None,
        client: genai.Client | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        relogio: Callable[[], float] = time.monotonic,
    ):
        if not modelos:
            raise ValueError("at least one model")
        self.client = client or genai.Client(api_key=api_key)
        self.modelos = modelos
        self.max_rodadas = max_rodadas
        self.timeout_s = timeout_s
        self.timeout_agente_s = timeout_agente_s
        self.fora_de_uso = {} if fora_de_uso is None else fora_de_uso
        self.sleep = sleep
        self.relogio = relogio

    def _fila(self) -> list[str]:
        """Models in order of preference, the ones cooling down skipped (unless all are)."""
        agora = self.relogio()
        prontos = [m for m in self.modelos if self.fora_de_uso.get(m, 0) <= agora]
        return prontos or self.modelos

    async def _gerar(self, contents, config: types.GenerateContentConfig, timeout_s: float, espera_base: float):
        """One call with model fallback; returns (response, model, seconds)."""
        ultimo = ""
        for rodada in range(self.max_rodadas):
            # Fall through the models in order of preference before sleeping.
            for modelo in self._fila():
                inicio = self.relogio()
                try:
                    r = await asyncio.wait_for(
                        self.client.aio.models.generate_content(model=modelo, contents=contents, config=config),
                        timeout_s,
                    )
                    return r, modelo, self.relogio() - inicio
                except TimeoutError:
                    ultimo = f"{modelo}: sem resposta em {timeout_s:.0f}s"
                except errors.APIError as exc:
                    if exc.code not in TRANSITORIOS and exc.code != 404:  # 404: model retired
                        raise LLMErro(f"{modelo}: {exc.code} {exc.message}") from exc
                    ultimo = f"{modelo}: {exc.code}"
                log.info("gemini %s fora por %ss (%s)", modelo, RESFRIAMENTO_S, ultimo)
                self.fora_de_uso[modelo] = self.relogio() + RESFRIAMENTO_S
            if rodada + 1 < self.max_rodadas:
                await self.sleep(min(espera_base * 2**rodada, 90) + random.uniform(0, 3))
        raise LLMIndisponivel(f"todos os modelos falharam {self.max_rodadas}x (último: {ultimo})")

    async def estruturado(self, *, sistema: str, conteudo: str, esquema: type[T]) -> Resposta[T]:
        config = types.GenerateContentConfig(
            system_instruction=sistema,
            response_mime_type="application/json",
            response_schema=esquema,
            temperature=0,
            # No tools are passed; this only silences the SDK's AFC warning.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        r, modelo, segundos = await self._gerar(conteudo, config, self.timeout_s, espera_base=10)
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
                segundos=segundos,
            ),
        )

    # --- Tool use ---------------------------------------------------------

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
        inicio = self.relogio()
        # Last step: only the closing tool is allowed, so the model answers with what it read.
        so_final = config.model_copy(
            update={
                "tool_config": types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode=types.FunctionCallingConfigMode.ANY, allowed_function_names=[final]
                    )
                )
            }
        )
        for passo in range(max_passos):
            atual = so_final if passo == max_passos - 1 else config
            r, modelo, _ = await self._gerar(contents, atual, self.timeout_agente_s, espera_base=5)
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
                    uso = Uso(modelo, entrada, saida, self.relogio() - inicio)
                    return RespostaAgente(final=args, chamadas=chamadas, uso=uso)
                resultado = await executar(f.name, args)
                chamadas.append(Chamada(f.name, args, resultado))
                respostas.append(
                    types.Part(function_response=types.FunctionResponse(id=f.id, name=f.name, response=resultado))
                )
            contents.append(types.Content(role="user", parts=respostas))
        raise LLMErro(f"{modelo} não respondeu em {max_passos} passos")
