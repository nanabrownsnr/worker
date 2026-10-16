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

    def develop(self, prompt, workspace: Path, feedback="", model=None, provider=None):
        instruction = ("You are Worker's software-development coding agent. Inspect the existing repository before changing it. "
                       "Implement the user's task completely, preserve compatible existing behavior, update dependencies carefully, "
                       "add or update meaningful tests, and run the project's relevant tests and build checks. "
                       "Work only inside the supplied workspace. Do not commit, push, deploy, send notifications, or access unrelated repositories or secrets. "
                       "If this is an existing project, update its current implementation rather than replacing it with a scaffold. "
                       "When the task references external documentation, APIs, dependencies, or current behavior, inspect the supplied URLs "
                       "before implementing by using available read-only tools such as curl or git. Prefer user-supplied sources, keep requests "
                       "bounded, and never submit credentials or send arbitrary write requests. Record important external assumptions in the workspace documentation.\n\n"
                       "USER TASK:\n" + prompt)
        if feedback:
            instruction += "\n\nRecovery context. Continue the existing implementation in this workspace; do not restart or discard uncommitted changes. Tests are evidence, not unquestionable truth; verify framework behavior before changing production code.\n" + feedback
        hermes_args = [self.s.hermes_command, "--provider", provider or self.s.hermes_provider, "-m", model or self.s.hermes_model, "-z", instruction, "--in", "/workspace", "--yolo"]
        log_dir = self.s.data_dir / "logs" / workspace.name
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"hermes-attempt-{int(time.time() * 1000)}.log"
        try:
            env = {"OPENAI_BASE_URL": self.s.hermes_endpoint} if self.s.hermes_endpoint else {}
            # GitHub credentials are publisher-only and must not reach Hermes.
            env.update({"GITHUB_TOKEN": None, "GH_TOKEN": None, "GIT_ASKPASS": None})
            if self.s.hermes_container_enabled:
                host_workspace = self._host_workspace(workspace)
                args = ["docker", "run", "--rm", "--name", f"worker-hermes-{workspace.name[:20]}-{int(time.time())}", "--network", self.s.hermes_network, "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--pids-limit", str(self.s.hermes_pids_limit), "--memory", self.s.hermes_memory, "--cpus", self.s.hermes_cpus, "--user", "1001:1003", "--tmpfs", "/tmp:rw,nosuid,nodev,size=1g", "-e", "HOME=/home/nbrown", "-v", f"{host_workspace}:/workspace", "-v", f"{Path.home() / '.hermes'}:/home/nbrown/.hermes", "-v", f"{Path.home() / '.local/bin/hermes'}:/usr/local/bin/hermes:ro"]
                for key, value in env.items():
                    if value is not None: args += ["-e", f"{key}={value}"]
                args += [self.s.hermes_container_image] + hermes_args
                result = run(args, cwd=workspace, timeout=self.s.hermes_timeout_seconds, env={}, log_path=log_path)
            else:
                args = [self.s.hermes_command, "--provider", provider or self.s.hermes_provider, "-m", model or self.s.hermes_model, "-z", instruction, "--in", str(workspace), "--yolo"]
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

    def _host_workspace(self, workspace: Path) -> Path:
        if self.s.hermes_host_data_dir:
            data_dir = Path(self.s.hermes_host_data_dir)
            marker = Path(self.s.data_dir).resolve()
            resolved = workspace.resolve()
            return data_dir / resolved.relative_to(marker)
        return workspace
