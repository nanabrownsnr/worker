import json
import shutil
import sys
from importlib.util import find_spec
from pathlib import Path

from ..execution import redact, run


class PytestRunner:
    def __init__(self, settings): self.s = settings

    @staticmethod
    def _has_python_tests(workspace):
        return any(p.is_file() for p in workspace.rglob("test_*.py")) or any(p.is_file() for p in workspace.rglob("*_test.py"))

    @staticmethod
    def _has_go_tests(workspace): return any(p.is_file() for p in workspace.rglob("*_test.go"))
    @staticmethod
    def _has_rust_tests(workspace): return (workspace / "tests").is_dir() or any(p.is_file() for p in workspace.rglob("*.rs"))

    def detect_runner(self, workspace: Path):
        if self.s.test_command: return self.s.test_command.split(), "override", "configured TEST_COMMAND"
        python_markers = (
            "pyproject.toml", "uv.lock", "requirements.txt", "requirements-dev.txt",
            "setup.py", "setup.cfg", "tox.ini", "pytest.ini",
        )
        python_project = any((workspace / marker).exists() for marker in python_markers)
        if not python_project:
            python_project = any(p.suffix == ".py" for p in workspace.rglob("*.py"))
        if python_project and self._has_python_tests(workspace):
            uv_project = (workspace / "uv.lock").exists() or (workspace / "pyproject.toml").exists()
            if uv_project and shutil.which("uv"): return ["uv", "run", "pytest", "-q"], "python-uv", "Python uv project with pytest files"
            if (workspace / ".venv/bin/python").exists(): return [str(workspace / ".venv/bin/python"), "-m", "pytest", "-q"], "python-venv", "Python project with .venv and pytest files"
            if shutil.which("pytest"): return ["pytest", "-q"], "python-pytest", "Python project with pytest executable and pytest files"
            if find_spec("pytest"): return [sys.executable, "-m", "pytest", "-q"], "python-interpreter", "Python project using the service interpreter's pytest"
            return None, "python", "Python tests found but neither uv nor .venv/bin/python is available"
        if (workspace / "package.json").exists():
            try: package = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): package = {}
            if package.get("scripts", {}).get("test"): return ["npm", "test"], "node", "package.json test script"
        if (workspace / "go.mod").exists() and self._has_go_tests(workspace): return ["go", "test", "./..."], "go", "go.mod with Go test files"
        if (workspace / "Cargo.toml").exists() and self._has_rust_tests(workspace): return ["cargo", "test"], "rust", "Cargo.toml with Rust test sources"
        if python_project: return None, "python", "Python project found but no pytest test files were found"
        if (workspace / "package.json").exists(): return None, "node", "package.json has no test script"
        if (workspace / "go.mod").exists(): return None, "go", "go.mod found but no *_test.go files were found"
        if (workspace / "Cargo.toml").exists(): return None, "rust", "Cargo.toml found but no Rust test sources were found"
        return None, "unsupported", "No supported test framework or test files found"

    def test(self, workspace: Path):
        args, framework, detection = self.detect_runner(workspace)
        if args is None:
            return {"command": [], "framework": framework, "returncode": 2, "passed": False, "summary": detection, "stdout": "", "stderr": detection, "collected": False, "timed_out": False}
        r = run(args, cwd=workspace, timeout=self.s.test_timeout_seconds)
        stdout, stderr = redact(r["stdout"]), redact(r["stderr"])
        output = stdout + "\n" + stderr
        collected = "collected" in output or " passed" in output or " failed" in output or framework in ("node", "go", "rust", "override")
        return {"command": args, "framework": framework, "detection": detection, "returncode": r["returncode"], "passed": r["returncode"] == 0 and collected and not r["timed_out"], "summary": output[-6000:], "stdout": stdout[-6000:], "stderr": stderr[-6000:], "collected": collected, "timed_out": r["timed_out"], "duration": r["duration"]}
