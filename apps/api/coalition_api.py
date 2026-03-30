"""Coalition map routes: async generation + GET by receipt_id.

Lives in apps/api/ (flat layout — not app/routers/).
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse

from coalition_service import run_coalition_generation
from models.coalition_map import CoalitionMapPostBody
from receipt_store import delete_coalition_map
from receipt_store import get_coalition_map as load_coalition_payload
from receipt_store import get_receipt

router = APIRouter(tags=["coalition-map"])

_inflight: set[str] = set()
_lock = threading.Lock()


@router.post("/coalition-map", response_model=None)
async def post_coalition_map(
    body: CoalitionMapPostBody,
    background_tasks: BackgroundTasks,
) -> None:
    rid = body.receipt_id.strip()
    if not rid:
        raise HTTPException(status_code=400, detail="receipt_id is required")

    existing = await asyncio.to_thread(load_coalition_payload, rid)
    if existing:
        return existing

    receipt = await asyncio.to_thread(get_receipt, rid)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    gp = receipt.get("global_perspectives") or {}
    if not isinstance(gp, dict):
        gp = {}
    if not gp.get("ecosystems") and not gp.get("most_divergent_pair") and not gp.get(
        "most_irreconcilable",
    ):
        raise HTTPException(
            status_code=400,
            detail="Receipt has no global perspectives for coalition map",
        )

    with _lock:
        if rid in _inflight:
            return JSONResponse(
                status_code=202,
                content={"receipt_id": rid, "status": "processing"},
            )
        _inflight.add(rid)

    def _job() -> None:
        try:
            run_coalition_generation(rid)
        finally:
            with _lock:
                _inflight.discard(rid)

    background_tasks.add_task(_job)
    return JSONResponse(
        status_code=202,
        content={"receipt_id": rid, "status": "processing"},
    )


@router.get("/coalition-map/{receipt_id}", response_model=None)
async def get_coalition_map_by_receipt(receipt_id: str):
    row = await asyncio.to_thread(load_coalition_payload, receipt_id.strip())
    if not row:
        raise HTTPException(status_code=404, detail="Coalition map not found")
    return row


@router.delete("/coalition-map/{receipt_id}", response_model=None)
async def delete_coalition_map_route(receipt_id: str) -> dict[str, Any]:
    """Delete stored map so POST /coalition-map can regenerate (Sprint 1A)."""
    rid = receipt_id.strip()
    if not rid:
        raise HTTPException(status_code=400, detail="receipt_id is required")
    deleted = await asyncio.to_thread(delete_coalition_map, rid)
    return {"deleted": deleted, "receipt_id": rid}
