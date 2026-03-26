"""GovInfo API — Congressional Record, Federal Register, statutes (GPO).

The search service requires POST to ``/search`` with a JSON body (GET is not supported).
Parameters match GovInfo docs: ``query``, ``pageSize``, ``offsetMark``, ``collections``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

_LOG = logging.getLogger(__name__)
_MISSING_KEY_LOGGED = False

SEARCH_URL = "https://api.govinfo.gov/search"
PACKAGES_BASE = "https://api.govinfo.gov/packages"


def _api_key() -> str | None:
    import os

    k = (os.environ.get("GOVINFO_API_KEY") or "").strip()
    return k or None


def _warn_no_key() -> None:
    global _MISSING_KEY_LOGGED
    if _api_key() is None and not _MISSING_KEY_LOGGED:
        _LOG.warning("GOVINFO_API_KEY not set; GovInfo calls return empty results.")
        _MISSING_KEY_LOGGED = True


def _date_only(s: str | None) -> str:
    if not s:
        return ""
    t = str(s).strip()
    return t.split("T", 1)[0] if "T" in t else t


def _details_url(raw: dict[str, Any]) -> str:
    return str(raw.get("detailsLink") or raw.get("resultLink") or "").strip()


def _agency(raw: dict[str, Any]) -> str:
    org = raw.get("organization")
    if isinstance(org, str) and org.strip():
        return org.strip()
    ga = raw.get("governmentAuthor")
    if isinstance(ga, list) and ga:
        first = ga[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    return ""


def _congress_from_statute(raw: dict[str, Any]) -> str:
    c = raw.get("congress")
    if c is not None and str(c).strip():
        return str(c).strip()
    pid = str(raw.get("packageId") or "")
    m = re.search(r"PLAW-(\d+)publ", pid, re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def _granule_class(raw: dict[str, Any]) -> str:
    for k in ("granuleClass", "granule_class", "docClass"):
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


async def _post_search(collection: str, query: str, limit: int) -> list[dict[str, Any]]:
    _warn_no_key()
    key = _api_key()
    if key is None:
        return []
    q = (query or "").strip()
    if not q:
        return []
    lim = min(max(limit, 1), 100)
    body: dict[str, Any] = {
        "query": q,
        "pageSize": str(lim),
        "offsetMark": "*",
        "collections": [collection],
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(
                SEARCH_URL,
                params={"api_key": key},
                json=body,
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("GovInfo search failed collection=%s: %s", collection, exc)
        return []

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []

    out: list[dict[str, Any]] = []
    for raw in results[:lim]:
        if isinstance(raw, dict):
            out.append(raw)
    return out


async def search_congressional_record(query: str, limit: int = 5) -> list[dict[str, Any]]:
    try:
        rows = await _post_search("CREC", query, limit)
        out: list[dict[str, Any]] = []
        for raw in rows:
            out.append(
                {
                    "title": str(raw.get("title") or "").strip(),
                    "date": _date_only(raw.get("dateIssued")),
                    "collection": "Congressional Record",
                    "package_id": str(raw.get("packageId") or "").strip(),
                    "url": _details_url(raw),
                    "granule_class": _granule_class(raw),
                    "source_type": "congressional_record",
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("search_congressional_record failed: %s", exc)
        return []


async def search_federal_register(query: str, limit: int = 5) -> list[dict[str, Any]]:
    try:
        rows = await _post_search("FR", query, limit)
        out: list[dict[str, Any]] = []
        for raw in rows:
            out.append(
                {
                    "title": str(raw.get("title") or "").strip(),
                    "date": _date_only(raw.get("dateIssued")),
                    "agency": _agency(raw),
                    "url": _details_url(raw),
                    "source_type": "federal_register",
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("search_federal_register failed: %s", exc)
        return []


async def search_statutes(query: str, limit: int = 5) -> list[dict[str, Any]]:
    try:
        rows = await _post_search("STATUTE", query, limit)
        out: list[dict[str, Any]] = []
        for raw in rows:
            out.append(
                {
                    "title": str(raw.get("title") or "").strip(),
                    "date": _date_only(raw.get("dateIssued")),
                    "congress": _congress_from_statute(raw),
                    "url": _details_url(raw),
                    "source_type": "statute",
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("search_statutes failed: %s", exc)
        return []


async def get_package_content(package_id: str) -> dict[str, Any]:
    try:
        _warn_no_key()
        key = _api_key()
        if key is None:
            return {}
        pid = (package_id or "").strip()
        if not pid:
            return {}
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.get(
                f"{PACKAGES_BASE}/{pid}/summary",
                params={"api_key": key},
            )
            r.raise_for_status()
            data = r.json()
        if not isinstance(data, dict):
            return {}
        dl = data.get("download")
        txt = ""
        if isinstance(dl, dict):
            txt = str(dl.get("txtLink") or "").strip()
        pages_val: int | None = None
        for pk in ("pages", "numberOfPages", "numPages"):
            v = data.get(pk)
            if isinstance(v, int):
                pages_val = v
                break
            if isinstance(v, str) and v.isdigit():
                pages_val = int(v)
                break
        return {
            "title": str(data.get("title") or "").strip(),
            "date": _date_only(data.get("dateIssued")),
            "pages": pages_val,
            "download_url": txt,
            "source_type": "govinfo_package",
        }
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("get_package_content failed for %s: %s", package_id, exc)
        return {}
