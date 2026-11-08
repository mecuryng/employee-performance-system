from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_URL = f"sqlite:///{(PROJECT_ROOT / 'employee_performance.db').as_posix()}"


class Settings(BaseSettings):
    app_name: str = "Employee Performance System"
    environment: str = "development"
    database_url: str = DEFAULT_DATABASE_URL
    jwt_secret: str = "change-this-secret-before-deploying"
    access_token_minutes: int = 30

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
