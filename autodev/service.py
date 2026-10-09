import threading
import uuid

from .schemas import Job, JobRequest


class Service:
    def __init__(self, settings, store, orchestrator): self.s,self.store,self.orch=settings,store,orchestrator; self.lock=threading.Lock(); self.workspace_locks=set(); self.active=False
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
        job=Job(job_id=req.job_id or uuid.uuid4().hex, prompt=req.prompt, repo_url=req.repo_url, max_returns=self.s.max_returns, base_branch=req.base_branch or "")
        self.store.put(job)
        def work():
            with self.lock:
                self.active=True
                try: self.orch.run(job)
                finally: self.active=False
        threading.Thread(target=work,daemon=True).start(); return job

    def resume(self, job_id: str):
        original = self.store.get(job_id)
        if not original: raise ValueError("job not found")
        if original.status != "failed": raise ValueError("only terminally failed jobs can be resumed")
        if not original.workspace or not __import__("pathlib").Path(original.workspace).is_dir(): raise ValueError("failed job workspace is unavailable")
        with self.lock:
            active_workspace = {j.workspace for j in self.store.list(100) if j.status not in ("completed", "failed")}
            if original.workspace in active_workspace or original.workspace in self.workspace_locks: raise ValueError("workspace already has an active execution")
            self.workspace_locks.add(original.workspace)
            child = Job(job_id=uuid.uuid4().hex, parent_job_id=original.job_id, prompt=original.prompt, repo_url=original.repo_url, workspace=original.workspace, base_branch=original.base_branch, working_branch=original.working_branch, base_sha=original.base_sha, max_returns=self.s.max_returns, failure_context=original.failure_context, failure_history=list(original.failure_history))
            self.store.put(child)
        def work():
            with self.lock: self.active=True
            try: self.orch.run(child, start_at="development")
            finally:
                with self.lock:
                    self.active=False
                    self.workspace_locks.discard(child.workspace)
        threading.Thread(target=work,daemon=True).start(); return child
