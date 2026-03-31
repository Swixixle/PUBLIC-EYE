"""
Resolve media URLs to transcript + provenance before yt-dlp.
YouTube: timedtext → publisher transcript (NPR/PBS/CNN) → Podcast Index MP3 → yt-dlp last.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import urllib.parse
from typing import Any

import httpx

from publisher_registry import (
    is_allowed_transcript_host,
    lookup_domain,
    lookup_youtube_channel,
)

logger = logging.getLogger(__name__)

_YT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
_CLAUDE_MODEL = os.environ.get("CLAUDE_SONNET_MODEL", "claude-sonnet-4-20250514")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_url(url: str) -> dict[str, Any]:
    url = (url or "").strip()

    yt_match = re.search(
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)"
        r"([A-Za-z0-9_-]{11})",
        url,
    )
    if yt_match:
        return {
            "platform": "youtube",
            "content_type": "video",
            "video_id": yt_match.group(1),
            "url": url,
        }

    if "open.spotify.com/episode/" in url:
        ep_id = url.split("/episode/", 1)[1].split("?", 1)[0]
        return {
            "platform": "spotify",
            "content_type": "podcast_episode",
            "episode_id": ep_id,
            "url": url,
        }

    if "podcasts.apple.com" in url:
        return {
            "platform": "apple_podcasts",
            "content_type": "podcast_episode",
            "url": url,
        }

    if re.search(r"\.(mp3|m4a|ogg|wav|flac|opus)(\?|$)", url, re.I):
        return {
            "platform": "direct_audio",
            "content_type": "audio_file",
            "url": url,
        }

    if re.search(r"\.(xml|rss)(\?|$)", url, re.I) or "feeds." in url.lower():
        return {
            "platform": "rss_feed",
            "content_type": "podcast_feed",
            "url": url,
        }

    try:
        parsed = urllib.parse.urlparse(url)
        domain = (parsed.netloc or "").replace("www.", "").lower()
        if lookup_domain(domain):
            return {
                "platform": "news_site",
                "content_type": "article_or_media",
                "domain": domain,
                "url": url,
            }
    except Exception:  # noqa: BLE001
        pass

    return _llm_classify(url)


def _llm_classify(url: str) -> dict[str, Any]:
    if not _ANTHROPIC_KEY:
        return {"platform": "unknown", "content_type": "unknown", "url": url}
    import anthropic as _ant

    client = _ant.Anthropic(api_key=_ANTHROPIC_KEY)
    try:
        msg = client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=200,
            messages=[
                {
                    "role": "user",
                    "content": f"""Classify this URL for a media analysis pipeline.
URL: {url}

Return ONLY JSON:
{{
  "platform": "youtube|spotify|apple_podcasts|soundcloud|vimeo|news_site|podcast_feed|direct_audio|unknown",
  "content_type": "video|podcast_episode|audio_file|article|unknown",
  "publisher_guess": "name of likely publisher or empty string",
  "notes": "one sentence about what this likely is"
}}""",
                },
            ],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1].lstrip("json").strip()
        data = json.loads(raw)
        data["url"] = url
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM classify failed: %s", exc)
        return {"platform": "unknown", "content_type": "unknown", "url": url}


def _handle_from_author_url(author_url: str) -> str:
    if not author_url:
        return ""
    m = re.search(r"youtube\.com/(@[\w-]+)", author_url, re.I)
    if m:
        return m.group(1) if m.group(1).startswith("@") else f"@{m.group(1)}"
    m = re.search(r"youtube\.com/(?:c|channel|user)/([\w-]+)", author_url, re.I)
    if m:
        return f"@{m.group(1)}"
    return ""


async def _fetch_youtube_metadata(video_id: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(
                "https://www.youtube.com/oembed",
                params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
                headers={"User-Agent": _YT_UA},
            )
            if r.status_code == 200:
                data = r.json()
                author_url = str(data.get("author_url") or "")
                handle = _handle_from_author_url(author_url)
                return {
                    "title": str(data.get("title") or ""),
                    "channel_name": str(data.get("author_name") or ""),
                    "channel_handle": handle,
                    "channel_url": author_url,
                    "published_at": "",
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("YouTube oEmbed fetch failed: %s", exc)
    return {}


async def verify_provenance(classification: dict[str, Any]) -> dict[str, Any]:
    url = classification.get("url", "")
    platform = classification.get("platform", "unknown")
    provenance: dict[str, Any] = {
        "content_url": url,
        "content_title": "",
        "published_at": "",
        "publisher": "",
        "publisher_type": "",
        "publisher_url": "",
        "verified_publisher": False,
        "resolution_path": [],
    }

    if platform == "youtube":
        video_id = classification.get("video_id", "")
        meta = await _fetch_youtube_metadata(video_id)
        channel_handle = meta.get("channel_handle", "")
        channel_name = meta.get("channel_name", "")
        pub = lookup_youtube_channel(channel_handle) if channel_handle else None
        provenance["content_title"] = meta.get("title", "")
        provenance["published_at"] = meta.get("published_at", "")
        if pub:
            provenance.update(
                {
                    "publisher": pub["name"],
                    "publisher_type": pub["type"],
                    "publisher_url": meta.get("channel_url")
                    or (f"https://www.youtube.com/{channel_handle}" if channel_handle else ""),
                    "verified_publisher": True,
                },
            )
        else:
            provenance.update(
                {
                    "publisher": channel_name or "Unknown YouTube channel",
                    "publisher_type": "unverified",
                    "publisher_url": meta.get("channel_url", ""),
                    "verified_publisher": False,
                },
            )

    elif platform == "news_site":
        domain = classification.get("domain", "")
        pub = lookup_domain(domain)
        if pub:
            provenance.update(
                {
                    "publisher": pub["name"],
                    "publisher_type": pub["type"],
                    "publisher_url": f"https://{domain}",
                    "verified_publisher": True,
                },
            )
        else:
            provenance["publisher"] = domain or "unknown"
            provenance["publisher_type"] = "unverified"

    elif platform in ("spotify", "apple_podcasts"):
        provenance["publisher"] = "Spotify" if platform == "spotify" else "Apple Podcasts"
        provenance["publisher_type"] = "podcast_platform"
        provenance["verified_publisher"] = True
        provenance["content_title"] = classification.get("episode_id", "") or ""

    elif platform == "rss_feed":
        provenance["publisher_type"] = "rss_feed"
        provenance["verified_publisher"] = False

    elif platform == "direct_audio":
        provenance["publisher_type"] = "direct_audio"
        provenance["verified_publisher"] = False

    return provenance


# ---------------------------------------------------------------------------
# YouTube timedtext
# ---------------------------------------------------------------------------

def _parse_caption_base_url(html: str, video_id: str) -> str | None:
    m = re.search(
        r'"baseUrl"\s*:\s*"(https://www\.youtube\.com/api/timedtext[^"]+)"',
        html,
    )
    if m:
        return m.group(1).replace("\\u0026", "&")
    idx = html.find('"captionTracks"')
    if idx != -1:
        chunk = html[idx : idx + 8000]
        m2 = re.search(
            r'https://www\.youtube\.com/api/timedtext[^"\\]+',
            chunk,
        )
        if m2:
            return m2.group(0).replace("\\u0026", "&")
    return None


async def _youtube_timedtext(video_id: str) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            r = await client.get(
                f"https://www.youtube.com/watch?v={video_id}",
                headers={"User-Agent": _YT_UA, "Accept-Language": "en-US,en;q=0.9"},
            )
            if r.status_code != 200:
                return None
            base = _parse_caption_base_url(r.text, video_id)
            if not base:
                try_url = (
                    f"https://www.youtube.com/api/timedtext?v={video_id}&lang=en&fmt=srv3"
                )
                tr = await client.get(try_url, headers={"User-Agent": _YT_UA})
                if tr.status_code != 200 or len(tr.text) <= 80:
                    return None
                cap_text = re.sub(r"<[^>]+>", " ", tr.text)
                cap_text = re.sub(r"\s+", " ", cap_text).strip()
                if len(cap_text) < 100:
                    return None
                return {
                    "full_text": cap_text,
                    "segments": [],
                    "source_url": try_url[:2000],
                    "language": "en",
                    "duration": 0.0,
                }
            sep = "&" if "?" in base else "?"
            caption_url = base if "fmt=" in base else f"{base}{sep}fmt=srv3"
            cr = await client.get(caption_url, headers={"User-Agent": _YT_UA})
            if cr.status_code != 200:
                return None
            full_text = re.sub(r"<[^>]+>", " ", cr.text)
            full_text = re.sub(r"\s+", " ", full_text).strip()
            if len(full_text) < 100:
                return None
            return {
                "full_text": full_text,
                "segments": [],
                "source_url": caption_url[:2000],
                "language": "en",
                "duration": 0.0,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("YouTube timedtext failed: %s", exc)
    return None


def _llm_transcript_url(video_id: str, title: str, publisher: str) -> dict[str, Any]:
    if not _ANTHROPIC_KEY or not title.strip():
        return {}
    import anthropic as _ant

    client = _ant.Anthropic(api_key=_ANTHROPIC_KEY)
    msg = client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": f'''A video titled "{title}" was published by {publisher}.
YouTube video ID: {video_id}

Many publishers post full transcripts on their own sites (e.g. pbs.org/newshour, npr.org).
What is the most likely URL for the official transcript of this video?

Return ONLY JSON:
{{
  "transcript_url": "full https URL or empty string",
  "confidence": "high|medium|low"
}}
Only return a URL if you believe it likely exists. Do not guess random paths.''',
            },
        ],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1].lstrip("json").strip()
    return json.loads(raw)


async def _publisher_transcript_search(
    video_id: str,
    title: str,
    publisher: str,
) -> dict[str, Any] | None:
    if not _ANTHROPIC_KEY or not title:
        return None
    try:
        data = await asyncio.to_thread(_llm_transcript_url, video_id, title, publisher)
        transcript_url = str(data.get("transcript_url") or "").strip()
        confidence = str(data.get("confidence") or "low").lower()
        if not transcript_url or confidence == "low":
            return None
        parsed = urllib.parse.urlparse(transcript_url)
        if parsed.scheme not in ("http", "https"):
            return None
        host = (parsed.netloc or "").lower()
        if not is_allowed_transcript_host(host):
            return None
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            r = await client.get(transcript_url, headers={"User-Agent": _YT_UA})
            if r.status_code != 200:
                return None
            text = re.sub(r"<script[^>]*>.*?</script>", " ", r.text, flags=re.I | re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) < 500:
                return None
            return {
                "full_text": text[:50_000],
                "segments": [],
                "source_url": transcript_url[:2000],
                "language": "en",
                "duration": 0.0,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Publisher transcript search failed: %s", exc)
    return None


def _podcast_index_headers() -> dict[str, str]:
    api_key = (os.environ.get("PODCAST_INDEX_API_KEY") or "").strip()
    secret = (os.environ.get("PODCAST_INDEX_API_SECRET") or "").strip()
    if not api_key or not secret:
        return {}
    ts = str(int(time.time()))
    auth = hashlib.sha1(f"{api_key}{secret}{ts}".encode()).hexdigest()
    return {
        "X-Auth-Key": api_key,
        "X-Auth-Date": ts,
        "Authorization": auth,
        "User-Agent": "FramePublicEye/1.0",
    }


async def _podcast_index_episode_audio(title: str, publisher: str) -> dict[str, Any] | None:
    headers = _podcast_index_headers()
    if not headers or not title.strip():
        return None
    q = f"{publisher} {title}".strip()[:180]
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(
                "https://api.podcastindex.org/api/1.0/episodes/byterm",
                params={"q": q, "max": "12"},
                headers=headers,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            items = data.get("items") or data.get("episodes") or []
            mp3_url = ""
            for ep in items:
                if not isinstance(ep, dict):
                    continue
                enc = ep.get("enclosureUrl") or ep.get("enclosureurl") or ""
                if isinstance(enc, str) and enc.lower().split("?", 1)[0].endswith(
                    (".mp3", ".m4a"),
                ):
                    mp3_url = enc
                    break
            if not mp3_url:
                return None
            return {
                "full_text": "",
                "segments": [],
                "source_url": mp3_url[:2000],
                "language": "en",
                "duration": 0.0,
                "requires_download": True,
                "download_url": mp3_url,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Podcast Index episode lookup failed: %s", exc)
    return None


def _ytdlp_signal(url: str) -> dict[str, Any]:
    return {
        "full_text": "",
        "segments": [],
        "source_url": url,
        "language": "unknown",
        "duration": 0.0,
        "requires_download": True,
        "download_url": url,
    }


async def fetch_transcript(
    classification: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    platform = classification.get("platform", "unknown")
    url = classification.get("url", "")
    path: list[str] = []

    if platform == "youtube":
        video_id = classification.get("video_id", "")
        result = await _youtube_timedtext(video_id)
        if result:
            path.append("youtube_timedtext")
            provenance["resolution_path"] = list(path)
            result["source"] = "youtube_timedtext"
            return {"transcript": result, "error": None}
        path.append("youtube_timedtext_failed")

        title = provenance.get("content_title") or ""
        publisher = provenance.get("publisher") or ""
        pub_result = await _publisher_transcript_search(video_id, title, publisher)
        if pub_result:
            path.append("publisher_transcript")
            provenance["resolution_path"] = list(path)
            pub_result["source"] = "publisher_transcript"
            return {"transcript": pub_result, "error": None}
        path.append("publisher_transcript_failed")

        pi_result = await _podcast_index_episode_audio(title, publisher)
        if pi_result:
            path.append("podcast_index_mp3")
            provenance["resolution_path"] = list(path)
            pi_result["source"] = "podcast_index_mp3"
            return {"transcript": pi_result, "error": None}
        path.append("podcast_index_mp3_failed")

        y = _ytdlp_signal(url)
        path.append("ytdlp_audio")
        provenance["resolution_path"] = list(path)
        y["source"] = "ytdlp_audio"
        return {"transcript": y, "error": None}

    if platform in ("spotify", "apple_podcasts"):
        title = provenance.get("content_title") or ""
        publisher = provenance.get("publisher") or ""
        result = await _podcast_index_episode_audio(title, publisher)
        if result:
            path.append("podcast_index_mp3")
            provenance["resolution_path"] = list(path)
            result["source"] = "podcast_index_mp3"
            return {"transcript": result, "error": None}
        path.append("podcast_index_mp3_failed")
        provenance["resolution_path"] = list(path)
        return {
            "transcript": None,
            "error": (
                "Could not resolve audio without platform authentication. "
                "Try an RSS feed URL, Podcast Index, or direct MP3 link."
            ),
        }

    y = _ytdlp_signal(url)
    path.append("ytdlp_audio")
    provenance["resolution_path"] = list(path)
    y["source"] = "ytdlp_audio"
    return {"transcript": y, "error": None}


def format_content_provenance(provenance: dict[str, Any]) -> dict[str, Any]:
    """Shape stored on receipts and dossiers."""
    return {
        "publisher": provenance.get("publisher", ""),
        "publisher_type": provenance.get("publisher_type", ""),
        "publisher_url": provenance.get("publisher_url", ""),
        "content_url": provenance.get("content_url", ""),
        "content_title": provenance.get("content_title", ""),
        "published_at": provenance.get("published_at", ""),
        "verified_publisher": bool(provenance.get("verified_publisher", False)),
        "resolution_path": list(provenance.get("resolution_path") or []),
    }


def provenance_user_upload(original_filename: str) -> dict[str, Any]:
    return format_content_provenance(
        {
            "publisher": "User upload",
            "publisher_type": "upload",
            "publisher_url": "",
            "content_url": "",
            "content_title": (original_filename or "")[:500],
            "published_at": "",
            "verified_publisher": False,
            "resolution_path": ["user_upload"],
        },
    )


async def resolve_url(url: str) -> dict[str, Any]:
    classification = await asyncio.to_thread(classify_url, url)
    provenance = await verify_provenance(classification)
    result = await fetch_transcript(classification, provenance)
    transcript = result.get("transcript")
    error = result.get("error")

    requires_download = False
    download_url: str | None = None
    if transcript and transcript.get("requires_download"):
        requires_download = True
        download_url = transcript.get("download_url") or url
        transcript = None

    return {
        "transcript": transcript,
        "provenance": provenance,
        "error": error,
        "requires_download": requires_download,
        "download_url": download_url or url,
        "classification": classification,
    }
