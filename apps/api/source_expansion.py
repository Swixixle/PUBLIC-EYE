"""
Fetch additional real articles on the same story so coalition alignment notes
can cite actual coverage (Sprint 1B.0).

Called from analyze-article after claim extraction; non-fatal on failure.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from article_ingest import fetch_article
from gdelt_adapter import search_gdelt

logger = logging.getLogger(__name__)

MAX_SOURCES_DEFAULT = 12
_CANDIDATE_MULTIPLIER = 4


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    try:
        p = urlparse(u)
        if not p.netloc:
            return u.lower()
        path = (p.path or "/").rstrip("/") or "/"
        return urlunparse(
            (
                (p.scheme or "https").lower(),
                p.netloc.lower(),
                path,
                "",
                p.query,
                "",
            )
        )
    except Exception:  # noqa: BLE001
        return u.lower()


def _build_queries(topic: str, entities: list[str]) -> list[str]:
    # Use short keyword form — GDELT needs keywords not full sentences
    topic_words = " ".join(topic.split()[:4])

    queries = []
    top_entities = [e for e in entities[:4] if len(e) > 2]

    queries.append(topic_words)
    if top_entities:
        second = top_entities[1] if len(top_entities) > 1 else topic_words
        queries.append(f"{top_entities[0]} {second}")
    if len(top_entities) > 1:
        queries.append(f"{top_entities[0]} {top_entities[1]}")
    if top_entities:
        queries.append(f"{top_entities[0]} local impact")
        queries.append(f"{top_entities[0]} regional news")

    return queries[:5]


def _search_urls_newsapi(query: str, cap: int) -> list[str]:
    key = (os.environ.get("NEWSAPI_KEY") or "").strip()
    if not key:
        return []
    urls: list[str] = []
    try:
        resp = httpx.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "sortBy": "relevancy",
                "pageSize": min(8, cap),
                "language": "en",
                "apiKey": key,
            },
            timeout=15.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Frame/1.0; +https://frame-2yxu.onrender.com)",
            },
        )
        if resp.status_code != 200:
            return []
        for a in resp.json().get("articles") or []:
            if not isinstance(a, dict):
                continue
            u = a.get("url")
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u.strip())
            if len(urls) >= cap:
                break
    except Exception as exc:  # noqa: BLE001
        logger.warning("NewsAPI search failed: %s", exc)
    return urls


def _search_urls_gdelt(query: str, cap: int) -> list[str]:
    urls: list[str] = []
    try:
        articles = search_gdelt(
            query=query[:400],
            max_records=min(50, max(20, cap + 8)),
            timespan="7d",
        )
        for a in articles:
            if not isinstance(a, dict):
                continue
            u = a.get("url")
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u.strip())
            if len(urls) >= cap:
                break
    except Exception as exc:  # noqa: BLE001
        logger.warning("GDELT search failed: %s", exc)
    return urls


def _search_urls(query: str, cap: int) -> list[str]:
    found = _search_urls_newsapi(query, cap)
    if not found:
        found = _search_urls_gdelt(query, cap)
    return found


def _fetch_source_row(url: str) -> dict[str, Any] | None:
    try:
        result = fetch_article(url, timeout=20)
        if result.get("fetch_error"):
            return None
        text = (result.get("text") or "").strip()
        if not text or len(text) < 80:
            return None
        snippet = text[:800].strip()
        return {
            "title": result.get("title") or "",
            "outlet": result.get("publication") or "",
            "publication": result.get("publication") or "",
            "url": result.get("url") or url,
            "date": "",
            "snippet": snippet,
            "fetched": True,
            "source": "source_expansion",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch expansion URL %s: %s", url[:80], exc)
        return None


def expand_sources(
    topic: str,
    entities: list[str],
    existing_url: str,
    max_sources: int = MAX_SOURCES_DEFAULT,
) -> list[dict[str, Any]]:
    topic_clean = (topic or "").strip()
    if not topic_clean:
        return []

    existing_n = _normalize_url(existing_url)
    seen: set[str] = set()
    if existing_n:
        seen.add(existing_n)

    queries = _build_queries(topic_clean, list(entities or []))
    candidate_urls: list[str] = []
    budget = max_sources * _CANDIDATE_MULTIPLIER

    for q in queries:
        if not q or len(candidate_urls) >= budget:
            break
        for u in _search_urls(q, cap=budget):
            n = _normalize_url(u)
            if not n or n in seen:
                continue
            seen.add(n)
            candidate_urls.append(u)
            if len(candidate_urls) >= budget:
                break

    if not candidate_urls:
        logger.info(
            "source_expansion: no URL candidates for topic=%r", topic_clean[:80]
        )
        return []

    out: list[dict[str, Any]] = []
    for u in candidate_urls:
        if len(out) >= max_sources:
            break
        row = _fetch_source_row(u)
        if row:
            out.append(row)

    logger.info(
        "source_expansion: kept %d sources (candidates=%d) topic=%r",
        len(out),
        len(candidate_urls),
        topic_clean[:80],
    )
    return out
