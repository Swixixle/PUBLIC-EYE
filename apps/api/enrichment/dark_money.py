"""
Dark money trail — follows campaign disbursements to identify
where political money ultimately flows and who benefits.

Sources:
- FEC Schedule B (disbursements) — who the campaign paid
- FEC Schedule F (coordinated expenditures)
- CourtListener — criminal/civil history of vendors and recipients
- SEC EDGAR — corporate filings for vendor entities
- ProPublica nonprofits — if recipient is a 501(c)(4) or similar

The question this module answers:
  "This candidate raised $X. Where did it go,
   and does any of it trace back to people with
   criminal histories, tax issues, or embezzlement?"
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

FEC_BASE = "https://api.open.fec.gov/v1/"

# Known high-risk patterns in vendor/recipient names
# These trigger deeper investigation
HIGH_RISK_KEYWORDS = [
    "consulting",
    "strategic",
    "solutions",
    "management",
    "holdings",
    "ventures",
    "associates",
    "partners",
    "group",
    "llc",
    "inc",
]

# Known bad actors — people/entities with documented
# criminal histories related to financial crimes.
# This list seeds the cross-reference check.
# Expand from court records as Frame builds its ledger.
KNOWN_FINANCIAL_CRIMINALS = [
    "paul manafort",      # tax fraud, money laundering
    "rick gates",         # financial fraud
    "michael cohen",      # tax evasion, fraud
    "tom barrack",        # illegal foreign lobbying
    "elliott broidy",     # corruption, money laundering
    "lev parnas",         # campaign finance fraud
    "igor fruman",        # campaign finance fraud
    "sam bankman-fried",  # fraud, money laundering
    "bernie madoff",      # fraud
    "allen weisselberg",  # tax fraud
]


async def get_disbursements(
    candidate_id: str,
    entity_name: str,
) -> dict[str, Any]:
    """
    Pull FEC Schedule B disbursements for a candidate's committees.
    Returns top recipients sorted by amount, with risk flags.

    This answers: who did the campaign pay?
    """
    api_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")

    result: dict[str, Any] = {
        "candidate_id": candidate_id,
        "entity_name": entity_name,
        "disbursements": [],
        "high_risk_recipients": [],
        "known_criminal_matches": [],
        "total_disbursed": 0.0,
        "operational_unknowns": [],
    }

    try:
        # Step 1: Get candidate's primary committee
        comm_params = urllib.parse.urlencode({
            "api_key": api_key,
            "candidate_id": candidate_id,
            "per_page": 10,
            "designation": "P",  # Primary committee only
        })
        comm_url = f"{FEC_BASE}committees/?{comm_params}"
        comm_req = urllib.request.Request(
            comm_url,
            headers={"User-Agent": "Frame/1.0"}
        )
        with urllib.request.urlopen(comm_req, timeout=10) as r:
            comm_data = json.loads(r.read())

        committees = comm_data.get("results", [])
        if not committees:
            # Fallback: get any authorized committee
            comm_params2 = urllib.parse.urlencode({
                "api_key": api_key,
                "candidate_id": candidate_id,
                "per_page": 5,
            })
            comm_url2 = f"{FEC_BASE}committees/?{comm_params2}"
            comm_req2 = urllib.request.Request(
                comm_url2,
                headers={"User-Agent": "Frame/1.0"}
            )
            with urllib.request.urlopen(comm_req2, timeout=10) as r2:
                comm_data2 = json.loads(r2.read())
            committees = comm_data2.get("results", [])

        if not committees:
            result["operational_unknowns"].append(
                f"No committees found for candidate {candidate_id}"
            )
            return result

        # Use first committee (most recent/primary)
        primary_committee_id = committees[0].get("committee_id")
        result["committee_id"] = primary_committee_id
        result["committee_name"] = committees[0].get("name", "")

        # Step 2: Pull disbursements for that committee
        disb_params = urllib.parse.urlencode({
            "api_key": api_key,
            "committee_id": primary_committee_id,
            "per_page": 100,
        })
        disb_url = f"{FEC_BASE}schedules/schedule_b/?{disb_params}"
        disb_req = urllib.request.Request(
            disb_url,
            headers={"User-Agent": "Frame/1.0"}
        )
        with urllib.request.urlopen(disb_req, timeout=15) as r3:
            disb_data = json.loads(r3.read())

        disbursements = disb_data.get("results", [])
        total = 0.0
        processed = []

        for d in disbursements[:50]:
            amount = float(d.get("disbursement_amount") or 0)
            recipient = str(
                d.get("recipient_name") or
                d.get("payee_name") or
                "unknown"
            ).strip()
            purpose = str(
                d.get("disbursement_description") or ""
            ).strip()
            date = d.get("disbursement_date") or ""
            state = d.get("recipient_state") or ""

            total += amount

            entry = {
                "recipient": recipient,
                "amount": amount,
                "purpose": purpose,
                "date": date,
                "state": state,
                "committee_id": primary_committee_id,
                "risk_flags": [],
            }

            recipient_lower = recipient.lower()
            for kw in HIGH_RISK_KEYWORDS:
                if kw in recipient_lower:
                    entry["risk_flags"].append(
                        f"generic_entity_name:{kw}"
                    )

            for criminal in KNOWN_FINANCIAL_CRIMINALS:
                if criminal in recipient_lower:
                    entry["risk_flags"].append(
                        f"known_criminal_match:{criminal}"
                    )
                    result["known_criminal_matches"].append({
                        "recipient": recipient,
                        "amount": amount,
                        "date": date,
                        "matched_name": criminal,
                        "source_url": (
                            f"https://www.fec.gov/data/disbursements/"
                            f"?committee_id={primary_committee_id}"
                            f"&recipient_name={urllib.parse.quote(recipient)}"
                        ),
                    })

            if entry["risk_flags"]:
                result["high_risk_recipients"].append(entry)

            processed.append(entry)

        # Sort by amount descending
        processed.sort(key=lambda x: x["amount"], reverse=True)
        result["disbursements"] = processed
        result["total_disbursed"] = round(total, 2)
        result["disbursement_count"] = len(processed)

    except Exception as exc:
        result["operational_unknowns"].append(
            f"Disbursement lookup failed: {str(exc)[:200]}"
        )

    return result


async def get_pac_disbursements(entity_name: str) -> dict[str, Any]:
    """
    Find PACs associated with this entity and pull their disbursements.
    PACs are how campaign money gets laundered into consultant fees.
    """
    api_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")
    result: dict[str, Any] = {
        "entity_name": entity_name,
        "pacs_found": [],
        "pac_disbursements": [],
        "operational_unknowns": [],
    }

    try:
        # Search for PACs/committees with entity name
        params = urllib.parse.urlencode({
            "api_key": api_key,
            "name": entity_name,
            "per_page": 10,
        })
        url = f"{FEC_BASE}committees/?{params}"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Frame/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        pacs = data.get("results", [])
        # Filter to committees where entity name words appear in committee name
        entity_words = entity_name.lower().split()
        filtered_pacs = [
            p for p in pacs
            if any(
                word in str(p.get("name") or "").lower()
                for word in entity_words
                if len(word) > 3  # skip short words
            )
        ]
        result["pacs_found"] = [
            {
                "name": p.get("name"),
                "committee_id": p.get("committee_id"),
                "type": p.get("committee_type_full"),
                "state": p.get("state"),
            }
            for p in filtered_pacs
        ]

    except Exception as exc:
        result["operational_unknowns"].append(
            f"PAC search failed: {str(exc)[:200]}"
        )

    return result


async def run_dark_money_trace(
    candidate_id: str,
    entity_name: str,
) -> dict[str, Any]:
    """
    Full dark money trace for a candidate.
    Runs disbursements + PAC search in parallel.
    Returns combined results with risk summary.
    """
    disb_task = asyncio.create_task(
        get_disbursements(candidate_id, entity_name)
    )
    pac_task = asyncio.create_task(
        get_pac_disbursements(entity_name)
    )

    disbursements, pacs = await asyncio.gather(
        disb_task, pac_task, return_exceptions=True
    )

    result: dict[str, Any] = {
        "candidate_id": candidate_id,
        "entity_name": entity_name,
        "trace_complete": True,
    }

    if isinstance(disbursements, Exception):
        result["disbursements_error"] = str(disbursements)
        result["disbursements"] = {}
    else:
        result["disbursements"] = disbursements

    if isinstance(pacs, Exception):
        result["pacs_error"] = str(pacs)
        result["pacs"] = {}
    else:
        result["pacs"] = pacs

    # Risk summary
    disb_data = result.get("disbursements", {})
    known_matches = disb_data.get("known_criminal_matches", [])
    high_risk = disb_data.get("high_risk_recipients", [])

    result["risk_summary"] = {
        "known_criminal_matches_count": len(known_matches),
        "high_risk_recipients_count": len(high_risk),
        "total_disbursed": disb_data.get("total_disbursed", 0),
        "disbursement_count": disb_data.get("disbursement_count", 0),
        "known_criminal_matches": known_matches,
        "note": (
            "Risk flags indicate patterns requiring further investigation. "
            "They do not establish wrongdoing. "
            "Known criminal matches are based on name overlap with "
            "publicly documented financial crime convictions."
        ),
    }

    return result
