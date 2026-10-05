"""Thin async client for the PNCP public API.

The portal is a public good with public-sector uptime: 20-second responses,
502/503 bursts that last minutes, endpoints that move (with a 301 and a JSON
body instead of a Location header). Every call goes through `_get`, which
retries what is worth retrying and gives up with `PncpIndisponivel` otherwise,
so callers can mark the work as failed and let the next run pick it up.
"""

import asyncio
import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

import httpx

from app.core.config import settings

# The search endpoint rejects anything above 50.
TAMANHO_PAGINA = 50
RETRY_STATUS = {429, 500, 502, 503, 504}


class PncpErro(Exception):
    """A request PNCP answered and refused (4xx): retrying will not help."""


class PncpIndisponivel(PncpErro):
    """PNCP kept failing after every retry."""


class ArquivoGrande(PncpErro):
    pass


@dataclass
class PaginaBusca:
    registros: list[dict]
    total_paginas: int
    total_registros: int


@dataclass
class Download:
    conteudo: bytes
    nome_arquivo: str | None


class PncpClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        base_url: str = settings.pncp_base_url,
        max_attempts: int = settings.pncp_max_attempts,
        base_delay: float = 2.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.sleep = sleep

    @classmethod
    def default_http(cls) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(settings.pncp_timeout_seconds, connect=15),
            headers={"User-Agent": "arremate/0.1 (+https://github.com/guialmm/arremate)"},
            follow_redirects=True,
        )

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None and (after := response.headers.get("retry-after", "")).isdigit():
            return min(float(after), 120)
        # Exponential with full jitter, so parallel workers do not retry in lockstep.
        return random.uniform(0, min(self.base_delay * 2**attempt, 60))

    async def _get(self, path_or_url: str, params: dict | None = None) -> httpx.Response:
        url = path_or_url if path_or_url.startswith("http") else self.base_url + path_or_url
        last = "sem resposta"
        for attempt in range(self.max_attempts):
            response = None
            try:
                response = await self.http.get(url, params=params)
            except httpx.TransportError as exc:  # timeouts, resets, DNS
                last = f"{type(exc).__name__}"
            else:
                if response.status_code < 400:
                    return response
                if response.status_code not in RETRY_STATUS:
                    raise PncpErro(f"{response.status_code} em {url}: {response.text[:200]}")
                last = f"HTTP {response.status_code}"
            if attempt + 1 < self.max_attempts:
                await self.sleep(self._delay(attempt, response))
        raise PncpIndisponivel(f"{last} após {self.max_attempts} tentativas: {url}")

    async def publicacoes(self, dia: date, modalidade: int, pagina: int) -> PaginaBusca:
        """Tenders published on `dia`, one page at a time (1-based)."""
        response = await self._get(
            "/consulta/v1/contratacoes/publicacao",
            {
                "dataInicial": dia.strftime("%Y%m%d"),
                "dataFinal": dia.strftime("%Y%m%d"),
                "codigoModalidadeContratacao": modalidade,
                "pagina": pagina,
                "tamanhoPagina": TAMANHO_PAGINA,
            },
        )
        if response.status_code == 204:  # no publications that day (weekends)
            return PaginaBusca([], 0, 0)
        body = response.json()
        return PaginaBusca(body["data"], body["totalPaginas"], body["totalRegistros"])

    async def itens(self, cnpj: str, ano: int, sequencial: int) -> list[dict]:
        path = f"/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens"
        itens: list[dict] = []
        pagina = 1
        while True:
            response = await self._get(path, {"pagina": pagina, "tamanhoPagina": TAMANHO_PAGINA})
            lote = response.json() if response.status_code != 204 else []
            itens.extend(lote)
            if len(lote) < TAMANHO_PAGINA:
                return itens
            pagina += 1

    async def arquivos(self, cnpj: str, ano: int, sequencial: int) -> list[dict]:
        response = await self._get(f"/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos")
        return response.json() if response.status_code != 204 else []

    async def baixar(self, url: str, limite_bytes: int) -> Download:
        """Download a document, refusing files above `limite_bytes` mid-stream."""
        for attempt in range(self.max_attempts):
            try:
                async with self.http.stream("GET", url) as response:
                    if response.status_code in RETRY_STATUS:
                        raise httpx.HTTPStatusError(
                            "retry", request=response.request, response=response
                        )
                    if response.status_code >= 400:
                        raise PncpErro(f"{response.status_code} ao baixar {url}")
                    tamanho = int(response.headers.get("content-length") or 0)
                    if tamanho > limite_bytes:
                        raise ArquivoGrande(f"{tamanho // 2**20} MB")
                    partes, total = [], 0
                    async for parte in response.aiter_bytes():
                        total += len(parte)
                        if total > limite_bytes:
                            raise ArquivoGrande(f"mais de {limite_bytes // 2**20} MB")
                        partes.append(parte)
                    return Download(b"".join(partes), _nome_arquivo(response))
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt + 1 == self.max_attempts:
                    raise PncpIndisponivel(f"download falhou {self.max_attempts}x: {url}")
                await self.sleep(self._delay(attempt, None))
        raise AssertionError("unreachable")


def _nome_arquivo(response: httpx.Response) -> str | None:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', disposition)
    return match.group(1).strip() if match else None
