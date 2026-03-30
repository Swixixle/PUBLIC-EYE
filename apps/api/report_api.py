"""Five-ring extended report: assemble surface, spread, origin, actor, pattern layers into one payload."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from actor_layer_fast import run_actor_layer_fast
from adapters.scholarly import academic_origin_candidates, search_openalex, search_semantic_scholar
from origin_api import run_origin
from pattern_api import run_pattern_match
from spread_api import run_spread
from surface_adapter import run_surface_layer

RING_TIMEOUT_SEC = 8.0
_RING_EXECUTOR = ThreadPoolExecutor(max_workers=12)
_LOG = logging.getLogger(__name__)


def _frame_repo_root() -> Path:
    override = os.environ.get("FRAME_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def _jcs_canonicalize(obj: Any) -> str:
    """RFC 8785 via repo `scripts/jcs-stringify.mjs` (same subprocess contract as main.jcs_canonicalize)."""
    root = _frame_repo_root()
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


def _frame_public_key_spki_b64() -> str:
    """SPKI DER, base64 (matches Node receipt embedding); honors FRAME_KEY_FORMAT like frame_crypto."""
    raw = os.environ.get("FRAME_PUBLIC_KEY", "").strip()
    if not raw:
        raise RuntimeError("FRAME_PUBLIC_KEY not set")
    fmt = (os.environ.get("FRAME_KEY_FORMAT") or "pem").strip().lower()
    if fmt == "base64":
        blob = base64.b64decode(raw.strip())
        try:
            pem_text = blob.decode("utf-8")
        except UnicodeDecodeError:
            pem_text = ""
        if "BEGIN" in pem_text and "PUBLIC" in pem_text:
            pem = pem_text.replace("\\n", "\n")
            pub = serialization.load_pem_public_key(pem.strip().encode())
        else:
            pub = serialization.load_der_public_key(blob)
    else:
        pem = raw.replace("\\n", "\n").strip("\"'")
        pub = serialization.load_pem_public_key(pem.strip().encode())
    if not isinstance(pub, Ed25519PublicKey):
        raise RuntimeError("FRAME_PUBLIC_KEY must be Ed25519")
    der = pub.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(der).decode("ascii")


def _attach_report_signing(
    base: dict[str, Any],
    narrative: str,
    rings: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    from frame_crypto import sign_frame_digest_hex

    signing_body = {
        "narrative": narrative,
        "rings": rings,
        "generated_at": generated_at,
    }
    canon = _jcs_canonicalize(signing_body)
    content_hash = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    signature = sign_frame_digest_hex(content_hash)
    public_key = _frame_public_key_spki_b64()
    short = content_hash[:16]
    return {
        **base,
        "content_hash": content_hash,
        "signature": signature,
        "signed": True,
        "public_key": public_key,
        "receipt_url": f"/v1/receipts/report/{short}",
    }


def attach_article_analysis_signing(body: dict[str, Any]) -> dict[str, Any]:
    """
    JCS-canonical semantic slice + SHA-256 + Ed25519, same pipeline as five-ring and deep receipts.
    """
    from frame_crypto import sign_frame_digest_hex

    generated_at = body.get("generated_at") or _now_iso()
    signing_body: dict[str, Any] = {
        "receipt_type": body.get("receipt_type"),
        "article": body.get("article"),
        "article_topic": body.get("article_topic"),
        "named_entities": body.get("named_entities") or [],
        "claims_extracted": body.get("claims_extracted"),
        "claims_verified": body.get("claims_verified") or [],
        "sources_checked": body.get("sources_checked") or [],
        "extraction_error": body.get("extraction_error"),
        "generated_at": generated_at,
    }
    try:
        canon = _jcs_canonicalize(signing_body)
        content_hash = hashlib.sha256(canon.encode("utf-8")).hexdigest()
        signature = sign_frame_digest_hex(content_hash)
        public_key = _frame_public_key_spki_b64()
        short = content_hash[:16]
        merged = {**body, "generated_at": generated_at}
        return {
            **merged,
            "content_hash": content_hash,
            "signature": signature,
            "signed": True,
            "public_key": public_key,
            "receipt_url": f"/v1/receipts/report/{short}",
        }
    except Exception as exc:  # noqa: BLE001 — never fail the receipt on signing
        _LOG.exception("Article analysis signing failed")
        return {
            **body,
            "generated_at": generated_at,
            "content_hash": None,
            "signature": None,
            "public_key": None,
            "signed": False,
            "signing_error": str(exc),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source(
    sid: str,
    adapter: str,
    url: str,
    title: str,
    retrieved_at: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": sid,
        "adapter": adapter,
        "url": url,
        "title": title,
        "retrievedAt": retrieved_at,
    }
    if metadata is not None:
        row["metadata"] = metadata
    return row


def _merge_source_check_status(a: str, b: str) -> str:
    if a == "found" or b == "found":
        return "found"
    if a == "timeout" or b == "timeout":
        return "timeout"
    if a == "error" or b == "error":
        return "error"
    if a == "deferred" or b == "deferred":
        return "deferred"
    return "not_found"


def _classify_ring_adapter_status(adapter: str, data: dict[str, Any]) -> str:
    if data.get("error"):
        return "error"
    if adapter == "layer_surface":
        if (str(data.get("what") or "").strip()) or (data.get("media_claims") or []):
            return "found"
        return "not_found"
    if adapter == "layer_spread":
        if (data.get("spread_indicators") or []) or (data.get("platforms_mentioned") or []):
            return "found"
        return "not_found"
    if adapter == "layer_origin":
        if (data.get("first_instance_indicators") or []) or (data.get("seeding_actors") or []):
            return "found"
        if data.get("academic_origin_candidates"):
            return "found"
        return "not_found"
    if adapter == "layer_actor":
        if data.get("actors_found") or (data.get("dynamic_lookups") or 0) > 0:
            return "found"
        return "not_found"
    if adapter == "layer_pattern":
        if data.get("matches"):
            return "found"
        return "not_found"
    return "not_found"


async def _run_ring_in_executor(
    loop: asyncio.AbstractEventLoop,
    adapter: str,
    fn: Callable[..., dict[str, Any]],
    *args: Any,
    timeout_sec: float | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Returns (adapter, run_status, payload). run_status is ok|timeout|error."""
    limit = RING_TIMEOUT_SEC if timeout_sec is None else timeout_sec
    try:
        payload = await asyncio.wait_for(
            loop.run_in_executor(_RING_EXECUTOR, lambda: fn(*args)),
            timeout=limit,
        )
        return adapter, "ok", payload
    except asyncio.TimeoutError:
        return (
            adapter,
            "timeout",
            {
                "error": f"adapter timeout after {limit:.0f}s",
                "absent_fields": ["adapter_timeout"],
            },
        )
    except Exception as exc:  # noqa: BLE001 — surface to report unknowns
        return (
            adapter,
            "error",
            {
                "error": str(exc),
                "absent_fields": ["adapter_failed"],
            },
        )


def build_extended_report(narrative: str) -> dict[str, Any]:
    """Sync wrapper for tests / callers; runs async implementation in one event loop."""
    return asyncio.run(build_extended_report_async(narrative))


async def build_extended_report_async(narrative: str) -> dict[str, Any]:
    """
    Build unsigned ExtendedReportPayload: rings in parallel (8s cap each), merged unknowns,
    plus sources_checked. Ring 4 uses ledger-only fast path (see actor_layer_fast); full stack
    remains at POST /v1/actor-layer.
    """
    text = narrative.strip()
    now = _now_iso()
    rid = str(uuid.uuid4())
    loop = asyncio.get_running_loop()

    (
        (ad_surface, st_surface, surface),
        (ad_spread, st_spread, spread),
        (ad_origin, st_origin, origin),
        (ad_actor, st_actor, actor),
        (ad_pattern, st_pattern, pattern),
    ) = await asyncio.gather(
        _run_ring_in_executor(loop, "layer_surface", run_surface_layer, {"narrative": text}),
        _run_ring_in_executor(loop, "layer_spread", run_spread, text),
        _run_ring_in_executor(loop, "layer_origin", run_origin, text),
        _run_ring_in_executor(loop, "layer_actor", run_actor_layer_fast, text),
        _run_ring_in_executor(loop, "layer_pattern", run_pattern_match, text),
    )

    oa_rows, ss_rows = await asyncio.gather(
        search_openalex(text, 3),
        search_semantic_scholar(text, 3),
    )
    acad_cand = academic_origin_candidates(oa_rows, ss_rows, cap=5)
    origin_enriched: dict[str, Any] = {**origin, "academic_origin_candidates": acad_cand}

    assert ad_surface == "layer_surface"
    assert ad_spread == "layer_spread"
    assert ad_origin == "layer_origin"
    assert ad_actor == "layer_actor"
    assert ad_pattern == "layer_pattern"

    s_tier = str(surface.get("what_confidence_tier") or "structural_heuristic")
    p_tier = str(spread.get("confidence_tier") or "structural_heuristic")
    o_tier = str(origin.get("confidence_tier") or "structural_heuristic")
    a_tier = str(actor.get("confidence_tier") or "structural_heuristic")
    if pattern.get("matches"):
        pat_tier = "PATTERN_MATCH"
    else:
        pat_tier = "structural_heuristic"

    repo_ref = "https://github.com/Swixixle/FRAME"
    rings: list[dict[str, Any]] = [
        {
            "ring": 1,
            "title": "Surface",
            "content": surface,
            "confidence_tier": s_tier,
            "absent_fields": list(surface.get("absent_fields") or []),
            "sources": [
                _source(
                    "ring-1-layer-surface",
                    "layer_surface",
                    repo_ref,
                    "Layer 1 — surface adapter (Frame)",
                    now,
                ),
            ]
            + (
                [
                    _source(
                        "ring-1-input-url",
                        "layer_surface",
                        str(surface.get("source_url")),
                        "Resolved input URL for surface extraction",
                        now,
                    )
                ]
                if surface.get("source_url")
                else []
            ),
        },
        {
            "ring": 2,
            "title": "Spread",
            "content": spread,
            "confidence_tier": p_tier,
            "absent_fields": list(spread.get("absent_fields") or []),
            "sources": [
                _source(
                    "ring-2-layer-spread",
                    "layer_spread",
                    repo_ref,
                    "Layer 2 — spread heuristic (Frame)",
                    now,
                ),
            ],
        },
        {
            "ring": 3,
            "title": "Origin",
            "content": origin_enriched,
            "confidence_tier": o_tier,
            "absent_fields": list(origin.get("absent_fields") or []),
            "sources": [
                _source(
                    "ring-3-layer-origin",
                    "layer_origin",
                    repo_ref,
                    "Layer 3 — origin heuristic (Frame)",
                    now,
                ),
            ]
            + [
                _source(
                    f"ring-3-academic-{i + 1}",
                    "manual",
                    str(c.get("url") or ""),
                    (c.get("title") or "Scholarly work")[:280],
                    now,
                    metadata={
                        "source_category": "academic",
                        "year": c.get("year"),
                        "cited_by_count": c.get("cited_by_count"),
                        "doi": c.get("doi"),
                        "scholarly_source": c.get("scholarly_source"),
                    },
                )
                for i, c in enumerate(acad_cand)
                if c.get("url")
            ],
        },
        {
            "ring": 4,
            "title": "Actor layer",
            "content": actor,
            "confidence_tier": a_tier,
            "absent_fields": list(actor.get("absent_fields") or []),
            "sources": [
                _source(
                    "ring-4-layer-actor",
                    "layer_actor",
                    repo_ref,
                    "Layer 4 — actor ledger fast path for reports (no outbound HTTP in this ring)",
                    now,
                ),
                _source(
                    "ring-4-actor-layer-full-stack",
                    "layer_actor",
                    repo_ref,
                    "Full source stack (archives, RSS, Wikidata, etc.): POST /v1/actor-layer",
                    now,
                ),
            ],
        },
        {
            "ring": 5,
            "title": "Pattern match",
            "content": {
                "pattern_result": pattern,
                "citations": [
                    {
                        "pattern_id": m.get("pattern_id"),
                        "criteria_met": m.get("criteria_met") or [],
                    }
                    for m in (pattern.get("matches") or [])
                ],
            },
            "confidence_tier": pat_tier,
            "absent_fields": list(
                dict.fromkeys(
                    (pattern.get("absent_fields") or [])
                    + (["no_pattern_match"] if not pattern.get("matches") else [])
                )
            ),
            "sources": [
                _source(
                    "ring-5-layer-pattern",
                    "layer_pattern",
                    repo_ref,
                    "Layer 5 — pattern catalog match (Frame)",
                    now,
                ),
                _source(
                    "ring-5-pattern-library",
                    "pattern_library",
                    f"{repo_ref}/blob/main/packages/pattern-lib/patterns.json",
                    "Signed pattern library (repository path)",
                    now,
                ),
            ],
        },
    ]

    operational: list[dict[str, Any]] = []
    epistemic: list[dict[str, Any]] = []

    for r in rings:
        for af in r.get("absent_fields") or []:
            operational.append(
                {
                    "text": f"Ring {r['ring']} ({r['title']}): gap or absence — {af}",
                    "resolution_possible": True,
                }
            )

    if pattern.get("no_match_reason"):
        epistemic.append(
            {
                "text": str(pattern["no_match_reason"]),
                "resolution_possible": False,
            }
        )

    sources_checked_map: dict[str, str] = {}
    ring_meta = [
        ("layer_surface", st_surface, surface),
        ("layer_spread", st_spread, spread),
        ("layer_origin", st_origin, origin_enriched),
        ("layer_actor", st_actor, actor),
        ("layer_pattern", st_pattern, pattern),
    ]
    for adapter, run_st, payload in ring_meta:
        if run_st == "timeout":
            status = "timeout"
            operational.append(
                {
                    "text": (
                        f"Adapter {adapter} timed out after {RING_TIMEOUT_SEC:.0f}s "
                        f"(operational; report still generated)."
                    ),
                    "resolution_possible": True,
                }
            )
        elif run_st == "error":
            status = "error"
            operational.append(
                {
                    "text": f"Adapter {adapter} failed: {payload.get('error', 'unknown')}",
                    "resolution_possible": True,
                }
            )
        else:
            status = _classify_ring_adapter_status(adapter, payload)
        sources_checked_map[adapter] = status

    for row in actor.get("sources_checked") or []:
        ad = str(row.get("adapter") or "")
        st = str(row.get("status") or "not_found")
        if not ad:
            continue
        if ad in sources_checked_map:
            sources_checked_map[ad] = _merge_source_check_status(sources_checked_map[ad], st)
        else:
            sources_checked_map[ad] = st
        if st == "timeout":
            operational.append(
                {
                    "text": f"Adapter {ad} timed out in Layer 4 stack (operational; resolution possible).",
                    "resolution_possible": True,
                }
            )

    defer_detail_by_adapter: dict[str, str] = {}
    for row in actor.get("sources_checked") or []:
        ad = str(row.get("adapter") or "")
        if row.get("status") == "deferred" and row.get("detail"):
            defer_detail_by_adapter[ad] = str(row["detail"])

    sources_checked = []
    for k, v in sorted(sources_checked_map.items(), key=lambda x: x[0]):
        entry: dict[str, Any] = {"adapter": k, "status": v}
        if v == "deferred" and k in defer_detail_by_adapter:
            entry["detail"] = defer_detail_by_adapter[k]
        sources_checked.append(entry)

    out: dict[str, Any] = {
        "report_id": rid,
        "generated_at": now,
        "narrative": text,
        "rings": rings,
        "signed": False,
        "signature": None,
        "unknowns": {
            "operational": operational,
            "epistemic": epistemic,
        },
        "sources_checked": sources_checked,
    }
    try:
        return _attach_report_signing(out, text, rings, now)
    except Exception as exc:  # noqa: BLE001 — never fail the report on signing
        _LOG.exception("Report signing failed")
        return {**out, "signed": False, "signing_error": str(exc)}
