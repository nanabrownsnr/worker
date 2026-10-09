from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def now() -> str: return datetime.now(UTC).isoformat()

class JobRequest(BaseModel):
    prompt: str = Field(min_length=1)
    repo_url: str = Field(min_length=1)
    job_id: str | None = None
    base_branch: str | None = None

class Job(BaseModel):
    job_id: str
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
