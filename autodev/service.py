import threading
import time
import uuid

from .schemas import Job, JobRequest, ProjectConfig


class Service:
    def __init__(self, settings, store, orchestrator): self.s,self.store,self.orch=settings,store,orchestrator; self.lock=threading.Lock(); self.workspace_locks=set(); self.threads=set(); self.active=False

    def wait_for_idle(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                threads = list(self.threads)
            if not threads: return True
            for thread in threads: thread.join(max(0, deadline - time.monotonic()))
        return not self.threads
    def reconcile_interrupted(self):
        """Convert work that died with the process into an explicit resumable failure."""
        for job in self.store.all_nonterminal():
            job.status = "failed"
            reason = "Worker process restarted before job reached a terminal state"
            job.failure_context = reason
            job.failure_history.append(reason)
            job.final_result = {"outcome": "failed", "reason": reason, "interrupted": True}
            self.store.put(job)
    def submit(self, req: JobRequest):
        if req.job_id and self.store.get(req.job_id): return self.store.get(req.job_id)
        config = req.project_config or ProjectConfig()
        job=Job(job_id=req.job_id or uuid.uuid4().hex, prompt=req.prompt, repo_url=req.repo_url, max_returns=config.max_validation_returns or self.s.max_returns, base_branch=req.base_branch or "", project_config=config, workflow_mode="incremental" if self.s.incremental_workflow_enabled else "legacy")
        if req.deployment_env is not None:
            env_dir = self.s.data_dir / "deployment-env"; env_dir.mkdir(parents=True, exist_ok=True)
            content = "\n".join(f"{key}={value}" for key, value in sorted(req.deployment_env.items())) + "\n"
            path = env_dir / f"{job.job_id}.env"; path.write_text(content, encoding="utf-8"); path.chmod(0o600)
            job.deployment_env_path = str(path)
        self.store.put(job)
        def work():
            with self.lock:
                self.active=True
                try: self.orch.run(job)
                finally:
                    self.active=False
                    self.threads.discard(threading.current_thread())
        thread = threading.Thread(target=work,daemon=True); self.threads.add(thread); thread.start(); return job

    def resume(self, job_id: str, deployment_env: dict[str, str] | None = None):
        original = self.store.get(job_id)
        if not original: raise ValueError("job not found")
        if original.status != "failed": raise ValueError("only terminally failed jobs can be resumed")
        if not original.workspace or not __import__("pathlib").Path(original.workspace).is_dir(): raise ValueError("failed job workspace is unavailable")
        with self.lock:
            active_workspace = {j.workspace for j in self.store.list(100) if j.status not in ("completed", "failed")}
            if original.workspace in active_workspace or original.workspace in self.workspace_locks: raise ValueError("workspace already has an active execution")
            self.workspace_locks.add(original.workspace)
            deployment_env_path = original.deployment_env_path
            if deployment_env is not None:
                env_dir = self.s.data_dir / "deployment-env"; env_dir.mkdir(parents=True, exist_ok=True)
                path = env_dir / f"{uuid.uuid4().hex}.env"
                path.write_text("\n".join(f"{key}={value}" for key, value in sorted(deployment_env.items())) + ("\n" if deployment_env else ""), encoding="utf-8")
                path.chmod(0o600)
                deployment_env_path = str(path)
            child = Job(
                job_id=uuid.uuid4().hex, parent_job_id=original.job_id,
                prompt=original.prompt, repo_url=original.repo_url,
                workspace=original.workspace, base_branch=original.base_branch,
                working_branch=original.working_branch, base_sha=original.base_sha,
                max_returns=self.s.max_returns,
                failure_context=original.failure_context,
                failure_history=list(original.failure_history),
                development_result=dict(original.development_result),
                test_result=dict(original.test_result),
                deployment_result=dict(original.deployment_result),
                commit_sha=original.commit_sha,
                remote_verified_sha=original.remote_verified_sha,
                published_branch=original.published_branch,
                deployment_env_path=deployment_env_path,
            )
            self.store.put(child)
        def work():
            with self.lock: self.active=True
            try: self.orch.run(child, start_at="resume")
            finally:
                with self.lock:
                    self.active=False
                    self.workspace_locks.discard(child.workspace)
                    self.threads.discard(threading.current_thread())
        thread = threading.Thread(target=work,daemon=True); self.threads.add(thread); thread.start(); return child
