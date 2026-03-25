"""
Depth map — six stacked jurisdictions. Kept in sync with `packages/types/src/depth.ts`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_DEPTH_LAYERS: list[dict[str, Any]] = [
    {
        "layer_number": 1,
        "layer_name": "Surface",
        "contents": (
            "Public-facing appearances: filings, registries, and crawlable primary pages "
            "that establish what is openly asserted without inferring motive."
        ),
        "confidence_tiers_allowed": [
            "official_primary",
            "official_secondary",
            "aggregated_registry",
        ],
        "adapter": "surface_adapter",
        "depth_available": True,
        "depth_limit_reason": None,
    },
    {
        "layer_number": 2,
        "layer_name": "Spread",
        "contents": (
            "Diffusion and syndication: how statements and documents propagate across "
            "outlets, mirrors, and aggregators relative to an anchor record."
        ),
        "confidence_tiers_allowed": [
            "official_secondary",
            "aggregated_registry",
            "cross_corroborated",
        ],
        "adapter": "spread_adapter",
        "depth_available": True,
        "depth_limit_reason": None,
    },
    {
        "layer_number": 3,
        "layer_name": "Origin",
        "contents": (
            "Provenance anchors: earliest retrievable artifact, filing identity, and "
            "chain-of-custody hints in the public record."
        ),
        "confidence_tiers_allowed": [
            "official_primary",
            "official_secondary",
            "cross_corroborated",
        ],
        "adapter": "origin_adapter",
        "depth_available": True,
        "depth_limit_reason": None,
    },
    {
        "layer_number": 4,
        "layer_name": "Actor",
        "contents": (
            "Named entities and roles: committees, employers, titles, and disclosed "
            "relationships as they appear in authoritative or corroborated sources."
        ),
        "confidence_tiers_allowed": [
            "aggregated_registry",
            "cross_corroborated",
            "single_source",
        ],
        "adapter": "actor_adapter",
        "depth_available": True,
        "depth_limit_reason": None,
    },
    {
        "layer_number": 5,
        "layer_name": "Pattern",
        "contents": (
            "Recurrence structure: timing clusters, repeated pairings, and schedule-level "
            "regularities constrained to what the record supports."
        ),
        "confidence_tiers_allowed": [
            "cross_corroborated",
            "single_source",
            "structural_heuristic",
        ],
        "adapter": "pattern_adapter",
        "depth_available": True,
        "depth_limit_reason": None,
    },
    {
        "layer_number": 6,
        "layer_name": "Comparative Jurisdiction",
        "contents": (
            "Cross-border and non-U.S. registry alignment: comparable disclosures, foreign "
            "corporate filings, and treaty-visible instruments when adapters exist."
        ),
        "confidence_tiers_allowed": [
            "official_primary",
            "cross_corroborated",
            "structural_heuristic",
        ],
        "adapter": "jurisdiction_adapter",
        "depth_available": False,
        "depth_limit_reason": "International source adapters not yet built",
    },
]


def get_depth_map_payload() -> dict[str, Any]:
    """Public shape for GET /v1/depth-map."""
    return {
        "layers": _DEPTH_LAYERS,
        "layer_count": len(_DEPTH_LAYERS),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
