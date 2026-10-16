import json
import time
from pathlib import Path

from ..execution import redact, run


class OpenCode:
    """Non-interactive OpenCode adapter for OpenAI-compatible model endpoints."""

    def __init__(self, settings):
        self.s = settings

    def endpoint_reachable(self):
        return True

    def develop(self, prompt, workspace: Path, feedback="", model=None, provider=None):
        instruction = (
            "Work only in this repository. Inspect existing code before editing. "
            "Implement the task completely, add meaningful tests, run tests and build checks, "
            "and do not commit, push, deploy, or access secrets.\n\nTASK:\n" + prompt
        )
        if feedback:
            instruction += "\n\nContinue existing work; preserve useful changes. Previous failure:\n" + feedback
        log_dir = self.s.data_dir / "logs" / workspace.name
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"opencode-attempt-{int(time.time() * 1000)}.log"
        config_path = workspace / "opencode.json"
        endpoint = self.s.opencode_endpoint or self.s.hermes_endpoint
        config_path.write_text(json.dumps({
            "$schema": "https://opencode.ai/config.json",
            "provider": {"vllm": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "vLLM",
                "options": {"baseURL": endpoint, "apiKey": "worker-local"},
                "models": {"qwen3.6-35b-a3b": {
                    "name": "Qwen3.6 35B A3B",
                    "limit": {"context": 80000, "output": 8192},
                }},
            }},
        }), encoding="utf-8")
        args = [self.s.opencode_command, "run", "--auto", "--model", model or self.s.opencode_model, instruction]
        env = {"OPENCODE_API_KEY": "worker-local"}
        try:
            result = run(args, cwd=workspace, timeout=self.s.opencode_timeout_seconds, env=env, log_path=log_path)
        except FileNotFoundError as exc:
            result = {"args": args, "returncode": 127, "stdout": "", "stderr": str(exc), "timed_out": False, "duration": 0.0}
        result["stdout"] = redact(result.get("stdout", ""))
        result["stderr"] = redact(result.get("stderr", ""))
        result["log_path"] = str(log_path)
        result["classification"] = "success" if result.get("returncode") == 0 else "uncertain_execution_failure"
        result["reason"] = f"OpenCode exited {result.get('returncode')}"
        config_path.unlink(missing_ok=True)
        return result
