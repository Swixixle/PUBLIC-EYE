"""
GDELT 2.0 adapter — narrative propagation and outlet framing (public API, no key).

DOC API: https://api.gdeltproject.org/api/v2/doc/doc
All HTTP calls are serialized with a module-level lock and a minimum 6s gap after
each completed request (GDELT often returns ``Please limit requests to one every 5 seconds``).

GKG HTTP endpoint availability varies; ``get_outlet_framing`` falls back to DOC + ToneChart.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import Counter
from typing import Any

import httpx

from adapter_result_run import run_adapter

_LOG = logging.getLogger(__name__)

DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GKG_API = "https://api.gdeltproject.org/api/v2/gkg/gkg"

_GDELT_MIN_GAP_S = 6.0
_gdelt_lock = asyncio.Lock()
_last_gdelt_request_end_mono: float = 0.0

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


_GDELT_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "and",
        "or",
        "that",
        "this",
        "its",
        "it",
        "as",
        "from",
        "has",
        "have",
        "been",
        "be",
        "will",
        "would",
        "could",
        "plans",
        "said",
        "says",
    }
)


def _strip_possessive_suffix(token: str) -> str:
    """Remove trailing possessive ``'s`` / ``'S`` (ASCII or curly apostrophe)."""
    if len(token) < 3:
        return token
    for suf in ("'s", "'S", "\u2019s", "\u2019S"):
        if token.endswith(suf):
            return token[: -len(suf)]
    return token


def _clean_gdelt_token(token: str) -> str:
    t = _strip_possessive_suffix(token)
    return re.sub(r"[^\w\-]", "", t, flags=re.UNICODE).strip()


def _tokens_meaningful(text: str, *, max_tokens: int | None) -> list[str]:
    """
    Order-preserving tokens: possessives stripped, punctuation cleaned, English stopwords removed.
    ``max_tokens`` caps how many non-stopword tokens are kept (``None`` = no cap).
    """
    t = _safe_phrase(text)
    if not t:
        return []
    out: list[str] = []
    for raw in t.split():
        w = _clean_gdelt_token(raw)
        if not w:
            continue
        if w.lower() in _GDELT_STOPWORDS:
            continue
        out.append(w)
        if max_tokens is not None and len(out) >= max_tokens:
            break
    return out


def _echo_query_keywords(claim_text: str) -> str:
    """Up to six non-stopword keywords for GDELT (no quotes); fallback if all tokens were stopwords."""
    meaningful = _tokens_meaningful(claim_text, max_tokens=6)
    if meaningful:
        return " ".join(meaningful)
    t = _safe_phrase(claim_text)
    if not t:
        return ""
    fallback: list[str] = []
    for raw in t.split():
        w = _clean_gdelt_token(raw)
        if w:
            fallback.append(w)
        if len(fallback) >= 6:
            break
    return " ".join(fallback).strip()


def _byline_query_name(journalist_name: str) -> str:
    """Journalist name for GDELT ``query``: stopwords stripped, possessives cleaned, then joined."""
    meaningful = _tokens_meaningful(journalist_name, max_tokens=20)
    if meaningful:
        return " ".join(meaningful)
    t = _safe_phrase(journalist_name)
    if not t:
        return ""
    fb: list[str] = []
    for raw in t.split():
        w = _clean_gdelt_token(raw)
        if w:
            fb.append(w)
    return " ".join(fb[:20]).strip()


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


async def _gdelt_http_get(url: str, params: dict[str, Any]) -> httpx.Response | None:
    """Single throttled GET for DOC/GKG — hold lock through request; gap after each completion."""
    global _last_gdelt_request_end_mono
    async with _gdelt_lock:
        now = time.monotonic()
        if _last_gdelt_request_end_mono > 0.0:
            rem = _GDELT_MIN_GAP_S - (now - _last_gdelt_request_end_mono)
            if rem > 0:
                await asyncio.sleep(rem)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(url, params=params)
            return r
        except Exception as exc:  # noqa: BLE001
            _LOG.debug("GDELT HTTP GET failed (%s): %s", url, exc)
            return None
        finally:
            _last_gdelt_request_end_mono = time.monotonic()


async def _doc_get_json(params: dict[str, Any]) -> dict[str, Any] | None:
    try:
        r = await _gdelt_http_get(DOC_API, params)
        if r is None:
            return None
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
        _LOG.debug("GDELT DOC JSON parse failed: %s", exc)
        return None


async def _gkg_get_json(params: dict[str, Any]) -> dict[str, Any] | None:
    try:
        r = await _gdelt_http_get(GKG_API, params)
        if r is None:
            return None
        if r.status_code != 200:
            return None
        ct = (r.headers.get("content-type") or "").lower()
        if "json" not in ct:
            return None
        return r.json()
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("GDELT GKG JSON parse failed: %s", exc)
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

    GDELT accepts ``domain:`` inside the ``query`` string only (no separate URL param).
    ``sourced:`` is not supported — use ``"{name}" domain:{domain}``, then name-only fallback.
    Name tokens use the same English stopword / possessive cleanup as narrative echo queries.
    """
    name = _byline_query_name(journalist_name)
    dom = _normalize_domain(publication)
    if not name:
        return []
    if dom:
        q = f'"{name}" domain:{dom}'
        rows = await _search_artlist_wrapped(query=q, timespan="2y", max_results=max_results)
        if rows:
            return rows
    return await _search_artlist_wrapped(
        query=f'"{name}"',
        timespan="2y",
        max_results=max_results,
    )


async def get_narrative_echo_score(
    claim_text: str,
    hours: int = 72,
    *,
    max_results: int = 250,
) -> dict[str, Any]:
    """
    Coverage concentration: echo_score = unique_domains / total_articles (0 if none).

    Query uses up to six **non-stopword** tokens from ``claim_text`` (possessives stripped,
    punctuation removed), **unquoted** for broader GDELT matching.
    Lower echo_score ⇒ more repeated domains per article.
    """
    phrase = _echo_query_keywords(claim_text)
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
            query=phrase,
            timespan=f"{max(1, int(hours))}h",
            max_results=max(1, min(int(max_results), 250)),
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
