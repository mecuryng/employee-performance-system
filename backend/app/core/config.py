from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Employee Performance System"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://employee_app:employee_app@localhost:5432/employee_performance"
    jwt_secret: str = "change-this-secret-before-deploying"
    access_token_minutes: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
