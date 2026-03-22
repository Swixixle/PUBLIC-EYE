# job_store.py
# In-memory job store. Resets on server restart.
# Acceptable at current deployment stage — no persistent state required.
# Future: replace with Redis or a lightweight SQLite store when persistence matters.

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


class JobStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class Job:
    def __init__(self, job_id: str, description: str = ""):
        self.job_id = job_id
        self.status = JobStatus.PENDING
        self.description = description
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.receipt: Optional[Any] = None
        self.error: Optional[str] = None
        self.processing_time_ms: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "description": self.description,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "receipt": self.receipt,
            "error": self.error,
            "processing_time_ms": self.processing_time_ms,
        }


_jobs: dict[str, Job] = {}


def create_job(description: str = "") -> Job:
    job_id = f"job_{uuid4().hex}"
    job = Job(job_id=job_id, description=description)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Optional[Job]:
    return _jobs.get(job_id)


def mark_processing(job: Job) -> None:
    job.status = JobStatus.PROCESSING
    job.started_at = datetime.now(timezone.utc).isoformat()


def mark_complete(job: Job, receipt: Any, started_ms: float) -> None:
    job.status = JobStatus.COMPLETE
    job.receipt = receipt
    job.completed_at = datetime.now(timezone.utc).isoformat()
    elapsed = (datetime.now(timezone.utc).timestamp() * 1000) - started_ms
    job.processing_time_ms = int(elapsed)


def mark_failed(job: Job, error: str) -> None:
    job.status = JobStatus.FAILED
    job.error = error
    job.completed_at = datetime.now(timezone.utc).isoformat()
