"""Ask the agent a question about a tender, from the terminal.

    python -m app.agente "<numeroControlePNCP>" "Precisa de amostra?"
"""

import asyncio
import json
import sys

from app.agente.service import perguntar
from app.core.db import SessionLocal, engine
from app.llm import get_llm
from app.models import Licitacao


async def main() -> None:
    licitacao_id, pergunta = sys.argv[1], sys.argv[2]
    async with SessionLocal() as session:
        lic = await session.get(Licitacao, licitacao_id)
        if lic is None:
            sys.exit(f"licitação {licitacao_id} não encontrada")
        r = await perguntar(session, get_llm(), lic, pergunta)
    await engine.dispose()
    for f in r.ferramentas:
        print(f"→ {f['nome']}({json.dumps(f['argumentos'], ensure_ascii=False)})")
    print(f"\n{r.resposta}\n")
    for c in r.citacoes:
        print(f"[p. {c['pagina']}] {c['status']}: {c['trecho']}")
    print(f"\n{r.modelo} · {r.tokens_entrada}+{r.tokens_saida} tokens · {r.segundos}s")


if __name__ == "__main__":
    asyncio.run(main())
