"""
Stage 3 — Dossier assembly for podcast receipts.
Bridges pod_... receipt IDs to the Frame/dossier system.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def run_stage3_dossier(
    receipt: dict,
    claims: list[dict],
    entities_resolved: list[dict],
    *,
    dossier_enabled: bool = True,
    opus_narrative: bool = True,
) -> dict[str, Any]:
    """
    For each resolved entity from Stage 2, assemble a full dossier.
    Stores dossiers in DB (or in-memory fallback).
    Returns summary of dossiers assembled.

    receipt: the signed receipt dict
    claims: raw claims from extract_speaker_claims
    entities_resolved: list of {entity_name, type, wikidata_id, ein, fec_id}
      from Stage 2 dispatch results
    """
    summary: dict[str, Any] = {
        "dossiers_attempted": 0,
        "dossiers_complete": 0,
        "dossiers_failed": 0,
        "dossier_ids": [],
        "operational_unknowns": [],
    }

    if not dossier_enabled:
        summary["operational_unknowns"].append({
            "text": "Dossier assembly disabled for this processing tier.",
            "resolution_possible": True,
        })
        return summary

    if not entities_resolved:
        summary["operational_unknowns"].append({
            "text": (
                "No named entities with sufficient public record "
                "matches were found for dossier assembly."
            ),
            "resolution_possible": True,
        })
        return summary

    receipt_id = receipt.get("receiptId", f"pod_{uuid.uuid4().hex[:12]}")

    print(
        f"[stage3] starting dossier assembly for {len(entities_resolved)} entities",
    )

    for entity_info in entities_resolved[:3]:  # cap at 3 dossiers
        entity_name = entity_info.get("entity_name") or entity_info.get("entity", "")
        if not entity_name:
            continue

        summary["dossiers_attempted"] += 1

        try:
            dossier_id = await _assemble_one_dossier(
                receipt_id=receipt_id,
                entity_name=entity_name,
                entity_info=entity_info,
                receipt=receipt,
                opus_narrative=opus_narrative,
            )
            summary["dossiers_complete"] += 1
            summary["dossier_ids"].append(dossier_id)
            print(
                f"[stage3] dossier complete: {dossier_id} for '{entity_name}'",
            )
        except Exception as exc:
            summary["dossiers_failed"] += 1
            summary["operational_unknowns"].append({
                "text": (
                    f"Dossier assembly failed for '{entity_name}': "
                    f"{str(exc)[:150]}"
                ),
                "resolution_possible": True,
            })

    return summary


def _frame_uuid_for(receipt_id: str, entity_name: str) -> str:
    """Stable UUID string for DB (frames.id / dossiers.frame_id must be UUID when using Postgres)."""
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"frame:{receipt_id}:{entity_name.strip().lower()}",
        )
    )


async def _assemble_one_dossier(
    receipt_id: str,
    entity_name: str,
    entity_info: dict,
    receipt: dict,
    *,
    opus_narrative: bool = True,
) -> str:
    """
    Build a Frame + ResolvedEntity and run assemble_dossier.
    Returns dossier frame_id.
    """
    from models.frame import Frame
    from models.entity import ResolvedEntity
    from dossier.assemble import assemble_dossier
    from db import save_frame

    frame_id = _frame_uuid_for(receipt_id, entity_name)

    # Build a Frame from the receipt
    first_claim = ""
    if receipt.get("claims"):
        first_claim = str(receipt["claims"][0].get("statement", ""))[:500]

    frame = Frame(
        id=frame_id,
        claim=first_claim or f"Claims about {entity_name}",
        claimant_name=entity_name,
        claimant_role="public figure",
        claimant_organization=entity_info.get("organization", ""),
        timestamp=str(receipt.get("createdAt", _now_iso())),
        hash=str(receipt.get("contentHash", "")),
        signature=str(receipt.get("signature", "")),
        enrichment_status="pending",
    )

    await save_frame(frame)

    entity_type = _infer_entity_type(entity_name, entity_info)
    enrichment_path = _enrichment_path_for_type(entity_type)

    resolved = ResolvedEntity(
        id=f"re_{uuid.uuid4().hex[:12]}",
        canonical_name=entity_name,
        type=entity_type,
        organization=entity_info.get("organization", ""),
        fec_candidate_id=entity_info.get("fec_id"),
        ein=entity_info.get("ein"),
        enrichment_path=enrichment_path,
    )

    dossier = await assemble_dossier(frame_id, resolved, opus_narrative=opus_narrative)
    return dossier.frame_id


def _infer_entity_type(
    name: str,
    info: dict,
) -> str:
    name_lower = name.lower()

    # Check info hints first
    if info.get("fec_id"):
        return "politician"
    if info.get("ein"):
        return "nonprofit"

    # Known executives
    known_exec = [
        "elon musk", "jeff bezos", "mark zuckerberg",
        "bill gates", "tim cook", "larry page",
        "sundar pichai", "satya nadella", "jamie dimon",
    ]
    if name_lower in known_exec:
        return "corporate_exec"

    # Known political donors / hybrid figures
    known_donors = [
        "george soros", "charles koch", "david koch",
        "sheldon adelson", "michael bloomberg",
        "peter thiel", "reid hoffman",
    ]
    if name_lower in known_donors:
        return "corporate_exec"

    # Politician detection — broader patterns
    politician_keywords = [
        "senator", "representative", "congressman",
        "congresswoman", "governor", "mayor",
        "president", "secretary", "admiral", "general",
    ]
    if any(kw in name_lower for kw in politician_keywords):
        return "politician"

    # Common US politician surnames — expand this list
    known_politicians = [
        "rand paul", "paul", "markwayne mullin", "mullin",
        "joe biden", "donald trump", "kamala harris",
        "nancy pelosi", "mitch mcconnell", "chuck schumer",
        "kevin mccarthy", "mike johnson", "bernie sanders",
        "elizabeth warren", "ted cruz", "marco rubio",
        "lindsey graham", "mitt romney", "john mccain",
        "barack obama", "hillary clinton", "mike pence",
        "ron desantis", "gavin newsom", "greg abbott",
        "kirsten gillibrand", "amy klobuchar", "pete buttigieg",
        "tulsi gabbard", "dan crenshaw", "matt gaetz",
        "marjorie taylor greene", "alexandria ocasio-cortez",
        "ilhan omar", "rashida tlaib", "jim jordan",
        "andy biggs", "lauren boebert", "paul gosar",
    ]
    if name_lower in known_politicians:
        return "politician"

    # If name has two words and looks like a person
    # default to politician for public figure context
    parts = name.strip().split()
    if len(parts) == 2 and all(p[0].isupper() for p in parts):
        # Two-word proper name in political context
        # Default to politician to trigger FEC lookup
        return "politician"

    return "other"


def _enrichment_path_for_type(entity_type: str) -> list[str]:
    paths = {
        "corporate_exec": [
            "fec", "sec", "courtlistener", "charitable"
        ],
        "politician": [
            "fec", "opensecrets", "courtlistener",
            "statements", "charitable"
        ],
        "nonprofit": ["charitable", "courtlistener"],
        "influencer": ["socialblade", "courtlistener"],
        "podcaster": ["socialblade", "courtlistener", "fec"],
        "musician": ["courtlistener", "charitable"],
        "other": ["courtlistener", "charitable"],
    }
    return paths.get(entity_type, ["courtlistener"])
