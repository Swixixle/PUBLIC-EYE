"""Pydantic models for coalition map API (PUBLIC EYE)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


AlignmentConfidence = Literal["high", "medium", "low"]
OutletType = Literal["state", "private", "public_broadcaster"]


class CoalitionChainLink(BaseModel):
    model_config = {"extra": "allow"}

    outlet: str
    country: str = ""
    flag: str = ""
    outlet_type: OutletType = "private"
    alignment_confidence: AlignmentConfidence = "medium"
    alignment_note: str = ""
    story_url: str = ""


class CoalitionPosition(BaseModel):
    model_config = {"extra": "allow"}

    label: str
    anchor_region: str
    anchor_outlets: list[str] = Field(default_factory=list)
    summary: str = ""
    emphasizes: list[str] = Field(default_factory=list)
    minimizes: list[str] = Field(default_factory=list)
    chain: list[CoalitionChainLink] = Field(default_factory=list)


class CoalitionMapPostBody(BaseModel):
    receipt_id: str


class CoalitionAcceptedResponse(BaseModel):
    receipt_id: str
    status: Literal["processing"] = "processing"


def chain_link_from_dict(d: dict[str, Any]) -> CoalitionChainLink:
    ot = d.get("outlet_type") or "private"
    if ot not in ("state", "private", "public_broadcaster"):
        ot = "private"
    conf = d.get("alignment_confidence") or "medium"
    if conf not in ("high", "medium", "low"):
        conf = "medium"
    return CoalitionChainLink(
        outlet=str(d.get("outlet", "")),
        country=str(d.get("country", "")),
        flag=str(d.get("flag", "")),
        outlet_type=ot,  # type: ignore[arg-type]
        alignment_confidence=conf,  # type: ignore[arg-type]
        alignment_note=str(d.get("alignment_note", "")),
        story_url=str(d.get("story_url") or ""),
    )


def _tags_from_value(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str) and val.strip():
        parts = re.split(r"[,;•]|\n", val)
        return [p.strip() for p in parts if p.strip()]
    return []


def position_from_dict(d: dict[str, Any], anchor_region: str) -> CoalitionPosition:
    raw_chain = [chain_link_from_dict(x) for x in (d.get("chain") or []) if isinstance(x, dict)]
    raw_chain.sort(
        key=lambda lk: {"high": 0, "medium": 1, "low": 2}.get(lk.alignment_confidence, 1),
    )
    emphasizes = d.get("emphasizes")
    if not isinstance(emphasizes, list):
        emphasizes = _tags_from_value(d.get("emphasized") or d.get("emphasises"))
    minimizes = d.get("minimizes")
    if not isinstance(minimizes, list):
        minimizes = _tags_from_value(d.get("minimized") or d.get("minimises"))
    outlets = d.get("anchor_outlets")
    if not isinstance(outlets, list):
        outlets = []
    return CoalitionPosition(
        label=str(d.get("label", "")),
        anchor_region=str(d.get("anchor_region") or anchor_region),
        anchor_outlets=[str(x) for x in outlets],
        summary=str(d.get("summary", "")),
        emphasizes=[str(x) for x in emphasizes],
        minimizes=[str(x) for x in minimizes],
        chain=raw_chain,
    )
