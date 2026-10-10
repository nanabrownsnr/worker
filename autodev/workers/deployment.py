import re
import time
from pathlib import Path

from ..execution import redact, run


class DeploymentGate:
    """Build and smoke-test repository Docker configuration before publication."""

    def __init__(self, settings):
        self.s = settings

    def run(self, workspace: Path, env_path: str = ""):
        compose = next((workspace / name for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml") if (workspace / name).exists()), None)
        dockerfile = workspace / "Dockerfile"
        if not compose and not dockerfile.exists():
            return {"passed": True, "skipped": True, "summary": "No Dockerfile or Compose configuration found"}
        started = time.monotonic()
        project = f"worker-{workspace.name[:20]}-{int(time.time())}"
        if compose:
                prefix = ["docker", "compose", "-p", project, "-f", str(compose)]
                if env_path: prefix += ["--env-file", env_path]
                command = prefix + ["up", "--build", "--abort-on-container-exit", "--exit-code-from", self._service_name(compose)]
                result = run(command, cwd=workspace, timeout=self.s.deployment_timeout_seconds)
                cleanup = prefix + ["down", "--volumes", "--remove-orphans"]
        else:
                tag = f"worker-gate:{workspace.name.lower()}-{int(time.time())}"
                build = run(["docker", "build", "-t", tag, str(workspace)], cwd=workspace, timeout=self.s.deployment_timeout_seconds)
                if build["returncode"]:
                    return self._result(build, started, "Docker build failed")
                args = ["docker", "run", "--rm", "--name", tag.replace(":", "-")]
                if env_path: args += ["--env-file", env_path]
                result = run(args + [tag], cwd=workspace, timeout=self.s.deployment_timeout_seconds)
                cleanup = ["docker", "rm", "-f", tag.replace(":", "-")]
        cleanup_result = run(cleanup, cwd=workspace, timeout=30)
        combined = (result.get("stdout", "") + "\n" + result.get("stderr", ""))
        fatal = self._fatal_log(combined)
        passed = result.get("returncode") == 0 and not result.get("timed_out") and not fatal
        return {**self._result(result, started, "Deployment validation passed" if passed else (fatal or "Deployment process failed")), "passed": passed, "cleanup_returncode": cleanup_result.get("returncode")}

    def _service_name(self, compose: Path) -> str:
        text = compose.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^\s{2}([A-Za-z0-9_-]+):\s*$", text, re.MULTILINE)
        return match.group(1) if match else ""

    def _fatal_log(self, text: str) -> str:
        patterns = [p.strip().lower() for p in self.s.deployment_log_patterns.split(",") if p.strip()]
        lines = [line.strip() for line in text.splitlines() if any(p in line.lower() for p in patterns)]
        return "\n".join(lines[-12:])

    @staticmethod
    def _result(result, started, summary):
        return {"passed": False, "returncode": result.get("returncode"), "timed_out": result.get("timed_out", False), "duration": time.monotonic() - started, "stdout": redact(result.get("stdout", ""))[-8000:], "stderr": redact(result.get("stderr", ""))[-8000:], "summary": summary}
