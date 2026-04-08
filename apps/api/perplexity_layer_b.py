"""
Layer B — Perplexity Sonar web research (cited, not signed).

Single entrypoint `_query()`; `CancelledError` propagates. All other failures return
a failed ``PerplexityResult`` (no bare exceptions to callers).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PERPLEXITY_CHAT_URL = "https://api.perplexity.ai/chat/completions"
MODEL_SONAR = "sonar"
MODEL_SONAR_PRO = "sonar-pro"
QUERY_TIMEOUT_S = 45.0
PERPLEXITY_MAX_TOKENS = 800

JOURNALIST_SYSTEM = (
    "You are a research assistant for an investigative journalism accountability tool. "
    "Return ONLY concrete, factual findings with citations. "
    "CRITICAL: If you find nothing relevant, return exactly the string NO_FINDINGS and nothing else. "
    "Do NOT explain what you searched for, do NOT suggest where to look, "
    "do NOT describe what the results contained or did not contain. "
    "Do NOT use phrases like 'I cannot', 'I was unable', 'the search results do not', 'you would need to'. "
    "Only report what you actually found. Keep responses under 300 words."
)


def _api_key() -> str:
    return (os.environ.get("PERPLEXITY_API_KEY") or "").strip()


@dataclass
class PerplexityResult:
    """Outcome of one Sonar call (field id is the Layer B payload key)."""

    field: str
    ok: bool
    model: str
    text: str | None = None
    citations: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    detail: str | None = None

    def to_record(self, **extra: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "layer": "B",
            "layer_note": "web_research_cited_not_signed",
            "ok": self.ok,
            "model": self.model,
            "text": self.text,
            "citations": list(self.citations or []),
            "latency_ms": round(self.latency_ms, 1),
            "detail": self.detail,
        }
        row.update(extra)
        return row


def _fail(field: str, model: str, detail: str, latency_ms: float = 0.0) -> PerplexityResult:
    return PerplexityResult(field=field, ok=False, model=model, detail=detail, latency_ms=latency_ms)


def _parse_citations(data: dict[str, Any]) -> list[str]:
    raw = data.get("citations")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for c in raw:
        if isinstance(c, str) and c.strip():
            out.append(c.strip())
        elif isinstance(c, dict):
            u = c.get("url") or c.get("href")
            if u:
                out.append(str(u).strip())
    return out[:80]


def _parse_content(data: dict[str, Any]) -> str | None:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    ch0 = choices[0]
    if not isinstance(ch0, dict):
        return None
    msg = ch0.get("message")
    if isinstance(msg, dict):
        c = msg.get("content")
        return str(c).strip() if c is not None else None
    return None


async def _query(
    prompt: str,
    *,
    field: str,
    model: str = MODEL_SONAR,
    timeout_s: float = QUERY_TIMEOUT_S,
    system: str | None = None,
) -> PerplexityResult:
    """One Perplexity chat completion with ``return_citations: True``."""
    t0 = time.monotonic()
    key = _api_key()
    if not key:
        return _fail(field, model, "PERPLEXITY_API_KEY not set", latency_ms=(time.monotonic() - t0) * 1000)

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": PERPLEXITY_MAX_TOKENS,
        "return_citations": True,
    }

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    try:
        timeout = httpx.Timeout(timeout_s, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(PERPLEXITY_CHAT_URL, json=payload, headers=headers)
    except asyncio.CancelledError:
        raise
    except httpx.TimeoutException as exc:
        ms = (time.monotonic() - t0) * 1000
        logger.warning("[perplexity_layer_b] timeout field=%s: %s", field, exc)
        return _fail(field, model, f"timeout:{exc!s}"[:300], latency_ms=ms)
    except Exception as exc:  # noqa: BLE001
        ms = (time.monotonic() - t0) * 1000
        logger.warning("[perplexity_layer_b] error field=%s: %s", field, exc)
        return _fail(field, model, str(exc)[:300], latency_ms=ms)

    ms = (time.monotonic() - t0) * 1000
    if resp.status_code < 200 or resp.status_code >= 300:
        logger.warning(
            "[perplexity_layer_b] HTTP %s field=%s body=%s",
            resp.status_code,
            field,
            (resp.text or "")[:200],
        )
        return _fail(field, model, f"http_{resp.status_code}", latency_ms=ms)

    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return _fail(field, model, f"invalid_json:{exc!s}"[:300], latency_ms=ms)

    if not isinstance(data, dict):
        return _fail(field, model, "response_not_object", latency_ms=ms)

    text = _parse_content(data)
    cites = _parse_citations(data)
    return PerplexityResult(
        field=field,
        ok=True,
        model=model,
        text=text,
        citations=cites,
        latency_ms=ms,
        detail=None,
    )


def _coerce_no_findings(res: PerplexityResult) -> None:
    """Literal NO_FINDINGS → failed row so HTML and clients hide the field."""
    if not res.ok or not isinstance(res.text, str):
        return
    if res.text.strip().casefold() == "no_findings":
        res.ok = False
        res.detail = "no_findings"
        res.text = None
        res.citations = []


async def query_prior_coverage(
    display_name: str,
    publication: str,
    article_topic: str | None,
) -> PerplexityResult:
    pub = (publication or "").strip() or "unknown publication"
    topic = (article_topic or "").strip() or "general beats"
    prompt = (
        f"Find articles written by {display_name} at {pub} about {topic}. "
        f"List article titles, dates, and URLs. Focus on the last 5 years. "
        f"Note if this journalist has covered this topic repeatedly or from a consistent angle."
    )
    return await _query(
        prompt,
        field="prior_coverage",
        model=MODEL_SONAR,
        system=JOURNALIST_SYSTEM,
    )


async def query_prior_positions(
    display_name: str,
    publication: str,
    article_topic: str | None,
) -> PerplexityResult:
    pub = (publication or "").strip() or "unknown publication"
    topic = (article_topic or "").strip() or "public issues"
    prompt = (
        f"Find public statements, op-eds, interviews, or commentary where journalist {display_name} "
        f"expressed a personal opinion or position on {topic}. "
        f"Include dates and source URLs. Note any apparent changes in position over time. "
        f"Only include direct quotes or clearly attributed statements."
    )
    return await _query(
        prompt,
        field="prior_positions",
        model=MODEL_SONAR,
        system=JOURNALIST_SYSTEM,
    )


async def query_affiliations(
    display_name: str,
    publication: str,
) -> PerplexityResult:
    """
    Institutional ties, controversies, defenses, appearances, awards — one deep query.
    Publication grounds context for wire / international journalists without US-only footprints.
    """
    pub = (publication or "").strip()
    pub_context = f" at {pub}" if pub else ""
    prompt = (
        f"Find any of the following about journalist {display_name}{pub_context}: "
        f"(1) fellowships, think tank affiliations, board memberships, or advisory roles; "
        f"(2) public controversies or criticism of their reporting from media critics or journalism reviews; "
        f"(3) public defenses of their reporting or editorial decisions; "
        f"(4) appearances at journalism conferences, universities, or panels; "
        f"(5) awards, grants, or institutional recognition. "
        f"Report only what you find with citations. Skip any category where you find nothing."
    )
    return await _query(
        prompt,
        field="affiliations",
        model=MODEL_SONAR_PRO,
        system=JOURNALIST_SYSTEM,
    )


async def query_recant_candidates(
    display_name: str,
    publication: str,
    article_topic: str | None,
) -> PerplexityResult:
    pub = (publication or "").strip() or "unknown publication"
    topic = (article_topic or "").strip() or "their work"
    prompt = (
        f"Has journalist {display_name} or their outlet issued corrections or retractions "
        f"related to {topic}? Have they faced documented public criticism, editor's notes, "
        f"or fact-checks of their reporting on this topic? "
        f"List only specific documented instances with dates and URLs."
    )
    return await _query(
        prompt,
        field="recant_candidates",
        model=MODEL_SONAR_PRO,
        system=JOURNALIST_SYSTEM,
    )


async def query_source_audit(
    source_person_name: str,
    *,
    journalist_name: str,
    publication: str,
    article_topic: str | None = None,
) -> PerplexityResult:
    pub = (publication or "").strip() or "unknown publication"
    topic = (article_topic or "").strip() or "the story"
    prompt = (
        f"What financial relationships, funding sources, or institutional ties does "
        f"{source_person_name} have relevant to {topic}? "
        f"Include employer, funding, lobbying activity, and any conflicts of interest. "
        f"Cite sources. Do not equate with journalist {journalist_name} ({pub})."
    )
    return await _query(
        prompt,
        field="source_audit",
        model=MODEL_SONAR,
        system=JOURNALIST_SYSTEM,
    )


async def query_outlet_ownership(
    outlet_name: str,
    domain: str | None,
) -> PerplexityResult:
    dom = (domain or "").strip() or "unknown domain"
    prompt = (
        f"Who owns or controls the outlet {outlet_name!r} (domain {dom})? "
        "Parent company, nonprofit structure, or major shareholders if public. Cite URLs."
    )
    return await _query(prompt, field="outlet_ownership", model=MODEL_SONAR)


async def query_outlet_funding(
    outlet_name: str,
    domain: str | None,
) -> PerplexityResult:
    dom = (domain or "").strip() or "unknown domain"
    prompt = (
        f"Describe major funding sources, grants, or advertisers publicly associated with "
        f"{outlet_name!r} ({dom}) that are not already obvious from SEC filings. Cite URLs."
    )
    return await _query(prompt, field="outlet_funding", model=MODEL_SONAR)


def _norm_name(s: str) -> str:
    return " ".join((s or "").lower().split())


async def build_journalist_layer_b(
    *,
    display_name: str,
    publication: str,
    article_topic: str | None,
    quoted_sources: list[dict[str, Any]],
    max_source_audits: int = 3,
) -> dict[str, Any]:
    """Run four core Sonar queries concurrently; source audits concurrent, capped."""
    t0 = time.monotonic()
    name = (display_name or "").strip()
    if not name:
        return {
            "prior_coverage": _fail("prior_coverage", MODEL_SONAR, "no_journalist_name").to_record(),
            "prior_positions": _fail("prior_positions", MODEL_SONAR, "no_journalist_name").to_record(),
            "affiliations": _fail("affiliations", MODEL_SONAR, "no_journalist_name").to_record(),
            "recant_candidates": _fail("recant_candidates", MODEL_SONAR_PRO, "no_journalist_name").to_record(),
            "source_audits": [],
            "wall_time_ms": round((time.monotonic() - t0) * 1000, 1),
        }

    core = await asyncio.gather(
        query_prior_coverage(name, publication, article_topic),
        query_prior_positions(name, publication, article_topic),
        query_affiliations(name, publication),
        query_recant_candidates(name, publication, article_topic),
    )
    prior_r, pos_r, aff_r, rec_r = core
    for r in (prior_r, pos_r, aff_r, rec_r):
        _coerce_no_findings(r)

    audit_names: list[str] = []
    for row in quoted_sources or []:
        if not isinstance(row, dict):
            continue
        nm = str(row.get("name") or "").strip()
        if not nm:
            continue
        if _norm_name(nm) == _norm_name(name):
            continue
        audit_names.append(nm)
        if len(audit_names) >= max_source_audits:
            break

    audit_results: list[dict[str, Any]] = []
    if audit_names:
        tasks = [
            query_source_audit(
                nm,
                journalist_name=name,
                publication=publication,
                article_topic=article_topic,
            )
            for nm in audit_names
        ]
        raw_audits = await asyncio.gather(*tasks)
        for nm, ar in zip(audit_names, raw_audits):
            _coerce_no_findings(ar)
            audit_results.append({"source_name": nm, **ar.to_record()})

    wall_ms = round((time.monotonic() - t0) * 1000, 1)
    return {
        "prior_coverage": prior_r.to_record(),
        "prior_positions": pos_r.to_record(),
        "affiliations": aff_r.to_record(),
        "recant_candidates": rec_r.to_record(),
        "source_audits": audit_results,
        "wall_time_ms": wall_ms,
    }


async def build_outlet_layer_b(
    *,
    outlet_name: str,
    domain: str | None,
    registry_match: bool,
) -> dict[str, Any]:
    """Ownership always; funding only when registry did not match (unknown outlet)."""
    t0 = time.monotonic()
    oname = (outlet_name or "").strip()
    if not oname or oname.lower() == "unknown":
        skip = _fail("outlet_ownership", MODEL_SONAR, "missing_outlet_name")
        return {
            "outlet_ownership": skip.to_record(),
            "outlet_funding": None,
            "wall_time_ms": round((time.monotonic() - t0) * 1000, 1),
        }

    own_r = await query_outlet_ownership(oname, domain)

    fund_r: PerplexityResult | None
    if registry_match:
        fund_r = PerplexityResult(
            field="outlet_funding",
            ok=False,
            model=MODEL_SONAR,
            detail="skipped_registry_match_public_records",
            latency_ms=0.0,
        )
    else:
        fund_r = await query_outlet_funding(oname, domain)

    wall_ms = round((time.monotonic() - t0) * 1000, 1)
    return {
        "outlet_ownership": own_r.to_record(),
        "outlet_funding": fund_r.to_record() if fund_r is not None else None,
        "wall_time_ms": wall_ms,
    }
