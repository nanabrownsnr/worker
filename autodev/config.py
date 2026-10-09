from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    data_dir: Path = Path("./data")
    api_token: str = "change-me"
    allowed_repos: str = ""
    max_returns: int = 5
    bind_host: str = "127.0.0.1"
    port: int = 8000
    hermes_command: str = "hermes"
    hermes_provider: str = "ollama"
    hermes_model: str = "qwen3.5:35b-a3b"
    hermes_timeout_seconds: int = 3600
    hermes_retries: int = 2
    test_timeout_seconds: int = 900
    test_command: str = ""
    git_remote_name: str = "origin"
    git_push_retries: int = 3
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_retries: int = 3

    @property
    def allowed_repo_set(self) -> set[str]:
        return {x.strip().rstrip("/") for x in self.allowed_repos.split(",") if x.strip()}
