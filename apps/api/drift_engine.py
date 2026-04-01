"""Compare two article-analysis receipts for narrative drift (framing / consensus shifts)."""

from __future__ import annotations

from typing import Any


def compute_drift(original_receipt: dict[str, Any], new_receipt: dict[str, Any]) -> dict[str, Any]:
    """
    Compare two receipts for the same article URL.
    Returns drift analysis dict suitable for drift_snapshots rows and API JSON.
    """
    orig_gp = original_receipt.get("global_perspectives") or {}
    new_gp = new_receipt.get("global_perspectives") or {}
    if not isinstance(orig_gp, dict):
        orig_gp = {}
    if not isinstance(new_gp, dict):
        new_gp = {}

    orig_ecosystems = {e["id"]: e for e in orig_gp.get("ecosystems", []) if isinstance(e, dict) and e.get("id")}
    new_ecosystems = {e["id"]: e for e in new_gp.get("ecosystems", []) if isinstance(e, dict) and e.get("id")}

    orig_outlets: set[str] = set()
    new_outlets: set[str] = set()
    for e in orig_gp.get("ecosystems", []) or []:
        if isinstance(e, dict):
            for o in e.get("outlets") or []:
                if o:
                    orig_outlets.add(str(o).strip())
    for e in new_gp.get("ecosystems", []) or []:
        if isinstance(e, dict):
            for o in e.get("outlets") or []:
                if o:
                    new_outlets.add(str(o).strip())

    outlets_added = list(new_outlets - orig_outlets)
    outlets_dropped = list(orig_outlets - new_outlets)

    orig_consensus = {str(x) for x in (orig_gp.get("consensus_elements") or []) if x}
    new_consensus = {str(x) for x in (new_gp.get("consensus_elements") or []) if x}
    orig_contested = {str(x) for x in (orig_gp.get("divergence_points") or []) if x}
    new_contested = {str(x) for x in (new_gp.get("divergence_points") or []) if x}

    consensus_formed = list(orig_contested & new_consensus)
    newly_contested = list(orig_consensus & new_contested)

    framing_changes: list[dict[str, Any]] = []
    for eco_id in set(orig_ecosystems.keys()) & set(new_ecosystems.keys()):
        o = orig_ecosystems[eco_id]
        n = new_ecosystems[eco_id]
        orig_lang = set(str(x) for x in (o.get("key_language") or []) if x)
        new_lang = set(str(x) for x in (n.get("key_language") or []) if x)
        added_terms = list(new_lang - orig_lang)
        dropped_terms = list(orig_lang - new_lang)
        if added_terms or dropped_terms:
            framing_changes.append(
                {
                    "ecosystem": eco_id,
                    "added_language": added_terms,
                    "dropped_language": dropped_terms,
                }
            )

    drift_score = min(
        100.0,
        float(
            len(outlets_added) * 3
            + len(outlets_dropped) * 3
            + len(consensus_formed) * 10
            + len(newly_contested) * 15
            + len(framing_changes) * 8
        ),
    )

    changes: list[str] = []
    if outlets_added:
        changes.append(f"{len(outlets_added)} new outlet(s) covering this story")
    if consensus_formed:
        changes.append(f"{len(consensus_formed)} previously contested point(s) reached consensus")
    if newly_contested:
        changes.append(f"{len(newly_contested)} previously agreed point(s) became contested")
    if framing_changes:
        changes.append(f"framing language shifted in {len(framing_changes)} ecosystem(s)")

    drift_summary = (
        "No significant drift detected."
        if not changes
        else "Coverage has shifted: " + "; ".join(changes) + "."
    )

    oe = original_receipt.get("echo_chamber") if isinstance(original_receipt.get("echo_chamber"), dict) else {}
    ne = new_receipt.get("echo_chamber") if isinstance(new_receipt.get("echo_chamber"), dict) else {}

    return {
        "drift_score": drift_score,
        "drift_summary": drift_summary,
        "outlets_added": outlets_added,
        "outlets_dropped": outlets_dropped,
        "consensus_formed": consensus_formed,
        "newly_contested": newly_contested,
        "framing_changes": framing_changes,
        "framing_before": {
            "key_language": [
                kw
                for e in orig_gp.get("ecosystems", [])
                if isinstance(e, dict)
                for kw in (e.get("key_language") or [])
            ],
            "divergence_score": oe.get("score"),
        },
        "framing_after": {
            "key_language": [
                kw
                for e in new_gp.get("ecosystems", [])
                if isinstance(e, dict)
                for kw in (e.get("key_language") or [])
            ],
            "divergence_score": ne.get("score"),
        },
    }
