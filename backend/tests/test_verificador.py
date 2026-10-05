import pytest

from app.analise.verificador import PaginaRef, Verificador, fragmentos, normalizar

P1 = """5. DA PARTICIPAÇÃO
5.1 A participação neste pregão será para empresas que estão sediadas no Município de
Marilena-PR, com base no Decreto Municipal n° 244/2026."""
P2 = """9.1 Para habilitação jurídica o licitante apresentará o contrato social em vigor, devida-
mente registrado na Junta Comercial, e a prova de inscrição no Cadastro Nacional
de Pessoas Jurídicas. O prazo de entrega será de até"""
P3 = """3 (três) dias úteis contados do recebimento da “ordem de fornecimento”, sob pena de
multa moratória de 0,5% ao dia."""


@pytest.fixture
def v():
    paginas = [
        PaginaRef(n, 10, "Edital", n, None, n, texto) for n, texto in enumerate([P1, P2, P3], start=1)
    ]
    return Verificador(paginas)


def test_literal_quote_on_the_right_page(v):
    r = v.verificar(1, "A participação neste pregão será para empresas que estão sediadas no Município de Marilena-PR")
    assert (r.status, r.pagina) == ("verificada", 1)


def test_line_breaks_hyphenation_case_and_quotes_are_tolerated(v):
    r = v.verificar(2, 'CONTRATO SOCIAL EM VIGOR, devidamente registrado na Junta Comercial')
    assert r.status == "verificada"
    r = v.verificar(3, 'contados do recebimento da "ordem de fornecimento"')
    assert r.status == "verificada"


def test_ellipsis_skips_text_but_every_piece_must_exist(v):
    assert v.verificar(2, "o licitante apresentará o contrato social ... inscrição no Cadastro Nacional").status == "verificada"
    assert v.verificar(2, "o licitante apresentará o contrato social … balanço patrimonial do último exercício").status == "nao_encontrada"


def test_sentence_across_a_page_break(v):
    r = v.verificar(2, "O prazo de entrega será de até 3 (três) dias úteis")
    assert (r.status, r.pagina) == ("verificada", 2)


def test_right_text_wrong_page_is_corrected(v):
    r = v.verificar(3, "sediadas no Município de Marilena-PR")
    assert (r.status, r.pagina) == ("corrigida", 1)


def test_small_slip_is_approximate(v):
    r = v.verificar(3, "sob pena de multa moratoria de 0,5% por dia")
    assert (r.status, r.pagina) == ("aproximada", 3)


@pytest.mark.parametrize(
    "inventada",
    [
        "Será exigido atestado de capacidade técnica de fornecimento de 50% do quantitativo",
        "A participação é aberta a empresas de todo o território nacional",
        "multa moratória de 10% ao dia",  # a real sentence with a wrong number
        "Balanço patrimonial do último exercício social",
    ],
)
def test_fabricated_quotes_are_flagged(v, inventada):
    r = v.verificar(1, inventada)
    assert (r.status, r.pagina) == ("nao_encontrada", None)


@pytest.mark.parametrize(
    "numero_errado",
    ["sob pena de multa moratória de 10% ao dia", "sob pena de multa moratória de 5% ao dia",
     "3 (três) dias úteis contados do recebimento da ordem de fornecimento, sob pena de multa de 2%"],
)
def test_wrong_numbers_are_never_approximate(v, numero_errado):
    # Similar wording on the right page, but a different fine: the claim is false.
    assert v.verificar(3, numero_errado).status == "nao_encontrada"


def test_quotes_too_short_to_prove_anything_are_not_accepted(v):
    assert v.verificar(1, "pregão").status == "nao_encontrada"
    assert v.verificar(1, "").status == "nao_encontrada"


def test_unknown_page_number_still_finds_the_text(v):
    assert v.verificar(99, "Decreto Municipal n° 244/2026").status == "corrigida"


def test_normalization_helpers():
    assert normalizar("Devida-\n  mente  “Registrado”") == 'devidamente "registrado"'
    assert fragmentos("contrato social [...] inscrição no CNPJ") == ["contrato social", "inscrição no cnpj"]
