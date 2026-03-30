"""
Frame Lens — mobile capture: document OCR, place + context, audio transcription, universal URL.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import anthropic
import httpx

from actor_layer_api import run_actor_layer
from article_ingest import fetch_article
from claim_extractor import extract_claims
from query_engine import extract_keywords, search_feeds


def _anthropic_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return anthropic.Anthropic(api_key=key or "unset")


OCR_PROMPT = """You are an OCR and document analysis engine.

Extract all text from this image. Then identify:
- Document type (newspaper article, court notice, flyer, sign, screenshot, other)
- Publication name if visible
- Publication date if visible
- Author if visible
- Any URLs visible in the image
- Language of the text

Return ONLY valid JSON. No preamble. No markdown fences.

{
  "document_type": "newspaper_article|court_notice|flyer|sign|screenshot|other",
  "publication": "name or null",
  "date": "date string or null",
  "author": "name or null",
  "url": "url if visible or null",
  "language": "en|es|fr|ar|ru|zh|other",
  "full_text": "complete extracted text",
  "confidence": "high|medium|low"
}"""


async def process_document_image(
    image_b64: str,
    media_type: str = "image/jpeg",
    location: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """OCR an image with Claude vision, optionally fetch detected URL, extract claims."""
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return {
            "receipt_id": str(uuid.uuid4()),
            "receipt_type": "lens_document",
            "error": "ANTHROPIC_API_KEY not set",
            "signed": False,
        }

    client = _anthropic_client()

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": OCR_PROMPT},
                    ],
                }
            ],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        ocr_result: dict[str, Any] = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {
            "receipt_id": str(uuid.uuid4()),
            "receipt_type": "lens_document",
            "error": f"OCR failed: {e}",
            "signed": False,
        }

    full_text = (ocr_result.get("full_text") or "").strip()
    if not full_text:
        return {
            "receipt_id": str(uuid.uuid4()),
            "receipt_type": "lens_document",
            "error": "No text detected in image",
            "ocr_result": ocr_result,
            "signed": False,
        }

    detected_url = ocr_result.get("url")
    fetched_article: dict[str, Any] | None = None
    if detected_url and isinstance(detected_url, str) and detected_url.startswith("http"):
        try:
            fetched_article = await asyncio.to_thread(fetch_article, detected_url)
            if fetched_article.get("text"):
                full_text = fetched_article["text"]
        except Exception:  # noqa: BLE001
            pass

    extracted = await asyncio.to_thread(
        extract_claims,
        full_text,
        ocr_result.get("publication"),
    )

    receipt: dict[str, Any] = {
        "receipt_id": str(uuid.uuid4()),
        "receipt_type": "lens_document",
        "source_type": "image_ocr",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document": {
            "type": ocr_result.get("document_type"),
            "publication": ocr_result.get("publication"),
            "date": ocr_result.get("date"),
            "author": ocr_result.get("author"),
            "detected_url": detected_url,
            "language": ocr_result.get("language", "en"),
            "ocr_confidence": ocr_result.get("confidence"),
        },
        "extracted_text_preview": full_text[:500],
        "article_topic": extracted.get("article_topic"),
        "named_entities": sorted(
            extracted.get("named_entities", []) or [],
            key=str.lower,
        ),
        "claims_extracted": len(extracted.get("claims", []) or []),
        "claims": (extracted.get("claims", []) or [])[:15],
        "location": location,
    }
    if fetched_article:
        receipt["fetched_article"] = {
            "url": detected_url,
            "title": fetched_article.get("title"),
            "word_count": fetched_article.get("word_count"),
        }

    try:
        from report_api import attach_article_analysis_signing

        receipt = attach_article_analysis_signing(receipt)
    except Exception:  # noqa: BLE001
        receipt["signed"] = False

    return receipt


PLACE_PROMPT = """You are a place identification engine.

Given an image and optional GPS coordinates, identify:
- What building, location, or place this is
- Its official name
- Its type (courthouse, city hall, government building, hospital, university, other)
- The jurisdiction (city, county, state, country)
- Any visible text on the building (name plaques, signs)

Return ONLY valid JSON. No preamble. No markdown fences.

{
  "place_name": "official name of the place",
  "place_type": "courthouse|city_hall|government|hospital|university|landmark|other",
  "jurisdiction": "city, state",
  "country": "country name",
  "visible_text": ["text visible on building"],
  "confidence": "high|medium|low",
  "search_query": "best search query to find news about this place"
}"""


async def process_place_image(
    image_b64: str,
    media_type: str = "image/jpeg",
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    """Identify a place from image + optional GPS; actor layer + RSS hits."""
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return {
            "receipt_id": str(uuid.uuid4()),
            "receipt_type": "lens_place",
            "error": "ANTHROPIC_API_KEY not set",
            "signed": False,
        }

    client = _anthropic_client()
    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_b64,
            },
        },
        {"type": "text", "text": PLACE_PROMPT},
    ]
    if latitude is not None and longitude is not None:
        content.append(
            {"type": "text", "text": f"\nGPS coordinates: {latitude}, {longitude}"},
        )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": content}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        place_result: dict[str, Any] = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {
            "receipt_id": str(uuid.uuid4()),
            "receipt_type": "lens_place",
            "error": f"Place identification failed: {e}",
            "signed": False,
        }

    place_name = (place_result.get("place_name") or "").strip()
    search_query = (place_result.get("search_query") or place_name or "").strip()

    actor_result: dict[str, Any] = {}
    if place_name:
        try:
            narrative = (
                f"{place_name} is a {place_result.get('place_type', 'location')} "
                f"in {place_result.get('jurisdiction', '')}. {place_name}."
            )
            actor_result = await asyncio.to_thread(run_actor_layer, narrative)
        except Exception:  # noqa: BLE001
            actor_result = {}

    recent_articles: list[dict[str, Any]] = []
    if search_query:
        try:
            keywords = extract_keywords(search_query)
            if keywords:
                feed_results = search_feeds(keywords, max_results=5)
                recent_articles = [
                    {
                        "title": r.get("title"),
                        "url": r.get("url"),
                        "outlet": r.get("outlet"),
                        "published": r.get("published"),
                        "ecosystem": r.get("ecosystem"),
                    }
                    for r in feed_results
                ]
        except Exception:  # noqa: BLE001
            pass

    receipt: dict[str, Any] = {
        "receipt_id": str(uuid.uuid4()),
        "receipt_type": "lens_place",
        "source_type": "image_geocode",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "place": place_result,
        "coordinates": {"latitude": latitude, "longitude": longitude}
        if latitude is not None and longitude is not None
        else None,
        "actor_records": actor_result.get("actors_found", []),
        "recent_coverage": recent_articles,
        "sources_checked": actor_result.get("sources_checked", []),
    }

    try:
        from report_api import attach_article_analysis_signing

        receipt = attach_article_analysis_signing(receipt)
    except Exception:  # noqa: BLE001
        receipt["signed"] = False

    return receipt


async def process_audio(
    audio_b64: str,
    audio_format: str = "m4a",
    context_note: str | None = None,
) -> dict[str, Any]:
    """Transcribe with AssemblyAI (HTTP API), then extract claims."""
    try:
        audio_bytes = base64.b64decode(audio_b64, validate=True)
    except Exception as e:  # noqa: BLE001
        return {
            "receipt_id": str(uuid.uuid4()),
            "receipt_type": "lens_audio",
            "error": f"Invalid base64 audio: {e}",
            "signed": False,
        }

    assemblyai_key = (os.environ.get("ASSEMBLYAI_API_KEY") or "").strip()
    transcript_text: str | None = None
    transcript_method: str | None = None

    if assemblyai_key:
        try:
            upload_resp = httpx.post(
                "https://api.assemblyai.com/v2/upload",
                headers={"authorization": assemblyai_key},
                content=audio_bytes,
                timeout=120.0,
            )
            upload_resp.raise_for_status()
            audio_url = upload_resp.json()["upload_url"]

            transcript_resp = httpx.post(
                "https://api.assemblyai.com/v2/transcript",
                headers={
                    "authorization": assemblyai_key,
                    "content-type": "application/json",
                },
                json={"audio_url": audio_url},
                timeout=60.0,
            )
            transcript_resp.raise_for_status()
            transcript_id = transcript_resp.json()["id"]

            for _ in range(24):
                await asyncio.sleep(5)
                poll = httpx.get(
                    f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
                    headers={"authorization": assemblyai_key},
                    timeout=30.0,
                )
                poll_data = poll.json()
                if poll_data.get("status") == "completed":
                    transcript_text = poll_data.get("text") or ""
                    transcript_method = "assemblyai"
                    break
                if poll_data.get("status") == "error":
                    break
        except Exception:  # noqa: BLE001
            pass

    if not transcript_text:
        return {
            "receipt_id": str(uuid.uuid4()),
            "receipt_type": "lens_audio",
            "error": "Transcription failed — check ASSEMBLYAI_API_KEY",
            "signed": False,
        }

    title = context_note or "Audio recording"
    extracted = await asyncio.to_thread(extract_claims, transcript_text, title)

    receipt: dict[str, Any] = {
        "receipt_id": str(uuid.uuid4()),
        "receipt_type": "lens_audio",
        "source_type": "audio_transcription",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "transcript": {
            "text": transcript_text,
            "method": transcript_method,
            "word_count": len(transcript_text.split()),
            "context_note": context_note,
            "audio_format": audio_format,
        },
        "article_topic": extracted.get("article_topic"),
        "named_entities": sorted(
            extracted.get("named_entities", []) or [],
            key=str.lower,
        ),
        "claims_extracted": len(extracted.get("claims", []) or []),
        "claims": (extracted.get("claims", []) or [])[:15],
    }

    try:
        from report_api import attach_article_analysis_signing

        receipt = attach_article_analysis_signing(receipt)
    except Exception:  # noqa: BLE001
        receipt["signed"] = False

    return receipt


async def process_media_url(url: str) -> dict[str, Any]:
    """
    Article URL, direct audio file, or podcast-adjacent host → receipt.
    """
    url_lower = url.lower()
    audio_extensions = r"\.(mp3|m4a|wav|ogg|opus|flac)(\?|#|$)"
    podcast_hints = (
        "anchor.fm",
        "buzzsprout.com",
        "podbean.com",
        "soundcloud.com",
        "spotify.com/episode",
        "podcasts.apple.com",
    )

    if re.search(audio_extensions, url_lower):
        try:
            resp = httpx.get(url, timeout=60.0, follow_redirects=True)
            resp.raise_for_status()
            audio_b64 = base64.b64encode(resp.content).decode("ascii")
            ext_match = re.search(audio_extensions, url_lower)
            fmt = ext_match.group(1) if ext_match else "mp3"
            return await process_audio(audio_b64, fmt, context_note=url)
        except Exception as e:  # noqa: BLE001
            return {"receipt_type": "lens_audio", "error": str(e), "signed": False}

    if any(h in url_lower for h in podcast_hints):
        return {
            "receipt_id": str(uuid.uuid4()),
            "receipt_type": "lens_url",
            "error": (
                "Podcast page URL — use POST /v1/analyze-podcast with this URL "
                "for full transcription pipeline, or paste a direct .mp3 link."
            ),
            "url": url,
            "signed": False,
        }

    article = await asyncio.to_thread(fetch_article, url)
    if article.get("fetch_error"):
        return {
            "receipt_id": str(uuid.uuid4()),
            "receipt_type": "lens_url",
            "error": article["fetch_error"],
            "signed": False,
        }

    extracted = await asyncio.to_thread(
        extract_claims,
        article.get("text") or "",
        article.get("title"),
    )

    receipt: dict[str, Any] = {
        "receipt_id": str(uuid.uuid4()),
        "receipt_type": "lens_url",
        "source_type": "url",
        "url": url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "article": {
            "url": url,
            "title": article.get("title"),
            "publication": article.get("publication"),
            "word_count": article.get("word_count"),
        },
        "article_topic": extracted.get("article_topic"),
        "named_entities": sorted(
            extracted.get("named_entities", []) or [],
            key=str.lower,
        ),
        "claims_extracted": len(extracted.get("claims", []) or []),
        "claims": (extracted.get("claims", []) or [])[:15],
    }

    try:
        from report_api import attach_article_analysis_signing

        receipt = attach_article_analysis_signing(receipt)
    except Exception:  # noqa: BLE001
        receipt["signed"] = False

    return receipt
