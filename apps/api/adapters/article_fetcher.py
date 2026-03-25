"""
Fetch and extract clean article text from URLs (news, blogs, Substack, etc.).
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

import httpx
from pydantic import BaseModel


def _clean_article_text(text: str) -> str:
    """Remove short lines, dedupe consecutive lines, normalize whitespace, cap length."""
    lines: list[str] = []
    for line in text.splitlines():
        t = line.strip()
        if len(t) < 20:
            continue
        lines.append(t)
    out: list[str] = []
    prev: str | None = None
    for line in lines:
        if line == prev:
            continue
        out.append(line)
        prev = line
    joined = "\n".join(out)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    joined = re.sub(r"[ \t]+", " ", joined)
    joined = joined.strip()
    if len(joined) > 50_000:
        joined = joined[:50_000]
    return joined


def _strip_html_regex(html: str) -> str:
    """Last-resort plain text from HTML."""
    without_scripts = re.sub(
        r"(?is)<script[^>]*>.*?</script>",
        " ",
        html,
    )
    without_styles = re.sub(
        r"(?is)<style[^>]*>.*?</style>",
        " ",
        without_scripts,
    )
    text = re.sub(r"(?s)<[^>]+>", "\n", without_styles)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class ArticleFetchResult(BaseModel):
    url: str
    title: Optional[str] = None
    author: Optional[str] = None
    publication: Optional[str] = None
    published_date: Optional[str] = None
    text: str = ""
    word_count: int = 0
    fetch_method: str = "raw"
    resolved: bool = False
    error: Optional[str] = None


class ArticleFetcher:
    async def fetch(self, url: str) -> ArticleFetchResult:
        """Fetch URL and extract article text; try trafilatura → BeautifulSoup → regex."""
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            return ArticleFetchResult(
                url=url,
                error="URL must be http(s)",
                resolved=False,
            )

        # 1) trafilatura
        try:
            r1 = await self._try_trafilatura(url)
            if r1.resolved and r1.text.strip():
                return r1
        except Exception:  # noqa: BLE001
            pass

        # 2) BeautifulSoup + httpx
        try:
            r2 = await self._try_beautifulsoup(url)
            if r2.resolved and r2.text.strip():
                return r2
        except Exception:  # noqa: BLE001
            pass

        # 3) raw strip
        try:
            r3 = await self._try_raw_strip(url)
            if r3.resolved and r3.text.strip():
                return r3
        except Exception as exc:  # noqa: BLE001
            return ArticleFetchResult(
                url=url,
                error=str(exc)[:500],
                resolved=False,
            )

        return ArticleFetchResult(
            url=url,
            error="Could not extract readable article text from this URL.",
            resolved=False,
        )

    async def _try_trafilatura(self, url: str) -> ArticleFetchResult:
        def _run() -> ArticleFetchResult:
            import trafilatura

            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return ArticleFetchResult(url=url, resolved=False, fetch_method="trafilatura")

            meta_obj = trafilatura.extract_metadata(downloaded)
            extracted = trafilatura.extract(downloaded)
            text_raw = (extracted or "").strip()
            title = None
            author = None
            publication = None
            published_date = None
            if meta_obj is not None:
                title = getattr(meta_obj, "title", None) or None
                author = getattr(meta_obj, "author", None) or None
                publication = (
                    getattr(meta_obj, "sitename", None)
                    or getattr(meta_obj, "hostname", None)
                ) or None
                published_date = getattr(meta_obj, "date", None) or None
                if hasattr(meta_obj, "as_dict"):
                    try:
                        d = meta_obj.as_dict()
                        if isinstance(d, dict):
                            title = title or d.get("title")
                            author = author or d.get("author")
                            publication = publication or d.get("sitename")
                            published_date = published_date or d.get("date")
                    except Exception:  # noqa: BLE001
                        pass

            cleaned = _clean_article_text(text_raw) if text_raw else ""
            wc = len(cleaned.split()) if cleaned else 0
            return ArticleFetchResult(
                url=url,
                title=title,
                author=author,
                publication=publication,
                published_date=str(published_date) if published_date else None,
                text=cleaned,
                word_count=wc,
                fetch_method="trafilatura",
                resolved=bool(cleaned and len(cleaned) > 50),
            )

        return await asyncio.to_thread(_run)

    async def _try_beautifulsoup(self, url: str) -> ArticleFetchResult:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(45.0),
            follow_redirects=True,
            headers={"User-Agent": "FrameWhistle/1.0 (article fetch)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        def _parse() -> ArticleFetchResult:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            paras = soup.find_all("p")
            parts = []
            for p in paras:
                t = p.get_text(separator=" ", strip=True)
                if t:
                    parts.append(t)
            text_raw = "\n".join(parts)
            title_el = soup.find("h1")
            title = title_el.get_text(strip=True) if title_el else None
            if not title and soup.title:
                title = soup.title.get_text(strip=True)
            cleaned = _clean_article_text(text_raw) if text_raw else ""
            wc = len(cleaned.split()) if cleaned else 0
            return ArticleFetchResult(
                url=url,
                title=title[:500] if title else None,
                author=None,
                publication=None,
                published_date=None,
                text=cleaned,
                word_count=wc,
                fetch_method="beautifulsoup",
                resolved=bool(cleaned and len(cleaned) > 50),
            )

        return await asyncio.to_thread(_parse)

    async def _try_raw_strip(self, url: str) -> ArticleFetchResult:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(45.0),
            follow_redirects=True,
            headers={"User-Agent": "FrameWhistle/1.0 (article fetch)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        def _parse() -> ArticleFetchResult:
            text_raw = _strip_html_regex(html)
            cleaned = _clean_article_text(text_raw) if text_raw else ""
            wc = len(cleaned.split()) if cleaned else 0
            return ArticleFetchResult(
                url=url,
                title=None,
                author=None,
                publication=None,
                published_date=None,
                text=cleaned,
                word_count=wc,
                fetch_method="raw",
                resolved=bool(cleaned and len(cleaned) > 50),
            )

        return await asyncio.to_thread(_parse)
