from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    data_dir: Path = Path("./data")
    max_returns: int = 5
    bind_host: str = "127.0.0.1"
    port: int = 8000
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
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_retries: int = 3
