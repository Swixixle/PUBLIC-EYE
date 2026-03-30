"""
Natural language query engine.
Given a query, searches RSS feeds across global media ecosystems,
fetches matching articles, and returns structured results for synthesis.
"""

from __future__ import annotations

import concurrent.futures
import re
import time
from typing import Any

import feedparser
import httpx

from article_ingest import fetch_article
from rss_sources import RSS_FEEDS

QUERY_STOP_WORDS = {
    "tell",
    "me",
    "about",
    "what",
    "is",
    "are",
    "was",
    "were",
    "the",
    "a",
    "an",
    "and",
    "or",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "how",
    "why",
    "when",
    "who",
    "where",
    "happening",
    "going",
    "today",
    "now",
    "latest",
    "recent",
    "news",
    "story",
    "stories",
    "based",
    "currently",
}


def extract_keywords(query: str) -> list[str]:
    words = re.findall(r"[a-zA-Z']+", query.lower())
    keywords = [w for w in words if w not in QUERY_STOP_WORDS and len(w) > 2]
    seen: set[str] = set()
    result: list[str] = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result[:8]


def _entry_score_inputs(entry: Any) -> dict[str, Any]:
    return {
        "title": (entry.get("title") or "") if hasattr(entry, "get") else "",
        "summary": (entry.get("summary") or entry.get("description") or "") if hasattr(entry, "get") else "",
        "published_parsed": entry.get("published_parsed") if hasattr(entry, "get") else None,
    }


def score_entry(entry: dict[str, Any], keywords: list[str]) -> float:
    title = (entry.get("title") or "").lower()
    summary = (entry.get("summary") or "").lower()
    combined = title + " " + summary

    score = 0.0
    for kw in keywords:
        if kw in title:
            score += 3.0
        elif kw in combined:
            score += 1.0

    published = entry.get("published_parsed")
    if published:
        age_hours = (time.time() - time.mktime(published)) / 3600
        if age_hours < 6:
            score += 2.0
        elif age_hours < 24:
            score += 1.0
        elif age_hours < 48:
            score += 0.5

    return score


def fetch_feed(feed_meta: dict[str, Any], keywords: list[str], timeout: int = 10) -> list[dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Frame/1.0; +https://frame-2yxu.onrender.com)",
    }
    try:
        resp = httpx.get(feed_meta["url"], headers=headers, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
        results: list[dict[str, Any]] = []
        for entry in parsed.entries[:20]:
            ed = _entry_score_inputs(entry)
            sc = score_entry(ed, keywords)
            if sc > 0:
                link = entry.get("link", "") if hasattr(entry, "get") else ""
                results.append(
                    {
                        "title": entry.get("title", "") if hasattr(entry, "get") else "",
                        "url": link,
                        "outlet": feed_meta["outlet"],
                        "ecosystem": feed_meta["ecosystem"],
                        "summary": (entry.get("summary", "") or "")[:300] if hasattr(entry, "get") else "",
                        "published": entry.get("published", "") if hasattr(entry, "get") else "",
                        "score": sc,
                    }
                )
        return results
    except Exception:  # noqa: BLE001
        return []


def search_feeds(
    keywords: list[str],
    max_results: int = 8,
    ecosystems: list[str] | None = None,
) -> list[dict[str, Any]]:
    feeds_to_search = RSS_FEEDS
    if ecosystems:
        feeds_to_search = [f for f in RSS_FEEDS if f["ecosystem"] in ecosystems]

    all_results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_feed, feed, keywords): feed for feed in feeds_to_search}
        for future in concurrent.futures.as_completed(futures, timeout=45):
            try:
                all_results.extend(future.result())
            except Exception:  # noqa: BLE001
                continue

    all_results.sort(key=lambda x: x["score"], reverse=True)

    seen_outlets: set[str] = set()
    diverse_results: list[dict[str, Any]] = []
    for r in all_results:
        if r["outlet"] not in seen_outlets:
            seen_outlets.add(r["outlet"])
            diverse_results.append(r)
        if len(diverse_results) >= max_results:
            break

    return diverse_results


def fetch_articles_parallel(urls: list[str], timeout: int = 15) -> list[dict[str, Any]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_article, url, timeout): url for url in urls}
        results: list[dict[str, Any]] = []
        for future in concurrent.futures.as_completed(futures, timeout=60):
            try:
                result = future.result()
                if not result.get("fetch_error") and result.get("text"):
                    results.append(result)
            except Exception:  # noqa: BLE001
                continue
    return results


def run_query(query: str, max_sources: int = 8) -> dict[str, Any]:
    q = (query or "").strip()
    keywords = extract_keywords(q)
    if not keywords:
        return {
            "query": q,
            "keywords": [],
            "articles": [],
            "error": "Could not extract search keywords from query",
        }

    feed_results = search_feeds(keywords, max_results=max_sources)

    if not feed_results:
        return {
            "query": q,
            "keywords": keywords,
            "articles": [],
            "sources_searched": len(RSS_FEEDS),
            "error": "No matching articles found across sources. "
            "Try a more specific query or paste a URL directly.",
        }

    urls = [r["url"] for r in feed_results if r.get("url")]
    fetched = fetch_articles_parallel(urls[:6])

    url_to_fetch = {f["url"]: f for f in fetched}
    articles: list[dict[str, Any]] = []
    for feed_result in feed_results:
        url = feed_result.get("url", "")
        fetched_data = url_to_fetch.get(url, {})
        articles.append(
            {
                "url": url,
                "title": fetched_data.get("title") or feed_result.get("title"),
                "outlet": feed_result["outlet"],
                "ecosystem": feed_result["ecosystem"],
                "publication": feed_result["outlet"],
                "text": fetched_data.get("text", ""),
                "word_count": fetched_data.get("word_count", 0),
                "summary": feed_result.get("summary", ""),
                "published": feed_result.get("published", ""),
                "relevance_score": feed_result["score"],
                "fetch_success": bool(fetched_data.get("text")),
            }
        )

    return {
        "query": q,
        "keywords": keywords,
        "sources_searched": len(RSS_FEEDS),
        "articles": articles,
        "ecosystems_covered": list({a["ecosystem"] for a in articles}),
    }
