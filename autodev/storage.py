import sqlite3
from pathlib import Path

from .schemas import Job, now


class JobStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True); self.path = path
        with sqlite3.connect(path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)")
            c.commit()
    def put(self, job: Job):
        job.updated_at = now()
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?, ?)", (job.job_id, job.model_dump_json(), job.updated_at)); c.commit()
    def get(self, job_id: str) -> Job | None:
        with sqlite3.connect(self.path) as c:
            row = c.execute("SELECT data FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return Job.model_validate_json(row[0]) if row else None
    def list(self, limit=50):
        with sqlite3.connect(self.path) as c: rows = c.execute("SELECT data FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [Job.model_validate_json(r[0]) for r in rows]

    def all_nonterminal(self):
        with sqlite3.connect(self.path) as c:
            rows = c.execute("SELECT data FROM jobs WHERE json_extract(data, '$.status') NOT IN ('completed', 'failed')").fetchall()
        return [Job.model_validate_json(r[0]) for r in rows]
