"""Turn whatever an agency uploaded into pages of plain text.

Sampled 40 pregões: 26 PDF, 13 ZIP (PDFs and DOCX inside), 1 DOCX. Pages are
kept as the unit of text because the analysis cites them and the verifier
checks each quote against the page it claims to come from.
"""

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

import docx
import pypdf

log = logging.getLogger(__name__)
# pypdf logs every malformed font table; the text still comes out fine.
logging.getLogger("pypdf").setLevel(logging.ERROR)

# DOCX has no pages; split into chunks about the size of a printed page.
CHARS_POR_PAGINA_DOCX = 3000
# Below this average the PDF is a scan: there is nothing to read without OCR.
MIN_CHARS_POR_PAGINA = 80
# ZIP bomb guards.
MAX_DESCOMPACTADO = 300 * 2**20
MAX_PROFUNDIDADE_ZIP = 2


class FormatoNaoSuportado(Exception):
    pass


@dataclass
class PaginaExtraida:
    arquivo: str | None
    pagina_no_arquivo: int
    texto: str


def detectar_formato(conteudo: bytes, nome: str | None = None) -> str:
    """By magic bytes first: agencies upload PDFs named .doc and ZIPs named .pdf."""
    if conteudo.startswith(b"%PDF"):
        return "pdf"
    if conteudo.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
                return "docx" if "word/document.xml" in z.namelist() else "zip"
        except zipfile.BadZipFile:
            return "zip"
    if conteudo.startswith(b"\xd0\xcf\x11\xe0"):
        return "doc"  # legacy Word (OLE2)
    if conteudo[:4] in (b"Rar!", b"7z\xbc\xaf"):
        return "rar" if conteudo.startswith(b"Rar!") else "7z"
    sufixo = PurePosixPath(nome or "").suffix.lower().lstrip(".")
    return sufixo or "desconhecido"


def limpar(texto: str) -> str:
    # Postgres text columns reject NUL; PDFs love emitting it.
    texto = texto.replace("\x00", "")
    texto = re.sub(r"[ \t ]+", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def extrair(conteudo: bytes, nome: str | None = None) -> list[PaginaExtraida]:
    """Pages of text, in reading order. Raises FormatoNaoSuportado."""
    paginas = _extrair(conteudo, nome, arquivo=None, profundidade=0)
    if not paginas:
        raise FormatoNaoSuportado("nenhum texto extraível")
    return paginas


def _extrair(
    conteudo: bytes, nome: str | None, arquivo: str | None, profundidade: int
) -> list[PaginaExtraida]:
    formato = detectar_formato(conteudo, nome)
    if formato == "pdf":
        return _pdf(conteudo, arquivo)
    if formato == "docx":
        return _docx(conteudo, arquivo)
    if formato == "zip":
        if profundidade >= MAX_PROFUNDIDADE_ZIP:
            return []
        return _zip(conteudo, profundidade)
    raise FormatoNaoSuportado(f"formato {formato}")


def _pdf(conteudo: bytes, arquivo: str | None) -> list[PaginaExtraida]:
    try:
        reader = pypdf.PdfReader(io.BytesIO(conteudo))
        if reader.is_encrypted:
            reader.decrypt("")  # "protected" against editing, not reading
        textos = [limpar(p.extract_text() or "") for p in reader.pages]
    except Exception as exc:  # pypdf raises a zoo of errors on broken files
        raise FormatoNaoSuportado(f"PDF ilegível: {type(exc).__name__}") from exc
    if not textos or sum(map(len, textos)) / len(textos) < MIN_CHARS_POR_PAGINA:
        raise FormatoNaoSuportado("PDF digitalizado, sem camada de texto")
    return [PaginaExtraida(arquivo, i, t) for i, t in enumerate(textos, start=1)]


def _docx(conteudo: bytes, arquivo: str | None) -> list[PaginaExtraida]:
    try:
        documento = docx.Document(io.BytesIO(conteudo))
    except Exception as exc:
        raise FormatoNaoSuportado(f"DOCX ilegível: {type(exc).__name__}") from exc
    blocos = [p.text for p in documento.paragraphs]
    for tabela in documento.tables:  # requirement lists often live in tables
        for linha in tabela.rows:
            blocos.append(" | ".join(c.text.strip() for c in linha.cells))

    paginas: list[str] = []
    atual = ""
    for bloco in filter(None, (limpar(b) for b in blocos)):
        if atual and len(atual) + len(bloco) > CHARS_POR_PAGINA_DOCX:
            paginas.append(atual)
            atual = ""
        atual = f"{atual}\n{bloco}" if atual else bloco
    if atual:
        paginas.append(atual)
    return [PaginaExtraida(arquivo, i, t) for i, t in enumerate(paginas, start=1)]


def _zip(conteudo: bytes, profundidade: int) -> list[PaginaExtraida]:
    try:
        z = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile as exc:
        raise FormatoNaoSuportado("ZIP corrompido") from exc
    membros = [
        m
        for m in z.infolist()
        if not m.is_dir() and not m.filename.startswith("__MACOSX") and "/." not in m.filename
    ]
    if sum(m.file_size for m in membros) > MAX_DESCOMPACTADO:
        raise FormatoNaoSuportado("ZIP grande demais descompactado")

    paginas: list[PaginaExtraida] = []
    ignorados: list[str] = []
    for membro in sorted(membros, key=_ordem_leitura):
        nome = _nome_legivel(membro)
        try:
            paginas += _extrair(z.read(membro), nome, nome, profundidade + 1)
        except FormatoNaoSuportado as exc:
            ignorados.append(f"{nome} ({exc})")
    if ignorados:
        log.info("zip: %d arquivos ignorados: %s", len(ignorados), "; ".join(ignorados))
    return paginas


def _nome_legivel(membro: zipfile.ZipInfo) -> str:
    nome = membro.filename
    if not membro.flag_bits & 0x800:
        # Windows zippers store names as CP437 bytes; Python decoded them as such.
        try:
            nome = nome.encode("cp437").decode("cp850")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return PurePosixPath(nome).name


def _ordem_leitura(membro: zipfile.ZipInfo) -> tuple:
    """The edital itself first, then annexes in natural order ("Anexo 2" before "Anexo 10")."""
    nome = _nome_legivel(membro).lower()
    principal = "edital" in nome and "anexo" not in nome.split("edital")[0]
    return (not principal, _chave_natural(nome))


def _chave_natural(texto: str) -> list:
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", texto)]
