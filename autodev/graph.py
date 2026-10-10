import sqlite3
import time
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .integrations.git import GitPublicationError
from .schemas import Job


class WorkerState(TypedDict):
    job: dict[str, Any]


class Orchestrator:
    """LangGraph workflow with durable SQLite checkpoints per job thread."""

    def __init__(self, settings, store, hermes, tester, git, telegram, deployment=None):
        self.s, self.store = settings, store
        self.hermes, self.tester, self.git, self.telegram = hermes, tester, git, telegram
        from .workers.deployment import DeploymentGate
        self.deployment = deployment or DeploymentGate(settings)
        self.s.data_dir.mkdir(parents=True, exist_ok=True)
        self._checkpoint_connection = sqlite3.connect(self.s.data_dir / "checkpoints.sqlite", check_same_thread=False)
        self.checkpointer = SqliteSaver(self._checkpoint_connection)
        graph = StateGraph(WorkerState)
        for name, node in (("prepare_workspace", self.prepare_workspace), ("development", self.development), ("independent_testing", self.independent_testing), ("deployment_validation", self.deployment_validation), ("github_publication", self.github_publication), ("telegram_notification", self.telegram_notification), ("terminal_success", self.terminal_success), ("terminal_failure", self.terminal_failure)):
            graph.add_node(name, node)
        graph.add_edge(START, "prepare_workspace")
        graph.add_edge("prepare_workspace", "development")
        graph.add_conditional_edges("development", self.route_development, {"retry_development": "development", "testing": "independent_testing", "failure": "terminal_failure"})
        graph.add_conditional_edges("independent_testing", self.route_test, {"development": "development", "deploy": "deployment_validation", "failure": "terminal_failure"})
        graph.add_conditional_edges("deployment_validation", self.route_deployment, {"development": "development", "publish": "github_publication", "failure": "terminal_failure"})
        graph.add_conditional_edges("github_publication", self.route_publish, {"notify": "telegram_notification", "repair": "development", "failure": "terminal_failure"})
        graph.add_conditional_edges("telegram_notification", self.route_notification, {"success": "terminal_success", "failure": "terminal_failure"})
        graph.add_edge("terminal_success", END)
        graph.add_edge("terminal_failure", END)
        self.workflow = graph.compile(checkpointer=self.checkpointer)
        resume_graph = StateGraph(WorkerState)
        for name, node in (("development", self.development), ("independent_testing", self.independent_testing), ("deployment_validation", self.deployment_validation), ("github_publication", self.github_publication), ("telegram_notification", self.telegram_notification), ("terminal_success", self.terminal_success), ("terminal_failure", self.terminal_failure)):
            resume_graph.add_node(name, node)
        resume_graph.add_edge(START, "development")
        resume_graph.add_conditional_edges("development", self.route_development, {"retry_development": "development", "testing": "independent_testing", "failure": "terminal_failure"})
        resume_graph.add_conditional_edges("independent_testing", self.route_test, {"development": "development", "deploy": "deployment_validation", "failure": "terminal_failure"})
        resume_graph.add_conditional_edges("deployment_validation", self.route_deployment, {"development": "development", "publish": "github_publication", "failure": "terminal_failure"})
        resume_graph.add_conditional_edges("github_publication", self.route_publish, {"notify": "telegram_notification", "repair": "development", "failure": "terminal_failure"})
        resume_graph.add_conditional_edges("telegram_notification", self.route_notification, {"success": "terminal_success", "failure": "terminal_failure"})
        resume_graph.add_edge("terminal_success", END); resume_graph.add_edge("terminal_failure", END)
        self.resume_workflow = resume_graph.compile(checkpointer=self.checkpointer)

    @staticmethod
    def _job(state):
        return Job.model_validate(state["job"])

    def _save(self, job):
        self.store.put(job)
        return {"job": job.model_dump()}

    def prepare_workspace(self, state):
        job = self._job(state); job.status = "preparing"; job.workspace = str((self.s.data_dir / "workspaces" / job.job_id).resolve())
        try:
            job.base_branch, job.working_branch, job.base_sha = self.git.prepare(job.repo_url, Path(job.workspace), job.job_id, job.base_branch or None)
        except Exception as exc:  # noqa: BLE001
            job.final_result = {"outcome": "failed", "reason": str(exc)}
        return self._save(job)

    def development(self, state):
        job = self._job(state)
        if job.final_result: return self._save(job)
        job.status = "developing"; job.attempt_number += 1
        self._save(job)
        result = self.hermes.develop(job.prompt, Path(job.workspace), job.failure_context); job.development_result = result
        if result.get("returncode") != 0:
            job.hermes_retry_count += 1
            job.failure_context = (f"{result.get('reason', 'Hermes failed')}\nclassification={result.get('classification')}\n"
                                   f"duration={result.get('duration')}\nlast_activity={result.get('last_activity', '')}\n"
                                   f"log_path={result.get('log_path', '')}\nstdout:\n{result.get('stdout', '')[-4000:]}\nstderr:\n{result.get('stderr', '')[-4000:]}")
            job.failure_history.append(job.failure_context)
            if result.get("classification") == "nonrecoverable_configuration" or not getattr(self.hermes, "endpoint_reachable", lambda: True)():
                job.final_result = {"outcome": "failed", "reason": job.failure_context}
        return self._save(job)

    def route_development(self, state):
        job = self._job(state)
        if not job.development_result.get("returncode") and not job.final_result: return "testing"
        if job.final_result: return "failure"
        if job.hermes_retry_count <= self.s.hermes_retries:
            if self.s.hermes_retry_delay_seconds: time.sleep(self.s.hermes_retry_delay_seconds)
            return "retry_development"
        job.final_result = {"outcome": "failed", "reason": job.failure_context or "Hermes retry limit reached"}
        self.store.put(job)
        return "failure"

    def independent_testing(self, state):
        job = self._job(state)
        if job.final_result: return self._save(job)
        job.status = "testing"; result = self.tester.test(Path(job.workspace)); job.test_result = result
        if not result.get("passed"):
            job.return_count += 1; job.failure_context = result.get("summary", "pytest failed"); job.failure_history.append(job.failure_context)
            if job.return_count >= job.max_returns: job.final_result = {"outcome": "failed", "reason": "maximum validation returns reached"}
        return self._save(job)

    def github_publication(self, state):
        job = self._job(state); job.status = "publishing"
        try:
            result = self.git.publish(Path(job.workspace), job.working_branch); job.commit_sha = result.get("commit_sha", ""); job.remote_verified_sha = result.get("remote_verified_sha", ""); job.published_branch = job.working_branch; job.final_result = {"outcome": "no_changes" if result.get("no_changes") else "completed", "verification": job.test_result}
        except GitPublicationError as exc:
            job.failure_context = str(exc)
            if exc.repairable and job.git_repair_count < self.s.git_repair_retries:
                job.git_repair_count += 1
                job.failure_history.append("Git publication hygiene failure: " + str(exc))
                job.final_result = {}
            else:
                job.final_result = {"outcome": "failed", "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001
            job.final_result = {"outcome": "failed", "reason": str(exc)}
        return self._save(job)

    def deployment_validation(self, state):
        job = self._job(state)
        if job.final_result: return self._save(job)
        result = self.deployment.run(Path(job.workspace), job.deployment_env_path) if self.s.deployment_gate_enabled else {"passed": True, "skipped": True, "summary": "Deployment gate disabled"}
        job.deployment_result = result
        if not result.get("passed"):
            job.deployment_retry_count += 1
            job.failure_context = "Deployment validation failed: " + result.get("summary", "unknown failure")
            job.failure_history.append(job.failure_context)
            if job.deployment_retry_count > self.s.deployment_retries:
                job.final_result = {"outcome": "failed", "reason": job.failure_context}
        return self._save(job)

    def telegram_notification(self, state):
        job = self._job(state); job.status = "notifying"; outcome = job.final_result.get("outcome", "failed")
        test = job.test_result
        message = (f"Worker {outcome}\njob={job.job_id}\nrepo={job.repo_url}\n"
                   f"stage={job.status} tests={'passed' if test.get('passed') else 'failed'} "
                   f"returns={job.return_count}/{job.max_returns} hermes_retries={job.hermes_retry_count}\n"
                   f"branch={job.published_branch or '-'} sha={job.remote_verified_sha or '-'}")
        if outcome == "failed": message += f"\nreason={job.final_result.get('reason', job.failure_context)[-500:]}"
        job.notification_status = self.telegram.send(message)
        return self._save(job)

    def terminal_success(self, state):
        job = self._job(state); job.status = "completed"; return self._save(job)

    def terminal_failure(self, state):
        job = self._job(state); job.status = "failed"
        if not job.notification_status:
            reason = job.final_result.get("reason", job.failure_context)[-500:]
            job.notification_status = self.telegram.send(f"Worker failed\njob={job.job_id}\nrepo={job.repo_url}\nstage={job.status}\nreturns={job.return_count}/{job.max_returns}\nhermes_retries={job.hermes_retry_count}\ngit_repairs={job.git_repair_count}\nreason={reason}")
        return self._save(job)

    def route_test(self, state):
        job = self._job(state)
        if job.final_result: return "failure"
        return "development" if job.test_result.get("passed") is False else "deploy"

    def route_deployment(self, state):
        job = self._job(state)
        if job.final_result: return "failure"
        return "publish" if job.deployment_result.get("passed") else "development"

    def route_publish(self, state):
        job = self._job(state)
        if not job.final_result and job.failure_context.startswith(("secret-like file", "generated artifact")):
            return "repair"
        return "notify" if job.final_result.get("outcome") in ("completed", "no_changes") else "failure"

    def route_notification(self, state):
        # Delivery status is persisted independently; it must not downgrade publication.
        return "success"

    def run(self, job: Job, start_at="prepare_workspace"):
        workflow = self.resume_workflow if start_at == "development" else self.workflow
        result = workflow.invoke({"job": job.model_dump()}, config={"configurable": {"thread_id": job.job_id}})
        return self._job(result)
