"""
GDELT 2.0 adapter — narrative propagation and outlet framing (public API, no key).

DOC API: https://api.gdeltproject.org/api/v2/doc/doc
The service may rate-limit (often ~1 request / 5s); callers should throttle in bulk.

GKG HTTP endpoint availability varies; ``get_outlet_framing`` falls back to DOC + ToneChart.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

import httpx

from adapter_result_run import run_adapter

_LOG = logging.getLogger(__name__)

DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GKG_API = "https://api.gdeltproject.org/api/v2/gkg/gkg"

__all__ = [
    "DOC_API",
    "GKG_API",
    "search_articles_by_claim",
    "search_byline_corpus",
    "get_narrative_echo_score",
    "get_outlet_framing",
]


def _safe_phrase(text: str) -> str:
    t = (text or "").strip().replace('"', " ").replace("\n", " ")
    return re.sub(r"\s+", " ", t).strip()


def _normalize_domain(publication: str) -> str:
    d = (publication or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def _parse_artlist_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("articles")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        seendate = str(a.get("seendate") or "").strip()
        out.append(
            {
                "url": str(a.get("url") or "").strip(),
                "title": str(a.get("title") or "").strip(),
                "domain": str(a.get("domain") or "").strip(),
                "seendate": seendate,
                "language": str(a.get("language") or "").strip(),
                "sourcecountry": str(a.get("sourcecountry") or "").strip(),
            }
        )
    return out


async def _doc_get_json(params: dict[str, Any]) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(DOC_API, params=params)
            if r.status_code != 200:
                return None
            ct = (r.headers.get("content-type") or "").lower()
            if "html" in ct and "json" not in ct:
                return None
            txt = (r.text or "").strip()
            if txt.startswith("<!DOCTYPE") or txt.startswith("<html"):
                return None
            if txt.startswith("Please limit requests"):
                return None
            if "no longer supported" in txt.lower():
                return None
            return r.json()
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("GDELT DOC request failed: %s", exc)
        return None


async def _gkg_get_json(params: dict[str, Any]) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(GKG_API, params=params)
            if r.status_code != 200:
                return None
            ct = (r.headers.get("content-type") or "").lower()
            if "json" not in ct:
                return None
            return r.json()
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("GDELT GKG request failed: %s", exc)
        return None


async def _search_artlist(
    *,
    query: str,
    timespan: str,
    max_results: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "query": query,
        "mode": "artlist",
        "maxrecords": max(1, min(int(max_results), 250)),
        "timespan": timespan,
        "format": "json",
    }
    data = await _doc_get_json(params)
    if not data:
        return []
    return _parse_artlist_payload(data)


async def _search_artlist_wrapped(
    *,
    query: str,
    timespan: str,
    max_results: int,
) -> list[dict[str, Any]]:
    async def _go() -> list[dict[str, Any]]:
        return await _search_artlist(query=query, timespan=timespan, max_results=max_results)

    res = await run_adapter(_go, adapter="gdelt_doc", timeout=15.0)
    if not res.ok or res.value is None:
        return []
    return res.value


async def search_articles_by_claim(
    claim_text: str,
    days: int = 3,
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """
    Exact-phrase article search over GDELT DOC (artlist).

    Returns rows: url, title, domain, seendate, language, sourcecountry.
    """
    phrase = _safe_phrase(claim_text)
    if len(phrase) < 3:
        return []
    q = f'"{phrase}"'
    hours = max(1, int(days) * 24)
    return await _search_artlist_wrapped(query=q, timespan=f"{hours}h", max_results=max_results)


async def search_byline_corpus(
    journalist_name: str,
    publication: str,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """
    Articles mentioning the journalist, scoped to outlet domain.

    Uses ``domain:`` (GDELT-supported). ``sourced:`` is not reliably documented;
    domain filter matches the intended outlet corpus.
    """
    name = _safe_phrase(journalist_name)
    dom = _normalize_domain(publication)
    if not name or not dom:
        return []
    # GDELT query syntax: exact name + sourced: filter (falls back to domain-only if empty).
    q = f'"{name}" sourced:{dom}'
    rows = await _search_artlist_wrapped(query=q, timespan="2y", max_results=max_results)
    if rows:
        return rows
    return await _search_artlist_wrapped(
        query=f'"{name}" domain:{dom}',
        timespan="2y",
        max_results=max_results,
    )


async def get_narrative_echo_score(
    claim_text: str,
    hours: int = 48,
) -> dict[str, Any]:
    """
    Coverage concentration: echo_score = unique_domains / total_articles (0 if none).

    Lower echo_score ⇒ more repeated domains (more concentrated sourcing).
    """
    phrase = _safe_phrase(claim_text)
    if len(phrase) < 3:
        return {
            "total_articles": 0,
            "unique_domains": 0,
            "unique_countries": 0,
            "echo_score": 0.0,
            "top_domains": [],
        }

    async def _go() -> dict[str, Any]:
        rows = await _search_artlist(
            query=f'"{phrase}"',
            timespan=f"{max(1, int(hours))}h",
            max_results=250,
        )
        if not rows:
            return {
                "total_articles": 0,
                "unique_domains": 0,
                "unique_countries": 0,
                "echo_score": 0.0,
                "top_domains": [],
            }
        total = len(rows)
        dom_c = Counter((r.get("domain") or "").strip() for r in rows if r.get("domain"))
        cc_c = Counter((r.get("sourcecountry") or "").strip() for r in rows if r.get("sourcecountry"))
        ud = len(dom_c)
        uc = len(cc_c)
        echo = (ud / total) if total else 0.0
        top = [{"domain": d, "articles": n} for d, n in dom_c.most_common(15)]
        return {
            "total_articles": total,
            "unique_domains": ud,
            "unique_countries": uc,
            "echo_score": round(echo, 6),
            "top_domains": top,
        }

    res = await run_adapter(_go, adapter="gdelt_echo", timeout=15.0)
    if not res.ok or not isinstance(res.value, dict):
        return {
            "total_articles": 0,
            "unique_domains": 0,
            "unique_countries": 0,
            "echo_score": 0.0,
            "top_domains": [],
        }
    return res.value


def _avg_tone_from_tonechart(data: dict[str, Any]) -> float | None:
    rows = data.get("tonechart")
    if not isinstance(rows, list) or not rows:
        return None
    num = 0.0
    den = 0
    for b in rows:
        if not isinstance(b, dict):
            continue
        c = int(b.get("count") or 0)
        binv = float(b.get("bin") or 0)
        if c <= 0:
            continue
        num += binv * c
        den += c
    if den <= 0:
        return None
    return round(num / den, 4)


def _themes_from_gkg(data: dict[str, Any]) -> list[str]:
    """Best-effort theme names from a GKG JSON payload (shape varies)."""
    out: list[str] = []
    for key in ("themes", "topThemes", "gkgthemes", "GKGThemes"):
        v = data.get(key)
        if isinstance(v, list):
            for t in v[:30]:
                if isinstance(t, str) and t.strip():
                    out.append(t.strip())
                elif isinstance(t, dict) and t.get("theme"):
                    out.append(str(t["theme"]).strip())
    return out[:25]


async def _get_outlet_framing_impl(
    outlet_domain: str,
    topic: str,
    days: int,
) -> dict[str, Any]:
    dom = _normalize_domain(outlet_domain)
    t = _safe_phrase(topic)
    if not dom or not t:
        return {
            "article_count": 0,
            "top_themes": [],
            "avg_tone": 0.0,
            "top_sources": [],
            "_framing_backend": "none",
        }

    ts = f"{max(1, int(days))}d"
    # Quote multi-token topics as phrase when it looks like a phrase
    qtopic = f'"{t}"' if " " in t else t
    combined = f"{qtopic} domain:{dom}"

    gkg_params = {
        "query": t,
        "domain": dom,
        "format": "json",
        "maxrecords": min(100, 250),
    }
    gkg_data = await _gkg_get_json(gkg_params)
    themes_gkg: list[str] = []
    if isinstance(gkg_data, dict):
        themes_gkg = _themes_from_gkg(gkg_data)

    art_params: dict[str, Any] = {
        "query": combined,
        "mode": "artlist",
        "maxrecords": 75,
        "timespan": ts,
        "format": "json",
    }
    art_data = await _doc_get_json(art_params)
    articles = _parse_artlist_payload(art_data or {})

    tone_params: dict[str, Any] = {
        "query": combined,
        "mode": "ToneChart",
        "timespan": ts,
        "format": "json",
    }
    tone_data = await _doc_get_json(tone_params) or {}
    avg_tone = _avg_tone_from_tonechart(tone_data)
    if avg_tone is None:
        avg_tone = 0.0

    top_sources: list[dict[str, str]] = []
    for a in articles[:12]:
        top_sources.append(
            {
                "url": str(a.get("url") or ""),
                "title": str(a.get("title") or ""),
                "domain": str(a.get("domain") or ""),
            }
        )

    backend = "gkg+json" if themes_gkg else "doc+tonechart"
    top_themes = themes_gkg
    if not top_themes and isinstance(gkg_data, dict):
        # Some payloads nest arrays under results/gkg
        for path in ("results", "data", "records"):
            blk = gkg_data.get(path)
            if isinstance(blk, list) and blk:
                top_themes = [str(x)[:120] for x in blk[:15] if x is not None]
                break

    return {
        "article_count": len(articles),
        "top_themes": top_themes,
        "avg_tone": float(avg_tone),
        "top_sources": top_sources,
        "_framing_backend": backend,
    }


async def get_outlet_framing(
    outlet_domain: str,
    topic: str,
    days: int = 30,
) -> dict[str, Any]:
    """
    Outlet + topic framing: article volume, tones (ToneChart), optional GKG themes.

    Tries ``GKG_API`` first for theme-like fields; always merges DOC artlist + ToneChart.
    """
    async def _go() -> dict[str, Any]:
        return await _get_outlet_framing_impl(outlet_domain, topic, days)

    res = await run_adapter(_go, adapter="gdelt_framing", timeout=15.0)
    if not res.ok or not isinstance(res.value, dict):
        return {
            "article_count": 0,
            "top_themes": [],
            "avg_tone": 0.0,
            "top_sources": [],
        }
    val = dict(res.value)
    val.pop("_framing_backend", None)
    return val
