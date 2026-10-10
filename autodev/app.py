from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import Settings
from .graph import Orchestrator
from .integrations.git import GitPublisher
from .integrations.telegram import Telegram
from .schemas import JobRequest
from .service import Service
from .storage import JobStore
from .workers.hermes import Hermes
from .workers.tester import PytestRunner


def create_app(settings=None, service=None):
    s=settings or Settings(); s.data_dir.mkdir(parents=True,exist_ok=True)
    store=JobStore(s.data_dir/"jobs.sqlite")
    service=service or Service(s,store,Orchestrator(s,store,Hermes(s),PytestRunner(s),GitPublisher(s),Telegram(s)))
    if service and hasattr(service, "reconcile_interrupted"):
        service.reconcile_interrupted()
    mcp=FastMCP("Worker")
    @mcp.tool()
    def submit_job(prompt: str, repo_url: str, deployment_env: str | None = None): return service.submit(JobRequest(prompt=prompt,repo_url=repo_url,deployment_env=deployment_env)).public_dict()
    @mcp.tool()
    def get_job_status(job_id: str):
        j=store.get(job_id); return j.public_dict(detail=True) if j else {"error":"not found"}
    @mcp.tool()
    def get_job_result(job_id: str): return get_job_status(job_id)
    @mcp.tool()
    def list_jobs(limit: int=50): return [j.public_dict() for j in store.list(min(limit,100))]
    @mcp.tool()
    def resume_job(job_id: str): return service.resume(job_id).public_dict()
    async def routes(request: Request):
        if request.url.path == "/health": return JSONResponse({"status":"ok"})
        if request.method=="POST" and request.url.path=="/jobs":
            try: return JSONResponse(service.submit(JobRequest.model_validate(await request.json())).public_dict(),status_code=202)
            except ValueError as e: return JSONResponse({"detail":str(e)},status_code=400)
        parts=request.url.path.strip("/").split("/")
        if request.method=="POST" and len(parts)==3 and parts[0]=="jobs" and parts[2]=="resume":
            try: return JSONResponse(service.resume(parts[1]).public_dict(), status_code=202)
            except ValueError as e: return JSONResponse({"detail":str(e)}, status_code=400)
        if len(parts)>=2 and parts[0]=="jobs":
            j=store.get(parts[1]);
            if not j: return JSONResponse({"detail":"not found"},status_code=404)
            return JSONResponse(j.public_dict(detail=True))
        return JSONResponse({"detail":"not found"},status_code=404)
    mcp.custom_route("/jobs",methods=["POST"])(routes); mcp.custom_route("/health",methods=["GET"])(routes); mcp.custom_route("/jobs/{job_id}",methods=["GET"])(routes); mcp.custom_route("/jobs/{job_id}/result",methods=["GET"])(routes); mcp.custom_route("/jobs/{job_id}/resume",methods=["POST"])(routes)
    return mcp.http_app()

app=create_app()
