from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://arremate:arremate@localhost:5433/arremate"
    redis_url: str = "redis://localhost:6380"

    # PNCP (Portal Nacional de Contratações Públicas)
    pncp_base_url: str = "https://pncp.gov.br/api"
    # The portal is slow (20s responses are common) and drops to 502/503 for minutes.
    pncp_timeout_seconds: float = 60
    pncp_max_attempts: int = 5
    pncp_concurrency: int = 4
    # Measured: ~22 requests in a burst trigger a 429; see app/pncp/client.py.
    pncp_requests_per_minute: float = 20
    # Pregão eletrônico: the bulk of federal, state and municipal purchases.
    pncp_modalidades: list[int] = [6]
    # Editais above this are almost always scanned annexes or drawings.
    max_document_mb: int = 40

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, url: str) -> str:
        """Accept the plain URLs hosts hand out (Neon, Render, Heroku):
        postgres://…?sslmode=require&channel_binding=require → asyncpg form."""
        parts = urlsplit(url)
        scheme = "postgresql+asyncpg" if parts.scheme in ("postgres", "postgresql") else parts.scheme
        query = dict(parse_qsl(parts.query))
        if (mode := query.pop("sslmode", None)) and mode != "disable":
            query["ssl"] = "require"
        query.pop("channel_binding", None)  # libpq-only option
        return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
