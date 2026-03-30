"""
Media axis + outlet/reporter dossier routes.

Axis is verifiable-record–anchored (not political left/right).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from media_axis_service import build_media_axis
from outlet_dossier_service import get_or_build_outlet_by_url_slug
from receipt_store import get_coalition_map, get_media_axis, get_receipt, save_media_axis
from reporter_dossier_service import get_or_build_reporter_by_url_slug

router = APIRouter(tags=["media-axis"])


class MediaAxisPostBody(BaseModel):
    receipt_id: str = Field(..., min_length=1)


@router.post("/media-axis")
async def post_media_axis(body: MediaAxisPostBody) -> dict:
    rid = body.receipt_id.strip()
    receipt = await asyncio.to_thread(get_receipt, rid)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    coalition = await asyncio.to_thread(get_coalition_map, rid)
    try:
        payload = build_media_axis(receipt, coalition)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await asyncio.to_thread(save_media_axis, payload)
    return payload


@router.get("/media-axis/{receipt_id}")
async def get_media_axis_by_receipt(receipt_id: str) -> dict:
    row = await asyncio.to_thread(get_media_axis, receipt_id.strip())
    if not row:
        raise HTTPException(status_code=404, detail="Media axis not found")
    return row


@router.get("/outlet/{slug}")
async def get_outlet_dossier(slug: str) -> dict:
    if not slug.strip():
        raise HTTPException(status_code=404, detail="Outlet not found")
    return await asyncio.to_thread(get_or_build_outlet_by_url_slug, slug.strip(), True)


@router.get("/reporter/{slug}")
async def get_reporter_dossier(slug: str) -> dict:
    if not slug.strip():
        raise HTTPException(status_code=404, detail="Reporter not found")
    return await asyncio.to_thread(get_or_build_reporter_by_url_slug, slug.strip(), True)
