import threading
import uuid

from .schemas import Job, JobRequest


class Service:
    def __init__(self, settings, store, orchestrator): self.s,self.store,self.orch=settings,store,orchestrator; self.lock=threading.Lock(); self.active=False
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
