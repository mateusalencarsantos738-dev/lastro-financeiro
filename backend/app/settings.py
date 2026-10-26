from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    app_host: str = "127.0.0.1"
    app_port: int = 8765

    model_config = SettingsConfigDict(
        env_file=Path.home() / ".config/meu-financeiro/.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
