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
    hermes_container_enabled: bool = True
    hermes_container_image: str = "worker-worker:latest"
    hermes_host_data_dir: str = ""
    hermes_network: str = "host"
    hermes_memory: str = "8g"
    hermes_cpus: str = "4"
    hermes_pids_limit: int = 256
    test_timeout_seconds: int = 900
    test_command: str = ""
    git_remote_name: str = "origin"
    git_push_retries: int = 3
    git_repair_retries: int = 2
    github_token: str = ""
    github_username: str = "x-access-token"
    git_author_name: str = "Worker"
    git_author_email: str = "worker@users.noreply.github.com"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_retries: int = 3
    deployment_gate_enabled: bool = True
    deployment_timeout_seconds: int = 300
    deployment_retries: int = 2
    deployment_log_patterns: str = "traceback,exception,error:"
    deployment_port_start: int = 8003
    deployment_port_end: int = 8005
    triage_enabled: bool = True
    triage_model: str = "glm-4.7-flash:latest"
    triage_timeout_seconds: int = 90
    incremental_workflow_enabled: bool = True
    ticket_max_attempts: int = 5
    planner_model: str = "qwen3-coder:30b"
    implementer_model: str = "vllm/qwen3.6-35b-a3b"
    worker_agent: str = Field("opencode", validation_alias=AliasChoices("WORKER_AGENT", "AGENT_BACKEND"))
    aider_command: str = "aider"
    aider_model: str = "qwen3-coder-30b"
    aider_endpoint: str = ""
    aider_timeout_seconds: int = 3600
    opencode_command: str = "opencode"
    opencode_model: str = "vllm/qwen3.6-35b-a3b"
    opencode_endpoint: str = ""
    opencode_timeout_seconds: int = 3600
