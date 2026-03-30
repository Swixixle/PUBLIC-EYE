"""
Coalition map generation: one Claude call reorganizes global_perspectives into
two ranked outlet chains + narrative fields. Divergence score is computed from
receipt emphasis/minimize tags when present, else taken from model output.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from llm_client import LLMMessage, llm_complete

from models.coalition_map import position_from_dict
from receipt_store import get_receipt as load_stored_receipt, save_coalition_map
from report_api import _frame_public_key_spki_b64, _jcs_canonicalize

_LOG = logging.getLogger(__name__)

COALITION_SYSTEM = """You are a coalition analysis engine for PUBLIC EYE.
You receive a signed news receipt containing a narrative summary and global
perspectives from multiple outlet clusters. You will ALSO receive a catalog of
sources actually attached to this receipt (URLs, primary article, citations).

Your job:
1. Identify the single most contested factual or interpretive claim in the narrative.
2. Confirm the two most irreconcilable positions (already flagged in most_irreconcilable).
3. For each position, produce a ranked chain of outlets/regions that align with it —
   ordered from strongest alignment to weakest.
4. For each outlet in the chain: name it, give its country (ISO 3166-1 alpha-2),
   flag emoji, outlet type (state / private / public_broadcaster),
   alignment confidence (high/medium/low), story_url, and alignment_note (see below).
5. Produce the irreconcilable_gap: one short paragraph naming what cannot be
   simultaneously true about both positions.
6. List 3-5 facts both sides acknowledge as true.

### alignment_note and story_url (mandatory grounding)

For EACH outlet row in each chain, alignment_note must be exactly ONE of:

A) If this outlet appears in the receipt source catalog (matching name or URL):
   Write ONE sentence summarizing what that source actually said or reported.
   Set story_url to the article URL from the catalog for that outlet (or the
   matching line's URL). Set alignment_confidence to high or medium based on how
   directly the coverage supports the position.

B) If the outlet did NOT appear in the receipt source catalog:
   Set alignment_note to exactly: "Not found in sources searched for this receipt."
   Set story_url to "".
   Set alignment_confidence to "low".

Banned in alignment_note: speculative or editorial guessing. Do NOT use:
"likely", "probably", "would", "tends to", "typically", "generally",
"expected to", "consistent with their editorial line", or similar.
If you lack evidence in the catalog, use (B).

Rules:
- Outlet type must be one of: state, private, public_broadcaster
- Alignment confidence must be one of: high, medium, low
- Never assign an outlet to both chains
- The contested_claim must be a single declarative sentence that one side would
  affirm and the other would deny
- Return valid JSON only. No prose outside the JSON object.

Output JSON shape:
{
  "contested_claim": "string",
  "position_a": {
    "label": "string",
    "anchor_region": "ecosystem_id",
    "anchor_outlets": ["string"],
    "summary": "string",
    "emphasizes": ["string"],
    "minimizes": ["string"],
    "chain": [
      {
        "outlet": "string",
        "country": "XX",
        "flag": "emoji",
        "outlet_type": "state|private|public_broadcaster",
        "alignment_confidence": "high|medium|low",
        "alignment_note": "string",
        "story_url": "string"
      }
    ]
  },
  "position_b": { ... same shape ... },
  "irreconcilable_gap": "string",
  "what_both_acknowledge": ["string"],
  "coalition_map_note": "string",
  "divergence_score": 0
}

If you cannot infer good emphasizes/minimizes tags from the receipt data,
still include best-effort short strings. Set divergence_score to an integer 0-100
estimating irreconcilability (used only as fallback).
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sources_catalog_text(receipt: dict[str, Any]) -> str:
    """Human-readable list of sources the receipt actually carries (for coalition grounding)."""
    lines: list[str] = []
    seen: set[str] = set()

    def add_line(s: str) -> None:
        s = s.strip()
        if not s or s in seen:
            return
        seen.add(s)
        lines.append(s)

    art = receipt.get("article") if isinstance(receipt.get("article"), dict) else {}
    if art:
        pub = str(art.get("publication") or "").strip()
        title = str(art.get("title") or "").strip()
        url = str(art.get("url") or "").strip()
        if url or title:
            add_line(f"- Primary article ({pub or 'publication unknown'}): '{title}' {url}".strip())

    for s in receipt.get("sources") or []:
        if not isinstance(s, dict):
            continue
        outlet = str(s.get("outlet") or s.get("publication") or "").strip()
        title = str(s.get("title") or "").strip()
        url = str(s.get("url") or s.get("link") or "").strip()
        date = str(s.get("date") or s.get("published_at") or "").strip()
        if outlet or title or url:
            line = f"- {outlet}: '{title}' ({date}) {url}".strip()
            snip = str(s.get("snippet") or "").strip()
            if snip:
                line += f" | excerpt: {snip[:400]}"
            add_line(line)

    for c in receipt.get("claims_verified") or []:
        if not isinstance(c, dict):
            continue
        cs = c.get("cited_source")
        if cs:
            add_line(f"- Cited in primary article: {cs}")

        for v in c.get("verifications") or []:
            if not isinstance(v, dict):
                continue
            for key in ("url", "link", "source_url"):
                u = v.get(key)
                if isinstance(u, str) and u.startswith("http"):
                    add_line(f"- Adapter / verification link: {u}")
            res = v.get("result")
            if isinstance(res, dict):
                for key in ("url", "link", "source_url", "permalink"):
                    u = res.get(key)
                    if isinstance(u, str) and u.startswith("http"):
                        add_line(f"- Record URL: {u}")

    adapters = receipt.get("sources_checked") or []
    if isinstance(adapters, list) and adapters:
        add_line(
            "- Adapters checked for this receipt (public-record tools, not necessarily URLs): "
            + ", ".join(str(a) for a in adapters[:40])
        )

    if not lines:
        return (
            "Sources actually present in this receipt:\n"
            "(No explicit source URLs beyond what appears in global perspectives; "
            "use primary article only if listed above.)"
        )
    return "Sources actually present in this receipt:\n" + "\n".join(lines)


def receipt_narrative(receipt: dict[str, Any]) -> str:
    syn = receipt.get("synthesis") or {}
    parts = [
        receipt.get("narrative"),
        syn.get("what_is_happening"),
        syn.get("summary"),
        syn.get("narrative"),
        receipt.get("query"),
        (receipt.get("article") or {}).get("title"),
        receipt.get("article_topic"),
    ]
    for p in parts:
        if isinstance(p, str) and p.strip():
            return p.strip()
    return ""


def _ecosystem_by_id(gp: dict[str, Any], eid: str) -> dict[str, Any]:
    for e in gp.get("ecosystems") or []:
        if isinstance(e, dict) and e.get("id") == eid:
            return e
    return {}


def most_irreconcilable_pair(gp: dict[str, Any]) -> tuple[str | None, str | None]:
    mi = gp.get("most_irreconcilable")
    if isinstance(mi, dict):
        a = mi.get("ecosystem_a") or mi.get("a") or mi.get("region_a")
        b = mi.get("ecosystem_b") or mi.get("b") or mi.get("region_b")
        if a and b:
            return str(a), str(b)
    if isinstance(mi, (list, tuple)) and len(mi) >= 2:
        return str(mi[0]), str(mi[1])
    md = gp.get("most_divergent_pair")
    if isinstance(md, dict):
        a, b = md.get("ecosystem_a"), md.get("ecosystem_b")
        if a and b:
            return str(a), str(b)
    eco = gp.get("ecosystems") or []
    if len(eco) >= 2 and isinstance(eco[0], dict) and isinstance(eco[1], dict):
        return eco[0].get("id"), eco[1].get("id")
    return None, None


def _tags_from_ecosystem_row(eco: dict[str, Any]) -> list[str]:
    for key in ("emphasizes", "emphasised"):
        v = eco.get(key)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
    for key in ("emphasized", "emphasised"):
        v = eco.get(key)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            parts = re.split(r"[,;•]|\n", v)
            return [p.strip() for p in parts if p.strip()]
    return []


def _minimize_tags_from_ecosystem(eco: dict[str, Any]) -> list[str]:
    for key in ("minimizes", "minimises"):
        v = eco.get(key)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
    v = eco.get("minimized")
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        parts = re.split(r"[,;•]|\n", v)
        return [p.strip() for p in parts if p.strip()]
    return []


def _confidence_weight_ecosystem(eco: dict[str, Any]) -> float:
    tier = str(eco.get("confidence_level") or eco.get("confidence_tier") or "medium").lower()
    conf_map = {
        "high": 1.0,
        "medium": 0.7,
        "low": 0.4,
        "official_primary": 1.0,
        "official_secondary": 0.7,
        "single_source": 0.4,
        "structural_heuristic": 0.4,
    }
    return conf_map.get(tier, 0.7)


def divergence_score_from_perspectives(
    perspectives: dict[str, Any],
    region_a: str,
    region_b: str,
) -> int | None:
    """
    Weighted composite 0-100 from spec (uses emphasizes/minimize inversion).
    Returns None if tags are too sparse to be meaningful.
    """
    a = _ecosystem_by_id(perspectives, region_a)
    b = _ecosystem_by_id(perspectives, region_b)
    if not a or not b:
        return None

    a_em = set(_tags_from_ecosystem_row(a))
    b_em = set(_tags_from_ecosystem_row(b))
    a_mn = set(_minimize_tags_from_ecosystem(a))
    b_mn = set(_minimize_tags_from_ecosystem(b))

    union_em = a_em | b_em
    if not union_em and not a_mn and not b_mn:
        return None

    def _eco_conf_one(eco: dict[str, Any]) -> float:
        cl = str(eco.get("confidence_level") or "").lower()
        if cl in ("high", "medium", "low"):
            return {"high": 1.0, "medium": 0.7, "low": 0.4}[cl]
        return _confidence_weight_ecosystem(eco)

    conf_weight = (_eco_conf_one(a) + _eco_conf_one(b)) / 2

    if not union_em:
        overlap = 0.0
    else:
        overlap = len(a_em & b_em) / max(len(union_em), 1)
    emphasis_divergence = 1.0 - overlap

    denom = max(len(union_em), 1)
    inversion = (len(a_mn & b_em) + len(b_mn & a_em)) / denom

    raw = emphasis_divergence * 0.4 + inversion * 0.4 + conf_weight * 0.2
    return min(100, int(raw * 110))


def coalition_id_for_receipt(receipt_id: str) -> str:
    clean = re.sub(r"[^a-fA-F0-9]", "", receipt_id)
    return f"cmap-{clean[:8].lower()}"


def attach_coalition_signing(body: dict[str, Any]) -> dict[str, Any]:
    from frame_crypto import sign_frame_digest_hex

    generated_at = body.get("generated_at") or _now_iso()
    signing_body: dict[str, Any] = {
        "receipt_id": body["receipt_id"],
        "coalition_id": body["coalition_id"],
        "contested_claim": body.get("contested_claim"),
        "divergence_score": body.get("divergence_score"),
        "position_a": body.get("position_a"),
        "position_b": body.get("position_b"),
        "irreconcilable_gap": body.get("irreconcilable_gap"),
        "what_both_acknowledge": body.get("what_both_acknowledge") or [],
        "coalition_map_note": body.get("coalition_map_note", ""),
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
        out["signed"] = True
        out["public_key"] = public_key
        out.pop("signing_error", None)
        return out
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("Coalition map signing failed")
        out = {**body, "generated_at": generated_at}
        out["content_hash"] = None
        out["signature"] = None
        out["public_key"] = None
        out["signed"] = False
        out["signing_error"] = str(exc)
        return out


def _strip_json_fence(text: str) -> str:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


def _call_claude(user_prompt: str) -> dict[str, Any]:
    resp = llm_complete(
        system=COALITION_SYSTEM,
        messages=[LLMMessage(role="user", content=user_prompt)],
        max_tokens=8000,
        temperature=0.2,
    )
    raw = _strip_json_fence(resp.text)
    return json.loads(raw)


def build_coalition_map_payload(receipt_id: str) -> dict[str, Any]:
    receipt = load_stored_receipt(receipt_id)
    if not receipt:
        raise ValueError("Receipt not found")

    gp = receipt.get("global_perspectives") or {}
    if not isinstance(gp, dict):
        gp = {}
    if not gp.get("ecosystems") and not gp.get("most_divergent_pair") and not gp.get("most_irreconcilable"):
        raise ValueError("Receipt has no global perspectives data for coalition analysis")

    ra, rb = most_irreconcilable_pair(gp)
    if not ra or not rb:
        raise ValueError("Could not resolve two anchor regions from global perspectives")

    narrative = receipt_narrative(receipt)
    sources_text = _sources_catalog_text(receipt)
    user_prompt = (
        f"Receipt narrative:\n{narrative}\n\n"
        f"Most irreconcilable pair (ecosystem ids): [{ra}, {rb}]\n\n"
        "Global perspectives data:\n"
        f"{json.dumps(gp, ensure_ascii=False, indent=2)}\n\n"
        f"{sources_text}\n\n"
        "Every chain entry's alignment_note must be grounded in the source catalog "
        "above or state exactly: Not found in sources searched for this receipt.\n"
        "position_a.anchor_region must be "
        f'"{ra}"; position_b.anchor_region must be "{rb}".\n'
        "Return the coalition map JSON."
    )

    parsed = _call_claude(user_prompt)

    pos_a_raw = parsed.get("position_a")
    pos_b_raw = parsed.get("position_b")
    if not isinstance(pos_a_raw, dict) or not isinstance(pos_b_raw, dict):
        raise ValueError("Invalid coalition map: positions missing")

    pos_a = position_from_dict(pos_a_raw, ra)
    pos_b = position_from_dict(pos_b_raw, rb)

    computed = divergence_score_from_perspectives(gp, ra, rb)
    model_score = parsed.get("divergence_score")
    if isinstance(model_score, (int, float)):
        score = int(computed if computed is not None else model_score)
    elif computed is not None:
        score = int(computed)
    else:
        score = 50

    score = max(0, min(100, score))

    note = parsed.get("coalition_map_note") or (
        "Alignment confidence reflects how explicitly each outlet endorsed the "
        "assigned position vs. being assigned by proximity. "
        "'State' outlet_type means government-controlled or government-funded "
        "editorial line. Chain order is ranked by alignment confidence descending."
    )

    out: dict[str, Any] = {
        "receipt_id": receipt_id,
        "coalition_id": coalition_id_for_receipt(receipt_id),
        "contested_claim": str(parsed.get("contested_claim", "")),
        "divergence_score": score,
        "position_a": pos_a.model_dump(),
        "position_b": pos_b.model_dump(),
        "irreconcilable_gap": str(parsed.get("irreconcilable_gap", "")),
        "what_both_acknowledge": list(parsed.get("what_both_acknowledge") or []),
        "coalition_map_note": str(note),
    }

    out = attach_coalition_signing(out)
    return out


def run_coalition_generation(receipt_id: str) -> None:
    """Background task: build map and persist (logs on failure)."""
    rid = receipt_id.strip()
    try:
        payload = build_coalition_map_payload(rid)
        save_coalition_map(payload)
    except Exception:  # noqa: BLE001
        _LOG.exception("Coalition map generation failed for %s", rid)
