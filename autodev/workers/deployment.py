import json
import re
import socket
import tempfile
import time
from pathlib import Path

import yaml

from ..execution import redact, run


class DeploymentGate:
    """Build and smoke-test repository Docker configuration before publication."""

    def __init__(self, settings):
        self.s = settings

    def run(self, workspace: Path, env_path: str = ""):
        compose = next((workspace / name for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml") if (workspace / name).exists()), None)
        dockerfile = workspace / "Dockerfile"
        if not compose and not dockerfile.exists():
            return {"passed": False, "skipped": False, "returncode": 2, "timed_out": False, "duration": 0.0, "summary": "Docker validation failed: no Dockerfile or Compose configuration found"}
        started = time.monotonic()
        log_dir = self.s.data_dir / 'logs' / workspace.name
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f'deployment-{int(time.time() * 1000)}.log'
        project = f"worker-{workspace.name[:20]}-{int(time.time())}"
        compose_path = compose
        deployment_env = {}
        if compose:
                # Prevent the project from colliding with Worker or other jobs on host ports.
                document = yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
                port_count = sum(len(service.get("ports", [])) for service in (document.get("services") or {}).values())
                allocated_ports = self._available_ports(port_count)
                if allocated_ports is None:
                    return {"passed": False, "summary": f"No deployment ports available in range {self.s.deployment_port_start}-{self.s.deployment_port_end}"}
                deployment_env["PORT"] = str(allocated_ports[0]) if allocated_ports else ""
                port_index = 0
                for service in (document.get("services") or {}).values():
                    service_ports = service.get("ports")
                    if service_ports:
                        rewritten = []
                        for mapping in service_ports:
                            if isinstance(mapping, str) and ":" in mapping:
                                parts = mapping.split(":")
                                parts[-2] = str(allocated_ports[port_index])
                                rewritten.append(":".join(parts))
                                port_index += 1
                            elif isinstance(mapping, str) and mapping.isdigit():
                                rewritten.append(f"{allocated_ports[port_index]}:{mapping}")
                                port_index += 1
                            elif isinstance(mapping, dict) and "published" in mapping:
                                item = dict(mapping); item["published"] = allocated_ports[port_index]; rewritten.append(item); port_index += 1
                            else:
                                rewritten.append(mapping)
                        service["ports"] = rewritten
                # Use the rewritten document as the sole Compose file.  Compose
                # list fields are merged when supplied as an override, which
                # would retain the original host ports and defeat allocation.
                fd, compose_path = tempfile.mkstemp(prefix=".worker-compose-", suffix=".yml", dir=str(workspace))
                Path(compose_path).write_text(yaml.safe_dump(document), encoding="utf-8")
                import os
                os.close(fd)
                prefix = ["docker", "compose", "-p", project, "-f", str(compose_path)]
                if env_path: prefix += ["--env-file", env_path]
                result = self._run_compose_health(
                    prefix,
                    self._service_name(compose),
                    workspace,
                    deployment_env,
                    log_path,
                )
                cleanup = prefix + ["down", "--volumes", "--remove-orphans"]
        else:
                tag = f"worker-gate:{workspace.name.lower()}-{int(time.time())}"
                build = run(["docker", "build", "-t", tag, str(workspace)], cwd=workspace, timeout=self.s.deployment_timeout_seconds, log_path=log_path)
                if build["returncode"]:
                    return self._result(build, started, "Docker build failed", log_path)
                args = ["docker", "run", "--rm", "--name", tag.replace(":", "-")]
                if env_path: args += ["--env-file", env_path]
                result = run(args + [tag], cwd=workspace, timeout=self.s.deployment_timeout_seconds, log_path=log_path)
                cleanup = ["docker", "rm", "-f", tag.replace(":", "-")]
        cleanup_result = run(cleanup, cwd=workspace, timeout=30)
        if compose_path != compose:
            Path(compose_path).unlink(missing_ok=True)
        combined = (result.get("stdout", "") + "\n" + result.get("stderr", ""))
        fatal = self._fatal_log(combined)
        passed = result.get("returncode") == 0 and not result.get("timed_out") and not fatal
        return {**self._result(result, started, "Deployment validation passed" if passed else (fatal or "Deployment process failed"), log_path), "passed": passed, "cleanup_returncode": cleanup_result.get("returncode")}

    def _run_compose_health(self, prefix, service, workspace, env, log_path):
        """Start a long-running Compose service detached and validate its health."""
        up = run(prefix + ["up", "-d", "--build"], cwd=workspace, timeout=self.s.deployment_timeout_seconds, env=env, log_path=log_path)
        if up.get("returncode") != 0 or up.get("timed_out"):
            return up
        ps = run(prefix + ["ps", "-q", service], cwd=workspace, timeout=30, env=env)
        container_id = ps.get("stdout", "").strip().splitlines()[-1] if ps.get("stdout", "").strip() else ""
        if not container_id:
            return {**up, "returncode": 1, "stderr": up.get("stderr", "") + "\nCompose started no container for service " + service}
        deadline = time.monotonic() + self.s.deployment_timeout_seconds
        last_state = ""
        while time.monotonic() < deadline:
            inspected = run(["docker", "inspect", "--format", "{{json .State}}", container_id], cwd=workspace, timeout=10, env=env)
            try:
                state = json.loads(inspected.get("stdout", "{}"))
            except json.JSONDecodeError:
                state = {}
            health = (state.get("Health") or {}).get("Status")
            running = state.get("Running") is True
            last_state = f"running={running} health={health or 'not-configured'}"
            if health == "healthy" or (running and health is None):
                return {**up, "stdout": up.get("stdout", "") + "\n" + last_state, "stderr": up.get("stderr", "")}
            if state.get("Status") in ("exited", "dead"):
                return {**up, "returncode": state.get("ExitCode", 1) or 1, "stderr": up.get("stderr", "") + f"\nContainer exited: {last_state}"}
            time.sleep(2)
        return {**up, "returncode": -1, "timed_out": True, "stderr": up.get("stderr", "") + f"\nTimed out waiting for Compose service health: {last_state}"}

    def _available_ports(self, count):
        available = []
        for port in range(self.s.deployment_port_start, self.s.deployment_port_end + 1):
            with socket.socket() as sock:
                try:
                    sock.bind(("127.0.0.1", port))
                except OSError:
                    continue
                available.append(port)
                if len(available) == count:
                    return available
        return available if len(available) == count else None

    def _service_name(self, compose: Path) -> str:
        text = compose.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^\s{2}([A-Za-z0-9_-]+):\s*$", text, re.MULTILINE)
        return match.group(1) if match else ""

    def _fatal_log(self, text: str) -> str:
        patterns = [p.strip().lower() for p in self.s.deployment_log_patterns.split(",") if p.strip()]
        lines = [line.strip() for line in text.splitlines() if any(p in line.lower() for p in patterns)]
        return "\n".join(lines[-12:])

    @staticmethod
    def _result(result, started, summary, log_path):
        return {"passed": False, "returncode": result.get("returncode"), "timed_out": result.get("timed_out", False), "duration": time.monotonic() - started, "log_path": str(log_path), "stdout": redact(result.get("stdout", ""))[-8000:], "stderr": redact(result.get("stderr", ""))[-8000:], "summary": summary}
