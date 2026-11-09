"""What the agent may do: search and read one tender's editais, and list its items.

Every tool is scoped to a single tender and never raises: a bad argument comes
back as {"erro": ...} so the model can correct itself.
"""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analise.verificador import PaginaRef
from app.llm import Ferramenta
from app.models import Item

MAX_RESULTADOS = 6
MAX_CARACTERES_PAGINA = 8000

DECLARACOES = [
    Ferramenta(
        "buscar_trechos",
        "Busca por palavras no texto dos documentos da licitação (edital, termo de referência, "
        "anexos). Devolve as páginas mais relevantes com um trecho de cada. Use termos que "
        "apareceriam no edital: 'atestado capacidade técnica', 'prazo entrega', 'amostra'.",
        {
            "type": "object",
            "properties": {"consulta": {"type": "string", "description": "Palavras a procurar"}},
            "required": ["consulta"],
        },
    ),
    Ferramenta(
        "ler_pagina",
        "Lê o texto completo de uma página, pelo número [p. N] devolvido pela busca. "
        "Leia a página antes de citar: a citação precisa ser cópia literal.",
        {
            "type": "object",
            "properties": {"pagina": {"type": "integer"}},
            "required": ["pagina"],
        },
    ),
    Ferramenta(
        "listar_itens",
        "Lista os itens da licitação cadastrados no PNCP: descrição, quantidade, unidade, "
        "valor estimado e benefício (exclusivo ME/EPP, cota reservada).",
        {"type": "object", "properties": {}},
    ),
    Ferramenta(
        "responder",
        "Entrega a resposta final ao usuário. Chame uma única vez, no fim.",
        {
            "type": "object",
            "properties": {
                "resposta": {
                    "type": "string",
                    "description": "Resposta em português, direta, em poucos parágrafos",
                },
                "citacoes": {
                    "type": "array",
                    "description": "Trechos literais que sustentam a resposta",
                    "items": {
                        "type": "object",
                        "properties": {
                            "pagina": {"type": "integer"},
                            "trecho": {"type": "string", "description": "Cópia literal, 1 a 3 frases"},
                        },
                        "required": ["pagina", "trecho"],
                    },
                },
            },
            "required": ["resposta", "citacoes"],
        },
    ),
]

# Hits for all the words first; when nothing has them all, any of them.
BUSCA = text(
    """
    WITH q AS (SELECT websearch_to_tsquery('portuguese', :consulta) AS e,
                      replace(plainto_tsquery('portuguese', :consulta)::text, '&', '|')::tsquery AS ou)
    SELECT p.documento_id, p.numero,
           ts_headline('portuguese', p.texto, CASE WHEN p.busca @@ q.e THEN q.e ELSE q.ou END,
                       'MaxFragments=2, MaxWords=30, MinWords=12, StartSel=«, StopSel=»') AS trecho
    FROM paginas p, q
    WHERE p.documento_id = ANY(:documentos) AND (p.busca @@ q.e OR p.busca @@ q.ou)
    ORDER BY (p.busca @@ q.e) DESC, ts_rank(p.busca, q.ou) DESC
    LIMIT :limite
    """
)


class FerramentasEdital:
    def __init__(self, session: AsyncSession, licitacao_id: str, paginas: list[PaginaRef]):
        self.session = session
        self.licitacao_id = licitacao_id
        self.paginas = {p.global_n: p for p in paginas}
        self._global = {(p.documento_id, p.numero): p.global_n for p in paginas}

    async def executar(self, nome: str, args: dict) -> dict:
        try:
            if nome == "buscar_trechos":
                return await self.buscar_trechos(str(args.get("consulta", "")))
            if nome == "ler_pagina":
                return self.ler_pagina(int(args.get("pagina", 0)))
            if nome == "listar_itens":
                return await self.listar_itens()
        except (TypeError, ValueError) as exc:
            return {"erro": f"argumentos inválidos para {nome}: {exc}"}
        return {"erro": f"a ferramenta {nome} não existe"}

    async def buscar_trechos(self, consulta: str) -> dict:
        if not consulta.strip():
            return {"erro": "consulta vazia"}
        documentos = sorted({doc for doc, _ in self._global})
        linhas = (
            await self.session.execute(
                BUSCA, {"consulta": consulta, "documentos": documentos, "limite": MAX_RESULTADOS}
            )
        ).all()
        resultados = []
        for doc, numero, trecho in linhas:
            n = self._global[(doc, numero)]
            resultados.append({"pagina": n, "documento": self.paginas[n].documento, "trecho": " ".join(trecho.split())})
        if not resultados:
            return {"resultados": [], "aviso": "nada encontrado; tente sinônimos ou menos palavras"}
        return {"resultados": resultados}

    def ler_pagina(self, pagina: int) -> dict:
        p = self.paginas.get(pagina)
        if p is None:
            return {"erro": f"a página {pagina} não existe; as páginas vão de 1 a {len(self.paginas)}"}
        return {"pagina": pagina, "documento": p.documento, "texto": p.texto[:MAX_CARACTERES_PAGINA]}

    async def listar_itens(self) -> dict:
        itens = (
            await self.session.scalars(
                select(Item).where(Item.licitacao_id == self.licitacao_id).order_by(Item.numero).limit(80)
            )
        ).all()
        return {
            "itens": [
                {
                    "numero": i.numero,
                    "descricao": " ".join(i.descricao.split())[:200],
                    "quantidade": float(i.quantidade) if i.quantidade is not None else None,
                    "unidade": i.unidade,
                    "valor_unitario": float(i.valor_unitario) if i.valor_unitario is not None else None,
                    "beneficio": i.beneficio,
                }
                for i in itens
            ]
        }
