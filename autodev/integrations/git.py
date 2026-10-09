import re
from pathlib import Path

from ..execution import redact, run


class GitPublisher:
    def __init__(self, settings): self.s = settings
    def _env(self):
        if not self.s.github_token: return None
        return {"GITHUB_TOKEN": self.s.github_token, "GIT_ASKPASS": "/app/autodev/integrations/git_askpass.py", "GIT_USERNAME": self.s.github_username}
    def prepare(self, repo_url, workspace: Path, job_id, base_branch=None):
        if not re.match(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?$", repo_url): raise ValueError("unsafe repository URL")
        workspace.parent.mkdir(parents=True, exist_ok=True)
        r = run(["git", "clone", repo_url, str(workspace)], timeout=900, env=self._env())
        if r["returncode"]: raise RuntimeError(redact(r["stderr"]))
        branch = base_branch or run(["git","branch","--show-current"], workspace)["stdout"].strip() or "main"
        sha = run(["git","rev-parse","HEAD"], workspace)["stdout"].strip()
        working = f"autodev/{job_id}"
        r = run(["git","switch","-c",working], workspace)
        if r["returncode"]: raise RuntimeError(redact(r["stderr"]))
        return branch, working, sha
    def publish(self, workspace: Path, branch: str):
        diff = run(["git","status","--porcelain"], workspace)["stdout"]
        if not diff.strip(): return {"no_changes": True, "branch": branch}
        forbidden = re.compile(r"(^|/)(\.env|.*(credential|secret|token).*)$", re.IGNORECASE)
        if any(forbidden.search(line[3:]) for line in diff.splitlines()): raise RuntimeError("forbidden or secret-like file in changes")
        for args in (["git","add","-A"],["git","commit","-m",f"AutoDev: implement job {branch}"]):
            r = run(args, workspace, env=self._env())
            if r["returncode"]: raise RuntimeError(redact(r["stderr"]))
        sha = run(["git","rev-parse","HEAD"], workspace)["stdout"].strip()
        for _ in range(self.s.git_push_retries):
            r = run(["git","push","--set-upstream",self.s.git_remote_name,branch], workspace, env=self._env())
            if r["returncode"] == 0:
                remote = run(["git","ls-remote",self.s.git_remote_name,f"refs/heads/{branch}"], workspace, env=self._env())["stdout"].split()[0]
                if remote != sha: raise RuntimeError("remote SHA mismatch")
                return {"commit_sha": sha, "remote_verified_sha": remote, "branch": branch}
        raise RuntimeError(redact(r["stderr"]))
