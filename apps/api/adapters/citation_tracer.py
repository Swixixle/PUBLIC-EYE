"""
Citation chain tracer — recursively follows citations from a URL toward primary sources.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import anthropic
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# --- Schemas -----------------------------------------------------------------


class CitationNode(BaseModel):
    depth: int
    url: str
    fetched_at: str  # ISO timestamp
    content_hash: str  # SHA-256 of page content at fetch time
    support_status: Literal["supports", "contradicts", "unrelated", "unverifiable"]
    support_confidence: float  # 0.0 - 1.0
    termination_type: str | None = None
    termination_reason: str | None = None
    origin_entity: str | None = None
    cited_sources: list[str] = Field(default_factory=list)
    page_title: str | None = None
    page_snippet: str


class CitationChain(BaseModel):
    claim_text: str
    initial_url: str
    nodes: list[CitationNode]
    terminal_node: CitationNode
    chain_depth: int
    origin_type: Literal[
        "primary_source",
        "named_assertion",
        "dead_end",
        "paywall",
        "loop",
        "max_depth",
    ]
    origin_label: str
    verified: bool
    chain_hash: str


TERMINATION_PRIMARY = "primary_source"
TERMINATION_NAMED = "named_assertion"
TERMINATION_DEAD = "dead_end"
TERMINATION_PAYWALL = "paywall"
TERMINATION_LOOP = "loop"
TERMINATION_MAX = "max_depth"

_PAYWALL_HINTS = re.compile(
    r"(subscribe|subscription required|paywall|members only|premium content|"
    r"sign in to read|login to continue|this article is for subscribers)",
    re.I,
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def _normalize_urls(base_url: str, raw: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        u = item.strip()
        if not u.startswith(("http://", "https://")):
            u = urljoin(base_url, u)
        try:
            parsed = urlparse(u)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                if u not in seen:
                    seen.add(u)
                    out.append(u)
        except Exception:  # noqa: BLE001
            continue
    return out


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
    raw = raw.strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


class CitationTracer:
    """Traces citation provenance from an initial URL for a factual claim."""

    def __init__(self) -> None:
        self._sonnet_model = os.environ.get(
            "CLAUDE_SONNET_MODEL", "claude-sonnet-4-20250514"
        )

    async def trace(
        self, claim_text: str, cited_url: str, max_depth: int = 4
    ) -> CitationChain:
        visited: set[str] = set()
        nodes: list[CitationNode] = []

        async def walk(url: str, depth: int) -> None:
            if url in visited:
                nodes.append(
                    self._terminal_node(
                        url=url,
                        depth=depth,
                        content="",
                        content_hash=_sha256_text(""),
                        support_status="unverifiable",
                        support_confidence=0.0,
                        cited_sources=[],
                        page_title=None,
                        page_snippet="",
                        term=TERMINATION_LOOP,
                        term_reason="URL already visited in this chain",
                    )
                )
                return
            if depth > max_depth:
                nodes.append(
                    self._terminal_node(
                        url=url,
                        depth=depth,
                        content="",
                        content_hash=_sha256_text(""),
                        support_status="unverifiable",
                        support_confidence=0.0,
                        cited_sources=[],
                        page_title=None,
                        page_snippet="",
                        term=TERMINATION_MAX,
                        term_reason="Maximum depth reached before resolution",
                    )
                )
                return

            visited.add(url)
            fetch = await self._fetch_page(url)
            if fetch["kind"] != "ok":
                nodes.append(
                    self._terminal_node(
                        url=url,
                        depth=depth,
                        content="",
                        content_hash=_sha256_text(""),
                        support_status="unverifiable",
                        support_confidence=0.0,
                        cited_sources=[],
                        page_title=None,
                        page_snippet=fetch.get("message", "")[:300],
                        term=fetch["term"],
                        term_reason=fetch.get("reason", ""),
                    )
                )
                return

            content = fetch["content"]
            content_hash = _sha256_text(content)
            analysis = await self._analyze_with_claude(
                claim_text=claim_text,
                page_url=url,
                page_text=content,
            )

            support_status = self._coerce_support_status(
                analysis.get("support_status")
            )
            support_confidence = self._coerce_confidence(
                analysis.get("support_confidence")
            )
            cited_urls = _normalize_urls(
                url, analysis.get("cited_urls") if isinstance(analysis.get("cited_urls"), list) else []
            )
            page_title = analysis.get("page_title")
            if page_title is not None:
                page_title = str(page_title)[:500]
            snippet = str(analysis.get("relevant_snippet") or "")[:300]
            is_primary = bool(analysis.get("is_primary_source"))
            is_named = bool(analysis.get("is_named_assertion"))
            asserting_entity = analysis.get("asserting_entity")
            if asserting_entity is not None:
                asserting_entity = str(asserting_entity).strip() or None

            if is_primary:
                nodes.append(
                    CitationNode(
                        depth=depth,
                        url=url,
                        fetched_at=_utc_iso(),
                        content_hash=content_hash,
                        support_status=support_status,
                        support_confidence=support_confidence,
                        termination_type=TERMINATION_PRIMARY,
                        termination_reason="Identified as primary source material",
                        origin_entity=None,
                        cited_sources=cited_urls,
                        page_title=page_title,
                        page_snippet=snippet or content[:300],
                    )
                )
                return

            if is_named:
                nodes.append(
                    CitationNode(
                        depth=depth,
                        url=url,
                        fetched_at=_utc_iso(),
                        content_hash=content_hash,
                        support_status=support_status,
                        support_confidence=support_confidence,
                        termination_type=TERMINATION_NAMED,
                        termination_reason="Named assertion without further citation",
                        origin_entity=asserting_entity,
                        cited_sources=cited_urls,
                        page_title=page_title,
                        page_snippet=snippet or content[:300],
                    )
                )
                return

            if not cited_urls:
                nodes.append(
                    CitationNode(
                        depth=depth,
                        url=url,
                        fetched_at=_utc_iso(),
                        content_hash=content_hash,
                        support_status=support_status,
                        support_confidence=support_confidence,
                        termination_type=TERMINATION_DEAD,
                        termination_reason="No outbound citations found on page",
                        origin_entity=None,
                        cited_sources=[],
                        page_title=page_title,
                        page_snippet=snippet or content[:300],
                    )
                )
                return

            nodes.append(
                CitationNode(
                    depth=depth,
                    url=url,
                    fetched_at=_utc_iso(),
                    content_hash=content_hash,
                    support_status=support_status,
                    support_confidence=support_confidence,
                    termination_type=None,
                    termination_reason=None,
                    origin_entity=None,
                    cited_sources=cited_urls,
                    page_title=page_title,
                    page_snippet=snippet or content[:300],
                )
            )
            await walk(cited_urls[0], depth + 1)

        await walk(cited_url, 0)

        if not nodes:
            placeholder = self._terminal_node(
                url=cited_url,
                depth=0,
                content="",
                content_hash=_sha256_text(""),
                support_status="unverifiable",
                support_confidence=0.0,
                cited_sources=[],
                page_title=None,
                page_snippet="",
                term=TERMINATION_DEAD,
                term_reason="No nodes produced",
            )
            nodes = [placeholder]

        terminal = nodes[-1]
        origin_type = self._origin_type_from_terminal(terminal)
        origin_label = self._build_origin_label(terminal)
        verified = (
            terminal.support_status == "supports"
            and terminal.support_confidence >= 0.5
            and origin_type in (TERMINATION_PRIMARY, TERMINATION_NAMED)
        )
        chain_hash = hashlib.sha256(
            json.dumps(
                [n.model_dump(mode="json") for n in nodes],
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        return CitationChain(
            claim_text=claim_text,
            initial_url=cited_url,
            nodes=nodes,
            terminal_node=terminal,
            chain_depth=terminal.depth,
            origin_type=origin_type,
            origin_label=origin_label,
            verified=verified,
            chain_hash=chain_hash,
        )

    def _terminal_node(
        self,
        *,
        url: str,
        depth: int,
        content: str,
        content_hash: str,
        support_status: Literal[
            "supports", "contradicts", "unrelated", "unverifiable"
        ],
        support_confidence: float,
        cited_sources: list[str],
        page_title: str | None,
        page_snippet: str,
        term: str,
        term_reason: str,
    ) -> CitationNode:
        return CitationNode(
            depth=depth,
            url=url,
            fetched_at=_utc_iso(),
            content_hash=content_hash,
            support_status=support_status,
            support_confidence=support_confidence,
            termination_type=term,
            termination_reason=term_reason,
            origin_entity=None,
            cited_sources=cited_sources,
            page_title=page_title,
            page_snippet=page_snippet or content[:300],
        )

    async def _fetch_page(self, url: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "Frame-CitationTracer/1.0 (+https://getframe.dev)"},
            ) as client:
                response = await client.get(url)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
            return {
                "kind": "error",
                "term": TERMINATION_DEAD,
                "reason": f"Network failure: {e!s}",
                "message": str(e)[:300],
            }

        status = response.status_code
        if status in (404, 410):
            return {
                "kind": "error",
                "term": TERMINATION_DEAD,
                "reason": f"HTTP {status}",
                "message": response.text[:300],
            }
        if status in (401, 402, 403):
            return {
                "kind": "error",
                "term": TERMINATION_PAYWALL,
                "reason": f"HTTP {status} (access restricted)",
                "message": response.text[:300],
            }
        if status >= 400:
            return {
                "kind": "error",
                "term": TERMINATION_DEAD,
                "reason": f"HTTP {status}",
                "message": response.text[:300],
            }

        text = response.text
        if len(text) > 400_000:
            text = text[:400_000] + "\n[… truncated …]"
        if _PAYWALL_HINTS.search(text[:8000]):
            return {
                "kind": "error",
                "term": TERMINATION_PAYWALL,
                "reason": "Paywall or subscription pattern detected in body",
                "message": text[:300],
            }

        return {"kind": "ok", "content": text}

    async def _analyze_with_claude(
        self,
        *,
        claim_text: str,
        page_url: str,
        page_text: str,
    ) -> dict[str, Any]:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        bounded = page_text if len(page_text) <= 48_000 else page_text[:48_000] + "\n[… truncated …]"
        if not key:
            logger.warning("ANTHROPIC_API_KEY missing; citation analysis degraded")
            return {
                "support_status": "unverifiable",
                "support_confidence": 0.0,
                "is_primary_source": False,
                "primary_source_type": None,
                "is_named_assertion": False,
                "asserting_entity": None,
                "cited_urls": [],
                "page_title": None,
                "relevant_snippet": bounded[:300],
            }

        prompt = f"""You are assisting with citation provenance for fact-checking.

Claim to evaluate (may or may not appear verbatim on the page):
{claim_text}

Page URL: {page_url}

Page text (may be HTML-stripped or raw):
{bounded}

Return ONLY valid JSON with this exact shape (no markdown):
{{
  "support_status": "supports|contradicts|unrelated|unverifiable",
  "support_confidence": 0.0,
  "is_primary_source": false,
  "primary_source_type": "government_document|court_filing|dataset|video|audio|null",
  "is_named_assertion": false,
  "asserting_entity": null,
  "cited_urls": ["list of absolute or relative URLs cited on this page as sources"],
  "page_title": "short title if inferable from text",
  "relevant_snippet": "most relevant ~300 characters regarding the claim"
}}

Rules:
- is_primary_source: true for raw government data, court filings, academic papers, official datasets, or direct links to video/audio of the event.
- is_named_assertion: true when a person or organization is clearly making a claim and no source links are offered.
- cited_urls: extract href-like URLs from the page; prefer primary sources. Empty list if none.
- If uncertain, use unverifiable and low confidence.
"""

        client = anthropic.AsyncAnthropic(api_key=key)
        try:
            msg = await client.messages.create(
                model=self._sonnet_model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(
                getattr(b, "text", "") or "" for b in msg.content if getattr(b, "text", None)
            )
            return _extract_json_object(text)
        except Exception as e:  # noqa: BLE001
            logger.warning("Claude citation analysis failed: %s", e)
            return {
                "support_status": "unverifiable",
                "support_confidence": 0.0,
                "is_primary_source": False,
                "primary_source_type": None,
                "is_named_assertion": False,
                "asserting_entity": None,
                "cited_urls": [],
                "page_title": None,
                "relevant_snippet": bounded[:300],
            }

    @staticmethod
    def _coerce_support_status(raw: Any) -> Literal[
        "supports", "contradicts", "unrelated", "unverifiable"
    ]:
        s = str(raw or "").strip().lower()
        if s in ("supports", "contradicts", "unrelated", "unverifiable"):
            return s  # type: ignore[return-value]
        return "unverifiable"

    @staticmethod
    def _coerce_confidence(raw: Any) -> float:
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, v))

    @staticmethod
    def _origin_type_from_terminal(node: CitationNode) -> Literal[
        "primary_source",
        "named_assertion",
        "dead_end",
        "paywall",
        "loop",
        "max_depth",
    ]:
        t = node.termination_type or TERMINATION_DEAD
        if t in (
            TERMINATION_PRIMARY,
            TERMINATION_NAMED,
            TERMINATION_DEAD,
            TERMINATION_PAYWALL,
            TERMINATION_LOOP,
            TERMINATION_MAX,
        ):
            return t  # type: ignore[return-value]
        return "dead_end"

    @staticmethod
    def _build_origin_label(node: CitationNode) -> str:
        tt = node.termination_type or "unknown"
        if tt == TERMINATION_PRIMARY:
            parts = ["Primary source"]
            if node.page_title:
                parts.append(node.page_title)
            return ", ".join(parts)
        if tt == TERMINATION_NAMED and node.origin_entity:
            return f"Named assertion: {node.origin_entity}"
        if tt == TERMINATION_NAMED:
            return "Named assertion (entity not identified)"
        if tt == TERMINATION_PAYWALL:
            return "Paywall or restricted content"
        if tt == TERMINATION_LOOP:
            return "Citation loop detected"
        if tt == TERMINATION_MAX:
            return "Stopped at maximum depth"
        if tt == TERMINATION_DEAD:
            return node.termination_reason or "Dead end"
        return tt


_URL_PATTERN = re.compile(r"https?://\S+")


_TRAILING_URL_CHARS = frozenset('),.;]}>\"\'')  # strip from regex-captured URL tail


def _strip_trailing_url_punctuation(url: str) -> str:
    u = url
    while u and u[-1] in _TRAILING_URL_CHARS:
        u = u[:-1]
    return u


def _first_http_url_in_text(text: str) -> str | None:
    m = _URL_PATTERN.search(text)
    if not m:
        return None
    return _strip_trailing_url_punctuation(m.group(0))


def _normalize_http_url_candidate(u: object) -> str | None:
    if u is None:
        return None
    s = str(u).strip()
    if not s.startswith(("http://", "https://")):
        return None
    return _strip_trailing_url_punctuation(s)


def _http_url_from_source_entry(entry: object) -> str | None:
    if isinstance(entry, dict):
        return _normalize_http_url_candidate(
            entry.get("url") or entry.get("href")
        )
    if isinstance(entry, str):
        return _normalize_http_url_candidate(entry)
    return None


def _http_url_from_source_list(entries: list[Any]) -> str | None:
    if not entries:
        return None
    return _http_url_from_source_entry(entries[0])


def _citation_start_url(claim: dict[str, Any]) -> str | None:
    """
    Prefer structured primary/source URLs (Sonnet extraction), then any http(s) in text.
    Field names mirror extracted claim dicts (`primary_sources`); `sources` / `source_urls`
    accepted as alternates.
    """
    for key in ("primary_sources", "sources", "source_urls"):
        raw = claim.get(key)
        if not isinstance(raw, list) or not raw:
            continue
        u = _http_url_from_source_list(raw)
        if u:
            return u
    stmt = str(claim.get("text") or claim.get("statement") or "").strip()
    return _first_http_url_in_text(stmt)


async def enrich_claims_with_citation_traces(claims: list[dict[str, Any]]) -> None:
    """
    For each claim dict, pick a starting URL (primary_sources[0].url if present, else first
    http(s) in text/statement), run CitationTracer, and set `citation_chain` and optional
    `origin_stamp`. Failures are swallowed so receipt assembly never blocks.
    """
    if not claims:
        return
    tracer = CitationTracer()
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        stmt = str(claim.get("text") or claim.get("statement") or "").strip()
        url = _citation_start_url(claim)
        if not url:
            continue
        try:
            chain = await tracer.trace(claim_text=stmt, cited_url=url, max_depth=4)
            claim["citation_chain"] = chain.model_dump(mode="json")
            stamp_parts = [p for p in (chain.terminal_node.origin_entity, chain.origin_label) if p]
            if stamp_parts:
                claim["origin_stamp"] = ", ".join(stamp_parts)[:500]
        except Exception:
            logger.debug("citation trace failed for claim", exc_info=True)


if __name__ == "__main__":
    async def _demo() -> None:
        tracer = CitationTracer()
        chain = await tracer.trace(
            claim_text="The Earth orbits the Sun.",
            cited_url="https://www.wikipedia.org/wiki/Earth",
            max_depth=2,
        )
        print(json.dumps(chain.model_dump(mode="json"), indent=2))

    asyncio.run(_demo())
