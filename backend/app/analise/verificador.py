"""Check every quote the model made against the page it says it came from.

A legal-ish document is the worst place for a confident hallucination: a
requirement the edital never made, or a deadline from another tender. The
model is asked to copy text literally, and this module holds it to that.

Accepted without penalty: PDF line breaks, hyphenation, curly quotes, case,
and "..." where the model skipped part of a sentence.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

Status = Literal["verificada", "corrigida", "aproximada", "nao_encontrada"]

# Fragments shorter than this prove nothing ("conforme", "do edital").
MIN_FRAGMENTO = 12
# partial_ratio threshold for quotes with small slips (a dropped word, an OCR-ish typo).
LIMIAR_APROXIMADO = 90


@dataclass
class PaginaRef:
    """One page as the model saw it: global number in the prompt → where it lives."""

    global_n: int
    documento_id: int
    documento: str
    numero: int
    arquivo: str | None
    pagina_no_arquivo: int
    texto: str


@dataclass
class Verificacao:
    status: Status
    pagina: int | None  # global page where the quote really is (None if nowhere)


ASPAS = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "º": "o", "ª": "a"})


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKC", texto).translate(ASPAS).lower()
    texto = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", texto)  # hyphenated line break
    return re.sub(r"\s+", " ", texto).strip()


def numeros(texto: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)*", texto))


def fragmentos(trecho: str) -> list[str]:
    """Split on ellipses the model used to skip text; drop the too-short pieces."""
    partes = re.split(r"\.{3,}|…|\[\s*\.{0,3}\s*\]", normalizar(trecho))
    return [p.strip(" .;,:\"'") for p in partes if len(p.strip(" .;,:\"'")) >= MIN_FRAGMENTO]


class Verificador:
    def __init__(self, paginas: Sequence[PaginaRef]):
        self.paginas = {p.global_n: p for p in paginas}
        self._norm = {p.global_n: normalizar(p.texto) for p in paginas}

    def _contem(self, n: int, partes: list[str]) -> bool:
        texto = self._norm.get(n, "")
        return bool(texto) and all(p in texto for p in partes)

    def verificar(self, pagina: int, trecho: str) -> Verificacao:
        partes = fragmentos(trecho)
        if not partes:
            return Verificacao("nao_encontrada", None)
        if self._contem(pagina, partes):
            return Verificacao("verificada", pagina)
        # A sentence split across a page break: the quote spans two pages.
        for vizinha in (pagina - 1, pagina + 1):
            juntas = self._norm.get(min(pagina, vizinha), "") + " " + self._norm.get(max(pagina, vizinha), "")
            if vizinha in self._norm and all(p in juntas for p in partes):
                return Verificacao("verificada", pagina)
        # Right text, wrong page number: keep the claim, fix the pointer.
        for n in self._norm:
            if self._contem(n, partes):
                return Verificacao("corrigida", n)
        # Wording may slip a little; numbers may not. "10% ao dia" quoted from a page
        # that says "0,5% ao dia" scores ~93 on similarity and must still fail.
        texto = self._norm.get(pagina, "")
        if (
            texto
            and all(fuzz.partial_ratio(p, texto) >= LIMIAR_APROXIMADO for p in partes)
            and numeros(" ".join(partes)) <= numeros(texto)
        ):
            return Verificacao("aproximada", pagina)
        return Verificacao("nao_encontrada", None)
