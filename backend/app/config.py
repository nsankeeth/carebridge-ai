from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    model_api_key: str = ""
    meta_base_url: str = "https://api.meta.ai/v1"
    meta_model: str = "muse-spark-1.3"
    ai_timeout_seconds: float = 90.0
    ai_max_retries: int = 2

    database_url: str = "postgresql+psycopg://medhandoff:medhandoff@localhost:5433/medhandoff"
    jwt_secret: str = "change-me"
    jwt_ttl_minutes: int = 12 * 60
    storage_dir: str = str(ROOT_DIR / "storage")
    cors_origins: str = "http://localhost:3000"
    max_upload_bytes: int = 10 * 1024 * 1024
    # Hours a handoff may sit unacknowledged before the follow-up agent flags it.
    ack_sla_hours: int = 24
    cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
