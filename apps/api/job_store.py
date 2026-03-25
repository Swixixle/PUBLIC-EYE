# job_store.py
# In-memory job store. Resets on server restart.
# Acceptable at current deployment stage — no persistent state required.
# Future: replace with Redis or a lightweight SQLite store when persistence matters.

import uuid
from datetime import datetime, timezone
from typing import Any, Iterator, Optional


class JobStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class Job:
    def __init__(self, job_id: str, description: str = "", tier: str | None = None):
        self.job_id = job_id
        self.status = JobStatus.PENDING
        self.description = description
        self.tier = tier
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.receipt: Optional[Any] = None
        self.error: Optional[str] = None
        self.processing_time_ms: Optional[int] = None
        # Streaming pipeline (SSE / live UI)
        self.stage: str = "pending"
        self.transcript: Optional[str] = None
        self.stream_claims: list[dict[str, Any]] = []
        self.stream_entities: list[dict[str, str]] = []
        self.stream_layer_zero: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "description": self.description,
            "tier": self.tier,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "receipt": self.receipt,
            "error": self.error,
            "processing_time_ms": self.processing_time_ms,
            "stage": self.stage,
        }


_jobs: dict[str, Job] = {}


def create_job(description: str = "", tier: str | None = None) -> Job:
    job_id = f"job_{uuid.uuid4().hex}"
    job = Job(job_id=job_id, description=description, tier=tier)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Optional[Job]:
    return _jobs.get(job_id)


def iter_jobs() -> Iterator[Job]:
    return iter(_jobs.values())


def find_receipt_by_receipt_id(receipt_id: str) -> Optional[dict[str, Any]]:
    """
    Return the signed receipt dict for a completed job whose receiptId matches.
    Checks top-level receiptId only (Frame signed payload shape).
    """
    rid = (receipt_id or "").strip()
    if not rid:
        return None
    for job in _jobs.values():
        if job.status != JobStatus.COMPLETE or not job.receipt:
            continue
        r = job.receipt
        if not isinstance(r, dict):
            continue
        if r.get("receiptId") == rid:
            return r
        inner = r.get("receipt")
        if isinstance(inner, dict) and inner.get("receiptId") == rid:
            return inner
    return None


def mark_processing(job: Job) -> None:
    job.status = JobStatus.PROCESSING
    job.started_at = datetime.now(timezone.utc).isoformat()


def mark_complete(job: Job, receipt: Any, started_ms: float) -> None:
    job.status = JobStatus.COMPLETE
    job.receipt = receipt
    job.stage = "complete"
    job.completed_at = datetime.now(timezone.utc).isoformat()
    elapsed = (datetime.now(timezone.utc).timestamp() * 1000) - started_ms
    job.processing_time_ms = int(elapsed)


def mark_failed(job: Job, error: str) -> None:
    job.status = JobStatus.FAILED
    job.error = error
    job.stage = "failed"
    job.completed_at = datetime.now(timezone.utc).isoformat()


def update_job(job: Job, **fields: Any) -> None:
    """Merge fields onto the job (streaming / stage updates)."""
    for k, v in fields.items():
        if hasattr(job, k):
            setattr(job, k, v)


def normalize_claim_for_stream(raw: dict[str, Any]) -> dict[str, Any]:
    st = str(raw.get("text") or raw.get("statement") or "")
    cid = str(raw.get("id") or "").strip()
    if not cid:
        cid = f"c{uuid.uuid4().hex[:8]}"
    return {
        "id": cid,
        "statement": st,
        "type": str(raw.get("type") or "observed"),
        "implication_risk": str(raw.get("implication_risk") or "low"),
        "entities": [str(e) for e in (raw.get("entities") or []) if e],
    }


def append_stream_claim(job: Job, raw: dict[str, Any]) -> None:
    norm = normalize_claim_for_stream(raw)
    if any(c.get("id") == norm["id"] for c in job.stream_claims):
        return
    job.stream_claims.append(norm)


def append_stream_entity(job: Job, name: str, entity_type: str = "unknown") -> None:
    n = (name or "").strip()
    if not n:
        return
    nl = n.lower()
    for row in job.stream_entities:
        if row.get("name", "").lower() == nl:
            return
    job.stream_entities.append({"name": n, "type": entity_type})
