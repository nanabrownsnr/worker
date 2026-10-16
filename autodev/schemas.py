from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def now() -> str: return datetime.now(UTC).isoformat()

class JobRequest(BaseModel):
    prompt: str = Field(min_length=1)
    repo_url: str = Field(min_length=1)
    job_id: str | None = None
    base_branch: str | None = None
    deployment_env: dict[str, str] | None = None
    project_config: "ProjectConfig | None" = None

    @model_validator(mode="after")
    def validate_deployment_env(self):
        if self.deployment_env is not None:
            for key, value in self.deployment_env.items():
                if not key or not key.replace("_", "").isalnum() or not key[0].isalpha():
                    raise ValueError(f"invalid deployment environment variable name: {key}")
                if "\n" in value or "\r" in value:
                    raise ValueError(f"deployment environment value for {key} cannot contain newlines")
        return self


class ResumeRequest(BaseModel):
    deployment_env: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_deployment_env(self):
        if self.deployment_env is not None:
            for key, value in self.deployment_env.items():
                if not key or not key.replace("_", "").isalnum() or not key[0].isalpha():
                    raise ValueError(f"invalid deployment environment variable name: {key}")
                if "\n" in value or "\r" in value:
                    raise ValueError(f"deployment environment value for {key} cannot contain newlines")
        return self


class ProjectConfig(BaseModel):
    """Non-secret project policy; credentials are resolved server-side."""
    agent_backend: Literal["hermes", "aider", "opencode"] | None = None
    model_provider: str | None = None
    model_name: str | None = None
    model_endpoint: str | None = None
    max_context_tokens: int | None = Field(default=None, ge=1024, le=1_000_000)
    development_timeout_seconds: int | None = Field(default=None, ge=1, le=86_400)
    max_validation_returns: int | None = Field(default=None, ge=1, le=100)
    deployment_gate_enabled: bool | None = None
    deployment_port_start: int | None = Field(default=None, ge=1024, le=65535)
    deployment_port_end: int | None = Field(default=None, ge=1024, le=65535)

    @model_validator(mode="after")
    def validate_port_range(self):
        if self.deployment_port_start and self.deployment_port_end and self.deployment_port_start > self.deployment_port_end:
            raise ValueError("deployment_port_start must not exceed deployment_port_end")
        return self


class Ticket(BaseModel):
    ticket_id: str
    title: str
    goal: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    status: Literal["queued", "active", "completed", "blocked"] = "queued"
    attempt_count: int = 0
    failure_history: list[str] = Field(default_factory=list)


class Job(BaseModel):
    job_id: str
    parent_job_id: str = ""
    prompt: str
    repo_url: str
    workspace: str = ""
    base_branch: str = ""
    working_branch: str = ""
    base_sha: str = ""
    status: Literal["queued","preparing","developing","testing","publishing","notifying","completed","failed"] = "queued"
    return_count: int = 0
    max_returns: int = 5
    attempt_number: int = 0
    hermes_retry_count: int = 0
    git_repair_count: int = 0
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    development_result: dict[str, Any] = Field(default_factory=dict)
    test_result: dict[str, Any] = Field(default_factory=dict)
    failure_context: str = ""
    failure_history: list[str] = Field(default_factory=list)
    commit_sha: str = ""
    remote_verified_sha: str = ""
    published_branch: str = ""
    notification_status: dict[str, Any] = Field(default_factory=dict)
    final_result: dict[str, Any] = Field(default_factory=dict)
    deployment_env_path: str = ""
    deployment_result: dict[str, Any] = Field(default_factory=dict)
    deployment_retry_count: int = 0
    triage_result: dict[str, Any] = Field(default_factory=dict)
    workflow_mode: Literal["legacy", "incremental"] = "legacy"
    project_plan: list[Ticket] = Field(default_factory=list)
    current_ticket_index: int = 0
    ticket_failure_count: int = 0
    escalation_count: int = 0
    project_config: ProjectConfig = Field(default_factory=ProjectConfig)

    def public_dict(self, *, detail: bool = False) -> dict[str, Any]:
        """Return a bounded API representation without the original prompt or raw logs."""
        result = {
            "job_id": self.job_id, "parent_job_id": self.parent_job_id, "repo_url": self.repo_url,
            "status": self.status, "workspace": self.workspace, "base_branch": self.base_branch,
            "working_branch": self.working_branch, "attempt_number": self.attempt_number,
            "hermes_retry_count": self.hermes_retry_count, "git_repair_count": self.git_repair_count,
            "return_count": self.return_count, "max_returns": self.max_returns,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "commit_sha": self.commit_sha, "remote_verified_sha": self.remote_verified_sha,
            "published_branch": self.published_branch, "notification_status": self.notification_status,
            "final_result": self.final_result, "deployment_env_provided": bool(self.deployment_env_path),
            "deployment_result": {k: self.deployment_result.get(k) for k in ("passed", "skipped", "summary", "returncode", "timed_out", "duration") if k in self.deployment_result},
        }
        if detail:
            result["test_result"] = {k: self.test_result.get(k) for k in ("command", "framework", "returncode", "passed", "summary", "collected", "timed_out", "duration") if k in self.test_result}
            result["failure_context"] = self.failure_context[-2000:]
        return result

    def status_dict(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "parent_job_id": self.parent_job_id, "repo_url": self.repo_url, "status": self.status, "stage": self.status, "attempt_number": self.attempt_number, "hermes_retry_count": self.hermes_retry_count, "git_repair_count": self.git_repair_count, "return_count": self.return_count, "max_returns": self.max_returns, "created_at": self.created_at, "updated_at": self.updated_at}

    def result_dict(self) -> dict[str, Any]:
        result = self.status_dict()
        result.update({"working_branch": self.working_branch, "base_sha": self.base_sha, "commit_sha": self.commit_sha, "remote_verified_sha": self.remote_verified_sha, "published_branch": self.published_branch, "outcome": self.final_result.get("outcome") or (self.status if self.status in ("completed", "failed") else None), "final_result": self.final_result, "pytest": {k: self.test_result.get(k) for k in ("command", "framework", "returncode", "passed", "summary", "collected", "timed_out", "duration") if k in self.test_result}, "deployment": {k: self.deployment_result.get(k) for k in ("passed", "skipped", "summary", "returncode", "timed_out", "duration") if k in self.deployment_result}, "notification": self.notification_status, "failure_summary": self.failure_context[-4000:] if self.failure_context else ""})
        return result
