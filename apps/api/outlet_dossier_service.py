"""
Builds and caches outlet dossiers.
Future: FEC, CourtListener, SEC, OpenCorporates. For now: stub payload suitable for API contract.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from receipt_store import get_stored_outlet_dossier, upsert_outlet_dossier


def outlet_slug(name: str) -> str:
    s = (name or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return (s.strip("-") or "unknown")[:120]


def get_baseline_accuracy_rating(outlet_name: str) -> float:
    """
    0.0–1.0 multiplier for the correction-history component (15 pt band).
    Pulls from stored dossier if present; else neutral 0.5 per MEDIA_AXIS spec.
    """
    slug = outlet_slug(outlet_name)
    row = get_stored_outlet_dossier(slug)
    if not row:
        return 0.5
    ncorr = row.get("corrections_on_record")
    if isinstance(ncorr, int) and ncorr > 20:
        return 0.35
    if isinstance(ncorr, int) and ncorr > 8:
        return 0.45
    if isinstance(ncorr, int) and ncorr < 0:
        return 0.5
    return 0.55


def build_outlet_dossier(outlet_name: str) -> dict[str, Any]:
    """Stub dossier — primary-source adapters wired in a later sprint."""
    slug = outlet_slug(outlet_name)
    now = datetime.now(timezone.utc).isoformat()
    return {
        "outlet": outlet_name.strip() or slug,
        "slug": slug,
        "outlet_type": "private",
        "country": "",
        "flag": "",
        "parent_company": None,
        "ownership_chain": [],
        "political_donations": [],
        "lawsuits": [],
        "corrections_on_record": 0,
        "notable_retractions": [],
        "coverage_bias_notes": (
            "Third-party bias labels (e.g. AllSides, MBFC) are not used for scoring. "
            "Per-story positions come from proximity to the verifiable record only."
        ),
        "recent_investigations": [],
        "dossier_generated_at": now,
        "signed": False,
        "sources_used": [],
    }


def get_or_build_outlet_dossier(outlet_name: str, persist: bool = True) -> dict[str, Any]:
    slug = outlet_slug(outlet_name)
    existing = get_stored_outlet_dossier(slug)
    if existing:
        return existing
    payload = build_outlet_dossier(outlet_name)
    if persist:
        upsert_outlet_dossier(slug, payload["outlet"], payload)
    return payload


def get_or_build_outlet_by_url_slug(url_slug: str, persist: bool = True) -> dict[str, Any]:
    """Resolve /v1/outlet/{slug} — slug is already URL-normalized."""
    s = (url_slug or "").strip().lower()
    if not s:
        return build_outlet_dossier("unknown")
    existing = get_stored_outlet_dossier(s)
    if existing:
        return existing
    display = s.replace("-", " ").strip().title()
    payload = build_outlet_dossier(display)
    payload["slug"] = s
    if persist:
        upsert_outlet_dossier(s, payload["outlet"], payload)
    return payload


def _fetch_fec_donations(_entity_name: str) -> list:
    return []


def _fetch_courtlistener_cases(_entity_name: str) -> list:
    return []


def _fetch_ownership_chain(_outlet_name: str) -> list:
    return []
