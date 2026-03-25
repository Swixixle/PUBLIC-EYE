"""Layer 4 fast path for five-ring reports: ledger word-boundary match only, no outbound HTTP."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    override = os.environ.get("FRAME_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def _ledger_path(repo_root: Path) -> Path:
    return repo_root / "packages" / "actor-ledger" / "ledger.json"


def _load_ledger(repo_root: Path) -> dict[str, Any]:
    path = _ledger_path(repo_root)
    if not path.is_file():
        raise RuntimeError(f"Missing ledger at {path}")
    with path.open(encoding="utf8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError("ledger.json must be a top-level object")
    return data


def _ledger_search_hints(ledger: dict[str, Any]) -> list[str]:
    hints: set[str] = set()
    for row in ledger.values():
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if name:
            hints.add(name)
        for al in row.get("aliases") or []:
            s = str(al).strip()
            if s:
                hints.add(s)
    return sorted(hints, key=len, reverse=True)


def _slug_for_hint(ledger: dict[str, Any], hint_lower: str) -> str | None:
    for slug, row in ledger.items():
        if not isinstance(row, dict):
            continue
        n = str(row.get("name") or "").strip().lower()
        if n == hint_lower:
            return str(slug)
        for al in row.get("aliases") or []:
            if str(al).strip().lower() == hint_lower:
                return str(slug)
    return None


_DEFER_DETAIL = "available via POST /v1/actor-layer endpoint"

_DEFERRED_ADAPTERS = sorted(
    [
        "internet_archive",
        "chronicling_america",
        "jstor",
        "mysterious_universe",
        "anomalist",
        "cryptomundo",
        "coast_to_coast",
        "singular_fortean",
        "fortean_times",
        "wikidata",
        "wikipedia_refs",
        "web_inference",
    ]
)


def run_actor_layer_fast(narrative: str) -> dict[str, Any]:
    """
    Ledger-only Layer 4: hints from actor-ledger (name + aliases), word-boundary match in narrative.
    No Internet Archive, Chronicling America, RSS, or resolver HTTP. Matches `ActorLayerResult` shape.
    """
    text = narrative.strip()
    root = _repo_root()
    ledger = _load_ledger(root)
    hints = _ledger_search_hints(ledger)
    matched: dict[str, dict[str, Any]] = {}

    for hint in hints:
        try:
            pat = re.compile(r"\b" + re.escape(hint) + r"\b", re.IGNORECASE)
        except re.error:
            continue
        if not pat.search(text):
            continue
        slug = _slug_for_hint(ledger, hint.lower())
        if not slug or slug in matched:
            continue
        row = ledger[slug]
        if not isinstance(row, dict):
            continue
        matched[slug] = {
            "slug": slug,
            "name": row.get("name"),
            "aliases": list(row.get("aliases") or []),
            "events": list(row.get("events") or []),
            "lookup_source": ["ledger"],
        }

    actors_found = sorted(matched.values(), key=lambda x: str(x.get("slug") or ""))

    any_cross = any(
        e.get("confidence_tier") == "cross_corroborated"
        for r in actors_found
        for e in (r.get("events") or [])
        if isinstance(e, dict)
    )
    if actors_found:
        confidence_tier = "cross_corroborated" if any_cross else "single_source"
    else:
        confidence_tier = "structural_heuristic"

    absent_fields: list[str] = []
    if not text:
        absent_fields.append("extracted_candidates")
    elif not actors_found:
        absent_fields.append("ledger_matches")

    sources_checked = [
        {"adapter": ad, "status": "deferred", "detail": _DEFER_DETAIL} for ad in _DEFERRED_ADAPTERS
    ]

    return {
        "actors_found": actors_found,
        "actors_absent": [],
        "confidence_tier": confidence_tier,
        "absent_fields": absent_fields,
        "dynamic_lookups": 0,
        "sources_checked": sources_checked,
    }
