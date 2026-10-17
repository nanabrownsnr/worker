from fastmcp.apps import AppConfig

from .ui.tasks.resource import VIEW_URI, load_view_html

JOBS_VIEW_URI = VIEW_URI
JOB_VIEW_URI = VIEW_URI

def _status_state(status):
    if status in ("developing", "testing", "publishing", "notifying", "preparing"): return "active"
    if status == "queued": return "queued"
    if status == "failed": return "failed"
    return "completed"

def _job_payload(job):
    data = job.status_dict()
    data["state"] = _status_state(job.status)
    if job.status in ("completed", "failed"): data["result"] = job.result_dict()
    return data


def job_content(job):
    data = _job_payload(job)
    prompt = " ".join((job.prompt or "").split())
    if len(prompt) > 240:
        prompt = prompt[:237] + "..."
    return (
        f"Task ID: {data['job_id']}\n"
        f"Repository: {data['repo_url']}\n"
        f"Status: {data['status']}\n"
        f"Stage: {data['stage']}\n"
        f"Created: {data['created_at']}\n"
        f"Updated: {data['updated_at']}\n"
        f"Attempt: {data['attempt_number']}\n"
        f"Validation returns: {data['return_count']}/{data['max_returns']}\n"
        f"Prompt: {prompt}\n"
        f"To retry this task, call resume_task with task_id='{data['job_id']}'."
    )

def register_worker_resources(mcp):
    @mcp.resource(JOBS_VIEW_URI, app=AppConfig())
    def worker_view():
        return load_view_html()
