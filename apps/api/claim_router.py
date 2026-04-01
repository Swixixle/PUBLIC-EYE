"""Route extracted article claims to adapter names (aligned with apps/api/adapters + routes)."""

from __future__ import annotations

from typing import Any

_ORG_SUBSTRINGS = (
    "department",
    "agency",
    "corporation",
    "corp",
    " inc",
    "llc",
    "ltd",
    "administration",
    "committee",
    "bureau",
    "office",
    "ministry",
    "pentagon",
    "congress",
    "senate",
    "house",
    "court",
    "government",
)


def subject_looks_like_person(claim: dict[str, Any]) -> bool:
    """
    Heuristic: person names are usually short; orgs often contain institutional tokens.
    Used to route CourtListener for background court checks on people.
    """
    claim_type = str(claim.get("claim_type") or "").lower()
    if claim_type in ("biographical", "rumored"):
        return True
    subject = str(claim.get("subject") or "").strip()
    if not subject:
        return False
    words = subject.split()
    if len(words) > 3:
        return False
    sl = subject.lower()
    if any(tok in sl for tok in _ORG_SUBSTRINGS):
        return False
    return True


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

    if claim_type == "rumored":
        adapters.append("courtlistener")

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

    if subject_looks_like_person(claim) and "courtlistener" not in adapters:
        adapters.append("courtlistener")

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
        if str(claim.get("claim_type") or "").lower() == "rumored":
            body = str(claim.get("claim") or "")
            return f"{subject} {body[:100]}".strip() or (subject or body)
        return subject or text
    if adapter == "actor":
        subject_str = (subject or text) or ""
        return (
            f"{subject_str} is a named entity referenced in this public record. {subject_str}."
        )
    if adapter == "surface":
        return subject or text

    return text
