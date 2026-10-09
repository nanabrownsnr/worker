import os
import re
import subprocess
import time
from pathlib import Path

SECRET = re.compile(r"(?i)(token|secret|password|api[_-]?key|authorization)([=:\s]+)[^\s,;]+")
def redact(text: str, extra=()) -> str:
    for value in extra:
        if value: text = text.replace(value, "[REDACTED]")
    return SECRET.sub(r"\1\2[REDACTED]", text)

def run(args, cwd: Path | None = None, timeout=900, env=None):
    started = time.monotonic(); merged = os.environ.copy(); merged.update(env or {})
    merged["GIT_TERMINAL_PROMPT"] = "0"
    try:
        p = subprocess.run(args, cwd=cwd, env=merged, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, start_new_session=True, check=False)
        return {"args": args, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr, "timed_out": False, "duration": time.monotonic()-started}
    except subprocess.TimeoutExpired as e:
        return {"args": args, "returncode": -1, "stdout": e.stdout or "", "stderr": e.stderr or "", "timed_out": True, "duration": time.monotonic()-started}
