"""Demo profile: a stationery distributor in the South, a common bidder in municipal pregões.

    python -m app.seed
"""

import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.core.db import SessionLocal, engine
from app.models import Perfil

PERFIL_DEMO = dict(
    nome="Papelaria Sul Distribuidora (exemplo)",
    descricao=(
        "Distribuidora de material de escritório, papelaria e material escolar. Vende papel "
        "sulfite A4, canetas, lápis, borrachas, cadernos, pastas, envelopes, etiquetas, "
        "grampeadores, clipes, colas, tesouras, toner e cartuchos de impressora. Não fabrica "
        "móveis, não presta serviços gráficos nem de manutenção de equipamentos."
    ),
    palavras_chave=[
        "material de escritório", "material de expediente", "material escolar", "papelaria",
        "papel sulfite", "papel A4", "caneta", "lápis", "caderno", "envelope", "grampeador",
        "toner", "cartucho", "kit escolar",
    ],
    ufs=["PR", "SC", "RS"],
    valor_minimo=Decimal("1000"),
    valor_maximo=Decimal("2000000"),
    documentos=[
        "Contrato social e alterações",
        "Cartão CNPJ",
        "Certidão negativa de débitos federais e dívida ativa da União",
        "Certidão negativa de débitos estaduais (PR)",
        "Certidão negativa de débitos municipais",
        "Certificado de regularidade do FGTS",
        "Certidão negativa de débitos trabalhistas (CNDT)",
        "Certidão negativa de falência e recuperação judicial",
        "Balanço patrimonial do exercício de 2025",
        "Atestado de capacidade técnica: fornecimento de material de expediente a prefeitura",
        "Enquadramento como empresa de pequeno porte (EPP)",
    ],
)


async def main() -> None:
    async with SessionLocal() as session:
        if await session.scalar(select(Perfil.id).limit(1)) is None:
            session.add(Perfil(**PERFIL_DEMO))
            await session.commit()
            print("perfil de exemplo criado")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
