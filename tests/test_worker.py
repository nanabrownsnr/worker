import time
from pathlib import Path

from autodev.config import Settings
from autodev.execution import redact
from autodev.graph import Orchestrator
from autodev.integrations.git import GitPublicationError
from autodev.schemas import Job, JobRequest
from autodev.service import Service
from autodev.storage import JobStore
from autodev.workers.tester import PytestRunner


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

class HermesSequence:
    def __init__(self, results): self.results=iter(results); self.calls=[]
    def develop(self,prompt,workspace,feedback=""):
        self.calls.append((prompt,workspace,feedback)); return next(self.results)
    def endpoint_reachable(self): return True

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

def test_git_hygiene_failure_returns_to_hermes(tmp_path):
    class HygieneGit(GitFake):
        def publish(self, workspace, branch):
            self.published += 1
            if self.published == 1:
                raise GitPublicationError("secret-like file in changes: .env", repairable=True)
            return {"commit_sha":"c","remote_verified_sha":"c","branch":branch}
    s,store,_,h,t,_,n=setup(tmp_path,tester=TesterFake([True, True]))
    g=HygieneGit()
    orch=Orchestrator(s,store,h,t,g,n)
    out=orch.run(Job(job_id="git-repair",prompt="p",repo_url="https://github.com/o/r.git"))
    assert out.status=="completed" and out.git_repair_count==1 and out.return_count==0 and len(h.calls)==2

def test_hermes_failure_retries_without_consuming_pytest_returns(tmp_path):
    h=HermesSequence([{"returncode":2,"stdout":"secret token=abc","stderr":"boom","timed_out":False,"duration":1,"classification":"uncertain_execution_failure","reason":"exit 2","last_activity":"boom"},{"returncode":0,"stdout":"ok","stderr":"","timed_out":False,"duration":1}])
    _,_,svc,_,_,_,_=setup(tmp_path,hermes=h); j=Job(job_id="j",prompt="p",repo_url="https://github.com/o/r.git")
    out=svc.orch.run(j); assert out.status=="completed" and out.hermes_retry_count==1 and out.return_count==0 and len(h.calls)==2 and "exit 2" in h.calls[1][2]

def test_hermes_retry_exhaustion_is_terminal(tmp_path):
    h=HermesSequence([{"returncode":2,"stdout":"x","stderr":"y","timed_out":False,"duration":1,"classification":"uncertain_execution_failure","reason":"exit 2","last_activity":"y"}] * 3)
    s,_,svc,_,_,_,_=setup(tmp_path,hermes=h); s.hermes_retries=2; j=Job(job_id="j",prompt="p",repo_url="https://github.com/o/r.git")
    out=svc.orch.run(j); assert out.status=="failed" and out.hermes_retry_count==3 and out.return_count==0 and len(h.calls)==3

def test_hermes_timeout_retries_and_nonrecoverable_executable_fails(tmp_path):
    timeout={"returncode":-1,"stdout":"partial","stderr":"","timed_out":True,"duration":3,"classification":"recoverable_interruption","reason":"timeout","last_activity":"partial"}
    h=HermesSequence([timeout,{"returncode":0,"stdout":"ok","stderr":"","timed_out":False,"duration":1}]); _,_,svc,_,_,_,_=setup(tmp_path,hermes=h)
    assert svc.orch.run(Job(job_id="timeout",prompt="p",repo_url="https://github.com/o/r.git")).status=="completed"
    bad=HermesSequence([{"returncode":127,"stdout":"","stderr":"missing executable","timed_out":False,"duration":0,"classification":"nonrecoverable_configuration","reason":"missing executable"}]); _,_,svc,_,_,_,_=setup(tmp_path / "bad",hermes=bad)
    out=svc.orch.run(Job(job_id="bad",prompt="p",repo_url="https://github.com/o/r.git")); assert out.status=="failed" and out.hermes_retry_count==1

def test_redaction_removes_secret_values():
    assert "abc" not in redact("token=abc password=hunter2")

def test_checkpoint_preserves_development_stage(tmp_path):
    _,_,svc,_,_,_,_=setup(tmp_path); j=Job(job_id="j",prompt="p",repo_url="https://github.com/o/r.git")
    svc.orch.run(j)
    states=list(svc.orch.workflow.get_state_history({"configurable":{"thread_id":"j"}}))
    assert any(x.values.get("job",{}).get("status")=="developing" for x in states if x.values)

def test_resume_links_child_and_preserves_workspace(tmp_path):
    _,store,svc,_,_,_,_=setup(tmp_path)
    workspace=tmp_path / "existing"; workspace.mkdir(); marker=workspace / "uncommitted.txt"; marker.write_text("keep")
    original=Job(job_id="failed",prompt="original",repo_url="https://github.com/o/r.git",workspace=str(workspace),status="failed",failure_context="Hermes stopped")
    store.put(original); child=svc.resume("failed")
    for _ in range(50):
        current=store.get(child.job_id)
        if current and current.status in ("completed","failed"): break
        time.sleep(0.01)
    assert child.parent_job_id=="failed" and store.get("failed").final_result=={}
    assert store.get(child.job_id).workspace==str(workspace) and marker.read_text()=="keep"

def test_resume_rejects_nonterminal_or_missing_workspace(tmp_path):
    _,store,svc,_,_,_,_=setup(tmp_path)
    store.put(Job(job_id="queued",prompt="p",repo_url="https://github.com/o/r.git",status="queued"))
    try: svc.resume("queued"); assert False
    except ValueError as exc: assert "terminally failed" in str(exc)
    store.put(Job(job_id="failed",prompt="p",repo_url="https://github.com/o/r.git",status="failed",workspace=str(tmp_path/"gone")))
    try: svc.resume("failed"); assert False
    except ValueError as exc: assert "workspace" in str(exc)

def test_resume_rejects_second_active_execution(tmp_path):
    _,store,svc,_,_,_,_=setup(tmp_path); workspace=tmp_path/"existing"; workspace.mkdir()
    store.put(Job(job_id="failed",prompt="p",repo_url="https://github.com/o/r.git",status="failed",workspace=str(workspace)))
    svc.orch.run=lambda *args, **kwargs: time.sleep(0.2)
    first=svc.resume("failed")
    try: svc.resume("failed"); assert False
    except ValueError as exc: assert "active execution" in str(exc)
    assert first.parent_job_id=="failed"

def test_submission_accepts_repo_and_is_idempotent(tmp_path):
    _,store,svc,_,_,_,_=setup(tmp_path)
    # avoid asynchronous timing dependency: durable idempotency is still stable
    j=Job(job_id="same",prompt="p",repo_url="https://github.com/o/r.git"); store.put(j); assert svc.submit(JobRequest(job_id="same",prompt="other",repo_url=j.repo_url)).job_id=="same"

def test_tester_detects_uv_and_executes_in_workspace(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n"); (tmp_path / "test_one.py").write_text("def test_ok(): pass\n")
    seen={}
    monkeypatch.setattr("autodev.workers.tester.run", lambda args, cwd, timeout: seen.update(args=args, cwd=cwd) or {"returncode":0,"stdout":"1 passed","stderr":"","timed_out":False,"duration":0.1})
    result=PytestRunner(Settings(test_command="")).test(tmp_path)
    assert result["command"]==["uv","run","pytest","-q"] and result["passed"] and seen["cwd"]==tmp_path

def test_tester_detects_venv_when_uv_unavailable(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(""); (tmp_path / "test_one.py").write_text(""); (tmp_path / ".venv/bin").mkdir(parents=True); (tmp_path / ".venv/bin/python").touch()
    monkeypatch.setattr("autodev.workers.tester.shutil.which", lambda name: None)
    assert PytestRunner(Settings(test_command="")).detect_runner(tmp_path)[0]==[str(tmp_path / ".venv/bin/python"),"-m","pytest","-q"]

def test_tester_detects_node_go_and_rust(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"test":"jest"}}')
    runner=PytestRunner(Settings(test_command="")); assert runner.detect_runner(tmp_path)[0]==["npm","test"]
    (tmp_path / "package.json").unlink(); (tmp_path / "go.mod").write_text("module x"); (tmp_path / "x_test.go").write_text("")
    assert runner.detect_runner(tmp_path)[0]==["go","test","./..."]
    (tmp_path / "go.mod").unlink(); (tmp_path / "x_test.go").unlink(); (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\nversion='0.1.0'\n"); (tmp_path / "tests").mkdir()
    assert runner.detect_runner(tmp_path)[0]==["cargo","test"]

def test_tester_fails_clearly_without_supported_tests(tmp_path):
    (tmp_path / "README.md").write_text("unsupported")
    result=PytestRunner(Settings(test_command="")).test(tmp_path)
    assert not result["passed"] and result["returncode"]==2 and "No supported" in result["summary"]
