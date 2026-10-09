from pathlib import Path

from .schemas import Job


class Orchestrator:
    def __init__(self, settings, store, hermes, tester, git, telegram): self.s,self.store,self.hermes,self.tester,self.git,self.telegram=settings,store,hermes,tester,git,telegram
    def run(self, job: Job):
        try:
            job.status="preparing"; self.store.put(job)
            job.workspace=str(self.s.data_dir / "workspaces" / job.job_id)
            job.base_branch,job.working_branch,job.base_sha=self.git.prepare(job.repo_url,Path(job.workspace),job.job_id,job.base_branch or None)
            while True:
                job.attempt_number += 1; job.status="developing"; self.store.put(job)
                dev=self.hermes.develop(job.prompt,Path(job.workspace),job.failure_context); job.development_result=dev
                if dev["returncode"] != 0:
                    job.failure_context="Hermes failed: "+dev.get("stderr","")[-3000:]; job.failure_history.append(job.failure_context)
                    job.status="failed"; break
                job.status="testing"; self.store.put(job); test=self.tester.test(Path(job.workspace)); job.test_result=test
                if test["passed"]: job.status="publishing"; self.store.put(job); pub=self.git.publish(Path(job.workspace),job.working_branch); job.commit_sha=pub.get("commit_sha",""); job.remote_verified_sha=pub.get("remote_verified_sha",""); job.published_branch=job.working_branch; job.final_result={"outcome":"no_changes" if pub.get("no_changes") else "completed","verification":test}; break
                job.return_count += 1; job.failure_context=test["summary"]; job.failure_history.append(job.failure_context)
                if job.return_count >= job.max_returns: job.status="failed"; job.final_result={"outcome":"failed","reason":"maximum validation returns reached"}; break
                self.store.put(job)
            job.status="notifying"; self.store.put(job)
            msg=f"Worker {job.status}: {job.job_id} {job.repo_url} returns={job.return_count}"
            job.notification_status=self.telegram.send(msg)
            if job.final_result.get("outcome") in ("completed","no_changes"): job.status="completed"
            else: job.status="failed"
        except Exception as e:  # noqa: BLE001 - the graph must persist every terminal failure
            job.status="failed"; job.final_result={"outcome":"failed","reason":str(e)}
            job.notification_status=self.telegram.send(f"Worker failed: {job.job_id} {str(e)[:500]}")
        self.store.put(job); return job
