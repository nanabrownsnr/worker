import time
from pathlib import Path

from ..execution import redact, run


class Aider:
    """Aider CLI adapter; Worker retains validation and publication ownership."""

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
        # Aider/LiteLLM needs an explicit provider for an OpenAI-compatible vLLM endpoint.
        log_dir = self.s.data_dir / "logs" / workspace.name
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"aider-attempt-{int(time.time() * 1000)}.log"
        settings_path = log_dir / "aider-model-settings.yml"
        settings_path.write_text(
            "- name: " + self.s.aider_model + "\n"
            "  extra_params:\n"
            "    extra_body:\n"
            "      chat_template_kwargs:\n"
            "        enable_thinking: false\n",
            encoding="utf-8",
        )
        args = [self.s.aider_command, "--yes", "--no-git", "--model-settings-file", str(settings_path), "--message", instruction, "--model", self.s.aider_model]
        env = {"OPENAI_API_BASE": self.s.aider_endpoint, "OPENAI_API_KEY": "worker-local"} if self.s.aider_endpoint else {}
        try:
            result = run(args, cwd=workspace, timeout=self.s.aider_timeout_seconds, env=env, log_path=log_path)
        except FileNotFoundError as exc:
            result = {"args": args, "returncode": 127, "stdout": "", "stderr": str(exc), "timed_out": False, "duration": 0.0}
        result["stdout"] = redact(result.get("stdout", ""))
        result["stderr"] = redact(result.get("stderr", ""))
        result["log_path"] = str(log_path)
        result["classification"] = "success" if result.get("returncode") == 0 else "uncertain_execution_failure"
        result["reason"] = f"Aider exited {result.get('returncode')}"
        return result
