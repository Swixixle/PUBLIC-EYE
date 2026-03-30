"""
Computes per-story accuracy axis positioning for outlets.

The axis is accuracy-anchored (proximity to the verifiable record), not politically assigned.
Higher score = more grounded in cross-checked facts for this story.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from outlet_dossier_service import get_baseline_accuracy_rating, outlet_slug


def _confirmed_fact_texts(receipt: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for c in receipt.get("confirmed") or []:
        if isinstance(c, dict):
            t = c.get("title") or c.get("claim")
            if t:
                out.append(str(t))
        elif c:
            out.append(str(c))
    for c in receipt.get("claims_verified") or []:
        if not isinstance(c, dict):
            continue
        if c.get("verified") is True or str(c.get("status", "")).lower() in (
            "verified",
            "confirmed",
            "true",
        ):
            t = c.get("claim") or c.get("subject")
            if t:
                out.append(str(t))
    syn = receipt.get("synthesis") or {}
    if isinstance(syn, dict):
        for x in syn.get("consensus_facts") or syn.get("agreed_facts") or []:
            if x:
                out.append(str(x))
    # de-dupe preserve order
    seen: set[str] = set()
    uniq = []
    for t in out:
        k = t.strip()
        if k and k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq[:40]


def _claim_texts(receipt: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for c in receipt.get("claims_verified") or []:
        if isinstance(c, dict) and (c.get("claim") or c.get("subject")):
            texts.append(str(c.get("claim") or c.get("subject")))
    return texts[:50]


def _source_quality_points(outlet_type: str) -> int:
    ot = (outlet_type or "private").strip()
    if ot == "public_broadcaster":
        return 13
    if ot == "state":
        return 8
    return 11


def compute_outlet_accuracy(
    outlet_data: dict[str, Any],
    receipt_claims: list[str],
    confirmed_facts: list[str],
    baseline_rating: float,
) -> dict[str, Any]:
    """
    Returns component scores (each sub-score already points-weighted) summing toward 0–100.
    """
    conf = (outlet_data.get("alignment_confidence") or "medium").strip().lower()
    if conf not in ("high", "medium", "low"):
        conf = "medium"

    claim_verifiability = {"high": 36, "medium": 26, "low": 14}[conf]

    n_conf = max(1, len(confirmed_facts))
    omission_raw = 30.0
    if confirmed_facts:
        note = str(outlet_data.get("alignment_note") or "").lower()
        missed = sum(1 for f in confirmed_facts[:15] if f[:80].lower() not in note)
        omission_raw = max(5.0, 30.0 * (1.0 - min(1.0, missed / float(n_conf))))
    omission_penalty = int(round(omission_raw))

    correction_pts = int(round(max(0.0, min(1.0, baseline_rating)) * 15))

    source_quality = _source_quality_points(str(outlet_data.get("outlet_type") or "private"))

    total = claim_verifiability + omission_penalty + correction_pts + source_quality
    total = max(0, min(100, total))

    verified_claims: list[str] = []
    unverified_claims: list[str] = []
    if conf == "high" and confirmed_facts:
        verified_claims = confirmed_facts[:2]
    elif conf == "medium" and confirmed_facts:
        verified_claims = confirmed_facts[:1]
    else:
        unverified_claims = [
            "Alignment tagged low — claims not fully echoed in cross-checked facts for this receipt."
        ]

    omissions_desc: list[str] = []
    if confirmed_facts:
        note = str(outlet_data.get("alignment_note") or "")
        for f in confirmed_facts[:5]:
            if f and f[:120] not in note:
                omissions_desc.append(f"{f[:120]}{'…' if len(f) > 120 else ''} — not reflected in this outlet row")

    return {
        "accuracy_score": total,
        "axis_position": round(total / 100.0, 4),
        "components": {
            "claim_verifiability": claim_verifiability,
            "omission_penalty": omission_penalty,
            "correction_history": correction_pts,
            "source_quality": source_quality,
        },
        "verified_claims": verified_claims,
        "unverified_claims": unverified_claims,
        "omissions": omissions_desc[:5],
    }


def _collect_outlet_rows(receipt: dict, coalition: dict | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_chain(chain: list[Any]) -> None:
        for item in chain or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("outlet") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(dict(item))

    if coalition:
        pa = coalition.get("position_a") or {}
        pb = coalition.get("position_b") or {}
        add_chain(pa.get("chain") or [])
        add_chain(pb.get("chain") or [])

    if not rows:
        art = receipt.get("article") or {}
        pub = ""
        if isinstance(art, dict):
            pub = str(art.get("publication") or "").strip()
        if pub:
            rows.append(
                {
                    "outlet": pub,
                    "country": "",
                    "flag": "",
                    "outlet_type": "private",
                    "alignment_confidence": "medium",
                    "alignment_note": "Primary article only; coalition chain not available.",
                }
            )

    return rows


def get_outlet_baseline(outlet_name: str) -> float:
    """0–1 baseline for correction-history band; delegates to dossier store."""
    return get_baseline_accuracy_rating(outlet_name)


def build_media_axis(receipt: dict[str, Any], coalition: dict | None) -> dict[str, Any]:
    """
    Full API payload for POST/GET /v1/media-axis. No DB IO.
    """
    rid = str(
        receipt.get("receipt_id") or receipt.get("report_id") or receipt.get("id") or "",
    ).strip()
    if not rid:
        raise ValueError("receipt has no receipt_id")

    axis_id = "maxis-" + hashlib.sha256(rid.encode()).hexdigest()[:8]
    now = datetime.now(timezone.utc).isoformat()
    confirmed = _confirmed_fact_texts(receipt)
    claims = _claim_texts(receipt)
    art = receipt.get("article") or {}
    art_title = art.get("title") if isinstance(art, dict) else ""
    art_url = art.get("url") if isinstance(art, dict) else ""

    outlet_rows = _collect_outlet_rows(receipt, coalition)
    outlets_out: list[dict[str, Any]] = []

    for row in outlet_rows:
        name = str(row.get("outlet") or "")
        baseline = get_outlet_baseline(name)
        acc = compute_outlet_accuracy(row, claims, confirmed, baseline)
        pub_lower = name.lower()
        story_url = ""
        story_headline = ""
        if isinstance(art, dict) and str(art.get("publication") or "").lower() == pub_lower:
            story_url = str(art_url or "")
            story_headline = str(art_title or "")
        o_payload = {
            "outlet": name,
            "country": str(row.get("country") or ""),
            "flag": str(row.get("flag") or ""),
            "outlet_type": str(row.get("outlet_type") or "private"),
            "accuracy_score": acc["accuracy_score"],
            "axis_position": acc["axis_position"],
            "components": acc["components"],
            "verified_claims": acc["verified_claims"],
            "unverified_claims": acc["unverified_claims"],
            "omissions": acc["omissions"],
            "story_url": story_url,
            "story_headline": story_headline,
            "story_date": "",
            "slug": outlet_slug(name),
        }
        outlets_out.append(o_payload)

    outlets_sorted = sorted(outlets_out, key=lambda x: x["accuracy_score"], reverse=True)
    most = outlets_sorted[0] if outlets_sorted else None
    least = outlets_sorted[-1] if outlets_sorted else None
    spread = (most["accuracy_score"] - least["accuracy_score"]) if most and least else 0

    return {
        "receipt_id": rid,
        "axis_id": axis_id,
        "generated_at": now,
        "signed": False,
        "axis": {
            "label_high": "More grounded in the verifiable record",
            "label_low": "More interpretive / less verified",
            "outlets": outlets_sorted,
        },
        "most_accurate": {"outlet": most["outlet"], "score": most["accuracy_score"]}
        if most
        else None,
        "least_accurate": {"outlet": least["outlet"], "score": least["accuracy_score"]}
        if least
        else None,
        "spread": spread,
        "note": (
            "Spread measures distance between most and least grounded outlets on this receipt's "
            "cross-checked facts. Higher spread = a more contested factual landscape. "
            "This axis is not political: any outlet can land right or wrong per story."
        ),
    }
