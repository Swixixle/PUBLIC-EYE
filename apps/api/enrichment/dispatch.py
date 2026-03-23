"""
Stage 2 adapter dispatch — routes extracted entities
to public record adapters and returns enrichment results.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any


async def dispatch_entity_enrichment(
    entities: list[str],
    claims: list[dict],
) -> dict[str, Any]:
    """
    Takes entities and claims from transcript extraction.
    Routes each entity to appropriate adapters.
    Returns enrichment results, additional sources,
    and any new operational unknowns.
    """
    results = {
        "adapter_results": [],
        "additional_sources": [],
        "operational_unknowns": [],
        "epistemic_unknowns": [],
        "verification_notes": [],
    }

    # Deduplicate and clean entities
    clean_entities = list({
        e.strip() for e in entities
        if e and len(e.strip()) > 2
        and e.strip().lower() not in (
            "ngo", "ngos", "non-profit", "nonprofit",
            "the government", "congress", "senate"
        )
    })

    if not clean_entities:
        results["operational_unknowns"].append({
            "text": (
                "No named entities with sufficient specificity "
                "were identified for public record lookup."
            ),
            "resolution_possible": True,
        })
        return results

    # Run enrichment for each entity concurrently
    tasks = [
        _enrich_single_entity(entity, claims)
        for entity in clean_entities[:5]  # cap at 5
    ]
    entity_results = await asyncio.gather(*tasks, return_exceptions=True)

    for entity, result in zip(clean_entities[:5], entity_results):
        if isinstance(result, Exception):
            results["operational_unknowns"].append({
                "text": (
                    f"Public record lookup failed for '{entity}': "
                    f"{str(result)[:150]}"
                ),
                "resolution_possible": True,
            })
        elif result:
            if result.get("sources"):
                results["additional_sources"].extend(result["sources"])
            if result.get("verification_notes"):
                results["verification_notes"].extend(
                    result["verification_notes"]
                )
            if result.get("operational_unknowns"):
                results["operational_unknowns"].extend(
                    result["operational_unknowns"]
                )
            results["adapter_results"].append({
                "entity": entity,
                "adapters_run": result.get("adapters_run", []),
                "found": result.get("found", False),
            })

    # If no named entities produced results, document that
    if not any(r.get("found") for r in results["adapter_results"]):
        results["epistemic_unknowns"].append({
            "text": (
                "The entities referenced in this recording could not "
                "be matched to specific public record entries. "
                "Claims about unnamed organizations or individuals "
                "cannot be verified against public databases."
            ),
            "resolution_possible": False,
        })

    return results


async def _enrich_single_entity(
    entity: str,
    claims: list[dict],
) -> dict[str, Any]:
    """
    Route one entity to appropriate adapters based on
    what type of entity it appears to be.
    """
    result = {
        "entity": entity,
        "adapters_run": [],
        "sources": [],
        "verification_notes": [],
        "operational_unknowns": [],
        "found": False,
    }

    # Determine entity type from name patterns
    is_person = _looks_like_person(entity)
    is_org = not is_person

    # Always try Wikidata for named entities
    try:
        wikidata_result = await asyncio.wait_for(
            asyncio.to_thread(_fetch_wikidata, entity),
            timeout=10.0
        )
        result["adapters_run"].append("wikidata")
        if wikidata_result:
            result["sources"].extend(wikidata_result.get("sources", []))
            result["found"] = True
    except Exception:
        result["operational_unknowns"].append({
            "text": f"Wikidata lookup timed out for '{entity}'.",
            "resolution_possible": True,
        })

    # Try ProPublica 990 for orgs and known philanthropists
    if is_org or _known_philanthropist(entity):
        try:
            nonprofit_result = await asyncio.wait_for(
                asyncio.to_thread(_fetch_990, entity),
                timeout=10.0
            )
            result["adapters_run"].append("propublica_990")
            if nonprofit_result:
                result["sources"].extend(
                    nonprofit_result.get("sources", [])
                )
                result["found"] = True
                # Add verification note if 990 data found
                total = nonprofit_result.get("total_revenue")
                if total:
                    result["verification_notes"].append(
                        f"ProPublica 990 data found for '{entity}': "
                        f"most recent total revenue ${total:,.0f}"
                    )
        except Exception:
            result["operational_unknowns"].append({
                "text": (
                    f"ProPublica 990 lookup failed for '{entity}'. "
                    f"Financial data may be available at "
                    f"projects.propublica.org/nonprofits"
                ),
                "resolution_possible": True,
            })

    # Try FEC for politicians and known political donors
    if _known_political_donor(entity) or _looks_like_politician(entity):
        try:
            fec_result = await asyncio.wait_for(
                asyncio.to_thread(_fetch_fec, entity),
                timeout=10.0
            )
            result["adapters_run"].append("fec")
            if fec_result:
                result["sources"].extend(fec_result.get("sources", []))
                result["found"] = True
                amount = fec_result.get("total_contributions")
                if amount:
                    result["verification_notes"].append(
                        f"FEC records found for '{entity}': "
                        f"${amount:,.0f} in documented contributions"
                    )
        except Exception:
            result["operational_unknowns"].append({
                "text": (
                    f"FEC lookup failed for '{entity}'. "
                    f"Campaign finance data available at fec.gov"
                ),
                "resolution_possible": True,
            })

    return result


def _looks_like_person(name: str) -> bool:
    """Heuristic: does this look like a person's name?"""
    parts = name.strip().split()
    if len(parts) < 2:
        return False
    # Known people
    known_people = [
        "elon musk", "george soros", "donald trump",
        "joe biden", "hillary clinton", "barack obama",
        "bill gates", "mark zuckerberg", "jeff bezos",
    ]
    return name.lower() in known_people or (
        len(parts) == 2 and
        all(p[0].isupper() for p in parts if p)
    )


def _known_philanthropist(name: str) -> bool:
    known = [
        "george soros", "bill gates", "open society",
        "gates foundation", "soros", "ford foundation",
        "rockefeller", "carnegie", "bloomberg",
    ]
    return any(k in name.lower() for k in known)


def _known_political_donor(name: str) -> bool:
    known = [
        "george soros", "elon musk", "koch", "adelson",
        "bloomberg", "saban", "steyer", "mercer",
    ]
    return any(k in name.lower() for k in known)


def _looks_like_politician(name: str) -> bool:
    titles = [
        "senator", "representative", "congressman",
        "governor", "president", "secretary",
    ]
    return any(t in name.lower() for t in titles)


def _fetch_wikidata(entity: str) -> dict:
    """Fetch Wikidata entry for entity. Synchronous."""
    import urllib.request
    import urllib.parse
    import json

    try:
        params = urllib.parse.urlencode({
            "action": "wbsearchentities",
            "search": entity,
            "language": "en",
            "limit": 1,
            "format": "json",
        })
        url = f"https://www.wikidata.org/w/api.php?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Frame/1.0 (fact-checking tool)"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        results = data.get("search", [])
        if not results:
            return {}
        item = results[0]
        return {
            "sources": [{
                "id": f"wd_{item.get('id', '')}",
                "adapter": "wikidata",
                "url": f"https://www.wikidata.org/wiki/{item.get('id','')}",
                "title": f"Wikidata: {item.get('label', entity)}",
                "retrievedAt": _now_iso(),
                "metadata": {
                    "description": item.get("description", ""),
                    "wikidata_id": item.get("id", ""),
                }
            }]
        }
    except Exception:
        return {}


def _fetch_990(entity: str) -> dict:
    """Fetch ProPublica 990 data. Synchronous."""
    import urllib.request
    import urllib.parse
    import json

    try:
        query = urllib.parse.quote(entity)
        url = (
            f"https://projects.propublica.org/nonprofits"
            f"/api/v2/search.json?q={query}"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Frame/1.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        orgs = data.get("organizations", [])
        if not orgs:
            return {}
        org = orgs[0]
        return {
            "sources": [{
                "id": f"pp990_{org.get('ein', '')}",
                "adapter": "propublica",
                "url": (
                    f"https://projects.propublica.org/nonprofits"
                    f"/organizations/{org.get('ein','')}"
                ),
                "title": f"990: {org.get('name', entity)}",
                "retrievedAt": _now_iso(),
                "metadata": {
                    "ein": str(org.get("ein", "")),
                    "state": org.get("state", ""),
                    "ntee_code": org.get("ntee_code", ""),
                    "subsection_code": str(
                        org.get("subsection_code", "")
                    ),
                }
            }],
            "total_revenue": org.get("income_amount"),
        }
    except Exception:
        return {}


def _fetch_fec(entity: str) -> dict:
    """Fetch FEC data for entity. Synchronous."""
    import urllib.request
    import urllib.parse
    import json

    api_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")
    try:
        params = urllib.parse.urlencode({
            "contributor_name": entity,
            "sort": "-contribution_receipt_amount",
            "per_page": 5,
            "api_key": api_key,
        })
        url = (
            f"https://api.open.fec.gov/v1"
            f"/schedules/schedule_a/?{params}"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Frame/1.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        results = data.get("results", [])
        if not results:
            return {}
        total = sum(
            float(r.get("contribution_receipt_amount", 0) or 0)
            for r in results
        )
        return {
            "sources": [{
                "id": f"fec_{entity.replace(' ','_')[:20]}",
                "adapter": "fec",
                "url": (
                    f"https://www.fec.gov/data/receipts/"
                    f"?contributor_name="
                    f"{urllib.parse.quote(entity)}"
                ),
                "title": f"FEC contributions: {entity}",
                "retrievedAt": _now_iso(),
                "metadata": {
                    "top_results_count": str(len(results)),
                    "sample_recipient": (
                        results[0].get(
                            "committee", {}
                        ).get("name", "")
                        if results else ""
                    ),
                }
            }],
            "total_contributions": total,
        }
    except Exception:
        return {}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
