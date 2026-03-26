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
from dotenv import load_dotenv

load_dotenv()
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from enum import Enum
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from datetime import datetime, timezone

import httpx

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from adapters_media import dispatch_adapter
from adapters_podcast import (
    PODCAST_MAX_SECONDS,
    acoustic_fingerprint,
    assemble_podcast_payload,
    download_audio,
    extract_speaker_claims,
    generate_layer_zero,
    probe_audio_duration_seconds,
    save_uploaded_audio,
    transcribe_audio,
    trim_audio_max,
)
from adapters.article_fetcher import ArticleFetcher
from adapters.citation_tracer import CitationChain, enrich_claims_with_citation_traces
from adapters.meta_ad_library import AD_LIBRARY_ADAPTER_VERSION, query_ad_library
from implication_notes import IMPLICATION_NOTES
from adapters.contradiction import ContradictionAnalyzer, _get_source_url as _receipt_source_url
from job_store import (
    Job,
    JobStatus,
    append_stream_claim,
    append_stream_entity,
    create_job,
    find_receipt_by_receipt_id,
    get_job,
    iter_jobs,
    mark_complete,
    mark_failed,
    mark_processing,
    update_job,
)
from core.chunked_pipeline import get_chunk_strategy, process_chunked_audio
from models.tiers import ProcessingTier, get_tier_config, resolve_tier
from router import route_claim
from depth_map import get_depth_map_payload
from schema_monitor import BASELINES_DIR, SCHEMA_MONITOR_VERSION, capture_baseline, load_baseline
from actor_ledger_api import (
    actor_ledger_append_event,
    actor_ledger_get_actor,
    actor_ledger_get_events,
    validate_actor_slug,
)
from pattern_api import get_pattern_lib_payload, run_pattern_match
from spread_api import run_spread
from origin_api import run_origin
from actor_layer_api import run_actor_layer
from deep_receipt_api import build_deep_receipt
from report_api import build_extended_report_async
from surface_adapter import SLENDERMAN_SURFACE_BASELINE, run_surface_layer
from dispute_api import pattern_ids_in_library, run_dispute_append, run_dispute_get
from verify_record import verify_generic_record

# Repo root: two levels up from apps/api/main.py. Prefer FRAME_REPO_ROOT on Render so
# Node subprocesses (npx tsx scripts/…) resolve scripts/ and node_modules/ regardless of uvicorn cwd.
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
        env={**os.environ},
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
    citation_chain: CitationChain | None = None
    origin_stamp: str | None = None

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


class SurfacePostBody(BaseModel):
    """Layer 1 surface extraction — exactly one of `narrative` or `url`."""

    model_config = ConfigDict(extra="forbid")

    narrative: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> SurfacePostBody:
        has_n = bool(self.narrative and self.narrative.strip())
        has_u = bool(self.url and self.url.strip())
        if has_n == has_u:
            raise ValueError("Provide exactly one of narrative or url")
        return self


class PatternMatchBody(BaseModel):
    """Layer 5 pattern heuristic — narrative text only."""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(..., min_length=1)


class SpreadPostBody(BaseModel):
    """Layer 2 spread heuristic — narrative text only."""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(..., min_length=1)


class OriginPostBody(BaseModel):
    """Layer 3 origin heuristic — narrative text only."""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(..., min_length=1)


class ActorLayerPostBody(BaseModel):
    """Layer 4 actor ledger — narrative text only."""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(..., min_length=1)


class ReportPostBody(BaseModel):
    """Assemble five-ring extended report from narrative (unsigned)."""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(..., min_length=1)


class ActorEventBody(BaseModel):
    """Append-only actor ledger event."""

    model_config = ConfigDict(extra="forbid")

    date: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    confidence_tier: str = Field(..., min_length=1)


class DisputePostBody(BaseModel):
    """Challenge to a pattern match flag (credibility gate)."""

    model_config = ConfigDict(extra="forbid")

    pattern_id: str = Field(..., min_length=1)
    counter_evidence: str = Field(..., min_length=1)
    submitter_note: str | None = None


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


class DeepReceiptBody(BaseModel):
    query: str = Field(..., min_length=1, max_length=20000)


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


class SecEdgarRequest(BaseModel):
    """Exactly one of `name` (EFTS search) or `cik` (zero-padded or numeric)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    cik: str | None = None

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> SecEdgarRequest:
        has_n = bool(self.name and self.name.strip())
        has_c = bool(self.cik and self.cik.strip())
        if has_n == has_c:
            raise ValueError("Provide exactly one of name or cik")
        return self


class SecReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)


class ScholarlyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)


class CourtListenerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)
    include_text: bool = False


class AdLibraryRequest(BaseModel):
    name: str = Field(..., min_length=1)
    country: str = "US"
    limit: int = Field(default=25, ge=1, le=100)


class JobRequest(BaseModel):
    """Async job request — one of `source_url` or `receipt_type` should be set."""

    model_config = ConfigDict(extra="allow")

    source_url: str | None = None
    receipt_type: str | None = None
    name: str | None = None
    candidate_id: str | None = None
    ein: str | None = None
    lobbying_clients: list[str] | None = None
    years: list[int] | None = None
    wikidata_id: str | None = None
    country: str | None = None
    limit: int | None = None


class PodcastInvestigateRequest(BaseModel):
    source_url: str | None = None
    subject_context: str | None = "public figure"


class ContradictionAnalysisRequest(BaseModel):
    receipt_a_id: str = Field(..., min_length=1)
    receipt_b_id: str = Field(..., min_length=1)
    entity_name: str = Field(..., min_length=1)


app = FastAPI(title="Frame API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.dossier_route import router as dossier_http_router  # noqa: E402
from api.frames import router as frames_http_router  # noqa: E402

app.include_router(frames_http_router)
app.include_router(dossier_http_router)

_web_dir = _repo_root() / "apps" / "web"
if _web_dir.is_dir():
    app.mount("/web", StaticFiles(directory=str(_web_dir), html=True), name="web")


async def _run_schema_baseline_capture() -> None:
    """
    Background: schema baselines for all active adapters (live API calls).
    Does not block app startup / Render health checks.
    """
    root = _repo_root()
    print(f"[startup] REPO_ROOT: {root}")
    print(f"[startup] scripts/ exists: {(root / 'scripts').is_dir()}")
    print(f"[startup] node_modules/ exists: {(root / 'node_modules').is_dir()}")

    print("[schema_monitor] Starting baseline capture...")

    tasks = [
        _capture_fec_baseline(),
        _capture_lda_baseline(),
        _capture_990_baseline(),
        _capture_wikidata_baseline(),
        _capture_meta_ad_library_baseline(),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    source_ids = ["fec", "lda", "propublica_990", "wikidata", "meta_ad_library"]
    for source_id, result in zip(source_ids, results):
        if isinstance(result, Exception):
            print(f"[schema_monitor] {source_id}: capture failed — {str(result)[:100]}")
        else:
            status = "CHANGED" if (isinstance(result, dict) and result.get("schema_changed")) else "ok"
            h = (result.get("full_schema_hash", "") if isinstance(result, dict) else "")[:16]
            print(f"[schema_monitor] {source_id}: {status} — hash {h}...")

    print("[schema_monitor] Baseline capture complete.")


@app.on_event("startup")
async def capture_schema_baselines() -> None:
    """
    On startup: schema baselines and signing smoke test run in the background
    so the app binds and answers /health immediately (Render health checks).

    First run: captures genesis baselines.
    Subsequent runs: verifies schema hasn't changed, updates last_verified_at.
    """
    asyncio.create_task(_run_schema_baseline_capture())
    asyncio.create_task(_verify_signing_pipeline())


async def _verify_signing_pipeline() -> None:
    """
    Smoke test the Node signing subprocess on startup.
    If this fails, receipt generation that uses sign-payload.ts will fail.
    """
    ts = datetime.now(timezone.utc).isoformat()
    test_payload: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "receiptId": "FRM-STARTUP-HEALTH",
        "createdAt": ts,
        "claims": [
            {
                "id": "claim-health",
                "statement": "Frame API startup signing health check.",
                "type": "observed",
                "implication_risk": "low",
            },
        ],
        "sources": [
            {
                "id": "src-health",
                "adapter": "manual",
                "url": "https://frame.invalid/health",
                "title": "Startup health",
                "retrievedAt": ts,
            },
        ],
        "narrative": [{"text": "Startup signing pipeline check.", "sourceId": "src-health"}],
        "unknowns": {"operational": [], "epistemic": []},
        "contentHash": "",
    }

    try:
        out = await asyncio.to_thread(_sign_frame_payload, test_payload)
        if out.get("signing_error"):
            print("[startup] Signing pipeline: FAILED")
            err = str(out.get("signing_error", ""))[:400]
            print(f"[startup] signing_error: {err}")
            return
        if out.get("signature"):
            print("[startup] Signing pipeline: OK")
        else:
            print("[startup] Signing pipeline: FAILED (no signature in output)")
    except Exception as exc:  # noqa: BLE001
        print("[startup] Signing pipeline: FAILED")
        print(f"[startup] exception: {str(exc)[:300]}")


async def _capture_fec_baseline() -> dict[str, Any]:
    """Capture FEC API schema baseline using a known stable candidate."""
    try:
        import httpx

        fec_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://api.open.fec.gov/v1/candidates/",
                params={
                    "api_key": fec_key,
                    "candidate_id": "S2TX00312",
                    "per_page": 1,
                },
            )
            response.raise_for_status()
            data = response.json()

        return capture_baseline(
            source_id="fec",
            sample_response=data,
            endpoint_description="FEC /v1/candidates/ — candidate lookup by ID",
        )
    except Exception as e:
        return capture_baseline(
            source_id="fec",
            sample_response={"error": "capture_failed", "note": str(e)[:200]},
            endpoint_description="FEC baseline capture failed at startup",
        )


async def _capture_lda_baseline() -> dict[str, Any]:
    """Capture Senate LDA API schema baseline."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://lda.senate.gov/api/v1/filings/",
                params={
                    "registrant_name": "Exxon",
                    "limit": 1,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

        return capture_baseline(
            source_id="lda",
            sample_response=data,
            endpoint_description="Senate LDA /api/v1/filings/ — registrant name search",
        )
    except Exception as e:
        return capture_baseline(
            source_id="lda",
            sample_response={"error": "capture_failed", "note": str(e)[:200]},
            endpoint_description="LDA baseline capture failed at startup",
        )


async def _capture_990_baseline() -> dict[str, Any]:
    """Capture ProPublica 990 API schema baseline."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://projects.propublica.org/nonprofits/api/v2/search.json",
                params={"q": "Gates Foundation", "page": 0},
            )
            response.raise_for_status()
            data = response.json()

        return capture_baseline(
            source_id="propublica_990",
            sample_response=data,
            endpoint_description="ProPublica 990 /api/v2/search.json — org name search",
        )
    except Exception as e:
        return capture_baseline(
            source_id="propublica_990",
            sample_response={"error": "capture_failed", "note": str(e)[:200]},
            endpoint_description="ProPublica 990 baseline capture failed at startup",
        )


async def _capture_wikidata_baseline() -> dict[str, Any]:
    """Capture Wikidata API schema baseline."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbsearchentities",
                    "search": "Ted Cruz",
                    "language": "en",
                    "format": "json",
                    "limit": 1,
                },
                headers={"User-Agent": "Frame/1.0 (https://getframe.dev)"},
            )
            response.raise_for_status()
            data = response.json()

        return capture_baseline(
            source_id="wikidata",
            sample_response=data,
            endpoint_description="Wikidata wbsearchentities — entity name search",
        )
    except Exception as e:
        return capture_baseline(
            source_id="wikidata",
            sample_response={"error": "capture_failed", "note": str(e)[:200]},
            endpoint_description="Wikidata baseline capture failed at startup",
        )


async def _capture_meta_ad_library_baseline() -> dict[str, Any]:
    """Capture Meta Ad Library response schema (adapter output shape)."""
    try:
        from adapters.meta_ad_library import query_ad_library

        data = await query_ad_library("Ted Cruz", country="US", limit=1)
        return capture_baseline(
            source_id="meta_ad_library",
            sample_response=data,
            endpoint_description="Meta Graph ads_archive — political/issue ads (adapter output)",
        )
    except Exception as e:
        return capture_baseline(
            source_id="meta_ad_library",
            sample_response={"error": "capture_failed", "note": str(e)[:200]},
            endpoint_description="Meta Ad Library baseline capture failed at startup",
        )


@app.get("/demo")
async def demo_redirect() -> FileResponse:
    return FileResponse(
        str(_repo_root() / "apps" / "web" / "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/pitch")
async def pitch_page() -> FileResponse:
    """Static pitch deck (React via CDN) — same cache policy as /demo."""
    return FileResponse(
        str(_repo_root() / "apps" / "web" / "pitch.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/")
async def root() -> dict[str, str]:
    """Base URL liveness (some checks hit `/` instead of `/health`)."""
    return {"status": "ok", "service": "frame-api", "health": "/health"}


@app.get("/health")
@app.get("/health/")
async def health() -> dict[str, Any]:
    """Liveness check — always responds immediately."""
    db_ok = False
    redis_ok = False
    try:
        from db import health_db

        db_ok = await asyncio.wait_for(health_db(), timeout=2.0)
    except Exception:
        db_ok = False
    try:
        from cache.redis import get_cache

        client = get_cache()
        if client is not None:
            await asyncio.wait_for(client.ping(), timeout=2.0)
            redis_ok = True
    except Exception:
        redis_ok = False
    return {
        "status": "ok",
        "service": "frame-api",
        "db": db_ok,
        "redis": redis_ok,
    }


@app.get("/v1/schema-baselines")
async def get_schema_baselines() -> dict[str, Any]:
    """
    Returns current schema baseline status for all monitored sources.
    Shows hash, capture date, field count, and whether a change was detected.
    Used for: PROOF.md generation, admin verification, and documentation.
    """
    sources = ["fec", "lda", "propublica_990", "wikidata", "meta_ad_library"]
    result: dict[str, Any] = {}

    for source_id in sources:
        baseline = load_baseline(source_id)
        if baseline:
            result[source_id] = {
                "status": "captured",
                "full_schema_hash": (baseline.get("full_schema_hash", "") or "")[:32] + "...",
                "critical_fields_hash": (baseline.get("critical_fields_hash", "") or "")[:16] + "...",
                "captured_at": baseline.get("captured_at"),
                "last_verified_at": baseline.get("last_verified_at"),
                "field_count": baseline.get("field_count"),
                "critical_field_count": baseline.get("critical_field_count"),
                "is_genesis": baseline.get("is_genesis", False),
                "schema_changed": baseline.get("schema_changed", False),
                "version_history_count": baseline.get("version_history_count", 0),
            }
        else:
            result[source_id] = {
                "status": "not_captured",
                "note": "No baseline exists. Will capture on next server startup.",
            }

    return {
        "baselines": result,
        "baselines_dir": BASELINES_DIR,
        "schema_monitor_version": SCHEMA_MONITOR_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/adapters")
def adapters() -> dict[str, list[str]]:
    return {
        "kinds": ["fec", "opensecrets", "propublica", "lobbying", "edgar", "manual", "congress", "wikidata"],
        "note": "Adapters normalize third-party data into Frame SourceRecord rows. Gap 3 routes OCR claims to fec/propublica/lobbying/congress/wikidata.",
    }


@app.get("/v1/depth-map")
def depth_map() -> dict[str, Any]:
    """
    Topographical depth map: six stacked jurisdictions, each with adapter wiring and
    current depth availability (explicit absences are labeled, not hidden).
    """
    return get_depth_map_payload()


# Literal /v1/surface/slenderman must stay before any future GET /v1/surface/{...} so
# Starlette does not bind "slenderman" as a path parameter.
@app.get("/v1/surface/slenderman")
def surface_slenderman_benchmark() -> dict[str, Any]:
    """
    Inoculation baseline: fully traced Layer 1 for Slender Man (2009, Eric Knudsen / Victor Surge, Something Awful).
    Does not invoke the adapter.
    """
    return SLENDERMAN_SURFACE_BASELINE


@app.post("/v1/surface")
async def surface_post(body: SurfacePostBody) -> dict[str, Any]:
    """
    Layer 1 (Surface): structured extraction from narrative text or URL via the TypeScript adapter (Anthropic).
    """
    if body.narrative and body.narrative.strip():
        payload = {"narrative": body.narrative.strip()}
    else:
        u = (body.url or "").strip()
        payload = {"url": u}
    try:
        return await asyncio.to_thread(run_surface_layer, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"surface adapter output: {exc}") from exc


@app.post("/v1/pattern-match")
async def pattern_match_post(body: PatternMatchBody) -> dict[str, Any]:
    """Layer 5: keyword/structural match against the pattern catalog (no AI, no external calls)."""
    try:
        return await asyncio.to_thread(run_pattern_match, body.narrative.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/spread")
async def spread_post(body: SpreadPostBody) -> dict[str, Any]:
    """Layer 2: diffusion / syndication heuristics from narrative (no external APIs)."""
    try:
        return await asyncio.to_thread(run_spread, body.narrative.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/origin")
async def origin_post(body: OriginPostBody) -> dict[str, Any]:
    """Layer 3: first-instance / provenance heuristics from narrative (no external APIs)."""
    try:
        return await asyncio.to_thread(run_origin, body.narrative.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/actor-layer")
async def actor_layer_post(body: ActorLayerPostBody) -> dict[str, Any]:
    """Layer 4: narrative mentions resolved against the actor ledger (Node + ledger.json)."""
    try:
        return await asyncio.to_thread(run_actor_layer, body.narrative.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/report")
async def report_post(body: ReportPostBody) -> dict[str, Any]:
    """
    Five-ring library report: surface, spread, origin, actor layer, pattern match (+ citations).
    When FRAME_PRIVATE_KEY / FRAME_PUBLIC_KEY are set, the body is JCS-hashed (narrative, rings,
    generated_at) and signed (Ed25519); otherwise `signed` is false with `signing_error`.
    Per-ring adapter failures are captured in-ring with absent_fields.
    """
    try:
        return await build_extended_report_async(body.narrative.strip())
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/v1/pattern-lib")
def pattern_lib_get() -> dict[str, Any]:
    """Full pattern library plus counts for unsigned (not yet sealed) records."""
    return get_pattern_lib_payload()


@app.post("/v1/dispute")
async def dispute_create(body: DisputePostBody) -> dict[str, Any]:
    """Append-only dispute against a catalogued pattern (must exist in signed library)."""
    pid = body.pattern_id.strip()
    try:
        ids = await asyncio.to_thread(pattern_ids_in_library)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if pid not in ids:
        raise HTTPException(
            status_code=404,
            detail={"absent": True, "reason": "Pattern not found in signed library"},
        )
    note = body.submitter_note
    submitter_note = (
        note.strip()
        if isinstance(note, str) and note.strip()
        else None
    )
    entry: dict[str, Any] = {
        "dispute_id": str(uuid.uuid4()),
        "pattern_id": pid,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "counter_evidence": body.counter_evidence.strip(),
        "submitter_note": submitter_note,
        "status": "RECEIVED",
        "resolution_note": None,
    }
    try:
        return await asyncio.to_thread(run_dispute_append, entry)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/dispute/{pattern_id}")
async def dispute_list_for_pattern(pattern_id: str) -> list[dict[str, Any]]:
    """Public transparency: all disputes filed against this pattern id."""
    pid = pattern_id.strip()
    if not pid:
        raise HTTPException(status_code=400, detail="pattern_id required")
    try:
        return await asyncio.to_thread(run_dispute_get, pid)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/actor/{slug}/events")
async def actor_events_list(slug: str) -> list[dict[str, Any]]:
    """Layer 4: sorted events for an actor (empty list if not in ledger)."""
    try:
        s = validate_actor_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return await asyncio.to_thread(actor_ledger_get_events, s)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/v1/actor/{slug}/events")
async def actor_events_append(slug: str, body: ActorEventBody) -> dict[str, Any]:
    """Layer 4: append one event (creates actor row if slug is new)."""
    try:
        s = validate_actor_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = body.model_dump()
    try:
        return await asyncio.to_thread(actor_ledger_append_event, s, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/v1/actor/{slug}")
async def actor_get(slug: str) -> dict[str, Any]:
    """Layer 4: full actor record or explicit absent response."""
    try:
        s = validate_actor_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        rec = await asyncio.to_thread(actor_ledger_get_actor, s)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail={"absent": True, "reason": "Actor not found in ledger"},
        )
    return rec


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

    Receipt prose (FINDINGS / CONTEXT / GAPS / SIGNIFICANCE) is generated in
    `packages/sources` with Claude Sonnet when `ANTHROPIC_API_KEY` is set; Rabbit Hole
    Layer 1 surface extraction remains on Haiku in `packages/adapters/src/surface.ts`.
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
        env={**os.environ},
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


@app.post("/v1/deep-receipt")
async def deep_receipt_post(body: DeepReceiptBody) -> dict[str, Any]:
    """
    Universal three-layer receipt: Layer A (verified), B (historical thread), C (pattern inference).
    Query type selects adapters; structure is always the same. Signed via JCS + Ed25519 when keys are set.
    """
    try:
        return await build_deep_receipt(body.query.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc)[:4000],
        ) from exc


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


@app.post("/v1/sec-edgar")
async def sec_edgar_post(body: SecEdgarRequest) -> dict[str, Any]:
    """SEC EDGAR probe: search by name or fetch by CIK — Form 4 + company facts (unsigned)."""
    from adapters.sec_edgar import sec_edgar_probe

    def _run() -> dict[str, Any]:
        return sec_edgar_probe(
            body.name.strip() if body.name else None,
            body.cik.strip() if body.cik else None,
        )

    try:
        return await asyncio.to_thread(_run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/v1/generate-sec-receipt")
async def generate_sec_receipt(req: SecReceiptRequest) -> dict[str, Any]:
    """Signed Frame receipt for top EDGAR match on `name` (submissions, Form 4 lines, XBRL facts)."""
    from adapters.sec_edgar import build_sec_receipt_payload

    payload = await asyncio.to_thread(build_sec_receipt_payload, req.name.strip())
    signed = await asyncio.to_thread(_sign_frame_payload, payload)
    if signed.get("signing_error"):
        return signed
    return _with_receipt_url(signed)


@app.post("/v1/scholarly")
async def scholarly_post(body: ScholarlyRequest) -> dict[str, Any]:
    """OpenAlex + Semantic Scholar + Crossref (concurrent); merged by DOI / citation."""
    from adapters.scholarly import scholarly_aggregate

    return await scholarly_aggregate(body.query.strip(), per_source_limit=5)


@app.post("/v1/courtlistener")
async def courtlistener_post(body: CourtListenerRequest) -> dict[str, Any]:
    """CourtListener: opinion search + docket search; optional full text for top opinion hit."""
    from adapters import courtlistener as cl

    q = body.query.strip()
    opinions, dockets = await asyncio.gather(
        cl.search_opinions(q, 5),
        cl.search_dockets(q, 5),
    )
    top_opinion_text: str | None = None
    if body.include_text and opinions:
        oid = opinions[0].get("opinion_id")
        if oid is not None:
            top_opinion_text = await cl.get_opinion_text(oid)
            if not (top_opinion_text or "").strip():
                top_opinion_text = None
    out: dict[str, Any] = {
        "query": q,
        "opinions": opinions,
        "dockets": dockets,
        "source_type": "judicial_opinion",
        "confidence_tier": "primary_legal",
        "sourcing_completeness": cl.sourcing_completeness_status(),
    }
    if top_opinion_text:
        out["top_opinion_text"] = top_opinion_text
    return out


def generate_receipt_id() -> str:
    """Short unique suffix for receipt IDs."""
    return uuid.uuid4().hex[:8].upper()


def build_claim_py(
    claim_id: str,
    statement: str,
    claim_type: str,
    risk: str,
    asserted_at: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Build a claim dict for Frame payloads. implication_note required for high risk."""
    if risk == "high" and not note:
        raise ValueError(f"implication_note required for high-risk claim: {statement[:80]}")
    claim: dict[str, Any] = {
        "id": claim_id,
        "statement": statement,
        "type": claim_type,
        "implication_risk": risk,
    }
    if asserted_at:
        claim["assertedAt"] = asserted_at
    if note:
        claim["implication_note"] = note
    return claim


def _build_ad_library_narrative_sentences(
    name: str,
    country: str,
    result: dict[str, Any],
    source_id: str,
) -> list[dict[str, Any]]:
    if result["status"] == "no_results":
        return [
            {
                "text": (
                    f"Frame queried the Meta Ad Library for political and issue advertisements "
                    f"associated with '{name}' in {result.get('country', country)}. "
                    f"No results were returned. This means no political or issue ads matching "
                    f"this name were found in Meta's disclosure database at the time of query. "
                    f"This does not mean the account is not running paid content — Meta only "
                    f"discloses political and issue ads, not commercial or boosted content."
                ),
                "sourceId": source_id,
            },
        ]
    if result["status"] == "results_found":
        entities = result.get("unique_funding_entities", [])
        entity_str = (
            f"Funding entities on record: {', '.join(entities)}."
            if entities
            else "No funding entity was disclosed."
        )
        active = result.get("active_ads_count", 0)
        total = result.get("total_ads_returned", 0)
        return [
            {
                "text": (
                    f"Frame queried the Meta Ad Library for political and issue advertisements "
                    f"associated with '{name}' in {result.get('country', country)}. "
                    f"The query returned {total} ad(s), of which {active} are currently active. "
                    f"{entity_str} "
                    f"Spend figures are estimated ranges as disclosed by Meta — exact amounts "
                    f"are not available through public disclosure. "
                    f"This receipt documents what Meta's Ad Library shows. It does not establish "
                    f"the purpose, effectiveness, or authorship of the content."
                ),
                "sourceId": source_id,
            },
        ]
    return [
        {
            "text": (
                f"Frame attempted to query the Meta Ad Library for '{name}' but the query "
                f"did not complete. See unknowns for details."
            ),
            "sourceId": source_id,
        },
    ]


def _build_ad_library_payload(
    name: str,
    country: str,
    limit: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    source_id = "src-meta-ad-library"
    claims: list[dict[str, Any]] = []
    operational_unknowns: list[dict[str, Any]] = []
    epistemic_unknowns: list[dict[str, Any]] = [
        {
            "text": (
                "Meta only discloses political and issue ads. Regular commercial or boosted content "
                "is not in the Ad Library. An account with no results here may still be running paid content."
            ),
            "resolution_possible": False,
        },
        {
            "text": "Spend figures are estimated ranges provided by Meta, not exact amounts.",
            "resolution_possible": False,
        },
        {
            "text": IMPLICATION_NOTES["paid_advertising"],
            "resolution_possible": False,
        },
    ]

    if result["status"] == "no_results":
        claims.append(
            build_claim_py(
                "claim-1",
                f"No political or issue ads were found in the Meta Ad Library for '{name}' in {country}.",
                "observed",
                "low",
                asserted_at=timestamp,
            ),
        )
        operational_unknowns.append(
            {
                "text": (
                    "Absence of results reflects only political and issue ads. "
                    "Commercial ad spend is not disclosed."
                ),
                "resolution_possible": False,
            },
        )

    elif result["status"] == "results_found":
        idx = 1
        claims.append(
            build_claim_py(
                f"claim-{idx}",
                (
                    f"The Meta Ad Library returned {result['total_ads_returned']} political or issue ad(s) "
                    f"matching '{name}' in {result['country']}."
                ),
                "observed",
                "high",
                asserted_at=timestamp,
                note=IMPLICATION_NOTES["paid_advertising"],
            ),
        )
        idx += 1
        if result.get("active_ads_count", 0) > 0:
            claims.append(
                build_claim_py(
                    f"claim-{idx}",
                    f"{result['active_ads_count']} ad(s) are currently active.",
                    "observed",
                    "medium",
                    asserted_at=timestamp,
                ),
            )
            idx += 1
        for entity in result.get("unique_funding_entities", []):
            claims.append(
                build_claim_py(
                    f"claim-{idx}",
                    f"Funding entity on record: {entity}",
                    "observed",
                    "high",
                    asserted_at=timestamp,
                    note=IMPLICATION_NOTES["paid_advertising"],
                ),
            )
            idx += 1

    elif result["status"] in ("unavailable", "api_error", "fetch_error"):
        operational_unknowns.append(
            {
                "text": result.get("note", result.get("error", "Meta Ad Library query did not complete.")),
                "resolution_possible": bool(result.get("resolution_possible", True)),
            },
        )
        claims.append(
            build_claim_py(
                "claim-1",
                "Meta Ad Library query did not complete successfully for this search.",
                "observed",
                "low",
                asserted_at=timestamp,
            ),
        )

    q = urllib.parse.quote(name)
    cc = urllib.parse.quote(country)
    library_url = (
        f"https://www.facebook.com/ads/library/?active_status=all&ad_type=political_and_issue_ads"
        f"&country={cc}&q={q}"
    )
    sources: list[dict[str, Any]] = [
        {
            "id": source_id,
            "adapter": "manual",
            "url": library_url,
            "title": "Meta Ad Library (political and issue ads)",
            "retrievedAt": timestamp,
            "externalRef": f"{name[:24]}:{country}",
            "metadata": {
                "ad_library": result,
                "adapter": AD_LIBRARY_ADAPTER_VERSION,
                "search_term": name,
                "country": country,
                "limit": limit,
            },
        },
    ]

    narrative = _build_ad_library_narrative_sentences(name, country, result, source_id)

    rid = f"FRM-ADL-{generate_receipt_id()}"
    return {
        "schemaVersion": "1.0.0",
        "receiptId": rid,
        "createdAt": timestamp,
        "claims": claims,
        "sources": sources,
        "narrative": narrative,
        "unknowns": {
            "operational": operational_unknowns,
            "epistemic": epistemic_unknowns,
        },
        "contentHash": "",
    }


def _sign_frame_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Sign a Frame-shaped payload via scripts/sign-payload.ts (stdin → stdout JSON)."""
    root = _repo_root()
    payload_str = json.dumps(payload, ensure_ascii=False)
    sign_result = subprocess.run(
        ["npx", "tsx", str(root / "scripts" / "sign-payload.ts")],
        input=payload_str,
        capture_output=True,
        text=True,
        cwd=str(root),
        env={**os.environ},
        timeout=120,
    )
    if sign_result.returncode == 0:
        try:
            return json.loads(sign_result.stdout.strip())
        except json.JSONDecodeError:
            err = (sign_result.stderr or sign_result.stdout or "")[:500]
            return {**payload, "signing_error": err}
    err = (sign_result.stderr or sign_result.stdout or "")[:500]
    return {**payload, "signing_error": err}


async def _generate_ad_library_receipt_internal(
    name: str,
    country: str,
    limit: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    payload = _build_ad_library_payload(name, country, limit, result)
    signed = await asyncio.to_thread(_sign_frame_payload, payload)
    if signed.get("signing_error"):
        return signed
    return _with_receipt_url(signed)


@app.post("/v1/generate-ad-library-receipt")
async def generate_ad_library_receipt(request: AdLibraryRequest) -> dict[str, Any]:
    """
    Query Meta Ad Library for political and issue ads associated with a name.
    Returns a signed Frame receipt documenting what was found — including
    explicit documentation of what was NOT found and why.
    """
    result = await query_ad_library(
        search_term=request.name.strip(),
        country=request.country,
        limit=request.limit,
    )
    return await _generate_ad_library_receipt_internal(
        request.name.strip(),
        request.country,
        request.limit,
        result,
    )


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
    if request.receipt_type == "ad_library":
        return f"Meta Ad Library: {request.name or 'unknown'}"
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


async def _generate_ad_library_receipt_for_job(request: JobRequest) -> dict[str, Any]:
    n = (request.name or "").strip()
    if not n:
        raise ValueError("ad_library job requires name")
    country = (request.country or "US").strip() or "US"
    lim = int(request.limit) if request.limit is not None else 25
    lim = max(1, min(100, lim))
    result = await query_ad_library(
        search_term=n,
        country=country,
        limit=lim,
    )
    return await _generate_ad_library_receipt_internal(n, country, lim, result)


async def _handle_source_url_job(job: Job, request: JobRequest, start_ms: float) -> None:
    """Fetch URL via FetchAdapter, build Frame receipt, sign with scripts/sign-payload.ts."""
    from adapters.fetch_adapter import AdapterUnavailableError, FetchError
    from adapters.router import get_adapter_for_url

    temp_dir_from_ytdlp: str | None = None
    spill_path: str | None = None

    try:
        try:
            adapter = get_adapter_for_url(request.source_url or "")
            fetch_result = await adapter.fetch(request.source_url or "")
        except AdapterUnavailableError as e:
            mark_complete(
                job,
                {
                    "status": "partial",
                    "source_url": request.source_url,
                    "note": str(e),
                    "unknowns": {
                        "operational": [{"text": str(e), "resolution_possible": True}],
                        "epistemic": [],
                    },
                },
                start_ms,
            )
            return
        except FetchError as e:
            mark_failed(job, error=str(e))
            return

        if fetch_result.metadata.get("temp_fetch_dir"):
            temp_dir_from_ytdlp = str(fetch_result.metadata["temp_fetch_dir"])

        coc = fetch_result.chain_of_custody
        temp_path = fetch_result.temp_file_path
        if not temp_path:
            tmp = tempfile.NamedTemporaryFile(
                delete=False,
                suffix=f".{fetch_result.file_extension}",
            )
            tmp.write(fetch_result.file_bytes)
            tmp.close()
            temp_path = tmp.name
            spill_path = temp_path

        rid = str(uuid.uuid4())
        source_id = "src-fetch-media"

        hive_task = asyncio.create_task(
            _run_hive_detection(fetch_result.file_bytes, fetch_result.content_type),
        )
        ocr_task = asyncio.create_task(
            _run_ocr(fetch_result.file_bytes, fetch_result.content_type),
        )
        try:
            hive_result, ocr_result = await asyncio.wait_for(
                asyncio.gather(hive_task, ocr_task),
                timeout=25.0,
            )
        except asyncio.TimeoutError:
            hive_result = {
                "detector": "none",
                "note": "Hive detection timed out after 25 seconds.",
                "resolution_possible": True,
            }
            ocr_result = {
                "status": "timeout",
                "note": "OCR timed out after 25 seconds.",
                "resolution_possible": True,
            }

        hive_meta = dict(hive_result)
        if hive_meta.get("ai_generated_probability") is not None:
            hive_meta["ai_generated_score"] = hive_meta["ai_generated_probability"]

        operational_unknowns: list[dict[str, Any]] = []
        epistemic_unknowns: list[dict[str, Any]] = [
            {
                "text": (
                    "A cryptographic hash proves file identity at observation time; it does not "
                    "establish the truth or falsity of any claims within the file."
                ),
                "resolution_possible": False,
            },
        ]

        if hive_result.get("detector") == "none" or hive_result.get("error"):
            operational_unknowns.append(
                {
                    "text": hive_result.get("note", "AI detection not available."),
                    "resolution_possible": True,
                },
            )

        if ocr_result.get("status") in ("unavailable", "error", "timeout"):
            operational_unknowns.append(
                {
                    "text": ocr_result.get("note", "OCR not available."),
                    "resolution_possible": True,
                },
            )

        if hive_result.get("ai_generated_probability") is not None:
            epistemic_unknowns.append(
                {
                    "text": (
                        "AI detection scores reflect model output probabilities; they do not constitute "
                        "a determination that content is or is not AI-generated."
                    ),
                    "resolution_possible": False,
                },
            )

        meta: dict[str, Any] = {
            "sha256": fetch_result.sha256_hash,
            "content_type": fetch_result.content_type,
            "file_size_bytes": len(fetch_result.file_bytes),
            "chain_of_custody": {
                "retrieval_timestamp": coc.retrieval_timestamp,
                "server_ip": coc.server_ip,
                "tls_verified": coc.tls_verified,
                "http_status": coc.http_status,
                "fetch_adapter_version": coc.fetch_adapter_version,
                "response_headers": dict(coc.response_headers),
            },
            "platform_metadata": {
                k: v for k, v in fetch_result.metadata.items() if k != "temp_fetch_dir"
            },
            "job_id": job.job_id,
            "detection": hive_meta,
            "ocr": ocr_result,
        }
        claims: list[dict[str, Any]] = [
            {
                "id": "claim-1",
                "statement": (
                    f"File with SHA-256 {fetch_result.sha256_hash} was retrieved from "
                    f"{request.source_url}"
                ),
                "assertedAt": coc.retrieval_timestamp,
                "type": "observed",
                "implication_risk": "low",
            },
        ]
        if hive_result.get("ai_generated_probability") is not None:
            claims.append(
                {
                    "id": "claim-2",
                    "statement": "Hive visual model reported an AI-generated probability score for this media.",
                    "assertedAt": coc.retrieval_timestamp,
                    "type": "observed",
                    "implication_risk": "high",
                    "implication_note": IMPLICATION_NOTES["ai_detection"],
                },
            )

        sources = [
            {
                "id": source_id,
                "adapter": "manual",
                "url": request.source_url or "",
                "title": f"Fetched media ({coc.fetch_adapter_version})",
                "retrievedAt": coc.retrieval_timestamp,
                "externalRef": fetch_result.sha256_hash[:16],
                "metadata": meta,
            },
        ]
        narrative = [
            {
                "text": (
                    f"Frame retrieved {len(fetch_result.file_bytes)} bytes from "
                    f"{request.source_url}. SHA-256: {fetch_result.sha256_hash}."
                ),
                "sourceId": source_id,
            },
            {
                "text": (
                    f"Fetch adapter {coc.fetch_adapter_version}; TLS verified: {coc.tls_verified}. "
                    f"Server IP: {coc.server_ip or 'unknown'}."
                ),
                "sourceId": source_id,
            },
        ]
        if hive_result.get("detector") == "hive" and hive_result.get("ai_generated_probability") is not None:
            p = float(hive_result["ai_generated_probability"])
            narrative.append(
                {
                    "text": (
                        f"Hive AI detection (visual): model-assigned AI-generated probability approximately "
                        f"{p:.4f}. {IMPLICATION_NOTES['ai_detection']}"
                    ),
                    "sourceId": source_id,
                },
            )
        if ocr_result.get("status") == "success" and ocr_result.get("text"):
            narrative.append(
                {
                    "text": (
                        f"Tesseract OCR extracted {ocr_result.get('char_count', 0)} characters from the image."
                    ),
                    "sourceId": source_id,
                },
            )

        unknowns = {
            "operational": operational_unknowns,
            "epistemic": epistemic_unknowns,
        }
        payload: dict[str, Any] = {
            "schemaVersion": "1.0.0",
            "receiptId": rid,
            "createdAt": coc.retrieval_timestamp,
            "claims": claims,
            "sources": sources,
            "narrative": narrative,
            "unknowns": unknowns,
            "contentHash": "",
        }
        payload_str = json.dumps(payload, ensure_ascii=False)
        _root = _repo_root()
        sign_result = subprocess.run(
            ["npx", "tsx", str(_root / "scripts" / "sign-payload.ts")],
            input=payload_str,
            capture_output=True,
            text=True,
            cwd=str(_root),
            env={**os.environ},
            timeout=120,
        )
        if sign_result.returncode == 0:
            try:
                signed = json.loads(sign_result.stdout.strip())
                receipt = _with_receipt_url(signed)
            except json.JSONDecodeError:
                err = (sign_result.stderr or sign_result.stdout or "")[:500]
                receipt = {**payload, "signing_error": err}
        else:
            err = (sign_result.stderr or sign_result.stdout or "")[:500]
            receipt = {**payload, "signing_error": err}

        mark_complete(job, receipt, start_ms)

    finally:
        if temp_dir_from_ytdlp:
            shutil.rmtree(temp_dir_from_ytdlp, ignore_errors=True)
        elif spill_path and os.path.exists(spill_path):
            try:
                os.unlink(spill_path)
            except OSError:
                pass


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
            await _handle_source_url_job(job, request, start_ms)
            return

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

        elif request.receipt_type == "ad_library":
            receipt = await _generate_ad_library_receipt_for_job(request)

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


SSE_JOB_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Access-Control-Allow-Origin": "*",
}

STAGE_PROGRESS: dict[str, int] = {
    "pending": 5,
    "fetching": 15,
    "downloading": 12,
    "transcribing": 25,
    "extracting": 45,
    "routing": 60,
    "dossier": 75,
    "narrative": 88,
    "signing": 95,
    "complete": 100,
    "failed": 0,
}

STAGE_MESSAGES: dict[str, str] = {
    "pending": "Preparing...",
    "fetching": "Fetching article...",
    "downloading": "Downloading source audio...",
    "transcribing": "Transcribing audio...",
    "extracting": "Extracting claims...",
    "routing": "Routing entities to public records...",
    "dossier": "Assembling dossier...",
    "narrative": "Writing auditor narrative...",
    "signing": "Sealing receipt...",
    "complete": "The record is sealed.",
    "failed": "Pipeline failed.",
}


def _emit_entities_from_claims(job: Job, claims: list[Any]) -> None:
    for c in claims:
        if not isinstance(c, dict):
            continue
        for e in (c.get("entities") or []):
            if e and len(str(e).strip()) > 2:
                append_stream_entity(job, str(e).strip(), "unknown")


async def stream_job_events(job_id: str):
    """Server-Sent Events: tail job stage, transcript, claims, entities, layer zero, receipt."""
    last_stage: str | None = None
    claimed_sent: set[str] = set()
    entity_sent: set[str] = set()
    layer_zero_draft_sent = False
    layer_zero_final_sent = False
    transcript_sent = False
    for _ in range(720):
        await asyncio.sleep(0.5)
        job = get_job(job_id)
        if not job:
            yield f"data: {json.dumps({'event': 'error', 'message': 'job not found'})}\n\n"
            return

        st = getattr(job, "stage", "pending")
        if st != last_stage:
            prog = STAGE_PROGRESS.get(st, 0)
            msg = STAGE_MESSAGES.get(st, st)
            yield f"data: {json.dumps({'event': 'stage_update', 'stage': st, 'message': msg, 'progress': prog})}\n\n"
            last_stage = st

        receipt = job.receipt if isinstance(job.receipt, dict) else {}

        if not transcript_sent and job.transcript:
            transcript_sent = True
            tr = str(job.transcript)
            preview = tr[:500]
            wc = len(tr.split())
            yield f"data: {json.dumps({'event': 'transcript_ready', 'transcript_preview': preview, 'word_count': wc}, default=str)}\n\n"

        for claim in list(job.stream_claims):
            cid = claim.get("id")
            if cid and cid not in claimed_sent:
                claimed_sent.add(str(cid))
                yield f"data: {json.dumps({'event': 'claim_found', 'claim': claim}, default=str)}\n\n"

        for claim in receipt.get("claims", []) if isinstance(receipt, dict) else []:
            cid = claim.get("id")
            if cid and str(cid) not in claimed_sent:
                claimed_sent.add(str(cid))
                yield f"data: {json.dumps({'event': 'claim_found', 'claim': claim}, default=str)}\n\n"

        for row in job.stream_entities:
            name = row.get("name")
            typ = row.get("type", "unknown")
            key = (name or "").lower()
            if name and key not in entity_sent:
                entity_sent.add(key)
                yield f"data: {json.dumps({'event': 'entity_detected', 'entity_name': name, 'entity_type': typ})}\n\n"

        lz = job.stream_layer_zero or (
            receipt.get("layer_zero") if isinstance(receipt, dict) else None
        )
        if isinstance(lz, dict) and not layer_zero_draft_sent:
            layer_zero_draft_sent = True
            yield f"data: {json.dumps({'event': 'layer_zero_draft', 'text': lz.get('text', ''), 'salience': lz.get('salience_score', 0), 'is_final': False}, default=str)}\n\n"

        if job.status == JobStatus.COMPLETE and job.receipt:
            r = job.receipt
            if isinstance(lz, dict) and not layer_zero_final_sent:
                layer_zero_final_sent = True
                yield f"data: {json.dumps({'event': 'layer_zero_final', 'text': lz.get('text', ''), 'salience': lz.get('salience_score', 0), 'is_final': True}, default=str)}\n\n"
            yield f"data: {json.dumps({'event': 'receipt_sealed', 'receipt_id': r.get('receiptId', ''), 'receipt_url': r.get('receiptUrl', ''), 'signature': r.get('signature', ''), 'content_hash': r.get('contentHash', '')}, default=str)}\n\n"
            return

        if job.status == JobStatus.FAILED:
            yield f"data: {json.dumps({'event': 'error', 'message': job.error or 'unknown error'})}\n\n"
            return

    yield f"data: {json.dumps({'event': 'error', 'message': 'stream timeout'})}\n\n"


@app.get("/v1/jobs/{job_id}/stream")
async def job_events_stream(job_id: str):
    return StreamingResponse(
        stream_job_events(job_id),
        media_type="text/event-stream",
        headers=SSE_JOB_HEADERS,
    )


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


def _load_receipt_for_contradiction(receipt_id: str) -> dict[str, Any] | None:
    """Resolve signed receipt from in-memory jobs first, then SQLite ledger."""
    rid = (receipt_id or "").strip()
    if not rid:
        return None
    r = find_receipt_by_receipt_id(rid)
    if r:
        return r
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT payload FROM receipts WHERE id = ?", (rid,)).fetchone()
            if not row:
                return None
            return json.loads(row["payload"])
        finally:
            conn.close()


@app.get("/v1/receipts")
def list_receipts_catalog() -> dict[str, Any]:
    """Receipt IDs and source URLs known to this server (jobs + persisted ledger)."""
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for job in iter_jobs():
        if job.status != JobStatus.COMPLETE or not job.receipt:
            continue
        rec = job.receipt
        if not isinstance(rec, dict):
            continue
        rid = rec.get("receiptId")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        items.append(
            {
                "receipt_id": rid,
                "source_url": _receipt_source_url(rec),
                "job_id": job.job_id,
            }
        )
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, payload FROM receipts ORDER BY created_at DESC LIMIT 500",
            ).fetchall()
            for row in rows:
                rid = row["id"]
                if rid in seen:
                    continue
                seen.add(rid)
                try:
                    data = json.loads(row["payload"])
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                items.append(
                    {
                        "receipt_id": rid,
                        "source_url": _receipt_source_url(data),
                        "job_id": None,
                    }
                )
        finally:
            conn.close()
    return {"receipts": items, "count": len(items)}


@app.get("/v1/receipts/report/{receipt_id}")
def report_receipt_stub(receipt_id: str) -> dict[str, Any]:
    """Placeholder until report receipts are persisted (e.g. PostgreSQL)."""
    return {
        "receipt_id": receipt_id,
        "status": "reports not yet persisted — upgrade to PostgreSQL to enable receipt lookup",
    }


@app.post("/v1/contradiction-analysis")
async def contradiction_analysis(
    request: ContradictionAnalysisRequest,
) -> dict[str, Any]:
    a = _load_receipt_for_contradiction(request.receipt_a_id.strip())
    b = _load_receipt_for_contradiction(request.receipt_b_id.strip())
    if not a:
        raise HTTPException(
            status_code=404,
            detail=f"Receipt not found: {request.receipt_a_id}",
        )
    if not b:
        raise HTTPException(
            status_code=404,
            detail=f"Receipt not found: {request.receipt_b_id}",
        )
    analyzer = ContradictionAnalyzer()
    dossier = await analyzer.compare(a, b, request.entity_name.strip())
    return dossier.model_dump(mode="json")


@app.get("/v1/dark-money/{candidate_id}")
async def dark_money_trace(candidate_id: str, name: str = "") -> dict[str, Any]:
    """
    Run dark money trace for a specific FEC candidate ID.
    Returns disbursement chain with risk flags.

    candidate_id: FEC candidate ID (e.g. S0KY00156 for Rand Paul)
    name: optional entity name for PAC search
    """
    from enrichment.dark_money import run_dark_money_trace

    try:
        result = await run_dark_money_trace(
            candidate_id=candidate_id,
            entity_name=name or candidate_id,
        )
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.get("/v1/podcast-receipt/{receipt_id}/dossier")
async def get_podcast_dossier(receipt_id: str) -> dict[str, Any]:
    """
    Retrieve the dossier assembled for a podcast receipt.
    Returns dossiers for all entities found in that receipt.
    """
    return {
        "receipt_id": receipt_id,
        "note": (
            "Use /v1/podcast-receipt/{receipt_id}/dossier/{entity_name} "
            "to retrieve a specific entity dossier"
        ),
    }


@app.get("/v1/podcast-receipt/{receipt_id}/dossier/{entity_name}")
async def get_podcast_entity_dossier(receipt_id: str, entity_name: str) -> dict[str, Any]:
    """
    Retrieve the dossier for a specific entity from a podcast receipt.
    """
    from db import fetch_dossier
    from enrichment.stage3 import _frame_uuid_for

    name = urllib.parse.unquote(entity_name)
    frame_id = _frame_uuid_for(receipt_id, name)

    dossier = await fetch_dossier(frame_id)
    if not dossier:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No dossier found for entity '{name}' "
                f"in receipt '{receipt_id}'. "
                f"Stage 3 may still be running or entity "
                f"was not found in public records."
            ),
        )
    return dossier.model_dump(mode="json")


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


HIVE_API_KEY = os.getenv("HIVE_API_KEY")
HIVE_ENDPOINT = "https://api.thehive.ai/api/v2/task/sync"


async def _run_hive_detection(file_bytes: bytes, content_type: str) -> dict[str, Any]:
    """
    Call Hive AI detection API.
    Returns structured detection result or a documented failure.
    Always returns a dict — never raises.
    """
    if not HIVE_API_KEY:
        return {
            "detector": "none",
            "note": "HIVE_API_KEY not configured. File hash and timestamp are valid without AI detection.",
            "resolution_possible": True,
        }

    try:
        import httpx

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                HIVE_ENDPOINT,
                headers={"token": HIVE_API_KEY},
                files={"media": ("upload", file_bytes, content_type)},
            )
            response.raise_for_status()
            data = response.json()

        ai_generated_prob = None
        raw_classes: list[Any] = []

        status_list = data.get("status", [])
        for status_item in status_list:
            output = status_item.get("response", {}).get("output", [])
            if not isinstance(output, list):
                output = [output] if output else []
            for item in output:
                if not isinstance(item, dict):
                    continue
                classes = item.get("classes", [])
                if isinstance(classes, list):
                    raw_classes.extend(classes)
                    for cls in classes:
                        if isinstance(cls, dict) and cls.get("class") == "ai_generated":
                            ai_generated_prob = cls.get("score")

        return {
            "detector": "hive",
            "ai_generated_probability": ai_generated_prob,
            "ai_generated_score": ai_generated_prob,
            "raw_classes": raw_classes[:10],
            "model_version": "hive_visual_v2",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "implication_risk": "high",
            "implication_note": IMPLICATION_NOTES["ai_detection"],
        }

    except Exception as e:  # noqa: BLE001
        return {
            "detector": "hive",
            "error": str(e)[:200],
            "note": "Hive detection failed. Hash and timestamp are valid without AI score.",
            "resolution_possible": True,
        }


async def _run_ocr(file_bytes: bytes, content_type: str) -> dict[str, Any]:
    """
    Run Tesseract OCR on image files.
    Returns extracted text or a documented failure.
    Always returns a dict — never raises.
    """
    if not content_type.startswith("image/"):
        return {
            "status": "skipped",
            "note": "OCR only runs on image files.",
        }

    try:
        import io

        import pytesseract
        from PIL import Image

        image = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(image).strip()

        if not text:
            return {
                "status": "no_text_found",
                "note": "OCR ran successfully but found no extractable text.",
            }

        return {
            "status": "success",
            "text": text,
            "char_count": len(text),
            "note": "Text extracted via Tesseract OCR. May be incomplete for stylized or small text.",
        }

    except ImportError:
        return {
            "status": "unavailable",
            "note": "pytesseract or Pillow not installed. Add to requirements.txt.",
            "resolution_possible": True,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "status": "error",
            "error": str(e)[:200],
            "resolution_possible": True,
        }


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

    # Step 5 — Hive AI + Tesseract OCR (parallel, 25s cap)
    hive_task = asyncio.create_task(_run_hive_detection(contents, content_type))
    ocr_task = asyncio.create_task(_run_ocr(contents, content_type))
    try:
        hive_result, ocr_result = await asyncio.wait_for(
            asyncio.gather(hive_task, ocr_task),
            timeout=25.0,
        )
    except asyncio.TimeoutError:
        hive_result = {
            "detector": "none",
            "note": "Hive detection timed out after 25 seconds.",
            "resolution_possible": True,
        }
        ocr_result = {
            "status": "timeout",
            "note": "OCR timed out after 25 seconds.",
            "resolution_possible": True,
        }

    detection_result: dict[str, Any] = dict(hive_result)
    if detection_result.get("ai_generated_probability") is not None:
        detection_result["ai_generated_score"] = detection_result["ai_generated_probability"]
    if "classes" not in detection_result and detection_result.get("raw_classes") is not None:
        detection_result["classes"] = detection_result["raw_classes"][:5]

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
        "ocr": ocr_result,
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

    try:
        await enrich_claims_with_citation_traces(extracted_claim_objects)
    except Exception:  # noqa: BLE001
        pass

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
            "note": "Local faster-whisper (base). First run downloads model weights; cold start can be slow on free tier.",
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
    ocr: dict[str, Any] | None = None
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


async def is_article_url(url: str) -> bool:
    """
    True if URL is likely a text article, not audio/video or known podcast hosts.
    """
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        return False
    try:
        parsed = urllib.parse.urlparse(u)
    except Exception:  # noqa: BLE001
        return False
    path = (parsed.path or "").lower()
    host = (parsed.netloc or "").lower()
    if ":" in host and not host.startswith("["):
        host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]

    for ext in (".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".webm"):
        if path.endswith(ext):
            return False

    blacklist = (
        "youtube.com",
        "youtu.be",
        "spotify.com",
        "soundcloud.com",
        "podtrac.com",
        "megaphone.fm",
        "simplecast.com",
        "buzzsprout.com",
        "anchor.fm",
    )
    for b in blacklist:
        if host == b or host.endswith(f".{b}"):
            return False

    article_domains = (
        "nytimes.com",
        "washingtonpost.com",
        "propublica.org",
        "reuters.com",
        "apnews.com",
        "theguardian.com",
        "substack.com",
        "medium.com",
        "theintercept.com",
        "motherjones.com",
        "politico.com",
        "thehill.com",
        "rollcall.com",
        "axios.com",
        "bloomberg.com",
        "wsj.com",
        "ft.com",
    )
    for d in article_domains:
        if host == d or host.endswith(f".{d}"):
            return True

    for marker in ("/article/", "/news/", "/story/", "/post/"):
        if marker in path:
            return True

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
        ) as client:
            r = await client.head(u)
            ct = (r.headers.get("content-type") or "").lower()
            if "text/html" in ct:
                return True
    except Exception:  # noqa: BLE001
        pass

    return False


async def _investigate_article(
    job: Job,
    url: str,
    tier_config: Any,
    subject_context: str,
    start_ms: float,
    tier_enum: ProcessingTier,
) -> None:
    """Article pipeline: fetch text → claims → enrichment → signed receipt (no Whisper)."""
    update_job(job, stage="fetching")
    fetcher = ArticleFetcher()
    result = await fetcher.fetch(url)
    if not result.resolved:
        mark_failed(
            job,
            f"Could not fetch article: {result.error or 'unknown error'}",
        )
        return

    update_job(job, stage="extracting", transcript=result.text)

    precontext = (
        f"Article: {result.title or 'unknown'}\n"
        f"Author: {result.author or 'unknown'}\n"
        f"Publication: {result.publication or 'unknown'}\n"
        f"Date: {result.published_date or 'unknown'}\n"
    )

    transcription: dict[str, Any] = {
        "full_text": result.text,
        "segments": [],
        "duration": 0.0,
        "language": "unknown",
    }

    claims: list[dict[str, Any]] = []
    if result.text.strip() and os.environ.get("ANTHROPIC_API_KEY"):
        try:

            def _extract_claims() -> list[dict[str, Any]]:
                return extract_speaker_claims(
                    transcription,
                    result.title or "article",
                    article_mode=True,
                    precontext=precontext,
                )

            claims = await asyncio.to_thread(_extract_claims)
        except Exception as claim_err:  # noqa: BLE001
            print(f"[article-investigate] Claim extraction failed: {claim_err}")
    for c in claims:
        append_stream_claim(job, c)

    if tier_config.citation_tracing:
        try:
            await enrich_claims_with_citation_traces(claims)
        except Exception:  # noqa: BLE001
            pass

    update_job(job, stage="routing")
    _emit_entities_from_claims(job, claims)
    all_entities = list(
        {
            e
            for c in claims
            for e in (c.get("entities") or [])
            if e and len(e) > 2
        }
    )
    if all_entities:
        try:
            from entity.resolver import resolve_entity

            for entity_name in all_entities[:5]:
                resolved = await resolve_entity(entity_name)
                if resolved:
                    append_stream_entity(
                        job,
                        resolved.canonical_name,
                        str(resolved.type),
                    )
                    print(
                        "[article-investigate] entity resolved: "
                        f"{resolved.canonical_name} ({resolved.type})"
                    )
        except Exception as entity_err:  # noqa: BLE001
            print(f"[article-investigate] entity resolution skipped: {entity_err}")

    update_job(job, stage="narrative")
    layer_zero: dict[str, Any] = {}
    if claims and os.environ.get("ANTHROPIC_API_KEY"):

        def _gen_lz() -> dict[str, Any]:
            return generate_layer_zero(
                claims,
                subject_context,
                cohort_definition="Claims extracted from article text via Claude",
            )

        layer_zero = await asyncio.to_thread(_gen_lz)
    update_job(job, stream_layer_zero=layer_zero)

    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    audio_info = {
        "title": result.title or "article",
        "source_url": url,
        "downloaded_at": retrieved_at,
        "path": "",
    }
    article_source_record = {
        "id": "s001",
        "adapter": "article",
        "url": url,
        "title": result.title or url,
        "author": result.author,
        "publication": result.publication,
        "retrievedAt": retrieved_at,
        "metadata": {
            "word_count": result.word_count,
            "fetch_method": result.fetch_method,
            "published_date": result.published_date,
        },
    }

    payload = assemble_podcast_payload(
        audio_info=audio_info,
        transcription=transcription,
        claims=claims,
        layer_zero=layer_zero,
        source_input="url",
        tier=tier_enum.value,
        chunks_processed=None,
        chunk_strategy=None,
        canonical_entities_chunked=None,
        content_source="article",
        article_source_record=article_source_record,
    )
    update_job(job, stage="dossier")
    all_entities_claims = list({
        e for c in claims
        for e in (c.get("entities") or [])
        if e and len(e.strip()) > 2
    })
    stage2_adapter_results: list[dict[str, Any]] = []
    if all_entities_claims:
        from adapters_podcast import run_stage2_enrichment

        payload, stage2_adapter_results = await run_stage2_enrichment(
            payload=payload,
            entities=all_entities_claims,
            claims=claims,
        )
    update_job(job, stage="signing")
    signed = await asyncio.to_thread(_sign_frame_payload, payload)
    receipt = _with_receipt_url(signed)
    mark_complete(job, receipt, start_ms)
    if stage2_adapter_results and tier_config.dossier_enabled:
        async def _run_stage3() -> None:
            try:
                from enrichment.stage3 import run_stage3_dossier

                print(
                    f"[stage3] background task started for receipt "
                    f"{signed.get('receiptId')}",
                )
                await run_stage3_dossier(
                    receipt=receipt,
                    claims=claims,
                    entities_resolved=stage2_adapter_results,
                    dossier_enabled=tier_config.dossier_enabled,
                    opus_narrative=tier_config.opus_narrative,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[stage3] dossier assembly error: {exc}")

        asyncio.create_task(_run_stage3())


@app.post("/v1/podcast-investigate")
async def podcast_investigate(
    request: PodcastInvestigateRequest,
    x_whistle_tier: str | None = Header(default=None, alias="X-Whistle-Tier"),
    tier: str | None = Query(default=None),
) -> dict[str, Any]:
    """
    Investigative pipeline for URLs: article pages (fetch + extract text) or
    audio/video (yt-dlp → Whisper → claims). Same downstream stages: routing,
    enrichment, Layer Zero, signed receipt. Returns job_id immediately;
    poll /v1/jobs/{job_id} for result.
    """
    if not request.source_url:
        raise HTTPException(status_code=400, detail="source_url is required")

    tier_enum = resolve_tier(x_whistle_tier, tier)
    tier_config = get_tier_config(tier_enum)
    job = create_job(
        f"Podcast investigation: {request.source_url[:80]}",
        tier=tier_enum.value,
    )

    async def _run() -> None:
        mark_processing(job)
        start_ms = time.time() * 1000
        try:
            src = (request.source_url or "").strip()
            if await is_article_url(src):
                await _investigate_article(
                    job,
                    src,
                    tier_config,
                    request.subject_context or "public figure",
                    start_ms,
                    tier_enum,
                )
                return
            update_job(job, stage="downloading")
            audio_info = await asyncio.to_thread(download_audio, request.source_url)
            update_job(job, stage="transcribing")
            orig_path = audio_info["path"]
            duration_sec: float | None = audio_info.get("duration")
            if duration_sec is None:
                duration_sec = probe_audio_duration_seconds(orig_path)
            if (
                tier_config.max_duration_seconds is not None
                and duration_sec is not None
                and duration_sec > tier_config.max_duration_seconds
            ):
                mark_failed(
                    job,
                    (
                        f"Audio duration exceeds {tier_enum.value} tier limit "
                        f"({tier_config.max_duration_seconds}s). "
                        "Upgrade to PRO for unlimited."
                    ),
                )
                return
            audio_path, _was_trimmed = await asyncio.to_thread(
                trim_audio_max, orig_path, PODCAST_MAX_SECONDS
            )
            trimmed_duration = probe_audio_duration_seconds(audio_path)
            if trimmed_duration is None:
                trimmed_duration = 0.0
            strategy = get_chunk_strategy(int(trimmed_duration))
            chunked_meta: dict[str, Any] | None = None
            used_chunked = False
            if strategy.method != "single":
                try:
                    chunked = await process_chunked_audio(
                        audio_path=audio_path,
                        duration_seconds=float(trimmed_duration),
                        precontext=request.subject_context or "public figure",
                        tier_config=tier_config,
                    )
                    if chunked is not None:
                        transcription = {
                            "full_text": chunked["transcript"],
                            "segments": [],
                            "duration": float(trimmed_duration),
                            "language": "unknown",
                        }
                        claims = chunked["claims"]
                        chunked_meta = {
                            "chunks_processed": chunked["chunks_processed"],
                            "chunk_strategy": chunked["strategy"],
                            "canonical_entities": chunked.get("canonical_entities") or [],
                        }
                        used_chunked = True
                        ft = transcription.get("full_text") or ""
                        update_job(job, transcript=ft, stage="extracting")
                        for c in claims:
                            append_stream_claim(job, c)
                except Exception as chunk_exc:  # noqa: BLE001
                    print(f"[podcast-investigate] chunked pipeline failed, fallback: {chunk_exc}")

            if not used_chunked:
                transcription = await asyncio.to_thread(transcribe_audio, audio_path)
                update_job(job, transcript=transcription.get("full_text", ""), stage="extracting")
                claims = []
                if transcription.get("full_text") and os.environ.get("ANTHROPIC_API_KEY"):
                    try:
                        claims = await asyncio.to_thread(
                            extract_speaker_claims,
                            transcription,
                            audio_info.get("title", "untitled"),
                        )
                    except Exception as claim_err:  # noqa: BLE001
                        print(f"[podcast-investigate] Claim extraction failed: {claim_err}")
                for c in claims:
                    append_stream_claim(job, c)
            if tier_config.citation_tracing:
                try:
                    await enrich_claims_with_citation_traces(claims)
                except Exception:  # noqa: BLE001
                    pass
            update_job(job, stage="routing")
            _emit_entities_from_claims(job, claims)
            # Wire entities from transcript into enrichment pipeline
            all_entities = list(
                {
                    e
                    for c in claims
                    for e in (c.get("entities") or [])
                    if e and len(e) > 2
                }
            )
            if all_entities:
                try:
                    from entity.resolver import resolve_entity

                    for entity_name in all_entities[:5]:  # cap at 5 per receipt
                        resolved = await resolve_entity(entity_name)
                        if resolved:
                            append_stream_entity(
                                job,
                                resolved.canonical_name,
                                str(resolved.type),
                            )
                            print(
                                "[podcast-investigate] entity resolved: "
                                f"{resolved.canonical_name} ({resolved.type})"
                            )
                except Exception as entity_err:  # noqa: BLE001
                    # Non-fatal — receipt generates even if entity resolution fails
                    print(
                        f"[podcast-investigate] entity resolution skipped: {entity_err}"
                    )
            update_job(job, stage="narrative")
            layer_zero: dict[str, Any] = {}
            if claims and os.environ.get("ANTHROPIC_API_KEY"):
                layer_zero = await asyncio.to_thread(
                    generate_layer_zero,
                    claims,
                    request.subject_context or "public figure",
                )
            update_job(job, stream_layer_zero=layer_zero)
            payload = assemble_podcast_payload(
                audio_info=audio_info,
                transcription=transcription,
                claims=claims,
                layer_zero=layer_zero,
                source_input="url",
                tier=tier_enum.value,
                chunks_processed=chunked_meta["chunks_processed"] if chunked_meta else None,
                chunk_strategy=chunked_meta["chunk_strategy"] if chunked_meta else None,
                canonical_entities_chunked=chunked_meta.get("canonical_entities")
                if chunked_meta
                else None,
            )
            update_job(job, stage="dossier")
            # Stage 2 — adapter dispatch
            # `claims` is raw output from extract_speaker_claims (not payload.claims)
            all_entities = list({
                e for c in claims
                for e in (c.get("entities") or [])
                if e and len(e.strip()) > 2
            })
            stage2_adapter_results: list[dict[str, Any]] = []
            if all_entities:
                from adapters_podcast import run_stage2_enrichment

                payload, stage2_adapter_results = await run_stage2_enrichment(
                    payload=payload,
                    entities=all_entities,
                    claims=claims,
                )
            # contentHash is computed in sign-payload.ts from this payload — must run after Stage 2
            update_job(job, stage="signing")
            signed = await asyncio.to_thread(_sign_frame_payload, payload)
            receipt = _with_receipt_url(signed)
            mark_complete(job, receipt, start_ms)
            # Stage 3 — dossier assembly (background, non-blocking)
            if stage2_adapter_results and tier_config.dossier_enabled:
                async def _run_stage3() -> None:
                    try:
                        from enrichment.stage3 import run_stage3_dossier

                        print(
                            f"[stage3] background task started for receipt "
                            f"{signed.get('receiptId')}",
                        )
                        await run_stage3_dossier(
                            receipt=receipt,
                            claims=claims,
                            entities_resolved=stage2_adapter_results,
                            dossier_enabled=tier_config.dossier_enabled,
                            opus_narrative=tier_config.opus_narrative,
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"[stage3] dossier assembly error: {exc}")

                asyncio.create_task(_run_stage3())
        except Exception as exc:  # noqa: BLE001
            mark_failed(job, str(exc))

    asyncio.create_task(_run())
    return {
        "job_id": job.job_id,
        "status": job.status,
        "poll_url": f"/v1/jobs/{job.job_id}",
        "description": job.description,
        "tier": tier_enum.value,
    }


@app.post("/v1/article-investigate")
async def article_investigate(
    request: PodcastInvestigateRequest,
    x_whistle_tier: str | None = Header(default=None, alias="X-Whistle-Tier"),
    tier: str | None = Query(default=None),
) -> dict[str, Any]:
    """
    Full investigative pipeline for article URLs (explicit).
    Always uses the article fetch path regardless of URL heuristics.
    Returns job_id immediately. Poll /v1/jobs/{job_id} for result.
    """
    if not request.source_url:
        raise HTTPException(status_code=400, detail="source_url is required")

    tier_enum = resolve_tier(x_whistle_tier, tier)
    tier_config = get_tier_config(tier_enum)
    job = create_job(
        f"Article investigation: {request.source_url[:80]}",
        tier=tier_enum.value,
    )

    async def _run() -> None:
        mark_processing(job)
        start_ms = time.time() * 1000
        try:
            await _investigate_article(
                job,
                request.source_url.strip(),
                tier_config,
                request.subject_context or "public figure",
                start_ms,
                tier_enum,
            )
        except Exception as exc:  # noqa: BLE001
            mark_failed(job, str(exc))

    asyncio.create_task(_run())
    return {
        "job_id": job.job_id,
        "status": job.status,
        "poll_url": f"/v1/jobs/{job.job_id}",
        "description": job.description,
        "tier": tier_enum.value,
    }


@app.post("/v1/podcast-investigate-upload")
async def podcast_investigate_upload(
    file: UploadFile = File(...),
    subject_context: str = "public figure",
    x_whistle_tier: str | None = Header(default=None, alias="X-Whistle-Tier"),
    tier: str | None = Query(default=None),
) -> dict[str, Any]:
    """
    Same pipeline as /v1/podcast-investigate but accepts an uploaded file.
    Returns job_id immediately. Poll /v1/jobs/{job_id} for result.
    """
    data = await file.read()
    filename = file.filename or "upload.mp3"
    tier_enum = resolve_tier(x_whistle_tier, tier)
    tier_config = get_tier_config(tier_enum)
    job = create_job(
        f"Podcast investigation (upload): {filename}",
        tier=tier_enum.value,
    )

    async def _run() -> None:
        mark_processing(job)
        update_job(job, stage="downloading")
        start_ms = time.time() * 1000
        try:
            audio_info = await asyncio.to_thread(save_uploaded_audio, data, filename)
            update_job(job, stage="transcribing")
            orig_path = audio_info["path"]
            duration_sec: float | None = audio_info.get("duration")
            if duration_sec is None:
                duration_sec = probe_audio_duration_seconds(orig_path)
            if (
                tier_config.max_duration_seconds is not None
                and duration_sec is not None
                and duration_sec > tier_config.max_duration_seconds
            ):
                mark_failed(
                    job,
                    (
                        f"Audio duration exceeds {tier_enum.value} tier limit "
                        f"({tier_config.max_duration_seconds}s). "
                        "Upgrade to PRO for unlimited."
                    ),
                )
                return
            audio_path, _was_trimmed = await asyncio.to_thread(
                trim_audio_max, orig_path, PODCAST_MAX_SECONDS
            )
            trimmed_duration = probe_audio_duration_seconds(audio_path)
            if trimmed_duration is None:
                trimmed_duration = 0.0
            strategy = get_chunk_strategy(int(trimmed_duration))
            chunked_meta: dict[str, Any] | None = None
            used_chunked = False
            if strategy.method != "single":
                try:
                    chunked = await process_chunked_audio(
                        audio_path=audio_path,
                        duration_seconds=float(trimmed_duration),
                        precontext=subject_context or "public figure",
                        tier_config=tier_config,
                    )
                    if chunked is not None:
                        transcription = {
                            "full_text": chunked["transcript"],
                            "segments": [],
                            "duration": float(trimmed_duration),
                            "language": "unknown",
                        }
                        claims = chunked["claims"]
                        chunked_meta = {
                            "chunks_processed": chunked["chunks_processed"],
                            "chunk_strategy": chunked["strategy"],
                            "canonical_entities": chunked.get("canonical_entities") or [],
                        }
                        used_chunked = True
                        ft = transcription.get("full_text") or ""
                        update_job(job, transcript=ft, stage="extracting")
                        for c in claims:
                            append_stream_claim(job, c)
                except Exception as chunk_exc:  # noqa: BLE001
                    print(f"[podcast-investigate-upload] chunked pipeline failed, fallback: {chunk_exc}")

            if not used_chunked:
                transcription = await asyncio.to_thread(transcribe_audio, audio_path)
                update_job(job, transcript=transcription.get("full_text", ""), stage="extracting")
                claims = []
                if transcription.get("full_text") and os.environ.get("ANTHROPIC_API_KEY"):
                    try:
                        claims = await asyncio.to_thread(
                            extract_speaker_claims,
                            transcription,
                            audio_info.get("title", "untitled"),
                        )
                    except Exception as claim_err:  # noqa: BLE001
                        print(f"[podcast-investigate-upload] Claim extraction failed: {claim_err}")
                for c in claims:
                    append_stream_claim(job, c)
            if tier_config.citation_tracing:
                try:
                    await enrich_claims_with_citation_traces(claims)
                except Exception:  # noqa: BLE001
                    pass
            update_job(job, stage="routing")
            _emit_entities_from_claims(job, claims)
            # Wire entities from transcript into enrichment pipeline
            all_entities = list(
                {
                    e
                    for c in claims
                    for e in (c.get("entities") or [])
                    if e and len(e) > 2
                }
            )
            if all_entities:
                try:
                    from entity.resolver import resolve_entity

                    for entity_name in all_entities[:5]:  # cap at 5 per receipt
                        resolved = await resolve_entity(entity_name)
                        if resolved:
                            append_stream_entity(
                                job,
                                resolved.canonical_name,
                                str(resolved.type),
                            )
                            print(
                                "[podcast-investigate-upload] entity resolved: "
                                f"{resolved.canonical_name} ({resolved.type})"
                            )
                except Exception as entity_err:  # noqa: BLE001
                    # Non-fatal — receipt generates even if entity resolution fails
                    print(
                        f"[podcast-investigate-upload] entity resolution skipped: {entity_err}"
                    )
            update_job(job, stage="narrative")
            layer_zero: dict[str, Any] = {}
            if claims and os.environ.get("ANTHROPIC_API_KEY"):
                layer_zero = await asyncio.to_thread(
                    generate_layer_zero,
                    claims,
                    subject_context or "public figure",
                )
            update_job(job, stream_layer_zero=layer_zero)
            payload = assemble_podcast_payload(
                audio_info=audio_info,
                transcription=transcription,
                claims=claims,
                layer_zero=layer_zero,
                source_input="upload",
                tier=tier_enum.value,
                chunks_processed=chunked_meta["chunks_processed"] if chunked_meta else None,
                chunk_strategy=chunked_meta["chunk_strategy"] if chunked_meta else None,
                canonical_entities_chunked=chunked_meta.get("canonical_entities")
                if chunked_meta
                else None,
            )
            update_job(job, stage="dossier")
            # Stage 2 — adapter dispatch
            # `claims` is raw output from extract_speaker_claims (not payload.claims)
            all_entities = list({
                e for c in claims
                for e in (c.get("entities") or [])
                if e and len(e.strip()) > 2
            })
            stage2_adapter_results: list[dict[str, Any]] = []
            if all_entities:
                from adapters_podcast import run_stage2_enrichment

                payload, stage2_adapter_results = await run_stage2_enrichment(
                    payload=payload,
                    entities=all_entities,
                    claims=claims,
                )
            # contentHash is computed in sign-payload.ts from this payload — must run after Stage 2
            update_job(job, stage="signing")
            signed = await asyncio.to_thread(_sign_frame_payload, payload)
            receipt = _with_receipt_url(signed)
            mark_complete(job, receipt, start_ms)
            # Stage 3 — dossier assembly (background, non-blocking)
            if stage2_adapter_results and tier_config.dossier_enabled:
                async def _run_stage3() -> None:
                    try:
                        from enrichment.stage3 import run_stage3_dossier

                        print(
                            f"[stage3] background task started for receipt "
                            f"{signed.get('receiptId')}",
                        )
                        await run_stage3_dossier(
                            receipt=receipt,
                            claims=claims,
                            entities_resolved=stage2_adapter_results,
                            dossier_enabled=tier_config.dossier_enabled,
                            opus_narrative=tier_config.opus_narrative,
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"[stage3] dossier assembly error: {exc}")

                asyncio.create_task(_run_stage3())
        except Exception as exc:  # noqa: BLE001
            mark_failed(job, str(exc))

    asyncio.create_task(_run())
    return {
        "job_id": job.job_id,
        "status": job.status,
        "poll_url": f"/v1/jobs/{job.job_id}",
        "description": job.description,
        "tier": tier_enum.value,
    }


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
async def verify_receipt(request: Request) -> dict[str, Any]:
    """
    Two shapes:

    - **Generic record:** `{ "record": object, "signature": hex, "public_key": hex }` →
      `{ "valid": bool, "checked_at": ISO }` (JCS + @noble/ed25519, same as pattern signing).

    - **Frame receipt:** signed receipt JSON with `contentHash`, `publicKey` (base64 SPKI),
      `signature` (base64) → `{ "ok": bool, "reasons": [...] }`.
    """
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid JSON: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=400,
            detail="Receipt must be a JSON object",
        )

    # Generic JCS + Ed25519 (hex) record verify — pattern lib, Rabbit Hole, etc.
    if (
        isinstance(data.get("record"), dict)
        and isinstance(data.get("signature"), str)
        and isinstance(data.get("public_key"), str)
    ):
        try:
            return await asyncio.to_thread(verify_generic_record, data)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    reasons: list[str] = []

    # Recompute contentHash — strip same fields as TypeScript
    content_hash_body = {
        k: v for k, v in data.items() if k not in ("contentHash", "signature", "publicKey")
    }
    expected_hash = sha256_hex_jcs(content_hash_body)
    if expected_hash != data.get("contentHash"):
        reasons.append("contentHash does not match JCS payload")

    # Recompute signing digest — strip only signature
    signing_body = {k: v for k, v in data.items() if k != "signature"}
    try:
        canon_signing = jcs_canonicalize(signing_body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    digest = hashlib.sha256(canon_signing.encode("utf-8")).digest()

    # Verify Ed25519 signature
    pub_key_b64 = data.get("publicKey", "")
    sig_b64 = data.get("signature", "")

    if not pub_key_b64 or not sig_b64:
        reasons.append("Missing publicKey or signature")
    else:
        try:
            der = base64.b64decode(pub_key_b64, validate=True)
            pub = serialization.load_der_public_key(der)
            if not isinstance(pub, Ed25519PublicKey):
                reasons.append("publicKey is not Ed25519")
            else:
                try:
                    sig = base64.b64decode(sig_b64, validate=True)
                    pub.verify(sig, digest)
                except Exception:
                    reasons.append("signature verification failed")
        except Exception:
            reasons.append("publicKey or signature is not valid base64/DER")

    return {"ok": len(reasons) == 0, "reasons": reasons}
