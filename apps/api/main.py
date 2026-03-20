"""
Frame API — verifies signed receipts using JCS (RFC 8785) via the same `canonicalize`
npm package as TypeScript (Node subprocess). Never use JSON.stringify-equivalent hashing here.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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


app = FastAPI(title="Frame API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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
