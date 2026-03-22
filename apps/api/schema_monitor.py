# schema_monitor.py
# Schema baseline capture and fingerprinting for Rule Change Receipt monitoring.
#
# Purpose: detect when an external API changes its response structure.
# Content changes (different values) are expected and ignored.
# Structure changes (fields added, removed, type changed) are significant.
#
# This module handles: capture, storage, fingerprinting.
# Monitoring (comparison + Rule Change Receipt generation) comes later.
#
# Baselines stored in: apps/api/baselines/
# Each baseline is a signed Frame receipt documenting the schema at capture time.

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

BASELINES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baselines")
SCHEMA_MONITOR_VERSION = "schema_monitor_v1"


# ─────────────────────────────────────────
# PATH NORMALIZATION
# ─────────────────────────────────────────


def _normalize_field_name(name: str) -> str:
    """
    Normalize a field name to snake_case for cross-format comparison.

    Rules (applied in order):
    1. Unicode normalize
    2. Split camelCase and PascalCase on boundaries
    3. Split on existing separators (-, _, space)
    4. Lowercase all parts
    5. Rejoin with underscore
    """
    name = unicodedata.normalize("NFC", name)

    # Insert underscore before uppercase runs following lowercase
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    # Insert underscore before uppercase followed by lowercase (PascalCase interior)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    # Replace hyphens, spaces with underscore
    name = re.sub(r"[-\s]+", "_", name)
    # Lowercase
    name = name.lower()
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores
    name = name.strip("_")

    return name


def _scalar_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "unknown"


def _extract_schema(data: Any, path: str = "") -> list[dict[str, Any]]:
    """
    Recursively extract the structural schema of a response.
    Returns a list of dicts: {path, node_type, scalar_type, cardinality}

    Content values are discarded. Only structure is retained.
    Array indices are replaced with [].
    Field names are normalized.
    """
    tuples: list[dict[str, Any]] = []

    if isinstance(data, dict):
        for key, value in data.items():
            normalized_key = _normalize_field_name(str(key))
            child_path = f"{path}.{normalized_key}" if path else normalized_key

            if isinstance(value, dict):
                tuples.append(
                    {
                        "path": child_path,
                        "node_type": "object",
                        "scalar_type": None,
                        "cardinality": "single",
                    },
                )
                tuples.extend(_extract_schema(value, child_path))

            elif isinstance(value, list):
                tuples.append(
                    {
                        "path": f"{child_path}[]",
                        "node_type": "array",
                        "scalar_type": None,
                        "cardinality": "repeated",
                    },
                )
                # Sample first element for type info
                if value and len(value) > 0:
                    tuples.extend(_extract_schema(value[0], f"{child_path}[]"))

            else:
                tuples.append(
                    {
                        "path": child_path,
                        "node_type": "scalar",
                        "scalar_type": _scalar_type(value),
                        "cardinality": "single",
                    },
                )

    elif isinstance(data, list):
        if data:
            tuples.extend(_extract_schema(data[0], path + "[]"))

    return tuples


# ─────────────────────────────────────────
# FINGERPRINTING
# ─────────────────────────────────────────

# Critical fields per adapter — losing these means Frame is missing data it needs
CRITICAL_FIELDS: dict[str, set[str]] = {
    "fec": {
        "candidate_id",
        "name",
        "total_receipts",
        "total_disbursements",
        "election_years",
        "office",
        "party",
        "state",
    },
    "lda": {
        "registrant_name",
        "client_name",
        "filing_year",
        "amount",
        "specific_issues",
    },
    "propublica_990": {
        "organization",
        "ein",
        "tax_period",
        "total_assets",
        "total_revenue",
        "total_functional_expenses",
    },
    "wikidata": {
        "id",
        "labels",
        "descriptions",
        "claims",
    },
    "meta_ad_library": {
        "id",
        "funding_entity",
        "spend",
        "impressions",
        "ad_delivery_start_time",
        "page_name",
    },
}


def fingerprint_schema(
    schema_tuples: list[dict[str, Any]],
    source_id: str,
) -> dict[str, Any]:
    """
    Generate two fingerprints from a schema tuple set:
    - full_schema_hash: all fields
    - critical_fields_hash: only fields designated critical for this adapter

    Returns dict with both hashes and the sorted tuple list.
    """
    # Sort for determinism
    sorted_tuples = sorted(schema_tuples, key=lambda t: t["path"])

    # Full schema fingerprint
    full_lines = [
        f"{t['path']}|{t['node_type']}|{t['scalar_type']}|{t['cardinality']}"
        for t in sorted_tuples
    ]
    full_hash = hashlib.sha256("\n".join(full_lines).encode()).hexdigest()

    # Critical fields fingerprint
    critical = CRITICAL_FIELDS.get(source_id, set())
    critical_tuples = [t for t in sorted_tuples if any(c in t["path"] for c in critical)]
    critical_lines = [
        f"{t['path']}|{t['node_type']}|{t['scalar_type']}|{t['cardinality']}"
        for t in critical_tuples
    ]
    critical_hash = hashlib.sha256("\n".join(critical_lines).encode()).hexdigest()

    return {
        "full_schema_hash": full_hash,
        "critical_fields_hash": critical_hash,
        "schema_tuples": sorted_tuples,
        "critical_tuples": critical_tuples,
        "field_count": len(sorted_tuples),
        "critical_field_count": len(critical_tuples),
    }


# ─────────────────────────────────────────
# STORAGE
# ─────────────────────────────────────────


def ensure_baselines_dir() -> None:
    os.makedirs(BASELINES_DIR, exist_ok=True)


def baseline_exists(source_id: str) -> bool:
    path = os.path.join(BASELINES_DIR, f"baseline_{source_id}.json")
    return os.path.exists(path)


def load_baseline(source_id: str) -> dict[str, Any] | None:
    path = os.path.join(BASELINES_DIR, f"baseline_{source_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_baseline(source_id: str, baseline_doc: dict[str, Any]) -> None:
    """
    Save baseline as a JSON document.
    Overwrites only if this is the first capture (genesis).
    Subsequent captures append to version history.
    """
    ensure_baselines_dir()
    path = os.path.join(BASELINES_DIR, f"baseline_{source_id}.json")

    if os.path.exists(path):
        # Load existing and append to version history
        with open(path, encoding="utf-8") as f:
            existing = json.load(f)

        # Keep genesis, update current, append to history
        if "version_history" not in existing:
            existing["version_history"] = []

        existing["version_history"].append(
            {
                "captured_at": existing.get("captured_at"),
                "full_schema_hash": existing.get("full_schema_hash"),
                "critical_fields_hash": existing.get("critical_fields_hash"),
            },
        )

        existing.update(baseline_doc)
        existing["version_history_count"] = len(existing["version_history"])

        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    else:
        # First capture — genesis
        baseline_doc["is_genesis"] = True
        baseline_doc["version_history"] = []
        baseline_doc["version_history_count"] = 0
        with open(path, "w", encoding="utf-8") as f:
            json.dump(baseline_doc, f, indent=2)


# ─────────────────────────────────────────
# CAPTURE (main entry point)
# ─────────────────────────────────────────


def capture_baseline(
    source_id: str,
    sample_response: Any,
    endpoint_description: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Capture a schema baseline from a sample API response.

    source_id: identifier for this source (e.g. "fec", "lda")
    sample_response: actual API response data (content will be discarded)
    endpoint_description: human-readable description of what was queried
    overwrite: if True, always capture; if False, skip if genesis exists

    Returns the baseline document.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Extract and fingerprint
    schema_tuples = _extract_schema(sample_response)
    fingerprint = fingerprint_schema(schema_tuples, source_id)

    baseline_doc: dict[str, Any] = {
        "source_id": source_id,
        "captured_at": timestamp,
        "endpoint_description": endpoint_description,
        "schema_monitor_version": SCHEMA_MONITOR_VERSION,
        "full_schema_hash": fingerprint["full_schema_hash"],
        "critical_fields_hash": fingerprint["critical_fields_hash"],
        "field_count": fingerprint["field_count"],
        "critical_field_count": fingerprint["critical_field_count"],
        "schema_tuples": fingerprint["schema_tuples"],
        "critical_tuples": fingerprint["critical_tuples"],
    }

    if not overwrite and baseline_exists(source_id):
        existing = load_baseline(source_id)
        if existing is None:
            save_baseline(source_id, baseline_doc)
            return baseline_doc
        # Check if schema changed
        if existing.get("full_schema_hash") == fingerprint["full_schema_hash"]:
            existing["last_verified_at"] = timestamp
            path = os.path.join(BASELINES_DIR, f"baseline_{source_id}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
            return existing
        # Schema changed — significant; Rule Change Receipt in a later task
        baseline_doc["previous_full_hash"] = existing.get("full_schema_hash")
        baseline_doc["schema_changed"] = True
        baseline_doc["change_detected_at"] = timestamp

    save_baseline(source_id, baseline_doc)
    return baseline_doc


def compare_to_baseline(source_id: str, current_response: Any) -> dict[str, Any]:
    """
    Compare a current API response to the stored baseline.
    Returns comparison result with change classification.

    Full confirmation logic (sequential probes) is in Rule Change Receipt — not yet built.
    """
    existing = load_baseline(source_id)
    if not existing:
        return {
            "status": "no_baseline",
            "source_id": source_id,
            "note": "No baseline exists for this source. Run capture first.",
        }

    schema_tuples = _extract_schema(current_response)
    fingerprint = fingerprint_schema(schema_tuples, source_id)

    full_changed = fingerprint["full_schema_hash"] != existing.get("full_schema_hash")
    critical_changed = fingerprint["critical_fields_hash"] != existing.get("critical_fields_hash")

    if not full_changed:
        return {
            "status": "unchanged",
            "source_id": source_id,
            "full_schema_hash": fingerprint["full_schema_hash"],
            "baseline_captured_at": existing.get("captured_at"),
        }

    # Find what changed
    old_paths = {t["path"] for t in existing.get("schema_tuples", [])}
    new_paths = {t["path"] for t in schema_tuples}

    removed = sorted(old_paths - new_paths)
    added = sorted(new_paths - old_paths)

    crit = CRITICAL_FIELDS.get(source_id, set())

    # Classify severity
    if critical_changed and removed:
        severity = (
            "critical"
            if any(any(c in r for c in crit) for r in removed)
            else "high"
        )
    elif removed:
        severity = "high"
    elif added:
        severity = "low"
    else:
        severity = "medium"

    return {
        "status": "changed",
        "source_id": source_id,
        "severity": severity,
        "full_schema_changed": full_changed,
        "critical_fields_changed": critical_changed,
        "fields_removed": removed,
        "fields_added": added,
        "current_full_hash": fingerprint["full_schema_hash"],
        "baseline_full_hash": existing.get("full_schema_hash"),
        "baseline_captured_at": existing.get("captured_at"),
        "note": "Schema change detected. Rule Change Receipt logic not yet implemented.",
    }
