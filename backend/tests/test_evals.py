from evals.casos import CASOS, NAO_INFORMA, Caso
from evals.pontuar import pontuar

CASO = Caso("x", "l", "Qual o prazo de entrega?", [r"\b5\b|cinco"], {42})


def cit(pagina, status="verificada"):
    return {"pagina": pagina, "trecho": "t", "status": status}


def test_passa_com_fato_e_citacao_na_pagina_certa():
    n = pontuar(CASO, "O prazo é de 5 dias.", [cit(42)], 3, 10.0, "m")
    assert n.passou


def test_falha_sem_o_fato_na_pagina_errada_ou_com_citacao_inventada():
    assert not pontuar(CASO, "O prazo é de 10 dias.", [cit(42)], 3, 1, "m").passou
    assert not pontuar(CASO, "O prazo é de 5 dias.", [cit(41)], 3, 1, "m").passou
    assert not pontuar(CASO, "O prazo é de 5 dias.", [cit(42, "nao_encontrada")], 3, 1, "m").passou
    n = pontuar(CASO, "O prazo é de 5 dias.", [cit(42), cit(7, "nao_encontrada")], 3, 1, "m")
    assert not n.passou and n.inventadas == 1


def test_pergunta_sem_resposta_nos_documentos():
    caso = Caso("y", "l", "Cor da caneta?", [NAO_INFORMA], ausente=True)
    assert pontuar(caso, "Os documentos não mencionam canetas.", [], 2, 1, "m").passou
    assert pontuar(caso, "O prazo está em branco no contrato.", [], 2, 1, "m").passou
    assert not pontuar(caso, "A tinta deve ser azul.", [], 2, 1, "m").passou


def test_casos_bem_formados():
    nomes = [c.nome for c in CASOS]
    assert len(nomes) == len(set(nomes))
    for c in CASOS:
        assert c.deve_conter and (c.ausente or c.paginas), c.nome
