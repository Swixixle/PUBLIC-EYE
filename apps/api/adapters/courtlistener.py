"""CourtListener REST v3 — opinions search, docket search, opinion text (Free Law Project)."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

_LOG = logging.getLogger(__name__)
_MISSING_KEY_LOGGED = False

BASE = "https://www.courtlistener.com"
API = f"{BASE}/api/rest/v3"


def _token() -> str | None:
    import os

    t = (os.environ.get("COURTLISTENER_API_KEY") or "").strip()
    return t or None


def _headers() -> dict[str, str]:
    tok = _token()
    if not tok:
        return {}
    return {"Authorization": f"Token {tok}"}


def _warn_no_key() -> None:
    global _MISSING_KEY_LOGGED
    if _token() is None and not _MISSING_KEY_LOGGED:
        _LOG.warning("COURTLISTENER_API_KEY not set; CourtListener calls return empty results.")
        _MISSING_KEY_LOGGED = True


def _abs_url(path: str | None) -> str:
    if not path:
        return ""
    p = str(path).strip()
    if p.startswith("http://") or p.startswith("https://"):
        return p
    if not p.startswith("/"):
        p = "/" + p
    return f"{BASE}{p}"


def _first_citation(citation: Any) -> str | None:
    if not citation or not isinstance(citation, list):
        return None
    c0 = citation[0]
    if isinstance(c0, str):
        return c0
    if isinstance(c0, dict):
        return str(c0.get("cite") or c0.get("volume") or c0) or None
    return str(c0) if c0 is not None else None


def _strip_html(html: str) -> str:
    s = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", s).strip()


def _date_only(iso: str | None) -> str:
    if not iso:
        return ""
    s = str(iso).strip()
    if "T" in s:
        return s.split("T", 1)[0]
    return s


async def search_opinions(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    Search published opinions (type=o). On failure or missing token, returns [].
    """
    _warn_no_key()
    if _token() is None:
        return []
    q = (query or "").strip()
    if not q:
        return []
    try:
        async with httpx.AsyncClient(timeout=40.0, headers=_headers()) as client:
            r = await client.get(
                f"{API}/search/",
                params={
                    "q": q,
                    "type": "o",
                    "format": "json",
                    "page_size": min(max(limit, 1), 50),
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("CourtListener search_opinions failed: %s", exc)
        return []

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []

    out: list[dict[str, Any]] = []
    for raw in results[:limit]:
        if not isinstance(raw, dict):
            continue
        snippet = str(raw.get("snippet") or "")
        summary = snippet[:500] if snippet else ""
        cit = _first_citation(raw.get("citation"))
        case = str(raw.get("caseName") or raw.get("case_name") or "").strip()
        court = str(raw.get("court") or raw.get("court_citation_string") or "").strip()
        dnum = str(raw.get("docketNumber") or raw.get("docket_number") or "").strip()
        filed = _date_only(raw.get("dateFiled") or raw.get("date_filed"))
        abs_p = raw.get("absolute_url") or raw.get("absoluteUrl")
        oid = raw.get("id")
        row: dict[str, Any] = {
            "case_name": case,
            "court": court,
            "date_filed": filed,
            "docket_number": dnum,
            "citation": cit,
            "summary": summary,
            "absolute_url": _abs_url(abs_p if isinstance(abs_p, str) else None),
            "source_type": "judicial_opinion",
        }
        if oid is not None:
            row["opinion_id"] = oid
        out.append(row)
    return out


async def get_opinion_text(opinion_id: int | str) -> str:
    """Fetch opinion plain text or stripped HTML, capped at 8000 chars."""
    _warn_no_key()
    if _token() is None:
        return ""
    oid = str(opinion_id).strip()
    if not oid:
        return ""

    async def _fetch_opinion_detail(pk: str) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=45.0, headers=_headers()) as client:
                resp = await client.get(f"{API}/opinions/{pk}/", params={"format": "json"})
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("CourtListener get_opinion_text failed for %s: %s", pk, exc)
            return None

    data = await _fetch_opinion_detail(oid)
    if isinstance(data, dict):
        plain = data.get("plain_text")
        if isinstance(plain, str) and plain.strip():
            return plain.strip()[:8000]
        html = data.get("html") or data.get("html_with_citations")
        if isinstance(html, str) and html.strip():
            return _strip_html(html)[:8000]

    # Search hits often use cluster id; list child opinions for the cluster.
    try:
        async with httpx.AsyncClient(timeout=45.0, headers=_headers()) as client:
            r = await client.get(
                f"{API}/opinions/",
                params={"cluster": oid, "format": "json", "page_size": 5},
            )
            if r.status_code == 200:
                lst = (r.json() or {}).get("results") or []
                if isinstance(lst, list) and lst:
                    first = lst[0]
                    if isinstance(first, dict) and first.get("id") is not None:
                        child = await _fetch_opinion_detail(str(first["id"]))
                        if isinstance(child, dict):
                            plain = child.get("plain_text")
                            if isinstance(plain, str) and plain.strip():
                                return plain.strip()[:8000]
                            html = child.get("html") or child.get("html_with_citations")
                            if isinstance(html, str) and html.strip():
                                return _strip_html(html)[:8000]
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("CourtListener cluster opinion fallback failed: %s", exc)

    return ""


async def search_dockets(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search docket index with q=; on failure returns []."""
    _warn_no_key()
    if _token() is None:
        return []
    q = (query or "").strip()
    if not q:
        return []
    try:
        async with httpx.AsyncClient(timeout=40.0, headers=_headers()) as client:
            r = await client.get(
                f"{API}/dockets/",
                params={
                    "q": q,
                    "format": "json",
                    "page_size": min(max(limit, 1), 50),
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("CourtListener search_dockets failed: %s", exc)
        return []

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []

    out: list[dict[str, Any]] = []
    for raw in results[:limit]:
        if not isinstance(raw, dict):
            continue
        case = str(raw.get("caseName") or raw.get("case_name") or "").strip()
        court_raw = raw.get("court")
        court = ""
        if isinstance(court_raw, str):
            court = court_raw.strip()
            if court.startswith("http"):
                court = str(raw.get("court_citation_string") or raw.get("court_id") or court)
        elif court_raw is not None:
            court = str(court_raw).strip()
        filed = _date_only(raw.get("dateFiled") or raw.get("date_filed"))
        dr = raw.get("docket_number") or raw.get("docketNumber")
        dnum = str(dr).strip() if dr is not None else ""
        pacer = raw.get("pacer_case_id") or raw.get("pacerCaseId")
        abs_p = raw.get("absolute_url") or raw.get("absoluteUrl")
        out.append(
            {
                "case_name": case,
                "court": court,
                "date_filed": filed,
                "docket_number": dnum,
                "pacer_case_id": pacer if pacer is not None else None,
                "absolute_url": _abs_url(abs_p if isinstance(abs_p, str) else None),
                "source_type": "court_docket",
            }
        )
    return out


def sourcing_completeness_status() -> str:
    """For API responses when the key is missing."""
    return "unavailable" if _token() is None else "partial"
