import socket
import time
from pathlib import Path
from urllib.parse import urlparse

from ..execution import redact, run


class Hermes:
    def __init__(self, settings): self.s = settings

    def endpoint_reachable(self):
        if not self.s.hermes_endpoint: return True
        parsed = urlparse(self.s.hermes_endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.hostname: return False
        try:
            with socket.create_connection((parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)), timeout=3): return True
        except OSError: return False

    def develop(self, prompt, workspace: Path, feedback=""):
        instruction = ("You are Worker's software-development coding agent. Inspect the existing repository before changing it. "
                       "Implement the user's task completely, preserve compatible existing behavior, update dependencies carefully, "
                       "add or update meaningful tests, and run the project's relevant tests and build checks. "
                       "Work only inside the supplied workspace. Do not commit, push, deploy, send notifications, or access unrelated repositories or secrets. "
                       "If this is an existing project, update its current implementation rather than replacing it with a scaffold.\n\n"
                       "USER TASK:\n" + prompt)
        if feedback:
            instruction += "\n\nRecovery context. Continue the existing implementation in this workspace; do not restart or discard uncommitted changes.\n" + feedback
        args = [self.s.hermes_command, "--provider", self.s.hermes_provider, "-m", self.s.hermes_model, "-z", instruction, "--in", str(workspace), "--yolo"]
        log_dir = self.s.data_dir / "logs" / workspace.name
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"hermes-attempt-{int(time.time() * 1000)}.log"
        try:
            env = {"OPENAI_BASE_URL": self.s.hermes_endpoint} if self.s.hermes_endpoint else {}
            # GitHub credentials are publisher-only and must not reach Hermes.
            env.update({"GITHUB_TOKEN": None, "GH_TOKEN": None, "GIT_ASKPASS": None})
            result = run(args, cwd=workspace, timeout=self.s.hermes_timeout_seconds, env=env, log_path=log_path)
        except FileNotFoundError as exc:
            result = {"args": args, "returncode": 127, "stdout": "", "stderr": str(exc), "timed_out": False, "duration": 0.0}
        result["stdout"] = redact(result.get("stdout", "")); result["stderr"] = redact(result.get("stderr", ""))
        redacted_log = redact(log_path.read_text(encoding="utf-8", errors="replace")) if log_path.exists() else result["stdout"] + "\n" + result["stderr"]
        log_path.write_text(redacted_log, encoding="utf-8")
        result["log_path"] = str(log_path)
        result["last_activity"] = next((line.strip() for line in reversed(redacted_log.splitlines()) if line.strip()), "")
        if result.get("timed_out"): result["classification"] = "recoverable_interruption"
        elif result.get("returncode") == 127: result["classification"] = "nonrecoverable_configuration"
        elif result.get("returncode") == 0: result["classification"] = "success"
        else: result["classification"] = "uncertain_execution_failure"
        result["reason"] = f"Hermes exited {result.get('returncode')}" + (" after timeout" if result.get("timed_out") else "")
        return result
