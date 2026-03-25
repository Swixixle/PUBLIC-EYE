"""
Contradiction dossier — compare two signed receipts for the same entity.
Documents conflicting claims; no conclusions about intent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import anthropic
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_CONFLICT_TYPES = frozenset(
    {
        "direct_contradiction",
        "position_change",
        "factual_inconsistency",
        "timeline_conflict",
    }
)


class ConflictingClaim(BaseModel):
    claim_a: str
    claim_b: str
    receipt_a_id: str
    receipt_b_id: str
    receipt_a_date: str
    receipt_b_date: str
    entity_name: str
    conflict_type: str
    conflict_description: str
    confidence: float = Field(ge=0.0, le=1.0)
    earlier_claim: str  # "a" | "b"
    time_delta_days: int | None = None


class ContradictionDossier(BaseModel):
    entity_name: str
    receipt_a_id: str
    receipt_b_id: str
    receipt_a_date: str
    receipt_b_date: str
    receipt_a_source: str
    receipt_b_source: str
    conflicts_found: list[ConflictingClaim]
    conflict_count: int
    dossier_hash: str
    disclaimer: str
    generated_at: str


def extract_claims_from_receipt(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull claims from flat or nested receipt shapes."""
    if not isinstance(receipt, dict):
        return []
    inner = receipt.get("receipt")
    claims = receipt.get("claims")
    if claims is None and isinstance(inner, dict):
        claims = inner.get("claims")
    if not isinstance(claims, list):
        return []
    out: list[dict[str, Any]] = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        ents = c.get("entities")
        if isinstance(ents, list):
            ent_list = [str(e) for e in ents if e]
        else:
            ent_list = []
        out.append(
            {
                "id": str(c.get("id") or ""),
                "statement": str(c.get("statement") or ""),
                "type": str(c.get("type") or ""),
                "implication_risk": str(c.get("implication_risk") or ""),
                "entities": ent_list,
            }
        )
    return out


def claims_for_entity(claims: list[dict[str, Any]], entity_name: str) -> list[dict[str, Any]]:
    en = (entity_name or "").strip().lower()
    if not en:
        return []
    out: list[dict[str, Any]] = []
    for c in claims:
        stmt = str(c.get("statement") or "")
        ents = c.get("entities") or []
        matched = False
        if isinstance(ents, list):
            for e in ents:
                if e and en in str(e).lower():
                    matched = True
                    break
        if not matched and en in stmt.lower():
            matched = True
        if matched:
            out.append(c)
    return out


def _get_source_url(receipt: dict[str, Any]) -> str:
    inner = receipt.get("receipt")
    sources = receipt.get("sources")
    if sources is None and isinstance(inner, dict):
        sources = inner.get("sources")
    if not isinstance(sources, list) or not sources:
        return "unknown"
    first = sources[0]
    if isinstance(first, dict) and first.get("url"):
        return str(first["url"])[:2000]
    return "unknown"


def _extract_json_array(text: str) -> list[Any]:
    raw = text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
    raw = raw.strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _parse_iso_date(s: str) -> datetime | None:
    if not s or s == "unknown":
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s2)
    except ValueError:
        return None


def _earlier_side(a_date: str, b_date: str) -> str:
    da = _parse_iso_date(a_date)
    db = _parse_iso_date(b_date)
    if da and db:
        return "a" if da <= db else "b"
    return "a"


def _time_delta_days(a_date: str, b_date: str) -> int | None:
    da = _parse_iso_date(a_date)
    db = _parse_iso_date(b_date)
    if da and db:
        return abs((da - db).days)
    return None


def _clamp_confidence(
    v: Any,
) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, x))


async def find_contradictions(
    entity_name: str,
    claims_a: list[dict[str, Any]],
    claims_b: list[dict[str, Any]],
    receipt_a_id: str,
    receipt_b_id: str,
    receipt_a_date: str,
    receipt_b_date: str,
) -> list[ConflictingClaim]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return []
    sonnet = os.environ.get("CLAUDE_SONNET_MODEL", "claude-sonnet-4-20250514")
    prompt = f"""You are analyzing two sets of factual claims about {entity_name} extracted from two different audio recordings at different times.

Receipt A (ID: {receipt_a_id}, Date: {receipt_a_date}):
{json.dumps(claims_a, default=str)[:3000]}

Receipt B (ID: {receipt_b_id}, Date: {receipt_b_date}):
{json.dumps(claims_b, default=str)[:3000]}

Identify claims that directly conflict, contradict, or are inconsistent with each other across the two receipts.

Return ONLY a JSON array:
[{{
    "claim_a": "exact claim text from receipt A",
    "claim_b": "exact claim text from receipt B",
    "conflict_type": "direct_contradiction|position_change|factual_inconsistency|timeline_conflict",
    "conflict_description": "factual description of how these claims conflict, no conclusions about intent",
    "confidence": 0.0,
    "earlier_claim": "a or b based on receipt dates"
}}]

Rules:
- Only flag genuine conflicts, not just different topics
- conflict_description must be purely factual: what claim A says vs what claim B says
- Do not use words: lie, lied, liar, deception, corrupt, dishonest
- confidence=1.0 only for direct word-for-word contradictions
- Return [] if no genuine conflicts found
- Valid JSON only, no markdown"""

    client = anthropic.AsyncAnthropic(api_key=key)
    try:
        msg = await client.messages.create(
            model=sonnet,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            getattr(b, "text", "") or "" for b in msg.content if getattr(b, "text", None)
        )
        rows = _extract_json_array(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("find_contradictions failed: %s", exc)
        return []

    td = _time_delta_days(receipt_a_date, receipt_b_date)
    out: list[ConflictingClaim] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            ct = str(row.get("conflict_type") or "factual_inconsistency").strip()
            if ct not in _CONFLICT_TYPES:
                ct = "factual_inconsistency"
            ec = str(row.get("earlier_claim") or "").lower().strip()
            if ec not in ("a", "b"):
                ec = _earlier_side(receipt_a_date, receipt_b_date)
            out.append(
                ConflictingClaim(
                    claim_a=str(row.get("claim_a") or "")[:4000],
                    claim_b=str(row.get("claim_b") or "")[:4000],
                    receipt_a_id=receipt_a_id,
                    receipt_b_id=receipt_b_id,
                    receipt_a_date=receipt_a_date,
                    receipt_b_date=receipt_b_date,
                    entity_name=entity_name.strip()[:500],
                    conflict_type=ct,
                    conflict_description=str(row.get("conflict_description") or "")[:4000],
                    confidence=_clamp_confidence(row.get("confidence")),
                    earlier_claim=ec,
                    time_delta_days=td,
                )
            )
        except Exception:  # noqa: BLE001
            continue
    return out


class ContradictionAnalyzer:
    async def compare(
        self,
        receipt_a: dict[str, Any],
        receipt_b: dict[str, Any],
        entity_name: str,
    ) -> ContradictionDossier:
        claims_a_all = extract_claims_from_receipt(receipt_a)
        claims_b_all = extract_claims_from_receipt(receipt_b)
        claims_a = claims_for_entity(claims_a_all, entity_name)
        claims_b = claims_for_entity(claims_b_all, entity_name)

        def _rid(r: dict[str, Any]) -> str:
            inner = r.get("receipt")
            if isinstance(inner, dict) and inner.get("receiptId"):
                return str(inner["receiptId"])
            return str(r.get("receiptId") or "unknown")

        def _created(r: dict[str, Any]) -> str:
            inner = r.get("receipt")
            if isinstance(inner, dict) and inner.get("createdAt"):
                return str(inner["createdAt"])
            return str(r.get("createdAt") or "unknown")

        receipt_a_id = _rid(receipt_a)
        receipt_b_id = _rid(receipt_b)
        receipt_a_date = _created(receipt_a)
        receipt_b_date = _created(receipt_b)

        conflicts = await find_contradictions(
            entity_name,
            claims_a,
            claims_b,
            receipt_a_id,
            receipt_b_id,
            receipt_a_date,
            receipt_b_date,
        )

        dossier_content = json.dumps(
            {
                "entity_name": entity_name.strip(),
                "receipt_a_id": receipt_a_id,
                "receipt_b_id": receipt_b_id,
                "conflicts": [c.model_dump() for c in conflicts],
            },
            sort_keys=True,
        )
        dossier_hash = hashlib.sha256(dossier_content.encode()).hexdigest()

        return ContradictionDossier(
            entity_name=entity_name.strip(),
            receipt_a_id=receipt_a_id,
            receipt_b_id=receipt_b_id,
            receipt_a_date=receipt_a_date,
            receipt_b_date=receipt_b_date,
            receipt_a_source=_get_source_url(receipt_a),
            receipt_b_source=_get_source_url(receipt_b),
            conflicts_found=conflicts,
            conflict_count=len(conflicts),
            dossier_hash=dossier_hash,
            disclaimer=(
                "This documents factual inconsistencies between two "
                "signed receipts. No intent, motive, or character "
                "judgment is asserted or implied. The receipts are "
                "the evidence."
            ),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
