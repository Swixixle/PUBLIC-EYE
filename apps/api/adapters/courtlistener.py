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
CITATION_LOOKUP_URL = f"{BASE}/api/rest/v4/citation-lookup/"


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


def _norm_cite_compare(s: str) -> str:
    """Normalize reporter cite for equality checks (volume/page)."""
    t = (s or "").lower()
    t = t.replace("u.s.", "us").replace("s.ct.", "sct")
    return re.sub(r"[^a-z0-9]", "", t)


def _parse_us_reporter_triad(citation: str) -> dict[str, str] | None:
    """Volume / U.S. / page triad for citation-lookup POST (CourtListener v4)."""
    s = (citation or "").strip()
    m = re.match(r"^(\d+)\s+U\.\s*S\.\s+(\d+)\s*$", s, re.IGNORECASE)
    if m:
        return {"volume": m.group(1), "reporter": "U.S.", "page": m.group(2)}
    return None


def _first_sub_opinion_id(cluster: dict[str, Any]) -> str | None:
    subs = cluster.get("sub_opinions")
    if not isinstance(subs, list) or not subs:
        return None
    first = subs[0]
    if not isinstance(first, str):
        return None
    m = re.search(r"/opinions/(\d+)/?$", first)
    return m.group(1) if m else None


def _row_from_citation_cluster(cluster: dict[str, Any], citation_searched: str) -> dict[str, Any]:
    abs_p = cluster.get("absolute_url")
    case = str(
        cluster.get("case_name_full")
        or cluster.get("case_name")
        or cluster.get("case_name_short")
        or "",
    ).strip()
    filed = _date_only(cluster.get("date_filed"))
    summary = str(cluster.get("summary") or "")[:500]
    cite_out: str | None = None
    cits = cluster.get("citations")
    if isinstance(cits, list) and cits:
        c0 = cits[0]
        if isinstance(c0, dict):
            cite_out = f'{c0.get("volume")} {c0.get("reporter")} {c0.get("page")}'.strip()
    oid = _first_sub_opinion_id(cluster)
    if oid is None and cluster.get("id") is not None:
        oid = str(cluster["id"])
    return {
        "case_name": case,
        "court": "",
        "date_filed": filed,
        "docket_number": "",
        "citation": cite_out or citation_searched,
        "summary": summary,
        "url": _abs_url(abs_p if isinstance(abs_p, str) else None),
        "opinion_id": int(oid) if oid and str(oid).isdigit() else oid,
        "source_type": "landmark_opinion",
        "citation_searched": citation_searched,
        "source_url": _abs_url(abs_p if isinstance(abs_p, str) else None),
    }


async def _citation_lookup_first_cluster(citation: str) -> dict[str, Any] | None:
    tri = _parse_us_reporter_triad(citation)
    try:
        async with httpx.AsyncClient(timeout=45.0, headers=_headers()) as client:
            if tri:
                r = await client.post(CITATION_LOOKUP_URL, data=tri)
            else:
                r = await client.post(CITATION_LOOKUP_URL, data={"text": citation})
            r.raise_for_status()
            items = r.json()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("CourtListener citation-lookup failed for %s: %s", citation, exc)
        return None
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") not in (200, 300):
            continue
        clusters = item.get("clusters")
        if isinstance(clusters, list) and clusters and isinstance(clusters[0], dict):
            return clusters[0]
    return None


def _citation_list_has_volume_page(raw: dict[str, Any], want_norm: str) -> bool:
    """True if any entry in CourtListener ``citation`` matches normalized cite."""
    if not want_norm:
        return False
    cit = raw.get("citation")
    if not isinstance(cit, list):
        return False
    for item in cit:
        if isinstance(item, str):
            if _norm_cite_compare(item) == want_norm:
                return True
        elif isinstance(item, dict):
            c = str(item.get("cite") or item.get("volume") or "")
            if c and _norm_cite_compare(c) == want_norm:
                return True
    return False


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


def _row_from_opinion_search_hit(
    raw: dict[str, Any],
    *,
    source_type: str = "judicial_opinion",
) -> dict[str, Any]:
    snippet = str(raw.get("snippet") or "")
    summary = snippet[:500] if snippet else ""
    cit = _first_citation(raw.get("citation"))
    case = str(raw.get("caseName") or raw.get("case_name") or "").strip()
    court = str(raw.get("court") or raw.get("court_citation_string") or "").strip()
    dnum = str(raw.get("docketNumber") or raw.get("docket_number") or "").strip()
    filed = _date_only(raw.get("dateFiled") or raw.get("date_filed"))
    abs_p = raw.get("absolute_url") or raw.get("absoluteUrl")
    oid = raw.get("id")
    return {
        "case_name": case,
        "court": court,
        "date_filed": filed,
        "docket_number": dnum,
        "citation": cit,
        "summary": summary,
        "url": _abs_url(abs_p if isinstance(abs_p, str) else None),
        "opinion_id": oid,
        "source_type": source_type,
    }


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
        out.append(_row_from_opinion_search_hit(raw, source_type="judicial_opinion"))
    return out


async def _get_opinion_by_citation_search_fallback(citation: str) -> dict[str, Any] | None:
    """Legacy type=o search when v4 citation-lookup does not apply or fails."""
    cit = (citation or "").strip()
    if not cit:
        return None
    q = f'"{cit}"'
    async with httpx.AsyncClient(timeout=45.0, headers=_headers()) as client:
        r = await client.get(
            f"{API}/search/",
            params={
                "q": q,
                "type": "o",
                "format": "json",
                "page_size": 25,
            },
        )
        r.raise_for_status()
        data = r.json()
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list) or not results:
        return None
    want = _norm_cite_compare(cit)
    raw0: dict[str, Any] | None = None
    for cand in results:
        if isinstance(cand, dict) and _citation_list_has_volume_page(cand, want):
            raw0 = cand
            break
    if raw0 is None:
        raw0 = results[0] if isinstance(results[0], dict) else None
    if raw0 is None:
        return None
    row = _row_from_opinion_search_hit(raw0, source_type="landmark_opinion")
    row["citation_searched"] = cit
    row["source_url"] = row.get("url") or ""
    return row


async def get_opinion_by_citation(citation: str) -> dict[str, Any] | None:
    """
    Resolve a reporter citation via CourtListener v4 citation-lookup when possible,
    else quoted type=o search; attach full_text from get_opinion_text (cap 8000).
    """
    try:
        _warn_no_key()
        if _token() is None:
            return None
        cit = (citation or "").strip()
        if not cit:
            return None

        cluster = await _citation_lookup_first_cluster(cit)
        if cluster is not None:
            row = _row_from_citation_cluster(cluster, cit)
        else:
            row = await _get_opinion_by_citation_search_fallback(cit)
        if row is None:
            return None
        oid = row.get("opinion_id")
        if oid is None:
            return None
        row["full_text"] = (await get_opinion_text(oid))[:8000]
        return row
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("CourtListener get_opinion_by_citation failed for %s: %s", citation, exc)
        return None


async def get_opinion_text(opinion_id: int | str) -> str:
    """Fetch opinion plain text or stripped HTML, capped at 8000 chars. On failure returns ""."""
    try:
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
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("CourtListener get_opinion_text failed: %s", exc)
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
        abs_p = raw.get("absolute_url") or raw.get("absoluteUrl")
        out.append(
            {
                "case_name": case,
                "court": court,
                "date_filed": filed,
                "docket_number": dnum,
                "url": _abs_url(abs_p if isinstance(abs_p, str) else None),
                "source_type": "court_docket",
            }
        )
    return out
