"""Configuration loader for the SRM prototype (env-driven, offline-friendly)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Load `.env` into process env (minimal parser, no extra dependency).

    Only sets variables that are not already present in `os.environ`.
    """

    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _get_env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


def _get_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _get_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_env_date(name: str) -> date | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    return date.fromisoformat(raw.strip())


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Config for local web app."""

    app_env: str
    db_path: Path
    artifacts_dir: Path
    uploads_dir: Path
    rules_path: Path
    session_days: int
    host: str
    port: int
    debug: bool
    secret_key: str
    default_analysis_date: date | None


def load_config() -> AppConfig:
    """Load configuration from environment variables (see `.env.example`)."""

    _load_dotenv(Path(".env"))

    # Server-friendly variables (preferred on вузовский сервер):
    app_env = (os.getenv("APP_ENV", "") or "").strip() or "local"
    host = (os.getenv("HOST", "") or os.getenv("SRM_HOST", "") or "127.0.0.1").strip()
    port = _get_env_int("PORT", _get_env_int("SRM_PORT", 8000))
    debug = _get_env_bool("DEBUG", _get_env_bool("SRM_DEBUG", False))

    # Map DATABASE_URL -> local sqlite path (we keep sqlite only).
    db_path = _get_env_path("SRM_DB_PATH", "./outputs/srm_web.sqlite3")
    db_url = (os.getenv("DATABASE_URL", "") or "").strip()
    if db_url.startswith("sqlite:///"):
        # sqlite:///./data/srm.db -> ./data/srm.db
        db_path = Path(db_url.replace("sqlite:///", "", 1)).expanduser()

    artifacts_dir = _get_env_path("SRM_ARTIFACTS_DIR", "./outputs/web_artifacts")
    uploads_dir = _get_env_path("SRM_UPLOADS_DIR", "./outputs/uploads")
    if os.getenv("ARTIFACTS_DIR"):
        artifacts_dir = Path(os.getenv("ARTIFACTS_DIR", "")).expanduser()
    if os.getenv("UPLOADS_DIR"):
        uploads_dir = Path(os.getenv("UPLOADS_DIR", "")).expanduser()

    secret_key = (os.getenv("SECRET_KEY", "") or "").strip()
    if not secret_key:
        secret_key = "dev-secret"

    # Production safety: disallow DEBUG=true in production env.
    if app_env.lower() == "production" and debug:
        raise ValueError("DEBUG=true запрещён в APP_ENV=production. Установите DEBUG=false.")
    if app_env.lower() == "production" and secret_key in {"dev-secret", "change_me", ""}:
        raise ValueError("SECRET_KEY не задан или небезопасен. Установите SECRET_KEY в .env.")

    return AppConfig(
        app_env=app_env,
        db_path=db_path,
        artifacts_dir=artifacts_dir,
        uploads_dir=uploads_dir,
        rules_path=_get_env_path("SRM_RULES_PATH", "./examples/repair_rules_ontology.json"),
        session_days=_get_env_int("SRM_SESSION_DAYS", 7),
        host=host,
        port=port,
        debug=debug,
        secret_key=secret_key,
        default_analysis_date=_get_env_date("SRM_DEFAULT_ANALYSIS_DATE"),
    )
