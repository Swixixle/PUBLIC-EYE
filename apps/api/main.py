"""
Frame API — verifies signed receipts using JCS (RFC 8785) via the same `canonicalize`
npm package as TypeScript (Node subprocess). Never use JSON.stringify-equivalent hashing here.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from enum import Enum
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from adapters_media import dispatch_adapter
from adapters_podcast import (
    PODCAST_MAX_SECONDS,
    acoustic_fingerprint,
    download_audio,
    extract_speaker_claims,
    save_uploaded_audio,
    transcribe_audio,
    trim_audio_max,
)
from job_store import Job, create_job, get_job, mark_complete, mark_failed, mark_processing
from router import route_claim

REPO_ROOT = Path(__file__).resolve().parents[2]
JCS_SCRIPT = REPO_ROOT / "scripts" / "jcs-stringify.mjs"


def _repo_root() -> Path:
    override = os.environ.get("FRAME_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return REPO_ROOT


def jcs_canonicalize(obj: Any) -> str:
    """RFC 8785 canonical JSON using repo `canonicalize` (Node)."""
    root = _repo_root()
    script = root / "scripts" / "jcs-stringify.mjs"
    payload = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    proc = subprocess.run(
        ["node", str(script)],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        cwd=str(root),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "JCS subprocess failed")
    return proc.stdout


def sha256_hex_jcs(obj: Any) -> str:
    canon = jcs_canonicalize(obj)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def receipt_body_for_content_hash(receipt: dict[str, Any]) -> dict[str, Any]:
    body = {
        k: v
        for k, v in receipt.items()
        if k not in ("contentHash", "signature", "publicKey")
    }
    return body


def receipt_body_for_signing(receipt: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in receipt.items() if k != "signature"}


class NarrativeSentence(BaseModel):
    text: str
    sourceId: str


class ImplicationRisk(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ClaimRecord(BaseModel):
    id: str
    statement: str
    type: str = "observed"
    implication_risk: ImplicationRisk = ImplicationRisk.low
    implication_note: str | None = None
    assertedAt: str | None = None

    @model_validator(mode="after")
    def note_required_for_high(self) -> ClaimRecord:
        if self.implication_risk == ImplicationRisk.high and not self.implication_note:
            raise ValueError("implication_note required when implication_risk is 'high'")
        return self


class SourceRecord(BaseModel):
    id: str
    adapter: str
    url: str
    title: str
    retrievedAt: str
    externalRef: str | None = None
    metadata: dict[str, Any] | None = None


class UnknownItem(BaseModel):
    text: str
    resolution_possible: bool


class UnknownsBlock(BaseModel):
    operational: list[UnknownItem] = Field(default_factory=list)
    epistemic: list[UnknownItem] = Field(default_factory=list)


class SignedReceipt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schemaVersion: str
    receiptId: str
    createdAt: str
    claims: list[ClaimRecord]
    sources: list[SourceRecord]
    narrative: list[NarrativeSentence]
    unknowns: UnknownsBlock | None = None
    contentHash: str
    signerPublicKey: str | None = None
    signature: str
    publicKey: str


class GenerateReceiptRequest(BaseModel):
    candidateId: str = Field(..., min_length=1, max_length=64)


class LobbyingRequest(BaseModel):
    name: str
    candidateId: str | None = None


class CombinedReceiptRequest(BaseModel):
    candidateId: str
    lobbyingClients: list[str]
    years: list[int]


class NineNinetyRequest(BaseModel):
    orgName: str
    ein: str | None = None


class WikidataRequest(BaseModel):
    personName: str
    wikidataId: str | None = None


class JobRequest(BaseModel):
    """Async job submission — one of `source_url` or `receipt_type` should be set."""

    model_config = ConfigDict(extra="allow")

    source_url: str | None = None
    receipt_type: str | None = None
    name: str | None = None
    candidate_id: str | None = None
    ein: str | None = None
    lobbying_clients: list[str] | None = None
    years: list[int] | None = None
    wikidata_id: str | None = None


app = FastAPI(title="Frame API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_web_dir = _repo_root() / "apps" / "web"
if _web_dir.is_dir():
    app.mount("/web", StaticFiles(directory=str(_web_dir), html=True), name="web")


@app.get("/demo")
async def demo_redirect() -> FileResponse:
    return FileResponse(
        str(_repo_root() / "apps" / "web" / "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/")
async def root() -> dict[str, str]:
    """Base URL liveness (some checks hit `/` instead of `/health`)."""
    return {"status": "ok", "service": "frame-api", "health": "/health"}


@app.get("/health")
@app.get("/health/")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "frame-api"}


@app.get("/v1/adapters")
def adapters() -> dict[str, list[str]]:
    return {
        "kinds": ["fec", "opensecrets", "propublica", "lobbying", "edgar", "manual", "congress", "wikidata"],
        "note": "Adapters normalize third-party data into Frame SourceRecord rows. Gap 3 routes OCR claims to fec/propublica/lobbying/congress/wikidata.",
    }


@app.get("/v1/fec-search")
async def fec_search(name: str) -> dict[str, Any]:
    """Resolve a human name to FEC candidate rows (OpenFEC `q=` search)."""
    fec_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")
    q = urllib.parse.quote(name)
    url = f"https://api.open.fec.gov/v1/candidates/?q={q}&per_page=5&api_key={fec_key}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Frame/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        results = (data.get("results") or [])[:5]
        return {
            "results": [
                {
                    "candidateId": r.get("candidate_id"),
                    "name": r.get("name"),
                    "office": r.get("office_full"),
                    "state": r.get("state"),
                    "party": r.get("party_full"),
                    "electionYears": r.get("election_years", []),
                }
                for r in results
                if r.get("candidate_id")
            ]
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _resolve_fec_candidate_id(name: str) -> str:
    """Resolve a display name to an FEC candidate_id via OpenFEC search."""
    fec_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")
    q = urllib.parse.quote(name.strip())
    url = f"https://api.open.fec.gov/v1/candidates/?q={q}&per_page=5&api_key={fec_key}"
    req = urllib.request.Request(url, headers={"User-Agent": "Frame/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    results = data.get("results") or []
    for r in results:
        cid = r.get("candidate_id")
        if cid:
            return str(cid)
    raise ValueError(f"No FEC candidate found for name: {name!r}")


def _http_exception_detail(exc: HTTPException) -> str:
    d = exc.detail
    if isinstance(d, (dict, list)):
        return json.dumps(d)
    return str(d)


def _generate_fec_receipt_sync(candidate_id: str) -> dict[str, Any]:
    """
    Build a live FEC receipt for `candidateId` via Node (`buildLiveFecReceipt` + `signReceipt`),
    same pipeline as `scripts/generate-receipt.ts`.
    """
    root = _repo_root()
    script = root / "scripts" / "generate-receipt.ts"
    if not script.is_file():
        raise HTTPException(status_code=500, detail="generate-receipt script missing")

    proc = subprocess.run(
        ["npx", "tsx", str(script), candidate_id],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "subprocess failed").strip()
        raise HTTPException(
            status_code=502,
            detail={"message": "generate-receipt failed", "stderr": err[:4000]},
        )
    try:
        out = json.loads(proc.stdout.strip())
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"invalid JSON from generate-receipt: {exc}",
        ) from exc
    return _with_receipt_url(out)


@app.post("/v1/generate-receipt")
def generate_receipt(body: GenerateReceiptRequest) -> dict[str, Any]:
    return _generate_fec_receipt_sync(body.candidateId)


def _generate_lobbying_receipt_sync(name: str, candidate_id: str | None) -> dict[str, Any]:
    root = _repo_root()
    script = root / "scripts" / "generate-lobbying-receipt.ts"
    if not script.is_file():
        raise HTTPException(status_code=500, detail="generate-lobbying-receipt script missing")

    proc = subprocess.run(
        ["npx", "tsx", str(script), name, candidate_id or ""],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
        env={**os.environ},
        timeout=120,
    )

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "subprocess failed").strip()
        raise HTTPException(
            status_code=500,
            detail={"message": "generate-lobbying-receipt failed", "stderr": err[:4000]},
        )

    try:
        return _with_receipt_url(json.loads(proc.stdout.strip()))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {exc}") from exc


@app.post("/v1/generate-lobbying-receipt")
def generate_lobbying_receipt(req: LobbyingRequest) -> dict[str, Any]:
    return _generate_lobbying_receipt_sync(req.name, req.candidateId)


def _generate_combined_receipt_sync(
    candidate_id: str,
    lobbying_clients: list[str],
    years: list[int],
) -> dict[str, Any]:
    root = _repo_root()
    script = root / "scripts" / "generate-combined-receipt.ts"
    if not script.is_file():
        raise HTTPException(status_code=500, detail="generate-combined-receipt script missing")

    fec_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")

    args = [
        "npx",
        "tsx",
        str(script),
        candidate_id,
        json.dumps(lobbying_clients),
        json.dumps(years),
        fec_key,
    ]

    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
        env={**os.environ},
        timeout=120,
    )

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "subprocess failed")[-4000:]
        raise HTTPException(
            status_code=500,
            detail={"message": "generate-combined-receipt failed", "stderr": err},
        )

    try:
        return _with_receipt_url(json.loads(proc.stdout.strip()))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {exc}") from exc


@app.post("/v1/generate-combined-receipt")
def generate_combined_receipt(req: CombinedReceiptRequest) -> dict[str, Any]:
    return _generate_combined_receipt_sync(req.candidateId, req.lobbyingClients, req.years)


def _generate_990_receipt_sync(org_name: str, ein: str | None) -> dict[str, Any]:
    root = _repo_root()
    script = root / "scripts" / "generate-990-receipt.ts"
    if not script.is_file():
        raise HTTPException(status_code=500, detail="generate-990-receipt script missing")

    proc = subprocess.run(
        ["npx", "tsx", str(script), org_name, ein or ""],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
        env={**os.environ},
        timeout=120,
    )

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "subprocess failed")[-4000:]
        raise HTTPException(
            status_code=500,
            detail={"message": "generate-990-receipt failed", "stderr": err},
        )

    try:
        return _with_receipt_url(json.loads(proc.stdout.strip()))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {exc}") from exc


@app.post("/v1/generate-990-receipt")
def generate_990_receipt(req: NineNinetyRequest) -> dict[str, Any]:
    return _generate_990_receipt_sync(req.orgName, req.ein)


def _generate_wikidata_receipt_sync(person_name: str, wikidata_id: str | None) -> dict[str, Any]:
    root = _repo_root()
    script = root / "scripts" / "generate-wikidata-receipt.ts"
    if not script.is_file():
        raise HTTPException(status_code=500, detail="generate-wikidata-receipt script missing")

    proc = subprocess.run(
        ["npx", "tsx", str(script), person_name, wikidata_id or ""],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
        env={**os.environ},
        timeout=120,
    )

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "subprocess failed")[-4000:]
        raise HTTPException(
            status_code=500,
            detail={"message": "generate-wikidata-receipt failed", "stderr": err},
        )

    try:
        return _with_receipt_url(json.loads(proc.stdout.strip()))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {exc}") from exc


@app.post("/v1/generate-wikidata-receipt")
def generate_wikidata_receipt(req: WikidataRequest) -> dict[str, Any]:
    return _generate_wikidata_receipt_sync(req.personName, req.wikidataId)


# ─────────────────────────────────────────
# ASYNC JOB SYSTEM
# POST /v1/jobs    — submit work, get job_id immediately
# GET  /v1/jobs/{job_id} — poll for status and receipt
# POST /v1/intake  — same as POST /v1/jobs (canonical intake)
# ─────────────────────────────────────────


def _describe_job(request: JobRequest) -> str:
    """Human-readable description of what this job will do."""
    if request.source_url:
        return f"Media analysis: {request.source_url[:80]}"
    if request.receipt_type == "fec":
        return f"FEC receipt: {request.name or request.candidate_id or 'unknown'}"
    if request.receipt_type == "lobbying":
        return f"Lobbying receipt: {request.name or 'unknown'}"
    if request.receipt_type == "990":
        return f"990 receipt: {request.name or request.ein or 'unknown'}"
    if request.receipt_type == "wikidata":
        return f"Wikidata receipt: {request.name or 'unknown'}"
    if request.receipt_type == "combined":
        return f"Combined receipt: {request.name or request.candidate_id or 'unknown'}"
    if request.receipt_type == "media":
        return "Media analysis (file)"
    return "Unknown job type"


async def _generate_fec_receipt_for_job(
    candidate_id: str | None,
    name: str | None,
) -> dict[str, Any]:
    cid = (candidate_id or "").strip()
    if not cid and name:
        cid = await asyncio.to_thread(_resolve_fec_candidate_id, name.strip())
    if not cid:
        raise ValueError("FEC job requires candidate_id or name")
    return await asyncio.to_thread(_generate_fec_receipt_sync, cid)


async def _generate_lobbying_receipt_for_job(
    name: str | None,
    candidate_id: str | None,
) -> dict[str, Any]:
    n = (name or "").strip()
    if not n:
        raise ValueError("Lobbying job requires name")
    return await asyncio.to_thread(_generate_lobbying_receipt_sync, n, (candidate_id or "").strip() or None)


async def _generate_990_receipt_for_job(name: str | None, ein: str | None) -> dict[str, Any]:
    org = (name or "").strip()
    if not org:
        raise ValueError("990 job requires name (organization name)")
    return await asyncio.to_thread(_generate_990_receipt_sync, org, (ein or "").strip() or None)


async def _generate_wikidata_receipt_for_job(
    name: str | None,
    wikidata_id: str | None,
) -> dict[str, Any]:
    n = (name or "").strip()
    if not n:
        raise ValueError("Wikidata job requires name")
    return await asyncio.to_thread(
        _generate_wikidata_receipt_sync,
        n,
        (wikidata_id or "").strip() or None,
    )


async def _generate_combined_receipt_for_job(
    name: str | None,
    candidate_id: str | None,
    lobbying_clients: list[str] | None,
    years: list[int] | None,
) -> dict[str, Any]:
    cid = (candidate_id or "").strip()
    if not cid and name:
        cid = await asyncio.to_thread(_resolve_fec_candidate_id, name.strip())
    if not cid:
        raise ValueError("Combined job requires candidate_id or name")
    clients = list(lobbying_clients) if lobbying_clients is not None else []
    ys = list(years) if years is not None else [2022, 2024]
    return await asyncio.to_thread(_generate_combined_receipt_sync, cid, clients, ys)


async def _run_job(job: Job, request: JobRequest) -> None:
    """
    Background task. Calls the same adapter logic as synchronous /v1/generate-* routes.
    Marks job complete or failed. Does not raise — errors are recorded on the job.
    """
    mark_processing(job)
    start_ms = time.time() * 1000

    try:
        receipt: dict[str, Any] | None = None

        if request.source_url:
            receipt = {
                "status": "fetch_adapter_pending",
                "note": "FetchAdapter not yet wired. URL received and logged.",
                "source_url": request.source_url,
            }

        elif request.receipt_type == "fec":
            receipt = await _generate_fec_receipt_for_job(request.candidate_id, request.name)

        elif request.receipt_type == "lobbying":
            receipt = await _generate_lobbying_receipt_for_job(request.name, request.candidate_id)

        elif request.receipt_type == "990":
            receipt = await _generate_990_receipt_for_job(request.name, request.ein)

        elif request.receipt_type == "wikidata":
            receipt = await _generate_wikidata_receipt_for_job(request.name, request.wikidata_id)

        elif request.receipt_type == "combined":
            receipt = await _generate_combined_receipt_for_job(
                request.name,
                request.candidate_id,
                request.lobbying_clients,
                request.years,
            )

        elif request.receipt_type == "media":
            receipt = {
                "status": "media_pipeline_pending",
                "note": "Use /v1/analyze-and-verify for media uploads; async media job not wired yet.",
            }

        else:
            raise ValueError(f"Unknown or missing receipt_type: {request.receipt_type!r}")

        mark_complete(job, receipt, start_ms)

    except HTTPException as e:
        mark_failed(job, _http_exception_detail(e))
    except Exception as e:  # noqa: BLE001
        mark_failed(job, str(e))


@app.post("/v1/jobs")
async def submit_job(request: JobRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """
    Submit work. Returns job_id immediately.
    Client polls GET /v1/jobs/{job_id} for status and receipt.
    """
    if not request.source_url and not request.receipt_type:
        raise HTTPException(
            status_code=400,
            detail="Provide source_url or receipt_type",
        )
    description = _describe_job(request)
    job = create_job(description=description)
    background_tasks.add_task(_run_job, job, request)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "description": description,
        "poll_url": f"/v1/jobs/{job.job_id}",
    }


@app.get("/v1/jobs/{job_id}")
async def poll_job(job_id: str) -> dict[str, Any]:
    """
    Poll job status.
    status: "pending" | "processing" | "complete" | "failed"
    Receipt is present when status is "complete".
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return job.to_dict()


@app.post("/v1/intake")
async def intake(request: JobRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """
    Primary intake endpoint. Accepts source_url or receipt_type + params.
    Returns job_id immediately. Client polls /v1/jobs/{job_id}.

    Synchronous /v1/generate-* endpoints remain available for direct use.
    """
    return await submit_job(request, background_tasks)


# SQLite-backed perceptual hash ledger
_DB_PATH = Path(os.environ.get("FRAME_DB_PATH", "/tmp/frame_ledger.db"))
_db_lock = threading.Lock()


def _init_db() -> None:
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS phash_ledger (
                perceptual_hash TEXT PRIMARY KEY,
                file_hash TEXT NOT NULL,
                file_name TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS receipts (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.commit()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entity_receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_name TEXT NOT NULL,
                entity_normalized TEXT NOT NULL,
                claim_type TEXT NOT NULL,
                claim_text TEXT NOT NULL,
                receipt_id TEXT NOT NULL,
                receipt_url TEXT,
                signed_at TEXT NOT NULL,
                adapter_names TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entity ON entity_receipts(entity_normalized)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_claim_type ON entity_receipts(entity_normalized, claim_type)"
        )
        conn.commit()
        conn.close()


_init_db()


def _frame_public_base_url() -> str:
    return os.environ.get("FRAME_PUBLIC_BASE_URL", "https://frame-2yxu.onrender.com").rstrip("/")


def _store_signed_receipt(data: dict[str, Any]) -> None:
    rid = data.get("receiptId")
    if not rid:
        return
    created = str(data.get("createdAt") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    payload = json.dumps(data)
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            conn.execute(
                "INSERT OR REPLACE INTO receipts (id, created_at, payload) VALUES (?, ?, ?)",
                (str(rid), created, payload),
            )
            conn.commit()
        finally:
            conn.close()


def _with_receipt_url(data: dict[str, Any]) -> dict[str, Any]:
    """Persist signed receipt and add shareable receiptUrl (not part of cryptographic payload)."""
    _store_signed_receipt(data)
    rid = data.get("receiptId")
    if not rid:
        return data
    base = _frame_public_base_url()
    return {**data, "receiptUrl": f"{base}/receipt/{rid}"}


def _normalize_entity_name(name: str) -> str:
    """Lowercase, strip punctuation; collapse whitespace (e.g. 'Lindsey Graham' -> 'lindsey graham')."""
    s = re.sub(r"[^\w\s]", " ", (name or "").lower())
    return " ".join(s.split())


def _path_param_to_normalized(name: str) -> str:
    """Accept URL path like lindsey-graham or Lindsey%20Graham."""
    raw = urllib.parse.unquote(name or "")
    if "-" in raw and " " not in raw:
        raw = raw.replace("-", " ")
    return _normalize_entity_name(raw)


def _verification_reason_from_http(code: int) -> str:
    if code == 403:
        return "http_403"
    if code == 404:
        return "http_404"
    return "http_non_2xx"


async def _verify_and_snapshot_source(url: str, timeout: int = 5) -> dict[str, Any]:
    """Fetch a source URL, hash its content. Returns SourceRecord.metadata contract fields (no suggestedBy)."""
    import re as _re
    import socket

    requested = str(url).strip()
    out: dict[str, Any] = {
        "verificationStatus": "unverified",
        "requestedUrl": requested,
        "finalUrl": None,
        "httpStatus": None,
        "contentHash": None,
        "pageTitle": None,
        "retrievedAt": None,
        "reason": "fetch_failed",
    }

    try:
        req = urllib.request.Request(
            requested,
            headers={
                "User-Agent": "Frame/1.0 (cryptographic public record verification; https://github.com/Swixixle/FRAME)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            final_url = resp.geturl()
            body = resp.read(524288)  # max 512KB
            retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if 200 <= status < 300:
                content_hash = hashlib.sha256(body).hexdigest()
                page_title: str | None = None
                try:
                    text = body.decode("utf-8", errors="ignore")
                    title_match = _re.search(r"<title[^>]*>([^<]{1,200})</title>", text, _re.IGNORECASE)
                    if title_match:
                        page_title = title_match.group(1).strip()
                except Exception:  # noqa: BLE001
                    pass
                out.update(
                    {
                        "verificationStatus": "verified",
                        "finalUrl": final_url,
                        "httpStatus": status,
                        "contentHash": content_hash,
                        "pageTitle": page_title,
                        "retrievedAt": retrieved_at,
                        "reason": None,
                    },
                )
            else:
                out["reason"] = "http_non_2xx"
    except urllib.error.HTTPError as e:
        out["reason"] = _verification_reason_from_http(int(e.code))
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, socket.timeout) or isinstance(reason, TimeoutError):
            out["reason"] = "timeout"
        elif isinstance(reason, OSError) and "timed out" in str(reason).lower():
            out["reason"] = "timeout"
        elif "timed out" in str(e).lower():
            out["reason"] = "timeout"
        else:
            out["reason"] = "fetch_failed"
    except TimeoutError:
        out["reason"] = "timeout"
    except Exception as e:  # noqa: BLE001
        if "timeout" in str(e).lower():
            out["reason"] = "timeout"
        else:
            out["reason"] = "fetch_failed"

    return out


async def _check_phash_ledger(phash: str) -> dict[str, Any] | None:
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM phash_ledger WHERE perceptual_hash = ?",
                (phash,),
            ).fetchone()
            if row:
                return {
                    "matchType": "exact",
                    "firstSeenAt": row["first_seen_at"],
                    "firstSeenFile": row["file_name"],
                    "fileHash": row["file_hash"],
                    "message": f"This content was first seen at {row['first_seen_at']}. Identical perceptual fingerprint.",
                }
            try:
                import imagehash

                query_hash = imagehash.hex_to_hash(phash)
                rows = conn.execute("SELECT * FROM phash_ledger").fetchall()
                for r in rows:
                    stored_hash = imagehash.hex_to_hash(r["perceptual_hash"])
                    distance = query_hash - stored_hash
                    if distance <= 10:
                        return {
                            "matchType": "near-duplicate",
                            "hammingDistance": int(distance),
                            "firstSeenAt": r["first_seen_at"],
                            "firstSeenFile": r["file_name"],
                            "fileHash": r["file_hash"],
                            "message": f"Near-duplicate content detected (Hamming distance: {distance}/64). Original first seen at {r['first_seen_at']}.",
                        }
            except Exception:  # noqa: BLE001
                pass
        finally:
            conn.close()
    return None


async def _add_to_phash_ledger(phash: str, file_hash: str, filename: str, timestamp: str) -> None:
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            conn.execute(
                "INSERT OR IGNORE INTO phash_ledger (perceptual_hash, file_hash, file_name, first_seen_at) VALUES (?, ?, ?, ?)",
                (phash, file_hash, filename, timestamp),
            )
            conn.commit()
        finally:
            conn.close()


@app.get("/v1/ledger")
def get_ledger() -> dict[str, Any]:
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT perceptual_hash, file_hash, file_name, first_seen_at FROM phash_ledger ORDER BY first_seen_at DESC LIMIT 100",
            ).fetchall()
            return {
                "count": len(rows),
                "entries": [dict(r) for r in rows],
            }
        finally:
            conn.close()


@app.get("/v1/receipt/{receipt_id}")
def get_receipt_json(receipt_id: str) -> dict[str, Any]:
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT payload FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Receipt not found")
            return json.loads(row["payload"])
        finally:
            conn.close()


@app.get("/receipt/{receipt_id}", response_class=HTMLResponse)
def receipt_share_page(receipt_id: str) -> HTMLResponse:
    """Shareable HTML view — client loads receipt JSON from GET /v1/receipt/{id}."""
    path = _repo_root() / "apps" / "web" / "receipt.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="receipt page template missing")
    return HTMLResponse(
        content=path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def _entity_ledger_payload(normalized: str, *, limit: int | None = None) -> dict[str, Any]:
    """Build JSON for GET /v1/entity/{name} and summary (optional row limit for receipts)."""
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM entity_receipts WHERE entity_normalized = ?",
                (normalized,),
            ).fetchone()
            n = int(total[0]) if total else 0
            if n == 0:
                raise HTTPException(status_code=404, detail="Entity not found")
            display_row = conn.execute(
                "SELECT entity_name FROM entity_receipts WHERE entity_normalized = ? ORDER BY id DESC LIMIT 1",
                (normalized,),
            ).fetchone()
            display = display_row["entity_name"] if display_row else normalized.title()
            type_rows = conn.execute(
                "SELECT claim_type, COUNT(*) AS c FROM entity_receipts WHERE entity_normalized = ? GROUP BY claim_type",
                (normalized,),
            ).fetchall()
            claim_types = {str(r["claim_type"]): int(r["c"]) for r in type_rows}
            q = (
                "SELECT receipt_id, receipt_url, claim_text, claim_type, signed_at, adapter_names "
                "FROM entity_receipts WHERE entity_normalized = ? ORDER BY id DESC"
            )
            params: tuple[Any, ...] = (normalized,)
            if limit is not None:
                q += " LIMIT ?"
                params = (normalized, int(limit))
            rows = conn.execute(q, params).fetchall()
        finally:
            conn.close()

    receipts: list[dict[str, Any]] = []
    for r in rows:
        raw_adapters = r["adapter_names"]
        adapters = (
            [a.strip() for a in str(raw_adapters).split(",") if a.strip()]
            if raw_adapters
            else []
        )
        receipts.append(
            {
                "receiptId": r["receipt_id"],
                "receiptUrl": r["receipt_url"],
                "claimText": r["claim_text"],
                "claimType": r["claim_type"],
                "signedAt": r["signed_at"],
                "adapters": adapters,
            }
        )
    return {
        "entity": display,
        "normalized": normalized,
        "receiptCount": n,
        "claimTypes": claim_types,
        "receipts": receipts,
    }


@app.get("/v1/entity/{name}/summary")
def get_entity_summary(name: str) -> dict[str, Any]:
    """Behavioral ledger for an entity — counts + most recent 3 receipts only."""
    normalized = _path_param_to_normalized(name)
    return _entity_ledger_payload(normalized, limit=3)


@app.get("/v1/entity/{name}")
def get_entity_ledger(name: str) -> dict[str, Any]:
    """Full behavioral ledger for a normalized entity name."""
    normalized = _path_param_to_normalized(name)
    return _entity_ledger_payload(normalized, limit=None)


@app.get("/v1/entities")
def list_entities() -> dict[str, Any]:
    """All entities Frame has indexed, by receipt count descending."""
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT
                  x.entity_normalized,
                  (
                    SELECT entity_name FROM entity_receipts er
                    WHERE er.entity_normalized = x.entity_normalized
                    ORDER BY er.id DESC LIMIT 1
                  ) AS entity_name,
                  x.cnt AS receipt_count
                FROM (
                  SELECT entity_normalized, COUNT(*) AS cnt
                  FROM entity_receipts
                  GROUP BY entity_normalized
                ) AS x
                ORDER BY x.cnt DESC
                """
            ).fetchall()
        finally:
            conn.close()
    return {
        "entities": [
            {
                "entity": r["entity_name"] or r["entity_normalized"].title(),
                "normalized": r["entity_normalized"],
                "receiptCount": int(r["receipt_count"]),
            }
            for r in rows
        ]
    }


@app.get("/entity/{name}", response_class=HTMLResponse)
def entity_share_page(name: str) -> HTMLResponse:
    """Standalone entity ledger page (baroque frame; loads JSON from GET /v1/entity/{name})."""
    path = _repo_root() / "apps" / "web" / "entity.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="entity page template missing")
    return HTMLResponse(
        content=path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


async def _build_analyze_media_response(
    contents: bytes,
    filename: str,
    content_type: str,
) -> dict[str, Any]:
    # Step 1 — cryptographic hash
    file_hash = hashlib.sha256(contents).hexdigest()
    file_size = len(contents)
    content_type = content_type or "unknown"
    filename = filename or "unknown"
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Step 2 — perceptual hash (survives re-compression, cropping, watermarks)
    perceptual_hash: str | None = None
    perceptual_hash_type: str | None = None
    try:
        import io

        import imagehash
        from PIL import Image

        img = Image.open(io.BytesIO(contents))
        ph = imagehash.phash(img)
        perceptual_hash = str(ph)
        perceptual_hash_type = "pHash-DCT-64bit"
    except Exception as e:  # noqa: BLE001
        perceptual_hash = None
        perceptual_hash_type = f"unavailable: {str(e)[:80]}"

    # Step 3 — OCR via Claude vision (extract text, claims, classification, and primary sources)
    extracted_text: str | None = None
    extracted_claims: list[str] = []
    extracted_claim_objects: list[dict[str, Any]] = []
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key and content_type.startswith("image/"):
        try:
            import anthropic as ant

            client = ant.Anthropic(api_key=anthropic_key)
            b64_image = base64.standard_b64encode(contents).decode("utf-8")
            media_type_map = {
                "image/jpeg": "image/jpeg",
                "image/png": "image/png",
                "image/gif": "image/gif",
                "image/webp": "image/webp",
            }
            ant_media_type = media_type_map.get(content_type, "image/jpeg")
            msg = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1200,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": ant_media_type,
                                    "data": b64_image,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Analyze this image and return JSON only — no markdown, no explanation.\n\n"
                                    "Return this exact structure:\n"
                                    "{\n"
                                    '  "extracted_text": "all visible text verbatim",\n'
                                    '  "claims": [\n'
                                    "    {\n"
                                    '      "text": "the specific claim",\n'
                                    '      "type": "one of: government_action | financial | death_toll | election | legal | scientific | corporate | lobbying | biographical | general",\n'
                                    '      "entities": ["named people, orgs, or programs mentioned"],\n'
                                    '      "primary_sources": [\n'
                                    "        {\n"
                                    '          "label": "short source name",\n'
                                    '          "url": "direct URL to the most authoritative primary source for this claim",\n'
                                    '          "type": "one of: government | database | legislation | nonprofit | news | academic"\n'
                                    "        }\n"
                                    "      ]\n"
                                    "    }\n"
                                    "  ]\n"
                                    "}\n\n"
                                    "For primary_sources, use real URLs to actual public records:\n"
                                    "- Government actions/foreign aid: state.gov, usaid.gov, congress.gov, gao.gov\n"
                                    "- Financial/donations: fec.gov, opensecrets.org, sec.gov\n"
                                    "- Death tolls/health: who.int, cdc.gov, reliefweb.int, acleddata.com\n"
                                    "- Legislation: congress.gov/bill/\n"
                                    "- Nonprofits: projects.propublica.org/nonprofits\n"
                                    "- Corporate: sec.gov/cgi-bin/browse-edgar\n"
                                    "Provide 1-3 primary sources per claim. Use real, specific URLs when possible.\n"
                                    'If no text is visible return {"extracted_text": "", "claims": []}.'
                                ),
                            },
                        ],
                    }
                ],
            )
            block = msg.content[0]
            ocr_raw = getattr(block, "text", str(block)).strip()
            if ocr_raw.startswith("```"):
                parts = ocr_raw.split("```")
                if len(parts) >= 2:
                    ocr_raw = parts[1]
                    if ocr_raw.startswith("json"):
                        ocr_raw = ocr_raw[4:]
            ocr_data = json.loads(ocr_raw)
            extracted_text = ocr_data.get("extracted_text", "")
            raw_claims = ocr_data.get("claims", [])
            # Support both old format (list of strings) and new format (list of objects)
            extracted_claims = []
            extracted_claim_objects = []
            for c in raw_claims:
                if isinstance(c, str):
                    extracted_claims.append(c)
                    extracted_claim_objects.append(
                        {"text": c, "type": "general", "entities": [], "primary_sources": []},
                    )
                elif isinstance(c, dict):
                    extracted_claims.append(str(c.get("text", "")))
                    extracted_claim_objects.append(c)
        except Exception as e:  # noqa: BLE001
            extracted_text = f"OCR unavailable: {str(e)[:120]}"
            extracted_claims = []
            extracted_claim_objects = []

    # Step 3b — verify and snapshot primary sources from claim objects
    verified_claim_objects: list[dict[str, Any]] = []
    for claim_obj in extracted_claim_objects:
        if not isinstance(claim_obj, dict):
            verified_claim_objects.append(claim_obj)
            continue
        verified_sources: list[Any] = []
        for ps in claim_obj.get("primary_sources", [])[:3]:
            if not isinstance(ps, dict):
                verified_sources.append(ps)
                continue
            url = ps.get("url", "")
            if url and str(url).startswith("http"):
                snapshot = await _verify_and_snapshot_source(str(url))
                snapshot["suggestedBy"] = "claude"
                verified_sources.append({**ps, "verification": snapshot})
            else:
                verified_sources.append(ps)
        verified_claim_objects.append({**claim_obj, "primary_sources": verified_sources})
    extracted_claim_objects = verified_claim_objects

    # Step 3c — Gap 3: route claims to public-record adapters (never blocks receipt)
    for claim_obj in extracted_claim_objects:
        if not isinstance(claim_obj, dict):
            continue
        specs = route_claim(claim_obj)
        results: list[dict[str, Any]] = []
        for spec in specs:
            adapter = str(spec.get("adapter") or "")
            try:
                data = await asyncio.to_thread(
                    dispatch_adapter,
                    adapter,
                    spec.get("params") or {},
                )
                results.append({"adapter": adapter, "data": data, "error": None})
            except Exception as e:  # noqa: BLE001
                results.append({"adapter": adapter, "data": None, "error": str(e)[:500]})
        claim_obj["adapterResults"] = results

    # Step 4 — check perceptual hash ledger for prior appearances
    ledger_match: dict[str, Any] | None = None
    if perceptual_hash:
        existing = await _check_phash_ledger(perceptual_hash)
        if existing:
            ledger_match = existing
        else:
            await _add_to_phash_ledger(perceptual_hash, file_hash, filename, timestamp)

    # Step 5 — Hive AI detection (if key configured)
    detection_result: dict[str, Any] | None = None
    hive_key = os.environ.get("HIVE_API_KEY", "")
    if hive_key:
        try:
            b64 = base64.b64encode(contents).decode()
            payload = json.dumps({"image": {"data": b64}}).encode()
            req = urllib.request.Request(
                "https://api.thehive.ai/api/v2/task/sync",
                data=payload,
                headers={
                    "Authorization": f"Token {hive_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                hive_data = json.loads(resp.read())
                classes = hive_data.get("status", [{}])[0].get("response", {}).get("output", [{}])[0].get("classes", [])
                ai_score = next(
                    (c.get("score", 0) for c in classes if c.get("class") == "ai_generated"),
                    None,
                )
                detection_result = {
                    "detector": "hive",
                    "ai_generated_score": ai_score,
                    "classes": classes[:5],
                }
        except Exception as e:  # noqa: BLE001
            detection_result = {"detector": "hive", "error": str(e)[:120]}
    else:
        detection_result = {
            "detector": "none",
            "note": "No HIVE_API_KEY configured — set it in Render environment to enable AI detection",
        }

    return {
        "fileHash": file_hash,
        "perceptualHash": perceptual_hash,
        "perceptualHashType": perceptual_hash_type,
        "fileName": filename,
        "fileSize": file_size,
        "contentType": content_type,
        "timestamp": timestamp,
        "extractedText": extracted_text,
        "extractedClaims": extracted_claims,
        "extractedClaimObjects": extracted_claim_objects,
        "detection": detection_result,
        "ledgerMatch": ledger_match,
        "note": "Submit to /v1/sign-media-analysis or POST /v1/analyze-and-verify for a signed Frame receipt",
    }


def _format_podcast_ts(seconds: float) -> str:
    s = int(max(0.0, float(seconds)))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


async def _build_podcast_analysis_response(
    *,
    url: str | None,
    upload_bytes: bytes | None,
    upload_filename: str | None,
) -> dict[str, Any]:
    """
    Download or save audio, trim to PODCAST_MAX_SECONDS, Whisper transcribe, Claude claims,
    verify sources + adapter routing — same shape as analyze-media (+ transcript, podcast fields).
    """
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    claim_extract_error: str | None = None

    if url and url.strip():
        try:
            dl = await asyncio.to_thread(download_audio, url.strip())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Download failed: {exc}") from exc
        audio_path = dl["path"]
        title = str(dl.get("title") or "podcast")[:500]
        source_url = str(dl.get("source_url") or url)
    elif upload_bytes is not None:
        dl = save_uploaded_audio(upload_bytes, upload_filename or "upload.mp3")
        audio_path = dl["path"]
        title = str(dl.get("title") or "upload")[:500]
        source_url = "upload://local"
    else:
        raise HTTPException(status_code=400, detail="Provide JSON {\"url\": \"...\"} or multipart file field \"file\".")

    trimmed_path, was_trimmed = trim_audio_max(audio_path, PODCAST_MAX_SECONDS)
    file_size = Path(trimmed_path).stat().st_size

    fp = await asyncio.to_thread(acoustic_fingerprint, trimmed_path)
    transcript = await asyncio.to_thread(transcribe_audio, trimmed_path)

    try:
        raw_claims = await asyncio.to_thread(extract_speaker_claims, transcript, title)
    except Exception as exc:  # noqa: BLE001
        raw_claims = []
        claim_extract_error = str(exc)[:300]

    extracted_claim_objects: list[dict[str, Any]] = [dict(c) for c in raw_claims]
    extracted_claims = [str(c.get("text") or "") for c in extracted_claim_objects if c.get("text")]

    # Verify primary sources (same as analyze-media)
    verified_claim_objects: list[dict[str, Any]] = []
    for claim_obj in extracted_claim_objects:
        if not isinstance(claim_obj, dict):
            verified_claim_objects.append(claim_obj)
            continue
        verified_sources: list[Any] = []
        for ps in claim_obj.get("primary_sources", [])[:3]:
            if not isinstance(ps, dict):
                verified_sources.append(ps)
                continue
            purl = ps.get("url", "")
            if purl and str(purl).startswith("http"):
                snapshot = await _verify_and_snapshot_source(str(purl))
                snapshot["suggestedBy"] = "claude"
                verified_sources.append({**ps, "verification": snapshot})
            else:
                verified_sources.append(ps)
        verified_claim_objects.append({**claim_obj, "primary_sources": verified_sources})
    extracted_claim_objects = verified_claim_objects

    # Route to public-record adapters
    for claim_obj in extracted_claim_objects:
        if not isinstance(claim_obj, dict):
            continue
        specs = route_claim(claim_obj)
        results: list[dict[str, Any]] = []
        for spec in specs:
            adapter = str(spec.get("adapter") or "")
            try:
                data = await asyncio.to_thread(
                    dispatch_adapter,
                    adapter,
                    spec.get("params") or {},
                )
                results.append({"adapter": adapter, "data": data, "error": None})
            except Exception as e:  # noqa: BLE001
                results.append({"adapter": adapter, "data": None, "error": str(e)[:500]})
        claim_obj["adapterResults"] = results

    note_parts = [
        "v1: First "
        + str(PODCAST_MAX_SECONDS // 60)
        + " minutes only — longer audio is truncated. Spotify app links unsupported; use RSS or YouTube.",
    ]
    if was_trimmed:
        note_parts.append("This file was trimmed to the cap.")
    if claim_extract_error:
        note_parts.append(f"Claim extraction issue: {claim_extract_error}")
    note = " ".join(note_parts)

    return {
        "fileHash": fp,
        "perceptualHash": None,
        "perceptualHashType": None,
        "fileName": title[:240],
        "fileSize": file_size,
        "contentType": "audio/mpeg",
        "timestamp": timestamp,
        "extractedText": transcript.get("full_text"),
        "extractedClaims": extracted_claims,
        "extractedClaimObjects": extracted_claim_objects,
        "detection": {
            "detector": "whisper",
            "note": "Local openai-whisper (base). First run downloads ~140MB model weights; cold start can be slow on free tier.",
            "model": os.environ.get("FRAME_WHISPER_MODEL", "base"),
        },
        "ledgerMatch": None,
        "sourceType": "podcast",
        "sourceUrl": source_url,
        "podcastTitle": title,
        "transcript": transcript,
        "note": note,
    }


@app.post("/v1/analyze-media")
async def analyze_media(file: UploadFile = File(...)) -> dict[str, Any]:
    contents = await file.read()
    return await _build_analyze_media_response(
        contents,
        file.filename or "unknown",
        file.content_type or "unknown",
    )


class MediaAnalysisRequest(BaseModel):
    fileHash: str
    perceptualHash: str | None = None
    perceptualHashType: str | None = None
    fileName: str
    fileSize: int
    contentType: str
    detection: dict[str, Any]
    timestamp: str
    extractedText: str | None = None
    extractedClaims: list[str] = Field(default_factory=list)
    extractedClaimObjects: list[dict[str, Any]] = Field(default_factory=list)
    ledgerMatch: dict[str, Any] | None = None
    claimText: str | None = None
    # Podcast / video (sign-media-analysis.ts + entity ledger)
    sourceType: str | None = None
    sourceUrl: str | None = None
    podcastTitle: str | None = None
    transcript: dict[str, Any] | None = None


def _index_entity_receipts(signed_payload: dict[str, Any], req: MediaAnalysisRequest) -> None:
    """Append rows to entity_receipts for each (claim, entity). Never raises."""
    rid = signed_payload.get("receiptId")
    if not rid:
        return
    receipt_url = signed_payload.get("receiptUrl")
    signed_at = str(signed_payload.get("createdAt") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    claims = req.extractedClaimObjects or []
    if not claims:
        return
    rows: list[tuple[Any, ...]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        claim_text = str(claim.get("text") or "").strip() or "(no text)"
        ts = claim.get("timestamp_start")
        if ts is not None:
            try:
                claim_text = f"{claim_text} [at {_format_podcast_ts(float(ts))}]"
            except (TypeError, ValueError):
                pass
        claim_type = str(claim.get("type") or "general").strip() or "general"
        entities = claim.get("entities") or []
        ars = claim.get("adapterResults") or []
        adapters: set[str] = set()
        for ar in ars:
            if isinstance(ar, dict) and ar.get("adapter"):
                adapters.add(str(ar["adapter"]).strip())
        adapter_names = ",".join(sorted(adapters)) if adapters else None
        if not entities:
            continue
        for ent in entities:
            entity_name = str(ent).strip()
            if not entity_name:
                continue
            en = _normalize_entity_name(entity_name)
            if not en:
                continue
            rows.append(
                (
                    entity_name,
                    en,
                    claim_type,
                    claim_text,
                    str(rid),
                    receipt_url,
                    signed_at,
                    adapter_names,
                )
            )
    if not rows:
        return
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            conn.executemany(
                """
                INSERT INTO entity_receipts (
                    entity_name, entity_normalized, claim_type, claim_text,
                    receipt_id, receipt_url, signed_at, adapter_names
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()


def _finalize_media_sign(req: MediaAnalysisRequest, signed_core: dict[str, Any]) -> dict[str, Any]:
    out = _with_receipt_url(signed_core)
    try:
        _index_entity_receipts(out, req)
    except Exception:  # noqa: BLE001
        pass
    return out


def _sign_media_analysis_core(req: MediaAnalysisRequest) -> dict[str, Any]:
    root = _repo_root()
    script = root / "scripts" / "sign-media-analysis.ts"
    if not script.is_file():
        raise HTTPException(status_code=500, detail="sign-media-analysis script missing")

    proc = subprocess.run(
        ["npx", "tsx", str(script)],
        input=req.model_dump_json(),
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
        env={**os.environ},
        timeout=600,
    )

    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={"message": "sign-media-analysis failed", "stderr": proc.stderr[-2000:]},
        )

    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {exc}") from exc


@app.post("/v1/sign-media-analysis")
def sign_media_analysis(req: MediaAnalysisRequest) -> dict[str, Any]:
    return _finalize_media_sign(req, _sign_media_analysis_core(req))


@app.post("/v1/analyze-and-verify")
async def analyze_and_verify(file: UploadFile = File(...)) -> dict[str, Any]:
    """One-shot: analyze media → route claims → adapter calls → signed receipt + receiptUrl."""
    contents = await file.read()
    body = await _build_analyze_media_response(
        contents,
        file.filename or "unknown",
        file.content_type or "unknown",
    )
    allowed = set(MediaAnalysisRequest.model_fields.keys())
    payload = {k: v for k, v in body.items() if k in allowed}
    try:
        req = MediaAnalysisRequest.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Invalid analysis payload: {exc}") from exc
    signed_core = _sign_media_analysis_core(req)
    out = _finalize_media_sign(req, signed_core)
    # Echo OCR claim objects for demo UI (not part of signed receipt; verify ignores extra keys)
    return {**out, "extractedClaimObjects": body.get("extractedClaimObjects", [])}


@app.post("/v1/analyze-podcast")
async def analyze_podcast(request: Request) -> dict[str, Any]:
    """Transcribe + extract claims from YouTube, podcast RSS, or uploaded audio (30 min cap)."""
    ct = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in ct:
        form = await request.form()
        f = form.get("file")
        if f is None or not hasattr(f, "read"):
            raise HTTPException(status_code=400, detail='Expected multipart field "file"')
        data = await f.read()
        name = getattr(f, "filename", None) or "upload.mp3"
        return await _build_podcast_analysis_response(url=None, upload_bytes=data, upload_filename=name)
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Expected JSON body {\"url\": \"...\"}") from exc
    url = (body or {}).get("url")
    if not url or not isinstance(url, str):
        raise HTTPException(status_code=400, detail='JSON body must include {"url": "https://..."}')
    return await _build_podcast_analysis_response(url=url.strip(), upload_bytes=None, upload_filename=None)


@app.post("/v1/analyze-and-verify-podcast")
async def analyze_and_verify_podcast(request: Request) -> dict[str, Any]:
    """Podcast pipeline → sign receipt → receiptUrl → entity index."""
    ct = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in ct:
        form = await request.form()
        f = form.get("file")
        if f is None or not hasattr(f, "read"):
            raise HTTPException(status_code=400, detail='Expected multipart field "file"')
        data = await f.read()
        name = getattr(f, "filename", None) or "upload.mp3"
        body = await _build_podcast_analysis_response(url=None, upload_bytes=data, upload_filename=name)
    else:
        try:
            jb = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Expected JSON body {\"url\": \"...\"}") from exc
        url = (jb or {}).get("url")
        if not url or not isinstance(url, str):
            raise HTTPException(status_code=400, detail='JSON body must include {"url": "https://..."}')
        body = await _build_podcast_analysis_response(url=url.strip(), upload_bytes=None, upload_filename=None)

    allowed = set(MediaAnalysisRequest.model_fields.keys())
    payload = {k: v for k, v in body.items() if k in allowed}
    try:
        req = MediaAnalysisRequest.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Invalid analysis payload: {exc}") from exc
    signed_core = _sign_media_analysis_core(req)
    out = _finalize_media_sign(req, signed_core)
    return {
        **out,
        "extractedClaimObjects": body.get("extractedClaimObjects", []),
        "transcript": body.get("transcript"),
        "sourceUrl": body.get("sourceUrl"),
        "podcastTitle": body.get("podcastTitle"),
        "note": body.get("note"),
    }


@app.post("/v1/jcs-sha256")
def jcs_sha256_demo(body: dict[str, Any]) -> dict[str, str]:
    """Debug: SHA-256 hex of JCS-canonical form (matches TypeScript helpers)."""
    try:
        h = sha256_hex_jcs(body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"sha256Hex": h}


@app.post("/v1/verify-receipt")
def verify_receipt(receipt: SignedReceipt) -> dict[str, Any]:
    # Omit unset optional fields so JCS matches TypeScript payloads.
    data = receipt.model_dump(mode="json", exclude_none=True, exclude_unset=True)
    reasons: list[str] = []

    expected_hash = sha256_hex_jcs(receipt_body_for_content_hash(data))
    if expected_hash != data.get("contentHash"):
        reasons.append("contentHash does not match JCS payload")

    signing_body = receipt_body_for_signing(data)
    try:
        canon_signing = jcs_canonicalize(signing_body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    digest = hashlib.sha256(canon_signing.encode("utf-8")).digest()

    try:
        der = base64.b64decode(data["publicKey"], validate=True)
        pub = serialization.load_der_public_key(der)
        if not isinstance(pub, Ed25519PublicKey):
            reasons.append("publicKey is not Ed25519")
        else:
            try:
                sig = base64.b64decode(data["signature"], validate=True)
                pub.verify(sig, digest)
            except Exception:  # noqa: BLE001
                reasons.append("signature verification failed")
    except Exception:  # noqa: BLE001
        reasons.append("publicKey or signature is not valid base64/DER")

    return {"ok": len(reasons) == 0, "reasons": reasons}
