from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def now() -> str: return datetime.now(UTC).isoformat()

class JobRequest(BaseModel):
    prompt: str = Field(min_length=1)
    repo_url: str = Field(min_length=1)
    job_id: str | None = None
    base_branch: str | None = None
    deployment_env: str | None = None

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
