from pathlib import Path

from ..execution import redact, run


class Hermes:
    def __init__(self, settings): self.s = settings
    def develop(self, prompt, workspace: Path, feedback=""):
        instruction = prompt + ("\n\nIndependent validation feedback from prior attempt:\n" + feedback if feedback else "")
        args = [self.s.hermes_command, "--provider", self.s.hermes_provider, "--model", self.s.hermes_model, instruction]
        result = run(args, cwd=workspace, timeout=self.s.hermes_timeout_seconds)
        result["stdout"] = redact(result["stdout"]); result["stderr"] = redact(result["stderr"])
        return result
