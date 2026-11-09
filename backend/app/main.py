"""HTTP API: what the site reads. Ingestion, triage and analysis run as commands.

    fastapi dev app/main.py --port 8003
"""

from fastapi import FastAPI

from app.api.rotas import router

app = FastAPI(title="Arremate", description="Triagem e análise de editais do PNCP")
app.include_router(router)
