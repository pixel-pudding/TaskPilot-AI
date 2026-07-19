from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings
from dotenv import load_dotenv

dotenv_path = Path(__file__).resolve().parent.parent / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path)
else:
    load_dotenv()


class Settings(BaseSettings):
    # ── LLM ──
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    llm_api_key: str = ""
    llm_model: str = "grok-3-mini"
    llm_base_url: str = "https://api.x.ai/v1"
    xai_api_key: str = ""

    # ── Connectors (fallback/demo credentials — env-var names match what the
    # ── connector classes actually read via os.environ) ──
    jira_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    github_token: str = ""
    github_repo_owner: str = "taskpilot-ai"
    github_repo_name: str = "backend"
    azure_client_id: str = ""
    azure_client_secret: str = ""
    azure_tenant_id: str = ""
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    servicenow_url: str = ""
    servicenow_user: str = ""
    servicenow_password: str = ""

    # ── Per-user OAuth apps ──
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    slack_oauth_client_id: str = ""
    slack_oauth_client_secret: str = ""
    oauth_redirect_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"
    credentials_encryption_key: str = ""

    # ── Database ──
    database_url: str = "sqlite+aiosqlite:///db/taskpilot.db"

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"

    # ── Celery ──
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── Security ──
    secret_key: str = "change-me-to-a-random-secret-at-least-32-chars"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24
    api_rate_limit_per_minute: int = 60

    # ── Embedding Model ──
    embedding_model_name: str = "all-MiniLM-L6-v2"
    embedding_cache_enabled: bool = True

    # ── Monitoring ──
    prometheus_enabled: bool = True
    otel_service_name: str = "taskpilot-ai"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"

    # ── Logging ──
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    # ── Pipeline ──
    extraction_confidence_threshold: float = 0.50
    pipeline_sync_interval_minutes: int = 15
    max_concurrent_syncs: int = 3

    @property
    def llm_key(self) -> str:
        return self.llm_api_key or self.xai_api_key

    @property
    def is_postgres(self) -> bool:
        return "postgresql" in self.database_url

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


settings = Settings()

# Backward compat: export to os.environ for modules that use os.environ
if not os.environ.get("LLM_API_KEY") and settings.llm_key:
    os.environ["LLM_API_KEY"] = settings.llm_key
