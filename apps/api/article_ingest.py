"""Fetch and extract plain text from a news article URL."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


def fetch_article(url: str, timeout: int = 15) -> dict[str, Any]:
    """
    Fetch and clean article text from a URL.
    Returns dict with: url, title, publication, text, word_count, truncated, fetch_error
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Frame/1.0; +https://frame-2yxu.onrender.com)"
    }
    try:
        resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return {
            "url": url,
            "title": None,
            "publication": None,
            "text": None,
            "word_count": 0,
            "truncated": False,
            "fetch_error": str(e),
        }

    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "iframe"]):
        tag.decompose()

    title = None
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    elif soup.find("title"):
        title = soup.find("title").get_text(strip=True)

    container = (
        soup.find("article")
        or soup.find("main")
        or soup.find("div", {"class": re.compile(r"article|story|content|body", re.I)})
        or soup.body
    )

    text = container.get_text(separator=" ", strip=True) if container else ""
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    truncated = len(words) > 8000
    text = " ".join(words[:8000])

    publication = urlparse(url).netloc.replace("www.", "")

    return {
        "url": url,
        "title": title,
        "publication": publication,
        "text": text,
        "word_count": len(words),
        "truncated": truncated,
        "fetch_error": None,
    }
