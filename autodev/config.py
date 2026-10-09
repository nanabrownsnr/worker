from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    data_dir: Path = Field(Path("./data"), validation_alias=AliasChoices("AUTODEV_DATA_DIR", "DATA_DIR"))
    max_returns: int = Field(5, validation_alias=AliasChoices("AUTODEV_MAX_RETURNS", "MAX_RETURNS"))
    bind_host: str = Field("127.0.0.1", validation_alias=AliasChoices("AUTODEV_BIND_HOST", "BIND_HOST"))
    port: int = Field(8000, validation_alias=AliasChoices("AUTODEV_PORT", "PORT"))
    hermes_command: str = "hermes"
    hermes_provider: str = "ollama"
    hermes_model: str = "qwen3.5:35b-a3b"
    hermes_timeout_seconds: int = 3600
    hermes_retries: int = 2
    hermes_retry_delay_seconds: float = 2.0
    hermes_endpoint: str = ""
    test_timeout_seconds: int = 900
    test_command: str = ""
    git_remote_name: str = "origin"
    git_push_retries: int = 3
    git_repair_retries: int = 2
    github_token: str = ""
    github_username: str = "x-access-token"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_retries: int = 3
