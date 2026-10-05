"""python -m app.triagem [--perfil 1] [--limite 200]"""

import argparse
import asyncio
import logging
import time

from sqlalchemy import select

from app.core.db import SessionLocal, engine
from app.llm import get_llm
from app.models import Licitacao, Perfil, Triagem
from app.triagem.service import triar


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.triagem")
    parser.add_argument("--perfil", type=int, default=1)
    parser.add_argument("--limite", type=int, default=200)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    try:
        async with SessionLocal() as session:
            perfil = await session.get(Perfil, args.perfil)
            if perfil is None:
                raise SystemExit(f"perfil {args.perfil} não existe (rode python -m app.seed)")
            inicio = time.monotonic()
            r = await triar(session, get_llm(), perfil, args.limite)
            print(
                f"{perfil.nome}: {r.candidatas} candidatas, {r.avaliadas} avaliadas, "
                f"{r.relevantes} relevantes, {r.lotes_com_erro} lotes com erro, "
                f"modelos {sorted(r.modelos)} ({time.monotonic() - inicio:.0f}s)"
            )
            ranking = await session.execute(
                select(Triagem.nota, Licitacao.uf, Licitacao.objeto, Triagem.motivo)
                .join(Licitacao)
                .where(Triagem.perfil_id == perfil.id)
                .order_by(Triagem.nota.desc())
            )
            for nota, uf, objeto, motivo in ranking:
                print(f"{nota:>3} {uf} {' '.join(objeto.split())[:80]}\n      → {motivo}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
