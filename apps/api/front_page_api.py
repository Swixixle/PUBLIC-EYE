"""GET /v1/front-page — JSON for the newspaper front page."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from front_page import build_front_page_payload

router = APIRouter(tags=["front-page"])


@router.get("/front-page")
async def get_front_page() -> dict:
    return await asyncio.to_thread(build_front_page_payload)
