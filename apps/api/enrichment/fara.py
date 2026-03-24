"""
FARA — Foreign Agents Registration Act.
Source: DOJ FARA database (public).

What this answers:
- Is this entity or anyone connected to them
  registered as a foreign agent?
- Which foreign principals are they representing?
- What activities have they disclosed?

Being a registered foreign agent is not illegal.
Failing to register when required is.
Frame documents registration status only.
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request
from typing import Any

FARA_BASE = "https://efile.fara.gov/api/v1/"


def search_fara_registrants(name: str) -> list[dict[str, Any]]:
    """
    Search FARA registrants by name.
    Returns registrant name, address, foreign principal,
    registration date, termination date if any.
    """
    try:
        params = urllib.parse.urlencode({
            "name": name,
            "activeonly": "false",
        })
        url = f"{FARA_BASE}Registrants.json?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Frame/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        registrants = data.get("REGISTRANTS", {}).get(
            "REGISTRANT", [],
        )
        if isinstance(registrants, dict):
            registrants = [registrants]

        return [
            {
                "registrant_name": reg.get("REGISTRANTNAME"),
                "registration_number": reg.get("REGISTRANTID"),
                "address": reg.get("ADDRESS"),
                "registration_date": reg.get("REGDATE"),
                "termination_date": reg.get("TERMDATE"),
                "active": not bool(reg.get("TERMDATE")),
                "fara_url": (
                    f"https://efile.fara.gov/ords/fara/f?"
                    f"p=181:200:0::NO:RP,200:"
                    f"P200_REG_NUMBER:{reg.get('REGISTRANTID')}"
                ),
            }
            for reg in registrants[:10]
        ]
    except Exception as exc:
        return [{"error": str(exc)[:200]}]


def search_fara_principals(name: str) -> list[dict[str, Any]]:
    """
    Search by foreign principal name.
    Who is lobbying on behalf of this foreign entity?
    """
    try:
        params = urllib.parse.urlencode({
            "foreignprincipalname": name,
        })
        url = f"{FARA_BASE}ForeignPrincipals.json?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Frame/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        principals = data.get(
            "FOREIGN_PRINCIPALS", {},
        ).get("FOREIGN_PRINCIPAL", [])
        if isinstance(principals, dict):
            principals = [principals]

        return [
            {
                "principal_name": p.get("FOREIGNPRINCIPALNAME"),
                "country": p.get("COUNTRY"),
                "registrant_name": p.get("REGISTRANTNAME"),
                "registration_date": p.get("REGISTRATIONDATE"),
                "termination_date": p.get("TERMINATIONDATE"),
            }
            for p in principals[:10]
        ]
    except Exception as exc:
        return [{"error": str(exc)[:200]}]


async def run_fara_check(entity_name: str) -> dict[str, Any]:
    """
    Full FARA check for an entity.
    Checks both as registrant and as principal.
    """
    result: dict[str, Any] = {
        "entity_name": entity_name,
        "as_registrant": [],
        "as_principal": [],
        "is_registered_foreign_agent": False,
        "operational_unknowns": [],
        "note": (
            "FARA registration is a legal disclosure "
            "requirement, not evidence of wrongdoing. "
            "Failure to register when required is a "
            "federal crime under 22 U.S.C. Section 612."
        ),
    }

    registrants, principals = await asyncio.gather(
        asyncio.to_thread(search_fara_registrants, entity_name),
        asyncio.to_thread(search_fara_principals, entity_name),
    )

    result["as_registrant"] = [
        r for r in registrants if not r.get("error")
    ]
    result["as_principal"] = [
        p for p in principals if not p.get("error")
    ]
    result["is_registered_foreign_agent"] = bool(
        result["as_registrant"],
    )

    return result
