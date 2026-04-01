"""
Comparative coverage: GDELT waterfall → optional NewsAPI → explicit empty result.
Query terms come from article content; author/outlet terms are excluded from searches.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from gdelt_adapter import search_gdelt

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset(
    """
    a an the is are was were be been being have has had do does did will would could
    should may might shall can need dare ought used of in on at to for with by from up
    about into through during including until against among throughout despite towards
    upon concerning and but or nor so yet both either neither not only own same than
    too very just because as while although after before since unless however therefore
    thus hence
    """.split()
)

FAILURE_REASON = (
    "No comparative coverage found in GDELT or NewsAPI for this story. "
    "The investigation can still proceed but framing analysis will be limited."
)


def _tokens_from_text(text: str, limit: int = 5) -> list[str]:
    words = re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?", text or "")
    out: list[str] = []
    for w in words:
        lw = w.lower()
        if lw in _STOPWORDS or len(w) < 2:
            continue
        out.append(w)
        if len(out) >= limit:
            break
    return out


def _norm_key(s: str) -> str:
    return " ".join((s or "").lower().split())


def _entity_excluded_as_author_or_outlet(
    entity: str, author: str, publication: str
) -> bool:
    if not entity or len(entity.strip()) < 2:
        return True
    en = _norm_key(entity)
    if not en:
        return True
    if author:
        au = _norm_key(author)
        ew = set(re.findall(r"\w+", en))
        aw = set(re.findall(r"\w+", au))
        if ew and ew <= aw:
            return True
        if en in au or au in en:
            return True
    if publication:
        pn = _norm_key(publication)
        pub_parts = set(re.findall(r"\w+", pn)) | {pn}
        if en == pn or en in pub_parts:
            return True
        if pn and (en in pn or pn in en) and len(en) < 24:
            return True
    return False


def extract_query_terms(article: dict[str, Any]) -> dict[str, Any]:
    """
    Structured query terms from article content. Never uses author name as a GDELT search term.

    Expects optional keys on article: title, text, publication, author,
    named_entities (list[str]), article_topic (str).
    """
    title = (article.get("title") or "").strip()
    text = (article.get("text") or "").strip()
    author = (article.get("author") or "").strip()
    publication = (article.get("publication") or "").strip()
    raw_entities = article.get("named_entities") or []
    named_entities = [
        str(e).strip() for e in raw_entities if isinstance(e, str) and str(e).strip()
    ]
    topic = (article.get("article_topic") or "").strip()

    headline_keywords = _tokens_from_text(title, 5)
    if len(headline_keywords) < 3 and topic:
        headline_keywords = _tokens_from_text(topic, 5)
    if len(headline_keywords) < 3:
        headline_keywords = _tokens_from_text(text[:800], 5)

    # Core entities: frequency in first 500 words of body, headline overlap boosts.
    body_head = (text[:2500] or "").lower()
    title_lower = title.lower()
    scored: list[tuple[str, int]] = []
    for e in named_entities:
        if _entity_excluded_as_author_or_outlet(e, author, publication):
            continue
        el = e.lower()
        count = body_head.count(el)
        if el in title_lower:
            count += 100
        if count > 0 or el in title_lower:
            scored.append((e, count))

    scored.sort(key=lambda x: (-x[1], len(x[0])))
    core_entities = [e for e, _ in scored[:3]]

    quoted_phrases: list[str] = []
    for e in core_entities:
        et = e.strip()
        if " " in et and et.lower() in title_lower:
            quoted_phrases.append(f'"{et}"')

    subject_words = headline_keywords[:3] if headline_keywords else _tokens_from_text(topic, 3)
    subject_summary = " ".join(subject_words) if subject_words else ""

    return {
        "headline_keywords": headline_keywords,
        "core_entities": core_entities,
        "quoted_phrases": quoted_phrases,
        "subject_summary": subject_summary,
    }


def _gdelt_query_from_terms(terms: dict[str, Any], use_core: bool) -> str:
    if use_core:
        ce = terms.get("core_entities") or []
        if not ce:
            return ""
        return " ".join(ce[:2])[:400]
    hk = terms.get("headline_keywords") or []
    if hk:
        return " ".join(hk)[:400]
    ce = terms.get("core_entities") or []
    if ce:
        return " ".join(ce[:2])[:400]
    ss = (terms.get("subject_summary") or "").strip()
    return ss[:400] if ss else ""


def fetch_gdelt_coverage(terms: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """
    GDELT waterfall (sync httpx). Returns (articles, stage_label).
    """
    strategies: list[dict[str, Any]] = [
        {
            "query_fn": lambda: _gdelt_query_from_terms(terms, use_core=False),
            "timespan": "7d",
            "maxrecords": 50,
            "label": "headline_keywords_7d",
        },
        {
            "query_fn": lambda: _gdelt_query_from_terms(terms, use_core=False),
            "timespan": "30d",
            "maxrecords": 75,
            "label": "headline_keywords_30d",
        },
        {
            "query_fn": lambda: _gdelt_query_from_terms(terms, use_core=True),
            "timespan": "30d",
            "maxrecords": 75,
            "label": "core_entities_30d",
        },
        {
            "query_fn": lambda: _gdelt_query_from_terms(terms, use_core=True),
            "timespan": "90d",
            "maxrecords": 100,
            "label": "core_entities_90d",
        },
    ]

    active: list[dict[str, Any]] = []
    for s in strategies:
        q = (s["query_fn"]() or "").strip()
        if not q or len(q.split()) < 2:
            continue
        active.append({**s, "query": q})

    for stage in active:
        query = stage["query"]
        try:
            arts = search_gdelt(
                query=query,
                max_records=int(stage["maxrecords"]),
                timespan=stage["timespan"],
                log_empty=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("GDELT error on stage %s: %s", stage["label"], exc)
            continue
        if arts:
            logger.info(
                "[GDELT] Stage=%s | articles=%s | query=%r | timespan=%s",
                stage["label"],
                len(arts),
                query,
                stage["timespan"],
            )
            for a in arts:
                if isinstance(a, dict):
                    a["_gdelt_stage"] = stage["label"]
            return arts, stage["label"]
        logger.warning(
            "[GDELT] Stage=%s | articles=0 | query=%r | timespan=%s",
            stage["label"],
            query,
            stage["timespan"],
        )

    logger.warning(
        "[GDELT] All stages empty | headline_keywords=%s | core_entities=%s",
        terms.get("headline_keywords"),
        terms.get("core_entities"),
    )
    return [], None


def _newsapi_to_article_shape(raw: dict[str, Any]) -> dict[str, Any]:
    url = (raw.get("url") or "").strip()
    title = (raw.get("title") or "").strip()
    published = (raw.get("publishedAt") or "").strip()
    src = raw.get("source")
    outlet = ""
    if isinstance(src, dict):
        outlet = str(src.get("name") or "").strip()
    domain = outlet
    ecosystem = "unknown"
    seendate = published.replace("-", "").replace(":", "")[:15] if published else ""

    return {
        "url": url,
        "title": title,
        "outlet": outlet,
        "ecosystem": ecosystem,
        "published": published,
        "gdelt_seendate": seendate,
        "language": "English",
        "source_country": "",
        "tone": 0,
        "relevance_score": 3.0,
        "source": "newsapi",
        "domain": domain,
        "summary": "",
        "score": 3.0,
        "_source_adapter": "newsapi",
    }


def fetch_newsapi_coverage(terms: dict[str, Any]) -> list[dict[str, Any]]:
    key = (os.environ.get("NEWSAPI_KEY") or "").strip()
    if not key:
        logger.debug("[NEWSAPI] Skipped — NEWSAPI_KEY not set")
        return []

    queries: list[str] = []
    hk = " ".join(terms.get("headline_keywords") or [])
    ce = terms.get("core_entities") or []
    ce_q = " ".join(ce[:2]) if ce else ""
    for q in (hk, ce_q):
        q = (q or "").strip()
        if q and len(q.split()) >= 2:
            queries.append(q[:400])

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Frame/1.0; +https://frame-2yxu.onrender.com)",
    }
    for query in queries:
        try:
            resp = httpx.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "apiKey": key,
                    "language": "en",
                    "sortBy": "relevancy",
                    "pageSize": 50,
                },
                timeout=15.0,
                headers=headers,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            raw_articles = data.get("articles") or []
            if not raw_articles:
                logger.warning("[NEWSAPI] articles=0 | query=%r", query)
                continue
            normalized: list[dict[str, Any]] = []
            for a in raw_articles:
                if isinstance(a, dict):
                    row = _newsapi_to_article_shape(a)
                    if row.get("url", "").startswith("http"):
                        normalized.append(row)
            if normalized:
                logger.info("[NEWSAPI] articles=%s | query=%r", len(normalized), query)
                return normalized
            logger.warning("[NEWSAPI] articles=0 | query=%r", query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("NewsAPI error: %s", exc)
            continue
    return []


def format_coverage_for_prompt(coverage_result: dict, max_articles: int = 30) -> str:
    """
    Formats retrieved articles into a compact, LLM-readable string for prompt injection.
    Returns an empty string if coverage_found is False — callers must handle that case.
    """
    if not coverage_result.get("coverage_found"):
        return ""

    articles = coverage_result.get("articles", [])[:max_articles]
    if not articles:
        return ""

    lines = [
        f"Comparative coverage ({len(articles)} sources retrieved via "
        f"{coverage_result.get('source_adapter', 'unknown')}):\n"
    ]

    for i, a in enumerate(articles, 1):
        title = a.get("title") or a.get("url", "")
        domain = a.get("domain") or a.get("outlet") or "unknown outlet"
        raw_date = (
            (a.get("seendate") or a.get("gdelt_seendate") or "").strip()
        )
        pub = (a.get("published") or "").strip()
        date = raw_date[:10] if raw_date else (pub[:10] if pub else "")
        lang = a.get("language") or ""
        country = (a.get("sourcecountry") or a.get("source_country") or "").strip()

        meta_parts = [p for p in [domain, country, lang, date] if p]
        meta = " | ".join(meta_parts)
        lines.append(f"{i}. {title} ({meta})")

    return "\n".join(lines)


def coverage_result_for_receipt(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "coverage_found": result.get("coverage_found"),
        "source_adapter": result.get("source_adapter"),
        "gdelt_stage": result.get("gdelt_stage"),
        "failure_reason": result.get("failure_reason"),
        "comparative_article_count": len(result.get("articles") or []),
        "query_terms": result.get("query_terms"),
        "query_expansions": result.get("query_expansions") or [],
        "coverage_sparse": bool(result.get("coverage_sparse", False)),
    }


def suggest_query_expansions(
    terms: dict[str, Any] | None,
    article: dict[str, Any],
) -> list[str]:
    """
    When coverage is sparse, ask Claude for broader/adjacent search terms.
    Synchronous; safe to call from get_comparative_coverage.
    """
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return []
    topic = (
        str(article.get("article_topic") or article.get("title") or article.get("text") or "")[:2000]
    )
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        prompt = (
            f"Original search terms: {json.dumps(terms)}\n"
            f"Story topic: {topic}\n\n"
            "The comparative search returned fewer than 5 articles.\n"
            "Suggest 4 alternative search queries that might find related coverage:\n"
            "- Broader terms (remove specifics, keep core topic)\n"
            "- Synonyms\n"
            "- Adjacent topics\n"
            "- Non-English key terms if relevant\n\n"
            "Return JSON array of strings only. Each string is a 2-5 word query.\n"
            "JSON only, no markdown."
        )
        msg = client.messages.create(
            model=model,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (msg.content[0].text or "").strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.lstrip().startswith("json"):
                    text = text.lstrip()[4:].lstrip()
        out = json.loads(text.strip())
        return out[:4] if isinstance(out, list) else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[QUERY_EXPANSION] %s", exc)
        return []


def _finalize_coverage_result(
    result: dict[str, Any],
    terms: dict[str, Any],
    article: dict[str, Any],
) -> dict[str, Any]:
    articles = result.get("articles") or []
    n = len(articles)
    sparse = (not result.get("coverage_found")) or n < 5
    result["coverage_sparse"] = sparse
    result["query_expansions"] = suggest_query_expansions(terms, article) if sparse else []
    return result


def get_comparative_coverage(article: dict[str, Any]) -> dict[str, Any]:
    """
    Main entry: GDELT waterfall, then NewsAPI. Never raises.
    """
    terms = extract_query_terms(article)

    gdelt_articles, gdelt_stage = fetch_gdelt_coverage(terms)
    if gdelt_articles:
        return _finalize_coverage_result(
            {
                "articles": gdelt_articles,
                "source_adapter": "gdelt",
                "gdelt_stage": gdelt_stage,
                "coverage_found": True,
                "query_terms": terms,
                "failure_reason": None,
            },
            terms,
            article,
        )

    newsapi_articles = fetch_newsapi_coverage(terms)
    if newsapi_articles:
        return _finalize_coverage_result(
            {
                "articles": newsapi_articles,
                "source_adapter": "newsapi",
                "gdelt_stage": None,
                "coverage_found": True,
                "query_terms": terms,
                "failure_reason": None,
            },
            terms,
            article,
        )

    logger.error(
        "[COVERAGE] Total failure — no articles from any source "
        "| headline_keywords=%s | core_entities=%s | article_url=%s",
        terms.get("headline_keywords"),
        terms.get("core_entities"),
        article.get("url", "unknown"),
    )
    return _finalize_coverage_result(
        {
            "articles": [],
            "source_adapter": "none",
            "gdelt_stage": None,
            "coverage_found": False,
            "query_terms": terms,
            "failure_reason": FAILURE_REASON,
        },
        terms,
        article,
    )
