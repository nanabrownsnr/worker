from pathlib import Path

from ..execution import redact, run


class PytestRunner:
    def __init__(self, settings): self.s = settings
    def test(self, workspace: Path):
        if self.s.test_command: args = self.s.test_command.split()
        elif (workspace / "uv.lock").exists() or (workspace / "pyproject.toml").exists(): args = ["uv", "run", "pytest", "-q"]
        elif (workspace / ".venv/bin/python").exists(): args = [str(workspace / ".venv/bin/python"), "-m", "pytest", "-q"]
        else: return {"command": [], "returncode": 2, "passed": False, "summary": "No Python project environment detected", "collected": False}
        r = run(args, cwd=workspace, timeout=self.s.test_timeout_seconds)
        output = redact(r["stdout"] + "\n" + r["stderr"])
        collected = "collected" in output or " passed" in output or " failed" in output
        return {"command": args, "returncode": r["returncode"], "passed": r["returncode"] == 0 and collected and not r["timed_out"], "summary": output[-6000:], "collected": collected, "timed_out": r["timed_out"], "duration": r["duration"]}
