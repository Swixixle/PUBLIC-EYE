"""Processing tier configuration (additive; no auth — default PRO)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ProcessingTier(str, Enum):
    FREE = "free"
    STANDARD = "standard"
    PRO = "pro"
    PRESS = "press"


class TierConfig(BaseModel):
    max_duration_seconds: int | None  # None = unlimited
    n_parallel_chunks: int
    dossier_enabled: bool
    opus_narrative: bool
    citation_tracing: bool
    rss_bypass: bool
    layer_zero_only: bool
    api_access: bool = False
    bulk_submission: bool = False
    receipt_export: bool = False


TIER_CONFIGS: dict[ProcessingTier, TierConfig] = {
    ProcessingTier.FREE: TierConfig(
        max_duration_seconds=1800,
        n_parallel_chunks=1,
        dossier_enabled=False,
        opus_narrative=False,
        citation_tracing=False,
        rss_bypass=True,
        layer_zero_only=True,
    ),
    ProcessingTier.STANDARD: TierConfig(
        max_duration_seconds=5400,
        n_parallel_chunks=2,
        dossier_enabled=True,
        opus_narrative=False,
        citation_tracing=False,
        rss_bypass=True,
        layer_zero_only=False,
    ),
    ProcessingTier.PRO: TierConfig(
        max_duration_seconds=None,
        n_parallel_chunks=4,
        dossier_enabled=True,
        opus_narrative=True,
        citation_tracing=True,
        rss_bypass=True,
        layer_zero_only=False,
    ),
    ProcessingTier.PRESS: TierConfig(
        max_duration_seconds=None,
        n_parallel_chunks=4,
        dossier_enabled=True,
        opus_narrative=True,
        citation_tracing=True,
        rss_bypass=True,
        layer_zero_only=False,
        api_access=True,
        bulk_submission=True,
        receipt_export=True,
    ),
}


def get_tier_config(tier: ProcessingTier) -> TierConfig:
    return TIER_CONFIGS[tier]


def resolve_tier(header_value: str | None, query_value: str | None) -> ProcessingTier:
    """
    Read tier from X-Whistle-Tier header or ?tier= query param.
    Default: PRO (no auth yet — all requests get full pipeline).
    Invalid values silently fall back to PRO.
    """
    raw = header_value or query_value or "pro"
    try:
        return ProcessingTier(raw.lower())
    except ValueError:
        return ProcessingTier.PRO
