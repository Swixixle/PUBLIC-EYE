"""
Natural language query engine.
Classifies the query, routes to RSS (current) or GDELT (historical / timeline),
fetches articles, and returns structured results for synthesis.
"""

from __future__ import annotations

import concurrent.futures
import re
import time
from datetime import timedelta
from typing import Any

import feedparser
import httpx

from article_ingest import fetch_article
from gdelt_adapter import deduplicate_by_ecosystem, search_gdelt, search_gdelt_timeline
from query_classifier import classify_query
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


def _public_classification(classification: dict[str, Any]) -> dict[str, Any]:
    dr = classification.get("date_range")
    return {
        "source": classification["source"],
        "search_terms": classification["search_terms"],
        "entity": classification.get("entity"),
        "date_range": (
            {"label": dr["label"], "type": dr["type"]} if dr else None
        ),
        "gdelt_timespan": classification.get("gdelt_timespan"),
    }


def _attach_fetched_bodies(articles: list[dict[str, Any]], max_fetch: int = 6) -> None:
    if not articles:
        return
    urls = [a["url"] for a in articles[:max_fetch] if a.get("url")]
    fetched = fetch_articles_parallel(urls)
    url_to_fetch = {f["url"]: f for f in fetched}
    for a in articles:
        fd = url_to_fetch.get(a.get("url", ""), {})
        a["text"] = fd.get("text", a.get("text", ""))
        a["word_count"] = fd.get("word_count", a.get("word_count", 0))
        a["fetch_success"] = bool(fd.get("text"))
        if fd.get("title") and not a.get("title"):
            a["title"] = fd["title"]
        a["publication"] = a.get("outlet", a.get("publication", ""))


def run_query(query: str, max_sources: int = 8) -> dict[str, Any]:
    q = (query or "").strip()
    classification = classify_query(q)
    source = classification["source"]
    search_terms = list(classification["search_terms"])
    if not search_terms:
        search_terms = extract_keywords(q)[:8]
    if not search_terms:
        search_terms = [w for w in re.findall(r"[a-zA-Z']+", q.lower()) if len(w) > 2][:5]
    entity = classification["entity"]
    date_range = classification["date_range"]
    query_type = classification["type"]

    if entity:
        gdelt_query = f'"{entity}"'
        if search_terms:
            extra = [t for t in search_terms if t.lower() not in entity.lower().split()]
            if extra:
                gdelt_query += " " + " ".join(extra[:3])
    else:
        gdelt_query = " ".join(search_terms[:5]) if search_terms else q[:200]

    articles: list[dict[str, Any]] = []
    timeline_data: list[dict[str, Any]] | None = None
    error: str | None = None
    classification_date_label_suffix = ""

    if source == "gdelt_timeline" and date_range:
        tl = search_gdelt_timeline(
            query=gdelt_query or q,
            start_dt=date_range["start"],
            end_dt=date_range["end"],
            max_records=75,
        )
        articles = deduplicate_by_ecosystem(tl["articles"], max_per_ecosystem=3, total_max=12)
        timeline_data = tl["timeline_groups"]
        _attach_fetched_bodies(articles, max_fetch=6)

    elif source == "gdelt" and date_range:
        raw = search_gdelt(
            query=gdelt_query or q,
            start_dt=date_range["start"],
            end_dt=date_range["end"],
            max_records=25,
        )
        articles = deduplicate_by_ecosystem(raw, max_per_ecosystem=2, total_max=max_sources)
        _attach_fetched_bodies(articles, max_fetch=6)
        if not articles:
            wider_start = date_range["start"] - timedelta(days=3)
            wider_end = date_range["end"] + timedelta(days=3)
            raw = search_gdelt(
                query=gdelt_query or q,
                start_dt=wider_start,
                end_dt=wider_end,
                max_records=25,
            )
            articles = deduplicate_by_ecosystem(raw, max_per_ecosystem=2, total_max=max_sources)
            if articles:
                classification_date_label_suffix = " (±3 days)"
            _attach_fetched_bodies(articles, max_fetch=6)

    else:
        keywords = search_terms if search_terms else extract_keywords(q)
        if not keywords:
            keywords = [gdelt_query] if gdelt_query else [q[:80]]
        feed_results = search_feeds(keywords, max_results=max_sources)

        if not feed_results:
            raw = search_gdelt(
                query=gdelt_query or " ".join(keywords[:3]) or q[:200],
                timespan=classification.get("gdelt_timespan") or "7d",
                max_records=20,
            )
            feed_results = deduplicate_by_ecosystem(
                raw, max_per_ecosystem=2, total_max=max_sources
            )

        if not feed_results:
            error = (
                "No matching articles found. "
                "Try a more specific query or paste a URL directly."
            )
        else:
            urls = [r["url"] for r in feed_results if r.get("url")]
            fetched = fetch_articles_parallel(urls[:6])
            url_to_fetch = {f["url"]: f for f in fetched}
            for r in feed_results:
                url = r.get("url", "")
                fetched_data = url_to_fetch.get(url, {})
                articles.append(
                    {
                        "url": url,
                        "title": fetched_data.get("title") or r.get("title"),
                        "outlet": r.get("outlet", r.get("domain", "")),
                        "ecosystem": r.get("ecosystem", "unknown"),
                        "publication": r.get("outlet", ""),
                        "text": fetched_data.get("text", ""),
                        "word_count": fetched_data.get("word_count", 0),
                        "summary": r.get("summary", ""),
                        "published": r.get("published", ""),
                        "relevance_score": r.get("relevance_score", r.get("score", 0)),
                        "fetch_success": bool(fetched_data.get("text")),
                        "source": r.get("source", "rss"),
                        "source_country": r.get("source_country"),
                    }
                )

    sources_searched: int | str = (
        len(RSS_FEEDS) if classification["source"] == "rss" else "GDELT"
    )

    pub_classification = _public_classification(classification)
    if classification_date_label_suffix and pub_classification.get("date_range"):
        dr = pub_classification["date_range"]
        pub_classification = {
            **pub_classification,
            "date_range": {
                **dr,
                "label": dr["label"] + classification_date_label_suffix,
            },
        }

    return {
        "query": q,
        "query_type": query_type,
        "classification": pub_classification,
        "keywords": search_terms,
        "sources_searched": sources_searched,
        "articles": articles,
        "timeline": timeline_data,
        "ecosystems_covered": list({a.get("ecosystem", "unknown") for a in articles}),
        "error": error,
    }
