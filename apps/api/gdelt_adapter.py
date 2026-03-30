"""
GDELT adapter — searches the GDELT 2.0 Doc API for news articles.
Free, no API key required.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

# Map GDELT sourcecountry to Frame ecosystem (approximate; GDELT uses varied country codes)
ECOSYSTEM_COUNTRIES: dict[str, list[str]] = {
    "western_anglophone": ["US", "GB", "UK", "AU", "CA", "NZ", "IE"],
    "russian_state": ["RU", "RS"],
    "chinese_state": ["CH", "CN"],
    "arab_gulf": ["QA", "AE", "SA", "EG", "KW", "BH"],
    "israeli": ["IS", "ISR"],
    "south_asian": ["PK", "IN", "BD", "LK"],
    "european": ["DE", "FR", "ES", "IT", "NL", "PL", "SE", "NO"],
    "iranian_regional": ["IR"],
}


def gdelt_timestring(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S")


def search_gdelt(
    query: str,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    max_records: int = 25,
    mode: str = "artlist",
    timespan: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {
        "query": query,
        "mode": mode,
        "maxrecords": str(max_records),
        "format": "json",
        "sort": "DateDesc",
    }

    if start_dt and end_dt:
        params["startdatetime"] = gdelt_timestring(start_dt)
        params["enddatetime"] = gdelt_timestring(end_dt)
    elif timespan:
        params["timespan"] = timespan

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Frame/1.0; +https://frame-2yxu.onrender.com)",
    }

    try:
        resp = httpx.get(
            GDELT_DOC_API,
            params=params,
            headers=headers,
            timeout=30,
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.TimeoutException, httpx.HTTPError, ValueError):
        return []

    articles = data.get("articles") or data.get("article") or []
    if not isinstance(articles, list):
        articles = []

    if not articles:
        logging.warning("GDELT returned 0 articles. URL: %s", getattr(resp, "url", ""))

    results: list[dict[str, Any]] = []
    for a in articles:
        if not isinstance(a, dict):
            continue
        url = a.get("url", "")
        if not url:
            continue

        source_country = (a.get("sourcecountry") or a.get("country") or "").strip()
        ecosystem = "unknown"
        for eco, countries in ECOSYSTEM_COUNTRIES.items():
            if source_country in countries:
                ecosystem = eco
                break

        seendate = a.get("seendate", "") or ""
        published = ""
        dt_utc: datetime | None = None
        if seendate:
            for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S"):
                try:
                    dt_utc = datetime.strptime(seendate, fmt).replace(tzinfo=timezone.utc)
                    published = dt_utc.strftime("%a, %d %b %Y %H:%M:%S +0000")
                    break
                except ValueError:
                    continue
            if not published:
                published = seendate

        results.append(
            {
                "url": url,
                "title": a.get("title", ""),
                "outlet": a.get("domain", "") or a.get("source", ""),
                "ecosystem": ecosystem,
                "published": published,
                "gdelt_seendate": seendate,
                "_sort_dt": dt_utc,
                "language": a.get("language", ""),
                "source_country": source_country,
                "tone": a.get("tone", 0),
                "relevance_score": 3.0,
                "source": "gdelt",
                "summary": "",
                "score": 3.0,
            }
        )

    return results


def search_gdelt_timeline(
    query: str,
    start_dt: datetime,
    end_dt: datetime,
    max_records: int = 75,
) -> dict[str, Any]:
    articles = search_gdelt(
        query=query,
        start_dt=start_dt,
        end_dt=end_dt,
        max_records=max_records,
    )

    if not articles:
        return {
            "articles": [],
            "timeline_groups": [],
            "total": 0,
            "date_range_label": f"{start_dt.strftime('%B %d')} – {end_dt.strftime('%B %d, %Y')}",
        }

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in articles:
        dt = a.get("_sort_dt")
        if dt is not None:
            iso_key = dt.strftime("%Y-%W")
            week_label = f"Week of {dt.strftime('%B %d, %Y')}"
        else:
            raw = a.get("gdelt_seendate", "") or a.get("published", "")
            week_label = raw[:16] if raw else "Unknown date"
            iso_key = week_label
        groups[f"{iso_key}|{week_label}"].append(a)

    timeline_groups: list[dict[str, Any]] = []
    for key in sorted(groups.keys()):
        _iso, week = key.split("|", 1) if "|" in key else ("", key)
        arts = groups[key]
        timeline_groups.append({"week": week, "articles": arts, "count": len(arts)})

    for a in articles:
        a.pop("_sort_dt", None)

    return {
        "articles": articles,
        "timeline_groups": timeline_groups,
        "total": len(articles),
        "date_range_label": f"{start_dt.strftime('%B %d')} – {end_dt.strftime('%B %d, %Y')}",
    }


def deduplicate_by_ecosystem(
    articles: list[dict[str, Any]],
    max_per_ecosystem: int = 2,
    total_max: int = 10,
) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    result: list[dict[str, Any]] = []

    for a in articles:
        eco = a.get("ecosystem", "unknown")
        if counts[eco] < max_per_ecosystem:
            counts[eco] += 1
            result.append(a)
        if len(result) >= total_max:
            break

    return result
