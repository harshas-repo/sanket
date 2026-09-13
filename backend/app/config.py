"""Runtime configuration. Everything sensitive comes from the environment."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
GEO_DIR = DATA_DIR / "geo"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Sanket"
    environment: str = Field(default="development", alias="SANKET_ENV")

    # --- persistence -------------------------------------------------------
    # Defaults to SQLite so the product runs on a clean machine. Point
    # DATABASE_URL at PostgreSQL/Supabase for anything beyond local dev and the
    # same models/migrations apply unchanged.
    database_url: str = Field(default=f"sqlite:///{DATA_DIR / 'sanket.db'}", alias="DATABASE_URL")

    # --- auth --------------------------------------------------------------
    secret_key: str = Field(default="", alias="SANKET_SECRET_KEY")
    token_ttl_hours: int = Field(default=12, alias="SANKET_TOKEN_TTL_HOURS")
    allow_demo_accounts: bool = Field(default=True, alias="SANKET_ALLOW_DEMO_ACCOUNTS")

    # --- ingestion ---------------------------------------------------------
    ingestion_enabled: bool = Field(default=True, alias="SANKET_INGESTION_ENABLED")
    http_timeout_seconds: float = Field(default=30.0, alias="SANKET_HTTP_TIMEOUT")
    # Government portals are slow and sometimes only speak plain HTTP.
    allow_insecure_official_sources: bool = Field(
        default=True, alias="SANKET_ALLOW_INSECURE_SOURCES"
    )
    usgs_min_magnitude: float = Field(default=3.0, alias="USGS_MIN_MAGNITUDE")
    usgs_lookback_days: int = Field(default=7, alias="USGS_LOOKBACK_DAYS")
    drr_lookback_days: int = Field(default=45, alias="DRR_LOOKBACK_DAYS")
    # Official catalogues carry years of history. Every row is stored, but only
    # events inside this window become incidents - a Response Center queue must not
    # be filled with events nobody can act on.
    incident_creation_window_days: int = Field(default=14, alias="SANKET_INCIDENT_WINDOW_DAYS")
    demo_mode: bool = Field(default=False, alias="SANKET_DEMO_MODE")

    # --- model / Strands ---------------------------------------------------
    # `LLM_PROVIDER` names the SDK to drive; `LLM_MODEL` is the model id asked of it.
    # With no provider named, `model_provider` infers one from whichever key is set, so a
    # deployment that only has OPENAI_API_KEY keeps working without naming anything. The key
    # itself never leaves this process: no response below is built from it, and the frontend
    # is told "configured / not configured" and nothing else.
    llm_provider: str = Field(default="", alias="LLM_PROVIDER")
    strands_model: str = Field(
        default="gemini-3.6-flash",
        validation_alias=AliasChoices("LLM_MODEL", "SANKET_MODEL"),
    )
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    llama_api_key: str = Field(default="", alias="LLAMA_API_KEY")
    bedrock_aws_region: str = Field(default="ap-south-1", alias="AWS_REGION")

    # --- misc --------------------------------------------------------------
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173", alias="SANKET_CORS_ORIGINS"
    )
    scheduler_poll_seconds: int = Field(default=15, alias="SANKET_SCHEDULER_TICK")

    @property
    def resolved_secret(self) -> str:
        return self.secret_key or "sanket-dev-insecure-secret-change-me"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_model_credentials(self) -> bool:
        return bool(self.api_key or _bedrock_credentials())

    @property
    def model_provider(self) -> str | None:
        """The named provider wins; otherwise infer it from the key that is present."""
        named = self.llm_provider.strip().lower()
        if named:
            return named
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key:
            return "openai"
        if self.gemini_api_key:
            return "gemini"
        if self.llama_api_key:
            return "llama"
        if _bedrock_credentials():
            return "bedrock"
        return None

    @property
    def api_key(self) -> str:
        """The key for the provider in play, or an empty string.

        Only ever read inside this process - it is a credential, not configuration, and a
        value that can be echoed by an endpoint is a value that will be.
        """
        return {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
            "llama": self.llama_api_key,
        }.get(self.model_provider or "", "")


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GEO_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()


def _bedrock_credentials() -> bool:
    """Read from the live environment, not from a settings field: these are two variable
    names the AWS SDK sets itself, and the model layer asks the SDK to resolve them."""
    return bool(os.environ.get("AWS_BEARER_TOKEN_BEDROCK") or os.environ.get("AWS_ACCESS_KEY_ID"))


settings = get_settings()
