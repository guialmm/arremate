"""Per-IP sliding window, in memory: the API runs as a single instance."""

import time
from collections import defaultdict, deque

from fastapi import Request


class Limite:
    def __init__(self, maximo: int, janela_s: float, relogio=time.monotonic):
        self.maximo, self.janela_s, self.relogio = maximo, janela_s, relogio
        self._vezes: dict[str, deque[float]] = defaultdict(deque)

    def permitir(self, chave: str) -> bool:
        agora = self.relogio()
        vezes = self._vezes[chave]
        while vezes and agora - vezes[0] > self.janela_s:
            vezes.popleft()
        if len(vezes) >= self.maximo:
            return False
        vezes.append(agora)
        return True


def ip(request: Request) -> str:
    # Render and Vercel put the client first in X-Forwarded-For.
    if encaminhado := request.headers.get("x-forwarded-for"):
        return encaminhado.split(",")[0].strip()
    return request.client.host if request.client else "?"
