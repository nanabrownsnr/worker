import re
from pathlib import Path

from ..execution import redact, run


class GitPublicationError(RuntimeError):
    def __init__(self, message, *, repairable=False):
        super().__init__(message)
        self.repairable = repairable


class GitPublisher:
    def __init__(self, settings): self.s = settings
    def _env(self):
        env = {"GIT_AUTHOR_NAME": self.s.git_author_name, "GIT_AUTHOR_EMAIL": self.s.git_author_email, "GIT_COMMITTER_NAME": self.s.git_author_name, "GIT_COMMITTER_EMAIL": self.s.git_author_email}
        if self.s.github_token:
            env.update({"GITHUB_TOKEN": self.s.github_token, "GIT_ASKPASS": "/app/autodev/integrations/git_askpass.py", "GIT_USERNAME": self.s.github_username})
        return env
    @staticmethod
    def _ensure_safe_ignores(workspace: Path):
        path = workspace / ".gitignore"
        rules = [".env\n", ".env.*\n", "!.env.example\n", ".venv/\n", "logs/\n", ".cache/\n", "node_modules/\n"]
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = [rule for rule in rules if rule not in existing.splitlines(keepends=True)]
        if missing:
            prefix = "\n# Worker-managed local and generated files\n"
            path.write_text(existing + prefix + "".join(missing), encoding="utf-8")
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
        self._ensure_safe_ignores(workspace)
        diff = run(["git","status","--porcelain"], workspace)["stdout"]
        if not diff.strip(): return {"no_changes": True, "branch": branch}
        changed = [line[3:] for line in diff.splitlines()]
        forbidden = re.compile(r"(^|/)(\.env$|.*(credential|secret|token).*)$", re.IGNORECASE)
        hygiene = re.compile(r"(^|/)(logs?|\.cache|\.venv|node_modules)(/|$)", re.IGNORECASE)
        forbidden_paths = [path for path in changed if forbidden.search(path)]
        hygiene_paths = [path for path in changed if hygiene.search(path)]
        if forbidden_paths:
            raise GitPublicationError("secret-like file in changes: " + ", ".join(forbidden_paths), repairable=True)
        if hygiene_paths:
            raise GitPublicationError("generated artifact in changes: " + ", ".join(hygiene_paths), repairable=True)
        for args in (["git","add","-A"],["git","commit","-m",f"AutoDev: implement job {branch}"]):
            r = run(args, workspace, env=self._env())
            if r["returncode"]: raise GitPublicationError(redact(r["stderr"]))
        sha = run(["git","rev-parse","HEAD"], workspace)["stdout"].strip()
        for _ in range(self.s.git_push_retries):
            r = run(["git","push","--set-upstream",self.s.git_remote_name,branch], workspace, env=self._env())
            if r["returncode"] == 0:
                remote = run(["git","ls-remote",self.s.git_remote_name,f"refs/heads/{branch}"], workspace, env=self._env())["stdout"].split()[0]
                if remote != sha: raise GitPublicationError("remote SHA mismatch")
                return {"commit_sha": sha, "remote_verified_sha": remote, "branch": branch}
        raise GitPublicationError(redact(r["stderr"]))
