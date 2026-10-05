"""python -m app.analise [--perfil 1] [--licitacao ID] [--limite 3] [--refazer]"""

import argparse
import asyncio
import logging

from sqlalchemy import select

from app.analise.service import SemTexto, analisar
from app.core.db import SessionLocal, engine
from app.llm import LLMErro, get_llm
from app.models import AnaliseEdital, Licitacao, Perfil, Triagem


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.analise")
    parser.add_argument("--perfil", type=int, default=1)
    parser.add_argument("--licitacao")
    parser.add_argument("--limite", type=int, default=3)
    parser.add_argument("--refazer", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    llm = get_llm()
    try:
        async with SessionLocal() as session:
            perfil = await session.get(Perfil, args.perfil)
            if args.licitacao:
                ids = [args.licitacao]
            else:
                query = (
                    select(Triagem.licitacao_id)
                    .where(Triagem.perfil_id == perfil.id, Triagem.relevante)
                    .order_by(Triagem.nota.desc())
                )
                if not args.refazer:
                    feitas = select(AnaliseEdital.licitacao_id).where(AnaliseEdital.perfil_id == perfil.id)
                    query = query.where(Triagem.licitacao_id.not_in(feitas))
                ids = (await session.scalars(query.limit(args.limite))).all()

            for lic_id in ids:
                lic = await session.get(Licitacao, lic_id)
                try:
                    a = await analisar(session, llm, perfil, lic)
                except SemTexto:
                    print(f"{lic_id}: nenhum edital legível")
                    continue
                except LLMErro as exc:
                    print(f"{lic_id}: falhou ({exc})")
                    continue
                r = a.resultado
                print(
                    f"{lic_id} · {a.recomendacao.upper()} · {a.paginas_lidas} págs · "
                    f"{a.tokens_entrada} tok entrada / {a.tokens_saida} saída · {a.segundos}s · {a.modelo}\n"
                    f"  citações verificadas: {a.citacoes_verificadas}/{a.citacoes_total} · "
                    f"{len(r['requisitos'])} requisitos, {len(r['prazos'])} prazos, "
                    f"{len(r['condicoes'])} condições, {len(r['riscos'])} riscos"
                )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
