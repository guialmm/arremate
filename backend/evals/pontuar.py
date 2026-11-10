"""Score one agent answer against its case. Pure: tested without any LLM."""

import re
from dataclasses import dataclass

from app.analise.service import VERIFICADAS
from evals.casos import Caso


@dataclass
class Nota:
    caso: str
    acertou: bool  # the answer states the expected fact (or that the documents don't say)
    citou_a_pagina: bool  # a verified quote on one of the expected pages (n/a when absent)
    citacoes: int
    verificadas: int
    inventadas: int  # quotes found nowhere in the documents
    passos: int  # tool calls
    segundos: float
    modelo: str

    @property
    def passou(self) -> bool:
        return self.acertou and self.citou_a_pagina and self.inventadas == 0


def pontuar(caso: Caso, resposta: str, citacoes: list[dict], passos: int, segundos: float, modelo: str) -> Nota:
    texto = resposta.lower()
    acertou = all(re.search(p, texto, re.IGNORECASE) for p in caso.deve_conter)
    ok = [c for c in citacoes if c.get("status") in VERIFICADAS]
    citou = True if caso.ausente else any(c.get("pagina") in caso.paginas for c in ok)
    return Nota(
        caso=caso.nome,
        acertou=acertou,
        citou_a_pagina=citou,
        citacoes=len(citacoes),
        verificadas=len(ok),
        inventadas=sum(c.get("status") == "nao_encontrada" for c in citacoes),
        passos=passos,
        segundos=segundos,
        modelo=modelo,
    )
