"""
Voting record cross-reference.
Source: ProPublica Congress API (no key required).

What this answers:
- What did this politician vote on?
- When did they receive money from related donors?
- What is the documented sequence of donation → vote?

Frame never says the donation influenced the vote.
Frame documents the sequence and proximity.
The reader concludes.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.parse
import urllib.request
from typing import Any

PROPUBLICA_BASE = "https://api.propublica.org/congress/v1/"


def _propublica_headers() -> dict[str, str]:
    key = os.environ.get("PROPUBLICA_API_KEY", "")
    if key:
        return {"X-API-Key": key}
    return {}


def search_member_by_name(name: str) -> dict[str, Any] | None:
    """
    Find a Congress member by name.
    Returns member_id, chamber, state, party, url.
    """
    try:
        # Search both chambers
        for chamber in ("senate", "house"):
            params = urllib.parse.urlencode({
                "q": name,
            })
            url = (
                f"{PROPUBLICA_BASE}members/search.json?{params}"
            )
            req = urllib.request.Request(
                url,
                headers={
                    **_propublica_headers(),
                    "User-Agent": "Frame/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())

            results = (
                data.get("results", [{}])[0]
                .get("members", [])
            )
            if results:
                m = results[0]
                return {
                    "member_id": m.get("member_id"),
                    "name": m.get("name"),
                    "chamber": chamber,
                    "state": m.get("state"),
                    "party": m.get("party"),
                    "url": m.get("url"),
                }
    except Exception as exc:
        return {"error": str(exc)[:200]}
    return None


def get_recent_votes(member_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """
    Get recent votes for a Congress member.
    Returns bill title, vote position, date, description.
    """
    try:
        url = f"{PROPUBLICA_BASE}members/{member_id}/votes.json"
        req = urllib.request.Request(
            url,
            headers={
                **_propublica_headers(),
                "User-Agent": "Frame/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        votes = (
            data.get("results", [{}])[0]
            .get("votes", [])
        )[:limit]

        return [
            {
                "date": v.get("date"),
                "bill_id": v.get("bill", {}).get("bill_id"),
                "bill_title": v.get("bill", {}).get("title"),
                "position": v.get("position"),
                "description": v.get("description"),
                "question": v.get("question"),
                "session": v.get("session"),
            }
            for v in votes
        ]
    except Exception as exc:
        return [{"error": str(exc)[:200]}]


def get_sponsored_bills(
    member_id: str, limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Get bills sponsored or cosponsored by this member.
    """
    try:
        url = (
            f"{PROPUBLICA_BASE}members/{member_id}"
            f"/bills/sponsored.json"
        )
        req = urllib.request.Request(
            url,
            headers={
                **_propublica_headers(),
                "User-Agent": "Frame/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        bills = (
            data.get("results", [{}])[0]
            .get("bills", [])
        )[:limit]

        return [
            {
                "bill_id": b.get("bill_id"),
                "title": b.get("title"),
                "introduced_date": b.get("introduced_date"),
                "committees": b.get("committees"),
                "primary_subject": b.get("primary_subject"),
                "status": b.get("active"),
            }
            for b in bills
        ]
    except Exception as exc:
        return [{"error": str(exc)[:200]}]


async def run_voting_record(entity_name: str) -> dict[str, Any]:
    """
    Full voting record pull for a politician.
    """
    result: dict[str, Any] = {
        "entity_name": entity_name,
        "member": None,
        "recent_votes": [],
        "sponsored_bills": [],
        "operational_unknowns": [],
    }

    member = await asyncio.to_thread(
        search_member_by_name, entity_name,
    )

    if not member or member.get("error"):
        result["operational_unknowns"].append(
            f"Congress member not found for '{entity_name}'. "
            f"ProPublica API may require PROPUBLICA_API_KEY."
        )
        return result

    result["member"] = member
    member_id = member.get("member_id")

    if not member_id:
        result["operational_unknowns"].append(
            f"No member_id found for '{entity_name}'"
        )
        return result

    votes, bills = await asyncio.gather(
        asyncio.to_thread(get_recent_votes, member_id),
        asyncio.to_thread(get_sponsored_bills, member_id),
    )

    result["recent_votes"] = votes
    result["sponsored_bills"] = bills
    return result
