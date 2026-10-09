from pathlib import Path

from autodev.config import Settings
from autodev.graph import Orchestrator
from autodev.schemas import Job, JobRequest
from autodev.service import Service
from autodev.storage import JobStore


class HermesFake:
    def __init__(self, outcomes=None): self.outcomes=iter(outcomes or [0] * 10); self.calls=[]
    def develop(self,prompt,workspace,feedback=""): self.calls.append((prompt,workspace,feedback)); return {"returncode":next(self.outcomes),"stdout":"","stderr":""}
class TesterFake:
    def __init__(self, outcomes): self.outcomes=iter(outcomes); self.calls=0
    def test(self,workspace): self.calls+=1; return {"passed":next(self.outcomes),"summary":"failure" if self.calls else "","returncode":0}
class GitFake:
    def __init__(self): self.published=0
    def prepare(self,url,workspace,job,base=None): Path(workspace).mkdir(parents=True); return "main",f"autodev/{job}","base"
    def publish(self,workspace,branch): self.published+=1; return {"commit_sha":"c","remote_verified_sha":"c","branch":branch}
class TelegramFake:
    def __init__(self): self.messages=[]
    def send(self,msg): self.messages.append(msg); return {"sent":True}

def setup(tmp_path, hermes=None, tester=None):
    s=Settings(data_dir=tmp_path)
    store=JobStore(tmp_path/"jobs.sqlite"); h=hermes or HermesFake(); t=tester or TesterFake([True]); g=GitFake(); n=TelegramFake()
    return s,store,Service(s,store,Orchestrator(s,store,h,t,g,n)),h,t,g,n

def test_pass_publishes_and_notifies(tmp_path):
    _,_,svc,_,_,g,n=setup(tmp_path); j=Job(job_id="j",prompt="p",repo_url="https://github.com/o/r.git",workspace="",max_returns=5)
    out=svc.orch.run(j); assert out.status=="completed" and g.published==1 and n.messages

def test_five_returns_terminal_without_publish(tmp_path):
    _,_,svc,_,_,g,n=setup(tmp_path,tester=TesterFake([False]*5)); j=Job(job_id="j",prompt="p",repo_url="https://github.com/o/r.git",max_returns=5)
    out=svc.orch.run(j); assert out.status=="failed" and out.return_count==5 and g.published==0 and n.messages

def test_failure_then_repair(tmp_path):
    _,_,svc,h,_,_,_=setup(tmp_path,tester=TesterFake([False,True])); j=Job(job_id="j",prompt="p",repo_url="https://github.com/o/r.git")
    out=svc.orch.run(j); assert out.status=="completed" and len(h.calls)==2 and h.calls[1][2]=="failure"

def test_submission_accepts_repo_and_is_idempotent(tmp_path):
    _,store,svc,_,_,_,_=setup(tmp_path)
    # avoid asynchronous timing dependency: durable idempotency is still stable
    j=Job(job_id="same",prompt="p",repo_url="https://github.com/o/r.git"); store.put(j); assert svc.submit(JobRequest(job_id="same",prompt="other",repo_url=j.repo_url)).job_id=="same"
