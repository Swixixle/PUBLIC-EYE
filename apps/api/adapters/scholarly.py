"""
Scholarly metadata — OpenAlex, Semantic Scholar, Crossref (no API keys).
Each search fails soft; callers combine with asyncio.gather.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote_plus

import httpx

OPENALEX_HEADERS = {"User-Agent": "FRAME/1.0 (mailto:contact@frame.dev)"}
SS_HEADERS = {"User-Agent": "FRAME/1.0 (mailto:contact@frame.dev)"}
CROSSREF_HEADERS = {"User-Agent": "FRAME/1.0 (mailto:contact@frame.dev)"}


def _norm_doi(doi: str | None) -> str | None:
    if not doi or not isinstance(doi, str):
        return None
    d = doi.strip().lower()
    if d.startswith("https://doi.org/"):
        d = d[16:]
    if d.startswith("http://doi.org/"):
        d = d[15:]
    if d.startswith("doi:"):
        d = d[4:]
    return d.strip() or None


def _dedupe_key(row: dict[str, Any]) -> str:
    d = _norm_doi(row.get("doi"))
    if d:
        return f"doi:{d}"
    t = (row.get("title") or "")[:240].lower().strip()
    y = row.get("year")
    return f"fallback:{t}|{y}"


def reconstruct_openalex_abstract(inv: dict[str, Any] | None) -> str:
    if not inv or not isinstance(inv, dict):
        return ""
    pairs: list[tuple[int, str]] = []
    for word, positions in inv.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for pos in positions:
            try:
                pairs.append((int(pos), word))
            except (TypeError, ValueError):
                continue
    pairs.sort(key=lambda x: x[0])
    return " ".join(w for _, w in pairs)


def _strip_jats_xml(text: str) -> str:
    if not text:
        return ""
    s = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", s).strip()


async def search_openalex(query: str, limit: int = 5) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    try:
        async with httpx.AsyncClient(timeout=35.0, headers=OPENALEX_HEADERS) as client:
            r = await client.get(
                "https://api.openalex.org/works",
                params={
                    "search": q,
                    "filter": "is_oa:true",
                    "per_page": min(max(limit, 1), 25),
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for w in (data.get("results") or [])[:limit]:
        authorships = w.get("authorships") or []
        authors: list[str] = []
        for a in authorships:
            au = (a or {}).get("author") or {}
            dn = au.get("display_name")
            if isinstance(dn, str) and dn.strip():
                authors.append(dn.strip())
        biblio = w.get("biblio") or {}
        year = w.get("publication_year")
        pl = w.get("primary_location") or {}
        src = pl.get("source") or {}
        journal = src.get("display_name") if isinstance(src, dict) else None
        doi_raw = w.get("doi") or (w.get("ids") or {}).get("doi")
        doi = doi_raw if isinstance(doi_raw, str) else None
        if isinstance(doi, str) and doi.startswith("https://doi.org/"):
            doi = doi.split("https://doi.org/", 1)[-1].strip()
        inv = w.get("abstract_inverted_index")
        abstract = reconstruct_openalex_abstract(inv) if isinstance(inv, dict) else ""
        wid = w.get("id")
        url = f"https://doi.org/{_norm_doi(doi)}" if _norm_doi(doi) else (wid or "")
        _tit = w.get("title")
        title_s = _tit if isinstance(_tit, str) else str(w.get("display_title") or "")
        out.append(
            {
                "title": title_s,
                "authors": authors,
                "year": year,
                "doi": doi,
                "abstract": abstract,
                "cited_by_count": w.get("cited_by_count") or 0,
                "journal": journal,
                "volume": biblio.get("volume"),
                "issue": biblio.get("issue"),
                "url": url,
            },
        )
    return out


async def search_semantic_scholar(query: str, limit: int = 5) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    try:
        async with httpx.AsyncClient(timeout=35.0, headers=SS_HEADERS) as client:
            r = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={
                    "query": q,
                    "limit": min(max(limit, 1), 20),
                    "fields": "title,authors,year,abstract,citationCount,externalIds",
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for p in (data.get("data") or [])[:limit]:
        authors: list[str] = []
        for a in p.get("authors") or []:
            if isinstance(a, dict):
                name = a.get("name")
                if isinstance(name, str) and name.strip():
                    authors.append(name.strip())
        ext = p.get("externalIds") or {}
        doi = ext.get("DOI") if isinstance(ext, dict) else None
        nd = _norm_doi(doi)
        url = f"https://doi.org/{nd}" if nd else ""
        out.append(
            {
                "title": p.get("title") or "",
                "authors": authors,
                "year": p.get("year"),
                "doi": doi,
                "abstract": (p.get("abstract") or "") if isinstance(p.get("abstract"), str) else "",
                "cited_by_count": int(p.get("citationCount") or 0),
                "journal": None,
                "url": url,
            },
        )
    return out


async def search_crossref(query: str, limit: int = 5) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    try:
        async with httpx.AsyncClient(timeout=35.0, headers=CROSSREF_HEADERS) as client:
            r = await client.get(
                "https://api.crossref.org/works",
                params={
                    "query": q,
                    "rows": min(max(limit, 1), 20),
                    "filter": "has-abstract:true",
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    items = ((data.get("message") or {}).get("items")) or []
    out: list[dict[str, Any]] = []
    for item in items[:limit]:
        titles = item.get("title") or []
        title = titles[0] if titles else ""
        authors: list[str] = []
        for a in item.get("author") or []:
            if not isinstance(a, dict):
                continue
            fam = (a.get("family") or "").strip()
            giv = (a.get("given") or "").strip()
            if fam and giv:
                authors.append(f"{giv} {fam}".strip())
            elif fam:
                authors.append(fam)
        year = None
        issued = item.get("issued") or {}
        dp = issued.get("date-parts")
        if isinstance(dp, list) and dp and isinstance(dp[0], list) and dp[0]:
            try:
                year = int(dp[0][0])
            except (TypeError, ValueError):
                year = None
        doi = item.get("DOI")
        abstract_raw = item.get("abstract")
        abstract = (
            _strip_jats_xml(abstract_raw) if isinstance(abstract_raw, str) else ""
        )
        cites = item.get("is-referenced-by-count")
        try:
            cited = int(cites) if cites is not None else 0
        except (TypeError, ValueError):
            cited = 0
        nd = _norm_doi(doi)
        url = f"https://doi.org/{nd}" if nd else f"https://api.crossref.org/works/{quote_plus(doi)}" if doi else ""
        container = (item.get("container-title") or [])
        journal = container[0] if container else None
        out.append(
            {
                "title": title,
                "authors": authors,
                "year": year,
                "doi": doi,
                "abstract": abstract,
                "cited_by_count": cited,
                "journal": journal,
                "url": url,
            },
        )
    return out


def dedupe_scholarly_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = _dedupe_key(r)
        c = int(r.get("cited_by_count") or 0)
        if key not in best or c > int(best[key].get("cited_by_count") or 0):
            best[key] = r
    return sorted(best.values(), key=lambda x: -int(x.get("cited_by_count") or 0))


async def scholarly_aggregate(
    query: str,
    per_source_limit: int = 5,
) -> dict[str, Any]:
    q = (query or "").strip()
    oa_raw, ss_raw, cr_raw = await asyncio.gather(
        search_openalex(q, per_source_limit),
        search_semantic_scholar(q, per_source_limit),
        search_crossref(q, per_source_limit),
    )
    tagged: list[dict[str, Any]] = []
    for r in oa_raw:
        tagged.append({**r, "source": "openalex"})
    for r in ss_raw:
        tagged.append({**r, "source": "semantic_scholar"})
    for r in cr_raw:
        tagged.append({**r, "source": "crossref"})
    merged = dedupe_scholarly_rows(tagged)
    return {
        "query": q,
        "results": merged,
        "confidence_tier": "academic",
        "sources_checked": ["openalex", "semantic_scholar", "crossref"],
    }


def academic_origin_candidates(
    oa_rows: list[dict[str, Any]],
    ss_rows: list[dict[str, Any]],
    cap: int = 5,
) -> list[dict[str, Any]]:
    """Map OpenAlex + Semantic Scholar rows to Ring 3 origin-style candidates."""
    tagged: list[dict[str, Any]] = []
    for r in oa_rows:
        tagged.append({**r, "source": "openalex"})
    for r in ss_rows:
        tagged.append({**r, "source": "semantic_scholar"})
    merged = dedupe_scholarly_rows(tagged)[:cap]
    out: list[dict[str, Any]] = []
    for r in merged:
        nd = _norm_doi(r.get("doi"))
        url = f"https://doi.org/{nd}" if nd else (r.get("url") or "")
        out.append(
            {
                "source_category": "academic",
                "title": r.get("title"),
                "year": r.get("year"),
                "cited_by_count": r.get("cited_by_count"),
                "doi": r.get("doi"),
                "url": url,
                "authors": r.get("authors"),
                "journal": r.get("journal"),
                "scholarly_source": r.get("source"),
            },
        )
    return out
