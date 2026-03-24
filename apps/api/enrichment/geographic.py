"""
Geographic donor analysis.

A politician represents a specific place.
Their donors may or may not be from that place.
Frame documents the geographic distribution
of their contributions.

Source: FEC schedule_a with state filter.

What this answers:
- What percentage of contributions came from
  the politician's home state?
- What states are the top donor sources?
- Is there a significant gap between where they
  represent and where their money comes from?

No conclusion is drawn from this gap.
The gap is documented as a fact.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.parse
import urllib.request
from typing import Any

FEC_BASE = "https://api.open.fec.gov/v1/"


def get_contributions_by_state(
    committee_id: str,
) -> dict[str, Any]:
    """
    Pull contributions to a committee grouped by state.
    Returns dict of state -> total amount.
    """
    api_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")
    state_totals: dict[str, Any] = {}

    try:
        params = urllib.parse.urlencode({
            "api_key": api_key,
            "committee_id": committee_id,
            "per_page": 100,
        })
        url = f"{FEC_BASE}schedules/schedule_a/?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Frame/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())

        for contrib in data.get("results", []):
            state = str(
                contrib.get("contributor_state") or "unknown",
            ).upper()
            amount = float(
                contrib.get("contribution_receipt_amount") or 0,
            )
            prev = float(state_totals.get(state, 0.0) or 0.0)
            state_totals[state] = prev + amount

    except Exception as exc:
        state_totals["error"] = str(exc)[:200]

    return state_totals


async def run_geographic_analysis(
    entity_name: str,
    home_state: str,
    committee_id: str,
) -> dict[str, Any]:
    """
    Geographic distribution of campaign contributions.
    """
    result: dict[str, Any] = {
        "entity_name": entity_name,
        "home_state": home_state,
        "state_totals": {},
        "home_state_pct": 0.0,
        "top_donor_states": [],
        "operational_unknowns": [],
        "note": (
            "Geographic distribution reflects contributor "
            "addresses as reported to FEC. Out-of-state "
            "contributions are legal and common. "
            "This documents distribution only."
        ),
    }

    if not committee_id:
        result["operational_unknowns"].append(
            "No committee_id available for geographic analysis.",
        )
        return result

    state_totals = await asyncio.to_thread(
        get_contributions_by_state, committee_id,
    )

    if "error" in state_totals:
        result["operational_unknowns"].append(
            f"Geographic lookup failed: {state_totals['error']}",
        )
        return result

    total = sum(
        v for k, v in state_totals.items()
        if k != "error" and isinstance(v, (int, float))
    )
    home_amount = float(
        state_totals.get(home_state.upper(), 0.0) or 0.0,
    )
    home_pct = (
        round(home_amount / total * 100, 1)
        if total > 0 else 0.0
    )

    sorted_states = sorted(
        [
            (k, v) for k, v in state_totals.items()
            if isinstance(v, (int, float))
        ],
        key=lambda x: x[1],
        reverse=True,
    )

    result["state_totals"] = state_totals
    result["total_analyzed"] = round(total, 2)
    result["home_state_amount"] = round(home_amount, 2)
    result["home_state_pct"] = home_pct
    result["top_donor_states"] = [
        {
            "state": s,
            "total": round(float(a), 2),
            "pct_of_analyzed": round(float(a) / total * 100, 1)
            if total > 0 else 0.0,
        }
        for s, a in sorted_states[:10]
    ]

    return result
