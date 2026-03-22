# meta_ad_library.py
# Meta Ad Library adapter — "was it paid for" layer.
# Queries Meta's Ad Library API for political and issue ads.
#
# HONEST LIMITATIONS (encoded in every receipt):
# - Meta only discloses "political and issue" ads
# - Regular commercial/boosted content is NOT in the library
# - Spend figures are ranges, not exact amounts
# - An account with no results here may still be running paid content
# - These limitations are epistemic unknowns — they do not resolve over time
#
# Setup: https://developers.facebook.com/
# Request: ads_read permission
# Add META_AD_LIBRARY_TOKEN to Render environment

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx

META_AD_LIBRARY_TOKEN = os.getenv("META_AD_LIBRARY_TOKEN")
META_AD_LIBRARY_ENDPOINT = "https://graph.facebook.com/v19.0/ads_archive"

AD_LIBRARY_ADAPTER_VERSION = "meta_ad_library_v1"

# Spend range mapping — Meta may return enum strings in some contexts
SPEND_RANGE_MAP: dict[str, str] = {
    "NONE": "$0",
    "LESS_THAN_100": "under $100",
    "100_499": "$100–$499",
    "500_999": "$500–$999",
    "1K_1999": "$1,000–$1,999",
    "2K_9999": "$2,000–$9,999",
    "10K_50K": "$10,000–$50,000",
    "50K_200K": "$50,000–$200,000",
    "200K_1M": "$200,000–$1,000,000",
    "MORE_THAN_1M": "over $1,000,000",
}


class AdLibraryUnavailableError(Exception):
    """Raised when META_AD_LIBRARY_TOKEN is not configured (optional; query_ad_library does not raise)."""

    pass


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


async def query_ad_library(
    search_term: str,
    country: str = "US",
    limit: int = 25,
) -> dict[str, Any]:
    """
    Query Meta Ad Library for political and issue ads matching search_term.

    Returns structured result dict — never raises (errors become unknowns).
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    if not META_AD_LIBRARY_TOKEN:
        return {
            "status": "unavailable",
            "note": (
                "META_AD_LIBRARY_TOKEN not configured. Sign up at https://developers.facebook.com/ "
                "and request ads_read permission."
            ),
            "resolution_possible": True,
            "timestamp": timestamp,
        }

    fields = [
        "id",
        "ad_creation_time",
        "ad_delivery_start_time",
        "ad_delivery_stop_time",
        "ad_creative_bodies",
        "ad_creative_link_titles",
        "funding_entity",
        "spend",
        "impressions",
        "publisher_platforms",
        "page_name",
        "page_id",
        "bylines",
        "estimated_audience_size",
        "delivery_by_region",
    ]

    # Graph API expects ad_reached_countries as a JSON array string for many clients
    params: dict[str, Any] = {
        "search_terms": search_term,
        "ad_type": "POLITICAL_AND_ISSUE_ADS",
        "ad_reached_countries": json.dumps([country]),
        "fields": ",".join(fields),
        "access_token": META_AD_LIBRARY_TOKEN,
        "limit": min(max(limit, 1), 100),
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(META_AD_LIBRARY_ENDPOINT, params=params)
            response.raise_for_status()
            raw = response.json()
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 400:
            error_data: dict[str, Any] = {}
            try:
                error_data = e.response.json()
            except Exception:
                pass
            err_msg = ""
            if isinstance(error_data.get("error"), dict):
                err_msg = str(error_data["error"].get("message", str(e)))[:300]
            else:
                err_msg = str(e)[:300]
            return {
                "status": "api_error",
                "http_status": 400,
                "error": err_msg,
                "note": (
                    "Meta API returned 400. Token may lack ads_read permission or "
                    "search term may be invalid."
                ),
                "resolution_possible": True,
                "timestamp": timestamp,
            }
        code = e.response.status_code if e.response is not None else 0
        return {
            "status": "api_error",
            "http_status": code,
            "error": str(e)[:300],
            "resolution_possible": True,
            "timestamp": timestamp,
        }
    except Exception as e:
        return {
            "status": "fetch_error",
            "error": str(e)[:300],
            "resolution_possible": True,
            "timestamp": timestamp,
        }

    ads = raw.get("data", [])
    paging = raw.get("paging", {})

    if not ads:
        return {
            "status": "no_results",
            "search_term": search_term,
            "country": country,
            "note": f"No political or issue ads found for '{search_term}' in {country}.",
            "timestamp": timestamp,
            "has_more": False,
        }

    normalized: list[dict[str, Any]] = []
    funding_entities: set[str] = set()
    active_count = 0

    for ad in ads:
        spend_raw = ad.get("spend") or {}
        impressions_raw = ad.get("impressions") or {}

        spend_lower = _safe_int(spend_raw.get("lower_bound"))
        spend_upper = _safe_int(spend_raw.get("upper_bound"))
        spend_display = _format_spend_range(spend_lower, spend_upper)

        imp_lower = _safe_int(impressions_raw.get("lower_bound"))
        imp_upper = _safe_int(impressions_raw.get("upper_bound"))

        is_active = not ad.get("ad_delivery_stop_time")
        if is_active:
            active_count += 1

        funding = ad.get("funding_entity") or ""
        if funding:
            funding_entities.add(str(funding))

        normalized.append(
            {
                "ad_id": ad.get("id"),
                "page_name": ad.get("page_name"),
                "funding_entity": funding,
                "is_active": is_active,
                "created_at": ad.get("ad_creation_time"),
                "delivery_start": ad.get("ad_delivery_start_time"),
                "delivery_stop": ad.get("ad_delivery_stop_time"),
                "spend_display": spend_display,
                "spend_lower_bound": spend_lower,
                "spend_upper_bound": spend_upper,
                "impressions_lower": imp_lower,
                "impressions_upper": imp_upper,
                "platforms": ad.get("publisher_platforms") or [],
                "bylines": ad.get("bylines") or [],
            },
        )

    return {
        "status": "results_found",
        "search_term": search_term,
        "country": country,
        "total_ads_returned": len(ads),
        "active_ads_count": active_count,
        "inactive_ads_count": len(ads) - active_count,
        "unique_funding_entities": sorted(funding_entities),
        "ads": normalized,
        "has_more": bool(paging.get("next")),
        "timestamp": timestamp,
        "adapter_version": AD_LIBRARY_ADAPTER_VERSION,
    }


def _format_spend_range(lower: int | None, upper: int | None) -> str:
    """Format Meta spend range bounds into human-readable string."""
    if lower is None and upper is None:
        return "spend not disclosed"
    if lower is not None and upper is not None:
        return f"${lower:,}–${upper:,} (estimated)"
    if lower is not None:
        return f"over ${lower:,} (estimated)"
    if upper is not None:
        return f"under ${upper:,} (estimated)"
    return "spend not disclosed"
