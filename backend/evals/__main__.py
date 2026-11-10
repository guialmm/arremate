"""Run the agent over the eval cases with the real model and report.

    python -m evals                 # every case
    python -m evals -k palhoca      # cases whose name contains "palhoca"

Free-tier quota is small (each case costs 3-8 calls): a case the model could not
answer at all is reported as inconclusive, not failed. Results go to
evals/resultados/<date>.json.
"""

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from app.agente.service import perguntar
from app.core.db import SessionLocal, engine
from app.llm import LLMErro, get_llm
from app.models import Licitacao
from evals.casos import CASOS
from evals.pontuar import pontuar

PAUSA_S = 8  # between cases, to stay under the per-minute limit


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", default="", help="só os casos cujo nome contém isto")
    casos = [c for c in CASOS if ap.parse_args().k in c.nome]
    llm = get_llm()
    notas, inconclusivos, saida = [], [], []
    async with SessionLocal() as session:
        for i, caso in enumerate(casos):
            if i:
                await asyncio.sleep(PAUSA_S)
            lic = await session.get(Licitacao, caso.licitacao)
            if lic is None:
                raise SystemExit(f"{caso.nome}: licitação {caso.licitacao} não está no banco (veja evals/README.md)")
            try:
                r = await perguntar(session, llm, lic, caso.pergunta)
            except LLMErro as exc:
                inconclusivos.append(caso.nome)
                print(f"?  {caso.nome}: inconclusivo ({exc})")
                continue
            n = pontuar(caso, r.resposta, r.citacoes, len(r.ferramentas), r.segundos, r.modelo)
            notas.append(n)
            marca = "✓" if n.passou else "✗"
            print(
                f"{marca}  {caso.nome}: resposta {'ok' if n.acertou else 'ERRADA'} · página "
                f"{'ok' if n.citou_a_pagina else 'NÃO citada'} · citações {n.verificadas}/{n.citacoes} "
                f"· {n.passos} passos · {n.segundos:.0f}s · {n.modelo}"
            )
            saida.append({**asdict(n), "pergunta": caso.pergunta, "resposta": r.resposta, "citacoes": r.citacoes,
                          "ferramentas": r.ferramentas})
    await engine.dispose()

    validos = len(notas)
    if validos:
        def taxa(f):
            return f"{sum(map(f, notas))}/{validos}"
        cit = sum(n.citacoes for n in notas)
        print(
            f"\npassaram {taxa(lambda n: n.passou)} · resposta certa {taxa(lambda n: n.acertou)} · "
            f"página certa {taxa(lambda n: n.citou_a_pagina)} · citações verificadas "
            f"{sum(n.verificadas for n in notas)}/{cit} · inventadas {sum(n.inventadas for n in notas)}"
            + (f" · inconclusivos: {', '.join(inconclusivos)}" if inconclusivos else "")
        )
    pasta = Path(__file__).parent / "resultados"
    pasta.mkdir(exist_ok=True)
    arquivo = pasta / f"{date.today()}.json"
    arquivo.write_text(json.dumps(saida, ensure_ascii=False, indent=2))
    print(f"detalhes em {arquivo.relative_to(Path.cwd()) if arquivo.is_relative_to(Path.cwd()) else arquivo}")


if __name__ == "__main__":
    asyncio.run(main())
