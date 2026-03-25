"""Five-ring extended report: assemble surface, spread, origin, actor, pattern layers into one payload."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from actor_layer_api import run_actor_layer
from origin_api import run_origin
from pattern_api import run_pattern_match
from spread_api import run_spread
from surface_adapter import run_surface_layer


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source(
    sid: str,
    adapter: str,
    url: str,
    title: str,
    retrieved_at: str,
) -> dict[str, Any]:
    return {
        "id": sid,
        "adapter": adapter,
        "url": url,
        "title": title,
        "retrievedAt": retrieved_at,
    }


def _safe_run(
    fn: Callable[..., dict[str, Any]],
    *args: Any,
) -> tuple[dict[str, Any], list[str]]:
    try:
        data = fn(*args)
        absent = list(data.get("absent_fields") or [])
        return data, absent
    except Exception as exc:
        err = str(exc)
        return (
            {
                "error": err,
                "absent_fields": ["adapter_failed"],
            },
            ["adapter_failed"],
        )


def build_extended_report(narrative: str) -> dict[str, Any]:
    """
    Build unsigned ExtendedReportPayload: five rings, merged unknowns, provenance rows per ring.
    """
    text = narrative.strip()
    now = _now_iso()
    rid = str(uuid.uuid4())

    surface, surface_absent = _safe_run(run_surface_layer, {"narrative": text})
    spread, spread_absent = _safe_run(run_spread, text)
    origin, origin_absent = _safe_run(run_origin, text)
    actor, actor_absent = _safe_run(run_actor_layer, text)
    pattern, pattern_absent = _safe_run(run_pattern_match, text)

    s_tier = str(surface.get("what_confidence_tier") or "structural_heuristic")
    p_tier = str(spread.get("confidence_tier") or "structural_heuristic")
    o_tier = str(origin.get("confidence_tier") or "structural_heuristic")
    a_tier = str(actor.get("confidence_tier") or "structural_heuristic")
    if pattern.get("matches"):
        pat_tier = "PATTERN_MATCH"
    else:
        pat_tier = "structural_heuristic"

    repo_ref = "https://github.com/Swixixle/FRAME"
    rings: list[dict[str, Any]] = [
        {
            "ring": 1,
            "title": "Surface",
            "content": surface,
            "confidence_tier": s_tier,
            "absent_fields": surface_absent,
            "sources": [
                _source(
                    "ring-1-layer-surface",
                    "layer_surface",
                    repo_ref,
                    "Layer 1 — surface adapter (Frame)",
                    now,
                ),
            ]
            + (
                [
                    _source(
                        "ring-1-input-url",
                        "layer_surface",
                        str(surface.get("source_url")),
                        "Resolved input URL for surface extraction",
                        now,
                    )
                ]
                if surface.get("source_url")
                else []
            ),
        },
        {
            "ring": 2,
            "title": "Spread",
            "content": spread,
            "confidence_tier": p_tier,
            "absent_fields": spread_absent,
            "sources": [
                _source(
                    "ring-2-layer-spread",
                    "layer_spread",
                    repo_ref,
                    "Layer 2 — spread heuristic (Frame)",
                    now,
                ),
            ],
        },
        {
            "ring": 3,
            "title": "Origin",
            "content": origin,
            "confidence_tier": o_tier,
            "absent_fields": origin_absent,
            "sources": [
                _source(
                    "ring-3-layer-origin",
                    "layer_origin",
                    repo_ref,
                    "Layer 3 — origin heuristic (Frame)",
                    now,
                ),
            ],
        },
        {
            "ring": 4,
            "title": "Actor layer",
            "content": actor,
            "confidence_tier": a_tier,
            "absent_fields": actor_absent,
            "sources": [
                _source(
                    "ring-4-layer-actor",
                    "layer_actor",
                    repo_ref,
                    "Layer 4 — actor ledger + dynamic stack (Frame)",
                    now,
                ),
            ],
        },
        {
            "ring": 5,
            "title": "Pattern match",
            "content": {
                "pattern_result": pattern,
                "citations": [
                    {
                        "pattern_id": m.get("pattern_id"),
                        "criteria_met": m.get("criteria_met") or [],
                    }
                    for m in (pattern.get("matches") or [])
                ],
            },
            "confidence_tier": pat_tier,
            "absent_fields": list(
                dict.fromkeys(
                    (pattern_absent or [])
                    + (["no_pattern_match"] if not pattern.get("matches") else [])
                )
            ),
            "sources": [
                _source(
                    "ring-5-layer-pattern",
                    "layer_pattern",
                    repo_ref,
                    "Layer 5 — pattern catalog match (Frame)",
                    now,
                ),
                _source(
                    "ring-5-pattern-library",
                    "pattern_library",
                    f"{repo_ref}/blob/main/packages/pattern-lib/patterns.json",
                    "Signed pattern library (repository path)",
                    now,
                ),
            ],
        },
    ]

    operational: list[dict[str, Any]] = []
    epistemic: list[dict[str, Any]] = []

    for r in rings:
        for af in r.get("absent_fields") or []:
            operational.append(
                {
                    "text": f"Ring {r['ring']} ({r['title']}): gap or absence — {af}",
                    "resolution_possible": True,
                }
            )

    if pattern.get("no_match_reason"):
        epistemic.append(
            {
                "text": str(pattern["no_match_reason"]),
                "resolution_possible": False,
            }
        )

    return {
        "report_id": rid,
        "generated_at": now,
        "narrative": text,
        "rings": rings,
        "signed": False,
        "signature": None,
        "unknowns": {
            "operational": operational,
            "epistemic": epistemic,
        },
    }
