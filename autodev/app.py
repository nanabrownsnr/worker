import json
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from .config import Settings
from .graph import Orchestrator
from .integrations.git import GitPublisher
from .integrations.telegram import Telegram
from .mcp_ui import (
    JOB_VIEW_URI,
    JOBS_VIEW_URI,
    _job_payload,
    job_content,
    register_worker_resources,
)
from .schemas import JobRequest, ResumeRequest
from .service import Service
from .storage import JobStore
from .workers.aider import Aider
from .workers.hermes import Hermes
from .workers.opencode import OpenCode
from .workers.tester import PytestRunner


def create_app(settings=None, service=None):
    s=settings or Settings(); s.data_dir.mkdir(parents=True,exist_ok=True)
    store=JobStore(s.data_dir/"jobs.sqlite")
    agent = {"aider": Aider, "opencode": OpenCode}.get(s.worker_agent.lower(), Hermes)(s)
    service=service or Service(s,store,Orchestrator(s,store,agent,PytestRunner(s),GitPublisher(s),Telegram(s)))
    if service and hasattr(service, "reconcile_interrupted"):
        service.reconcile_interrupted()
    mcp=FastMCP("Developer")
    @mcp.tool()
    def new_task(prompt: str, repo_url: str, deployment_env: dict[str, str] | None = None, project_config: dict | None = None):
        job = service.submit(JobRequest(prompt=prompt, repo_url=repo_url, deployment_env=deployment_env, project_config=project_config))
        return ToolResult(content=job_content(job), structured_content=job.status_dict())
    @mcp.tool(app=AppConfig(resource_uri=JOB_VIEW_URI, visibility=["model", "app"]))
    def get_task_status(task_id: str):
        j = store.get(task_id)
        if not j:
            return ToolResult(
                content=f"Worker task {task_id} was not found. Call get_tasks to find a valid task ID.",
                structured_content={"error": "not found", "job_id": task_id},
                meta={"ui": {"resourceUri": JOB_VIEW_URI}, "ui/resourceUri": JOB_VIEW_URI},
            )
        return ToolResult(
            content=job_content(j),
            structured_content={"job": _job_payload(j)},
            meta={"ui": {"resourceUri": JOB_VIEW_URI}, "ui/resourceUri": JOB_VIEW_URI},
        )
    @mcp.tool()
    def get_task_result(task_id: str):
        j = store.get(task_id)
        if not j:
            return {"error": "not found", "task_id": task_id, "next_action": "Call get_tasks to find a valid task ID."}
        result = j.result_dict()
        return ToolResult(
            content=f"{job_content(j)}\n\nResult:\n{json.dumps(result, indent=2, default=str)}",
            structured_content=result,
        )
    @mcp.tool(app=AppConfig(resource_uri=JOBS_VIEW_URI, visibility=["model", "app"]))
    def get_tasks(limit: int = 50, active_only: bool = False):
        """Show queued and running Worker jobs, with optional completed history."""
        jobs = store.list(min(max(limit, 1), 100))
        if active_only:
            jobs = [j for j in jobs if j.status not in ("completed", "failed")]
        payload = [_job_payload(j) for j in jobs]
        summary = "\n\n".join(job_content(j) for j in jobs)
        return ToolResult(content=f"{len(payload)} Worker tasks:\n\n{summary or 'No tasks found.'}", structured_content={"tasks": payload}, meta={"ui": {"resourceUri": JOBS_VIEW_URI}, "ui/resourceUri": JOBS_VIEW_URI})

    @mcp.tool(app=AppConfig(resource_uri=JOB_VIEW_URI, visibility=["model", "app"]))
    def get_task(task_id: str):
        """Show detailed status and result information for one Worker task."""
        job = store.get(task_id)
        if not job:
            return ToolResult(content=f"Worker task {task_id} was not found. Call get_tasks to find a valid task ID.", structured_content={"error": "not found", "job_id": task_id}, meta={"ui": {"resourceUri": JOB_VIEW_URI}, "ui/resourceUri": JOB_VIEW_URI})
        return ToolResult(content=job_content(job), structured_content={"job": _job_payload(job)}, meta={"ui": {"resourceUri": JOB_VIEW_URI}, "ui/resourceUri": JOB_VIEW_URI})
    @mcp.tool()
    def resume_task(task_id: str, deployment_env: dict[str, str] | None = None):
        job = service.resume(task_id, deployment_env)
        return ToolResult(content=f"Resumed task.\n\n{job_content(job)}", structured_content=job.status_dict())
    @mcp.tool()
    def get_task_logs(task_id: str, stage: str = "all", tail: int = 4000):
        job = store.get(task_id)
        if not job:
            return {"error": "not found", "task_id": task_id, "next_action": "Call get_tasks to find a valid task ID."}
        logs = _job_logs(job, stage, tail)
        return ToolResult(
            content=f"{job_content(job)}\n\nLogs requested: stage={stage}, tail={tail}\n{json.dumps(logs, indent=2, default=str)}",
            structured_content={"task": _job_payload(job), "logs": logs},
        )
    register_worker_resources(mcp)
    async def routes(request: Request):
        if request.url.path == "/health": return JSONResponse({"status":"ok"})
        if request.method == "GET" and request.url.path == "/jobs":
            try: limit = min(max(int(request.query_params.get("limit", "50")), 1), 100)
            except ValueError: limit = 50
            return JSONResponse([j.status_dict() for j in store.list(limit)])
        if request.method == "GET" and request.url.path in ("/", "/dashboard"):
            return HTMLResponse(DASHBOARD_HTML)
        if request.method=="POST" and request.url.path=="/jobs":
            try: return JSONResponse(service.submit(JobRequest.model_validate(await request.json())).status_dict(),status_code=202)
            except ValueError as e: return JSONResponse({"detail":str(e)},status_code=400)
        parts=request.url.path.strip("/").split("/")
        if request.method=="POST" and len(parts)==3 and parts[0]=="jobs" and parts[2]=="resume":
            try:
                raw_body = await request.body()
                body = json.loads(raw_body) if raw_body else {}
                resume = ResumeRequest.model_validate(body or {})
                return JSONResponse(service.resume(parts[1], resume.deployment_env).status_dict(), status_code=202)
            except ValueError as e: return JSONResponse({"detail":str(e)}, status_code=400)
        if request.method == "GET" and len(parts)==3 and parts[0]=="jobs" and parts[2]=="logs":
            job=store.get(parts[1])
            if not job: return JSONResponse({"detail":"not found"}, status_code=404)
            try: tail=min(max(int(request.query_params.get("tail","4000")),100),12000)
            except ValueError: tail=4000
            return JSONResponse(_job_logs(job, request.query_params.get("stage","all"), tail))
        if request.method == "GET" and len(parts)==3 and parts[0]=="jobs" and parts[2]=="result":
            j=store.get(parts[1]);
            if not j: return JSONResponse({"detail":"not found"},status_code=404)
            return JSONResponse(j.result_dict())
        if request.method == "GET" and len(parts)==2 and parts[0]=="jobs":
            j=store.get(parts[1]);
            if not j: return JSONResponse({"detail":"not found"},status_code=404)
            return JSONResponse(j.status_dict())
        return JSONResponse({"detail":"not found"},status_code=404)
    mcp.custom_route("/",methods=["GET"])(routes); mcp.custom_route("/dashboard",methods=["GET"])(routes); mcp.custom_route("/jobs",methods=["GET", "POST"])(routes); mcp.custom_route("/health",methods=["GET"])(routes); mcp.custom_route("/jobs/{job_id}",methods=["GET"])(routes); mcp.custom_route("/jobs/{job_id}/result",methods=["GET"])(routes); mcp.custom_route("/jobs/{job_id}/logs",methods=["GET"])(routes); mcp.custom_route("/jobs/{job_id}/resume",methods=["POST"])(routes)
    middleware = [Middleware(CORSMiddleware, allow_origins=["https://dev.twynity.ai", "https://twynity.ai", "http://localhost:3000", "http://localhost:5173"], allow_methods=["*"], allow_headers=["*"], expose_headers=["mcp-session-id"])]
    return mcp.http_app(middleware=middleware)

def _job_logs(job, stage="all", tail=4000):
    sources={"development":job.development_result,"testing":job.test_result,"test":job.test_result,"deployment":job.deployment_result}
    selected=sources if stage=="all" else {stage:sources.get(stage,{})}
    logs={}
    for name,data in selected.items():
        if not data: continue
        path=data.get("log_path",""); text=""
        if path:
            try: text=Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError: pass
        if not text: text=(str(data.get("stdout",""))+"\n"+str(data.get("stderr",""))).strip()
        logs[name]={"log_path":path,"excerpt":text[-tail:]}
    return {"job_id":job.job_id,"stage":stage,"logs":logs}

app=create_app()


DASHBOARD_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Worker Status</title><style>
body{font:16px system-ui,sans-serif;max-width:980px;margin:40px auto;padding:0 20px;color:#17202a;background:#f6f8fa}.card{background:white;border:1px solid #d0d7de;border-radius:12px;padding:20px;margin-bottom:18px;box-shadow:0 2px 8px #0000000a}.state{display:flex;align-items:center;gap:10px;font-size:22px;font-weight:650}.dot{width:14px;height:14px;border-radius:50%;background:#cf222e}.dot.ok{background:#1a7f37;box-shadow:0 0 0 4px #1a7f3722}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px 8px;border-bottom:1px solid #eaeef2;font-size:14px}code{font-size:12px}
</style></head><body><h1>Worker</h1><section class="card"><div class="state"><span id="dot" class="dot"></span><span id="health">Checking worker…</span></div><p id="updated"></p></section><section class="card"><h2>Jobs</h2><table><thead><tr><th>ID</th><th>Repository</th><th>Status</th><th>Attempt</th><th>Returns</th><th>Updated</th></tr></thead><tbody id="jobs"><tr><td colspan="6">Loading…</td></tr></tbody></table></section>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function refresh(){try{const h=await fetch('/health');if(!h.ok)throw Error();document.querySelector('#dot').className='dot ok';document.querySelector('#health').textContent='Worker online';const jobs=await (await fetch('/jobs?limit=50')).json();document.querySelector('#jobs').innerHTML=jobs.length?jobs.map(j=>`<tr><td><code>${esc(j.job_id.slice(0,12))}</code></td><td>${esc(j.repo_url)}</td><td>${esc(j.status)}</td><td>${esc(j.attempt_number)}</td><td>${esc(j.return_count)}/${esc(j.max_returns)}</td><td>${esc(j.updated_at)}</td></tr>`).join(''):'<tr><td colspan="6">No jobs</td></tr>';document.querySelector('#updated').textContent='Last checked '+new Date().toLocaleTimeString()}catch(e){document.querySelector('#dot').className='dot';document.querySelector('#health').textContent='Worker unavailable';}}refresh();setInterval(refresh,5000);
</script></body></html>"""
