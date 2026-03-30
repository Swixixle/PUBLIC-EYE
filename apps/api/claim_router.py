"""Route extracted article claims to adapter names (aligned with apps/api/adapters + routes)."""

from __future__ import annotations

from typing import Any


def route_claim(claim: dict[str, Any]) -> list[str]:
    """
    Given a claim dict from claim_extractor, return list of adapter names to query.
    Adapters match what already exists in apps/api/adapters/ and the existing endpoint map.
   
    Note: `main.py` also imports `route_claim` from `router` (OCR/media pipeline). Import this
    module's symbols with an alias when both are needed.
    """
    claim_type = claim.get("claim_type", "")
    text = (claim.get("claim") or "").lower()

    adapters: list[str] = []

    if claim_type == "financial" or any(
        w in text
        for w in [
            "donation",
            "contribution",
            "campaign finance",
            "pac",
            "super pac",
            "funded",
            "spent",
            "raised",
            "lobbying",
            "lobbyist",
        ]
    ):
        adapters.append("fec")

    if claim_type == "legislative" or any(
        w in text
        for w in [
            "bill",
            "act",
            "senate",
            "house",
            "congress",
            "legislation",
            "vote",
            "passed",
            "signed",
            "law",
            "amendment",
        ]
    ):
        adapters.append("congress")

    if claim_type == "judicial" or any(
        w in text
        for w in [
            "court",
            "ruling",
            "judge",
            "justice",
            "opinion",
            "decision",
            "lawsuit",
            "case",
            "appeal",
            "supreme court",
            "circuit",
        ]
    ):
        adapters.append("courtlistener")

    if claim_type == "biographical" or claim.get("subject"):
        adapters.append("actor")
        adapters.append("surface")

    if claim_type == "institutional":
        adapters.append("surface")

    if not adapters:
        adapters.append("surface")

    return list(dict.fromkeys(adapters))


def build_query_for_adapter(claim: dict[str, Any], adapter: str) -> str:
    """Build an adapter-specific query string from a claim."""
    subject = claim.get("subject", "")
    text = claim.get("claim", "")

    if adapter == "fec":
        return subject or text
    if adapter == "congress":
        return text
    if adapter == "courtlistener":
        return subject or text
    if adapter in ("actor", "surface"):
        return subject or text

    return text
