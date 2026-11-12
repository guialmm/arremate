"""HTTP API: what the site reads. Ingestion, triage and analysis run as commands.

    fastapi dev app/main.py --port 8003
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.rotas import router
from app.core.config import settings

app = FastAPI(title="Arremate", description="Triagem e análise de editais do PNCP")
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origens, allow_methods=["GET", "POST"], allow_headers=["Content-Type"]
)
app.include_router(router)
