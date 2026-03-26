"""Deep receipt: universal three-layer structure + adapters by query type + Claude Sonnet + JCS sign."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from adapters.courtlistener import search_opinions
from adapters.scholarly import search_openalex, search_semantic_scholar
from frame_crypto import sign_frame_digest_hex
from report_api import _frame_public_key_spki_b64, _jcs_canonicalize

_LOG = logging.getLogger(__name__)

FEC_CANDIDATE_ID_RE = re.compile(r"^[HSP][0-9][A-Z0-9]{6,}$", re.IGNORECASE)


def _repo_root() -> Path:
    import os

    override = os.environ.get("FRAME_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def classify_query_type(query: str) -> str:
    """Lightweight keyword / id classifier."""
    q = (query or "").strip()
    ql = q.lower()
    if FEC_CANDIDATE_ID_RE.match(q.strip()):
        return "campaign_finance"
    if any(
        k in ql
        for k in (
            "fec",
            "campaign finance",
            "pac contribution",
            "citizens united",
            "fundraising",
            "openfec",
        )
    ):
        return "campaign_finance"
    if any(k in ql for k in ("lobby", "lda", "senate disclosure", "lobbying disclosure")):
        return "legislation"
    if any(k in ql for k in ("sec ", "sec filing", "edgar", "10-k", "10k", "8-k")):
        return "corporate"
    if any(
        k in ql
        for k in ("court", "lawsuit", "docket", "plaintiff", "defendant", "opinion", "circuit")
    ):
        return "judicial"
    if any(k in ql for k in ("bill ", "statute", "public law", "congress.gov", "govinfo")):
        return "legislation"
    if any(k in ql for k in ("wikidata", "entity", "ein ")):
        return "entity"
    return "narrative"


def _fec_key() -> str:
    import os

    return os.environ.get("FEC_API_KEY", "DEMO_KEY").strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_fec_url(url: str) -> str:
    try:
        from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

        p = urlparse(url)
        q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != "api_key"]
        return urlunparse(p._replace(query=urlencode(q)))
    except Exception:  # noqa: BLE001
        return url.replace("api_key=", "api_key_redacted=")


async def _fetch_fec_bundle(candidate_id: str) -> dict[str, Any]:
    """Live OpenFEC candidate + totals; primary_sources rows for Layer A anchoring."""
    cid = candidate_id.strip().upper()
    key = _fec_key()
    base = "https://api.open.fec.gov/v1"
    cand_url = f"{base}/candidates/"
    totals_url = f"{base}/candidates/totals/"
    primary_sources: list[dict[str, Any]] = []
    now = _now_iso()
    async with httpx.AsyncClient(timeout=35.0) as client:
        cr = await client.get(cand_url, params={"candidate_id": cid, "api_key": key})
        cr.raise_for_status()
        cand_json = cr.json()
        tr = await client.get(
            totals_url,
            params={"candidate_id": cid, "api_key": key, "per_page": 20, "sort": "-election_year"},
        )
        tr.raise_for_status()
        totals_json = tr.json()

    c0 = (cand_json.get("results") or [None])[0]
    name = (c0 or {}).get("name") or cid
    qs = _sanitize_fec_url(f"{cand_url}?candidate_id={cid}")
    primary_sources.append(
        {
            "id": f"fec-candidate-{cid}",
            "title": f"FEC candidate profile: {name}",
            "url": qs,
            "adapter": "fec",
            "retrieved_at": now,
        }
    )
    ts = _sanitize_fec_url(f"{totals_url}?candidate_id={cid}")
    primary_sources.append(
        {
            "id": f"fec-totals-{cid}",
            "title": f"FEC fundraising totals by cycle: {name}",
            "url": ts,
            "adapter": "fec",
            "retrieved_at": now,
        }
    )

    return {
        "adapter": "fec",
        "candidate_id": cid,
        "candidate": cand_json,
        "totals": totals_json,
        "primary_sources": primary_sources,
    }


def _attach_signing(body: dict[str, Any]) -> dict[str, Any]:
    """JCS hash of semantic fields; Ed25519 over hex digest (utf-8)."""
    generated_at = body.get("generated_at") or _now_iso()
    signing_body: dict[str, Any] = {
        "query": body.get("query", ""),
        "query_type": body.get("query_type", ""),
        "layer_a": body.get("layer_a", {}),
        "layer_b": body.get("layer_b", {}),
        "layer_c": body.get("layer_c", {}),
        "why_this_matters": body.get("why_this_matters", ""),
        "where_to_look_next": body.get("where_to_look_next", []),
        "generated_at": generated_at,
    }
    try:
        canon = _jcs_canonicalize(signing_body)
        content_hash = hashlib.sha256(canon.encode("utf-8")).hexdigest()
        signature = sign_frame_digest_hex(content_hash)
        public_key = _frame_public_key_spki_b64()
        out = {**body, "generated_at": generated_at}
        out["content_hash"] = content_hash
        out["signature"] = signature
        out["public_key"] = public_key
        out["signed"] = True
        out.pop("signing_error", None)
        return out
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("deep-receipt signing failed")
        out = {**body, "generated_at": generated_at}
        out["content_hash"] = ""
        out["signature"] = ""
        out["public_key"] = ""
        out["signed"] = False
        out["signing_error"] = str(exc)
        return out


def _run_three_layer_ts(
    query: str,
    query_type: str,
    primary_sources: dict[str, Any],
    historical_sources: dict[str, Any],
) -> dict[str, Any]:
    root = _repo_root()
    script = root / "scripts" / "run-three-layer-narrative.ts"
    if not script.is_file():
        raise RuntimeError("run-three-layer-narrative.ts missing")
    payload = {
        "query": query,
        "queryType": query_type,
        "primarySources": primary_sources,
        "historicalSources": historical_sources,
    }
    import os

    proc = subprocess.run(
        ["npx", "tsx", str(script)],
        cwd=str(root),
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ},
        timeout=240,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "three-layer subprocess failed").strip()
        raise RuntimeError(err[:8000])
    return json.loads(proc.stdout.strip())


def _merge_layer_a_sources(payload: dict[str, Any], adapter_sources: list[dict[str, Any]] | None) -> None:
    if not adapter_sources:
        return
    la = payload.get("layer_a")
    if not isinstance(la, dict):
        return
    la["sources"] = adapter_sources


async def build_deep_receipt(query: str) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        raise ValueError("query is required")

    qtype = classify_query_type(q)
    primary: dict[str, Any] = {"query_echo": q, "query_type": qtype}

    if qtype == "campaign_finance" and FEC_CANDIDATE_ID_RE.match(q):
        try:
            primary["fec"] = await _fetch_fec_bundle(q)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("FEC fetch for deep receipt failed: %s", exc)
            primary["fec_error"] = str(exc)[:500]
    elif qtype == "campaign_finance":
        primary["note"] = (
            "No FEC candidate id in query. Include a candidate id such as S0WV00090 for live OpenFEC pulls."
        )

    oa, ss, cl_opinions = await asyncio.gather(
        search_openalex(q, 5),
        search_semantic_scholar(q, 5),
        search_opinions(q, 3),
    )
    layer_b_candidates: list[dict[str, Any]] = []
    for op in cl_opinions:
        if not isinstance(op, dict):
            continue
        df = str(op.get("date_filed") or "")
        year = int(df[:4]) if len(df) >= 4 and df[:4].isdigit() else 0
        case = str(op.get("case_name") or "").strip()
        summ = str(op.get("summary") or "")
        url = str(op.get("url") or "").strip()
        event = f"{case} — {summ[:200]}"
        if not event.strip() or not url:
            continue
        layer_b_candidates.append(
            {
                "year": year,
                "event": event,
                "source_url": url,
                "source_type": "judicial_opinion",
            }
        )
    historical: dict[str, Any] = {
        "openalex": oa,
        "semantic_scholar": ss,
        "courtlistener": {
            "opinions": cl_opinions,
            "layer_b_candidates": layer_b_candidates,
            "sourcing_completeness": "partial" if cl_opinions else "unavailable",
        },
    }

    payload = _run_three_layer_ts(q, qtype, primary, historical)

    fec_sources = None
    fec_block = primary.get("fec")
    if isinstance(fec_block, dict):
        fec_sources = fec_block.get("primary_sources")
    if isinstance(fec_sources, list):
        _merge_layer_a_sources(payload, fec_sources)

    deep_id = str(uuid.uuid4())
    payload["deep_receipt_id"] = deep_id

    return _attach_signing(payload)
