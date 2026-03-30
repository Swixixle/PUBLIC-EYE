"""
receipt_versioning.py
Schema versioning for PUBLIC EYE receipts.

Drop this file into apps/api/ and import the helpers into report_api.py.

HOW TO INTEGRATE:

1. Copy this file to apps/api/receipt_versioning.py

2. In report_api.py, add near the top:
       from receipt_versioning import stamp_receipt_version, CURRENT_SCHEMA_VERSION

3. In build_extended_report_async (or wherever the final receipt dict is assembled),
   call stamp_receipt_version(receipt_dict) before signing.

4. In verify_record.py, call assert_receipt_version_compatible(receipt_dict)
   before verification so old receipts stay verifiable forever.

VERSIONING POLICY:
    MAJOR bump  → breaking change to signing structure (rare, requires migration)
    MINOR bump  → new fields added (backward compatible)
    PATCH bump  → cosmetic / metadata only changes

Current: 1.0.0
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Version registry
# Each entry documents what changed and when.
# Never remove entries — old receipts must stay verifiable.
# ---------------------------------------------------------------------------

SCHEMA_CHANGELOG = {
    "1.0.0": (
        "2026-03-30",
        "Initial versioned schema. Fields: receipt_id, receipt_type, signed, "
        "timestamp, narrative, confirmed, what_nobody_is_covering, timeline, "
        "sources, global_perspectives, depth_layers.",
    ),
}

CURRENT_SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def stamp_receipt_version(receipt: dict[str, Any]) -> dict[str, Any]:
    """
    Add schema_version to a receipt dict in-place and return it.
    Call this BEFORE the JCS signing step so the version is part of the
    signed payload and therefore tamper-evident.

    Example:
        receipt = build_raw_receipt(...)
        receipt = stamp_receipt_version(receipt)
        signed  = sign_receipt(receipt)
    """
    receipt.setdefault("schema_version", CURRENT_SCHEMA_VERSION)
    return receipt


def assert_receipt_version_compatible(receipt: dict[str, Any]) -> None:
    """
    Raise ValueError if the receipt's schema_version is incompatible
    with the current verifier.

    Compatibility rule: same MAJOR version is always compatible.
    Missing schema_version is treated as "0.x" (pre-versioning) and
    is still accepted with a warning.
    """
    version = receipt.get("schema_version")

    if version is None:
        # Pre-versioning receipt — acceptable, warn only
        import warnings
        warnings.warn(
            "Receipt has no schema_version field. "
            "This is a pre-1.0 receipt and may lack some fields.",
            stacklevel=2,
        )
        return

    if not _is_semver(version):
        raise ValueError(f"Receipt has malformed schema_version: {version!r}")

    receipt_major = int(version.split(".")[0])
    current_major = int(CURRENT_SCHEMA_VERSION.split(".")[0])

    if receipt_major > current_major:
        raise ValueError(
            f"Receipt schema_version {version} is newer than this verifier "
            f"({CURRENT_SCHEMA_VERSION}). Please update PUBLIC EYE."
        )

    if receipt_major < current_major:
        raise ValueError(
            f"Receipt schema_version {version} is from an older major version "
            f"and is no longer supported by this verifier ({CURRENT_SCHEMA_VERSION})."
        )


def describe_version(version: str) -> dict[str, str]:
    """Return the changelog entry for a given version string."""
    entry = SCHEMA_CHANGELOG.get(version)
    if entry is None:
        return {"version": version, "date": "unknown", "description": "No changelog entry."}
    date, description = entry
    return {"version": version, "date": date, "description": description}


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

def _is_semver(s: str) -> bool:
    return bool(_SEMVER_RE.match(s))


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    # Test stamp
    r = {"receipt_id": "abc123", "signed": True}
    stamp_receipt_version(r)
    assert r["schema_version"] == CURRENT_SCHEMA_VERSION
    print("stamp_receipt_version: PASS")

    # Test compatible
    assert_receipt_version_compatible(r)
    print("assert_receipt_version_compatible (current): PASS")

    # Test pre-versioning
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert_receipt_version_compatible({"receipt_id": "old"})
        assert len(w) == 1
    print("assert_receipt_version_compatible (pre-versioning): PASS")

    print("\nAll tests passed.")
    print(f"\nCurrent schema version: {CURRENT_SCHEMA_VERSION}")
    print(json.dumps(describe_version(CURRENT_SCHEMA_VERSION), indent=2))
