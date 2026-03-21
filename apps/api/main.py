"""
Frame API — verifies signed receipts using JCS (RFC 8785) via the same `canonicalize`
npm package as TypeScript (Node subprocess). Never use JSON.stringify-equivalent hashing here.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from datetime import datetime, timezone

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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


class ClaimRecord(BaseModel):
    id: str
    statement: str
    assertedAt: str | None = None


class SourceRecord(BaseModel):
    id: str
    adapter: str
    url: str
    title: str
    retrievedAt: str
    externalRef: str | None = None
    metadata: dict[str, Any] | None = None


class SignedReceipt(BaseModel):
    schemaVersion: str
    receiptId: str
    createdAt: str
    claims: list[ClaimRecord]
    sources: list[SourceRecord]
    narrative: list[NarrativeSentence]
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
        "kinds": ["fec", "opensecrets", "propublica", "lobbying", "edgar", "manual"],
        "note": "Adapters normalize third-party data into Frame SourceRecord rows.",
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


@app.post("/v1/generate-receipt")
def generate_receipt(body: GenerateReceiptRequest) -> dict[str, Any]:
    """
    Build a live FEC receipt for `candidateId` via Node (`buildLiveFecReceipt` + `signReceipt`),
    same pipeline as `scripts/generate-receipt.ts`.
    """
    root = _repo_root()
    script = root / "scripts" / "generate-receipt.ts"
    if not script.is_file():
        raise HTTPException(status_code=500, detail="generate-receipt script missing")

    proc = subprocess.run(
        ["npx", "tsx", str(script), body.candidateId],
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
    return out


@app.post("/v1/generate-lobbying-receipt")
def generate_lobbying_receipt(req: LobbyingRequest) -> dict[str, Any]:
    root = _repo_root()
    script = root / "scripts" / "generate-lobbying-receipt.ts"
    if not script.is_file():
        raise HTTPException(status_code=500, detail="generate-lobbying-receipt script missing")

    proc = subprocess.run(
        ["npx", "tsx", str(script), req.name, req.candidateId or ""],
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
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {exc}") from exc


@app.post("/v1/generate-combined-receipt")
def generate_combined_receipt(req: CombinedReceiptRequest) -> dict[str, Any]:
    root = _repo_root()
    script = root / "scripts" / "generate-combined-receipt.ts"
    if not script.is_file():
        raise HTTPException(status_code=500, detail="generate-combined-receipt script missing")

    fec_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")

    args = [
        "npx",
        "tsx",
        str(script),
        req.candidateId,
        json.dumps(req.lobbyingClients),
        json.dumps(req.years),
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
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {exc}") from exc


@app.post("/v1/generate-990-receipt")
def generate_990_receipt(req: NineNinetyRequest) -> dict[str, Any]:
    root = _repo_root()
    script = root / "scripts" / "generate-990-receipt.ts"
    if not script.is_file():
        raise HTTPException(status_code=500, detail="generate-990-receipt script missing")

    proc = subprocess.run(
        ["npx", "tsx", str(script), req.orgName, req.ein or ""],
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
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {exc}") from exc


@app.post("/v1/generate-wikidata-receipt")
def generate_wikidata_receipt(req: WikidataRequest) -> dict[str, Any]:
    root = _repo_root()
    script = root / "scripts" / "generate-wikidata-receipt.ts"
    if not script.is_file():
        raise HTTPException(status_code=500, detail="generate-wikidata-receipt script missing")

    proc = subprocess.run(
        ["npx", "tsx", str(script), req.personName, req.wikidataId or ""],
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
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {exc}") from exc


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
        conn.close()


_init_db()


async def _verify_and_snapshot_source(url: str, timeout: int = 8) -> dict[str, Any]:
    """Fetch a source URL, hash its content, return verification record."""
    import re as _re

    result: dict[str, Any] = {
        "url": url,
        "verified": False,
        "httpStatus": None,
        "contentHash": None,
        "contentLength": None,
        "pageTitle": None,
        "retrievedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "error": None,
    }

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Frame/1.0 (cryptographic public record verification; https://github.com/Swixixle/FRAME)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result["httpStatus"] = resp.status
            body = resp.read(524288)  # max 512KB
            result["contentLength"] = len(body)
            result["contentHash"] = hashlib.sha256(body).hexdigest()
            result["verified"] = resp.status == 200
            # Extract page title
            try:
                text = body.decode("utf-8", errors="ignore")
                title_match = _re.search(r"<title[^>]*>([^<]{1,200})</title>", text, _re.IGNORECASE)
                if title_match:
                    result["pageTitle"] = title_match.group(1).strip()
            except Exception:  # noqa: BLE001
                pass
    except urllib.error.HTTPError as e:
        result["httpStatus"] = e.code
        result["error"] = f"HTTP {e.code}"
    except urllib.error.URLError as e:
        result["error"] = f"URL error: {str(e.reason)[:80]}"
    except Exception as e:  # noqa: BLE001
        result["error"] = f"Error: {str(e)[:80]}"

    if not result["verified"]:
        result["note"] = "Source suggested but could not be verified at signing time."

    return result


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
                            "hammingDistance": distance,
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


@app.post("/v1/analyze-media")
async def analyze_media(file: UploadFile = File(...)) -> dict[str, Any]:
    contents = await file.read()

    # Step 1 — cryptographic hash
    file_hash = hashlib.sha256(contents).hexdigest()
    file_size = len(contents)
    content_type = file.content_type or "unknown"
    filename = file.filename or "unknown"
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
                                    '      "type": "one of: government_action | financial | death_toll | election | legal | scientific | corporate | general",\n'
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
                verified_sources.append({**ps, "verification": snapshot})
            else:
                verified_sources.append(ps)
        verified_claim_objects.append({**claim_obj, "primary_sources": verified_sources})
    extracted_claim_objects = verified_claim_objects

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
        "note": "Submit to /v1/sign-media-analysis to get a signed Frame receipt",
    }


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


@app.post("/v1/sign-media-analysis")
def sign_media_analysis(req: MediaAnalysisRequest) -> dict[str, Any]:
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
        timeout=60,
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
