"""
Known publishers and YouTube channels for URL resolver provenance.
Verified = registry match; unknown outlets still process with verified_publisher=False.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

# Domain → publisher metadata
KNOWN_PUBLISHERS: dict[str, dict[str, str]] = {
    "npr.org": {"name": "NPR", "type": "public_broadcaster", "country": "US"},
    "pbs.org": {"name": "PBS", "type": "public_broadcaster", "country": "US"},
    "wnyc.org": {"name": "WNYC", "type": "public_broadcaster", "country": "US"},
    "wbur.org": {"name": "WBUR", "type": "public_broadcaster", "country": "US"},
    "cnn.com": {"name": "CNN", "type": "cable_news", "country": "US"},
    "foxnews.com": {"name": "Fox News", "type": "cable_news", "country": "US"},
    "msnbc.com": {"name": "MSNBC", "type": "cable_news", "country": "US"},
    "cbsnews.com": {"name": "CBS News", "type": "broadcast_news", "country": "US"},
    "abcnews.go.com": {"name": "ABC News", "type": "broadcast_news", "country": "US"},
    "nbcnews.com": {"name": "NBC News", "type": "broadcast_news", "country": "US"},
    "nytimes.com": {"name": "The New York Times", "type": "newspaper", "country": "US"},
    "washingtonpost.com": {"name": "The Washington Post", "type": "newspaper", "country": "US"},
    "wsj.com": {"name": "The Wall Street Journal", "type": "newspaper", "country": "US"},
    "apnews.com": {"name": "Associated Press", "type": "wire_service", "country": "US"},
    "reuters.com": {"name": "Reuters", "type": "wire_service", "country": "UK"},
    "propublica.org": {"name": "ProPublica", "type": "investigative", "country": "US"},
    "theintercept.com": {"name": "The Intercept", "type": "investigative", "country": "US"},
    "politico.com": {"name": "Politico", "type": "political_news", "country": "US"},
    "thehill.com": {"name": "The Hill", "type": "political_news", "country": "US"},
    "axios.com": {"name": "Axios", "type": "digital_news", "country": "US"},
    "bbc.co.uk": {"name": "BBC", "type": "public_broadcaster", "country": "UK"},
    "bbc.com": {"name": "BBC", "type": "public_broadcaster", "country": "UK"},
    "theguardian.com": {"name": "The Guardian", "type": "newspaper", "country": "UK"},
    "aljazeera.com": {"name": "Al Jazeera", "type": "broadcast_news", "country": "QA"},
    "dw.com": {"name": "Deutsche Welle", "type": "public_broadcaster", "country": "DE"},
    "france24.com": {"name": "France 24", "type": "broadcast_news", "country": "FR"},
    "economist.com": {"name": "The Economist", "type": "magazine", "country": "UK"},
    "time.com": {"name": "Time", "type": "magazine", "country": "US"},
    "ft.com": {"name": "Financial Times", "type": "newspaper", "country": "UK"},
    "bloomberg.com": {"name": "Bloomberg", "type": "digital_news", "country": "US"},
    "forbes.com": {"name": "Forbes", "type": "digital_news", "country": "US"},
    "businessinsider.com": {"name": "Business Insider", "type": "digital_news", "country": "US"},
    "vice.com": {"name": "Vice", "type": "digital_news", "country": "US"},
    "huffpost.com": {"name": "HuffPost", "type": "digital_news", "country": "US"},
    "usatoday.com": {"name": "USA Today", "type": "newspaper", "country": "US"},
    "latimes.com": {"name": "Los Angeles Times", "type": "newspaper", "country": "US"},
    "bostonglobe.com": {"name": "The Boston Globe", "type": "newspaper", "country": "US"},
    "chicagotribune.com": {"name": "Chicago Tribune", "type": "newspaper", "country": "US"},
    "houstonchronicle.com": {"name": "Houston Chronicle", "type": "newspaper", "country": "US"},
    "startribune.com": {"name": "Star Tribune", "type": "newspaper", "country": "US"},
    "sfchronicle.com": {"name": "San Francisco Chronicle", "type": "newspaper", "country": "US"},
    "miamiherald.com": {"name": "Miami Herald", "type": "newspaper", "country": "US"},
    "denverpost.com": {"name": "The Denver Post", "type": "newspaper", "country": "US"},
    "azcentral.com": {"name": "Arizona Republic / azcentral", "type": "newspaper", "country": "US"},
    "feeds.npr.org": {"name": "NPR", "type": "public_broadcaster", "country": "US"},
    "podcastone.com": {"name": "PodcastOne", "type": "podcast_network", "country": "US"},
    "spotify.com": {"name": "Spotify", "type": "podcast_platform", "country": "SE"},
}

# YouTube handles (lookup normalizes case)
KNOWN_YOUTUBE_CHANNELS: dict[str, dict[str, str]] = {
    "@newshour": {"name": "PBS NewsHour", "type": "public_broadcaster", "country": "US"},
    "@pbsnewshour": {"name": "PBS NewsHour", "type": "public_broadcaster", "country": "US"},
    "@npr": {"name": "NPR", "type": "public_broadcaster", "country": "US"},
    "@cnn": {"name": "CNN", "type": "cable_news", "country": "US"},
    "@foxnews": {"name": "Fox News", "type": "cable_news", "country": "US"},
    "@msnbc": {"name": "MSNBC", "type": "cable_news", "country": "US"},
    "@abcnews": {"name": "ABC News", "type": "broadcast_news", "country": "US"},
    "@nbcnews": {"name": "NBC News", "type": "broadcast_news", "country": "US"},
    "@cbsnews": {"name": "CBS News", "type": "broadcast_news", "country": "US"},
    "@bbcnews": {"name": "BBC News", "type": "public_broadcaster", "country": "UK"},
    "@aljazeeraenglish": {"name": "Al Jazeera English", "type": "broadcast_news", "country": "QA"},
    "@guardian": {"name": "The Guardian", "type": "newspaper", "country": "UK"},
    "@wsj": {"name": "The Wall Street Journal", "type": "newspaper", "country": "US"},
    "@theatlantic": {"name": "The Atlantic", "type": "magazine", "country": "US"},
    "@vox": {"name": "Vox", "type": "digital_news", "country": "US"},
    "@thehill": {"name": "The Hill", "type": "political_news", "country": "US"},
    "@politico": {"name": "Politico", "type": "political_news", "country": "US"},
}

def is_allowed_transcript_host(host: str) -> bool:
    """Only fetch transcript pages from a small set of publisher domains."""
    h = (host or "").lower()
    if h.startswith("www."):
        h = h[4:]
    return h.endswith("npr.org") or h.endswith("pbs.org") or h.endswith("cnn.com")


def lookup_domain(domain: str) -> dict[str, str] | None:
    domain = domain.lower().replace("www.", "").strip()
    return KNOWN_PUBLISHERS.get(domain)


def _norm_handle(h: str) -> str:
    h = (h or "").strip()
    if not h:
        return ""
    if not h.startswith("@"):
        h = "@" + h
    return h


def lookup_youtube_channel(handle: str) -> dict[str, str] | None:
    if not handle:
        return None
    nh = _norm_handle(handle)
    for key in (nh, nh.lower()):
        pub = KNOWN_YOUTUBE_CHANNELS.get(key)
        if pub:
            return pub
    return None


def is_verified_publisher(domain: str) -> bool:
    return lookup_domain(domain) is not None


def content_provenance_for_article(url: str, title: str = "") -> dict[str, Any]:
    """Minimal provenance for article HTML investigations (no URL resolver cascade)."""
    parsed = urllib.parse.urlparse(url)
    domain = (parsed.netloc or "").replace("www.", "").lower()
    pub = lookup_domain(domain)
    out: dict[str, Any] = {
        "publisher": domain or "unknown",
        "publisher_type": "unverified",
        "publisher_url": f"https://{domain}" if domain else "",
        "content_url": url,
        "content_title": title or "",
        "published_at": "",
        "verified_publisher": False,
        "resolution_path": ["article_html_extract"],
    }
    if pub:
        out["publisher"] = pub["name"]
        out["publisher_type"] = pub["type"]
        out["verified_publisher"] = True
    return out
