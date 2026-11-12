"""Questions about real editais, with answers checked by hand against the page text.

`deve_conter`: each entry is a regex the answer must match (all of them).
`paginas`: global page numbers ([p. N]) where the fact is; a verified quote must hit one.
`ausente`: the documents do not say it; the agent must say so instead of guessing.

The tenders are in the local database (ingested 2026-10); see evals/README.md.
"""

from dataclasses import dataclass, field

MARILENA = "75971010000173-1-000030/2026"
ENCRUZILHADA = "89363642000169-1-001354/2026"
PALHOCA = "82892316000108-1-000328/2026"
CAXIAS = "88830609000139-1-000558/2026"

NAO_INFORMA = r"n[ãa]o (h[áa]|consta|informa|menciona|especifica|encontr|aparece|traz|define|est[áa] (definid|preenchid|informad|especificad))|em branco|lacuna|sem (definir|informar)"


@dataclass
class Caso:
    nome: str
    licitacao: str
    pergunta: str
    deve_conter: list[str] = field(default_factory=list)
    paginas: set[int] = field(default_factory=set)
    ausente: bool = False


CASOS = [
    Caso("garantia_marilena", MARILENA, "Qual é o prazo de garantia exigido para os produtos?",
         [r"\b12\b|doze", r"mes"], {19}),
    Caso("pagamento_marilena", MARILENA, "Em quantos dias a prefeitura paga depois da entrega?",
         [r"\b30\b|trinta"], {61}),
    Caso("empresa_local_marilena", MARILENA, "Uma empresa de Curitiba pode participar deste pregão?",
         [r"sediad|local|munic[ií]pio de marilena", r"n[ãa]o|apenas|somente|exclusiv|restrit"], {12, 14}),
    Caso("pagamento_encruzilhada", ENCRUZILHADA, "Como é feito o pagamento?",
         [r"empenho|nota fiscal"], {18}),
    # The contract template (p. 93) leaves the period blank ("...... dias"), but the edital
    # itself sets it on p. 17. The first version of this case expected "not informed":
    # the agent found p. 17 and the eval was the one that was wrong.
    Caso("entrega_encruzilhada", ENCRUZILHADA,
         "Qual é o prazo de entrega, em dias, depois do empenho?", [r"\b15\b|quinze", r"corridos"], {17}),
    Caso("amostra_palhoca", PALHOCA, "É preciso apresentar amostra? Em quanto tempo?",
         [r"\b0?3\b|tr[êe]s", r"[úu]teis"], {17}),
    Caso("entrega_palhoca", PALHOCA, "Qual o prazo de entrega depois da ordem de compra?",
         [r"\b5\b|cinco"], {42}),
    Caso("substituicao_palhoca", PALHOCA,
         "Se um material for rejeitado, em quanto tempo precisa ser substituído?",
         [r"\b48\b|quarenta e oito", r"hora"], {45}),
    Caso("entrega_caxias", CAXIAS, "Qual o prazo máximo de entrega?",
         [r"\b10\b|dez", r"dias"], {16}),
    Caso("canetas_palhoca", PALHOCA, "Qual a cor de tinta exigida para as canetas?",
         [NAO_INFORMA], ausente=True),
    Caso("visita_caxias", CAXIAS, "Qual o endereço e o horário da visita técnica obrigatória?",
         [NAO_INFORMA], ausente=True),
]
