from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value else default
    except ValueError:
        return default


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value else default
    except ValueError:
        return default


@dataclass
class Config:
    lidarr_url: str
    lidarr_api_key: str

    ai_provider: str
    ai_model: str
    ai_api_key: str
    ai_base_url: str | None

    dry_run: bool
    confidence_threshold: float

    resolver_poll_seconds: int
    reconciler_poll_seconds: int
    reprocess_cooldown_minutes: int

    db_path: str
    log_level: str

    @classmethod
    def load(cls, env_file: str | None = ".env") -> "Config":
        if env_file:
            load_dotenv(env_file)

        lidarr_url = os.getenv("LIDARR_URL", "").rstrip("/")
        lidarr_api_key = os.getenv("LIDARR_API_KEY", "")
        if not lidarr_url or not lidarr_api_key:
            raise ValueError(
                "LIDARR_URL and LIDARR_API_KEY must be set (copy .env.example to .env)"
            )

        ai_provider = os.getenv("AI_PROVIDER", "anthropic").strip().lower()
        ai_api_key = os.getenv("AI_API_KEY", "")
        if ai_provider != "ollama" and not ai_api_key:
            raise ValueError(f"AI_API_KEY must be set for provider '{ai_provider}'")

        return cls(
            lidarr_url=lidarr_url,
            lidarr_api_key=lidarr_api_key,
            ai_provider=ai_provider,
            ai_model=os.getenv("AI_MODEL", "claude-sonnet-4-6"),
            ai_api_key=ai_api_key,
            ai_base_url=os.getenv("AI_BASE_URL") or None,
            dry_run=_bool(os.getenv("DRY_RUN"), True),
            confidence_threshold=_float(os.getenv("CONFIDENCE_THRESHOLD"), 0.85),
            resolver_poll_seconds=_int(os.getenv("RESOLVER_POLL_SECONDS"), 300),
            reconciler_poll_seconds=_int(os.getenv("RECONCILER_POLL_SECONDS"), 3600),
            reprocess_cooldown_minutes=_int(os.getenv("REPROCESS_COOLDOWN_MINUTES"), 720),
            db_path=os.getenv("DB_PATH", "./data/lidarr_ai_import.db"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
