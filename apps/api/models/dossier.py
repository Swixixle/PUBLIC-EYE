"""
DossierSchema — matches `.cursorrules` contract; nested models for enrichment + Claude assembly.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Contribution(BaseModel):
    contributor_name: str
    recipient_committee: str
    amount: float
    transaction_date: str | None = None  # FEC may omit on some parsed rows
    election_cycle: str | None = None  # optional cycle label when present
    fec_url: str | None = None  # deep link when available


class Case(BaseModel):
    name: str
    court: str | None = None  # CourtListener may not normalize court name
    docket_id: str | None = None
    date_filed: str | None = None
    citation: str | None = None
    source_url: str | None = None


class Statement(BaseModel):
    text: str
    stated_at: str | None = None  # public record may lack precise timestamp
    source_url: str | None = None


class PolicyChain(BaseModel):
    topic: str
    links: list[str] = Field(default_factory=list)


class SponsorRecord(BaseModel):
    sponsor_name: str
    sponsor_type: str | None = None  # e.g. PAC vs individual when inferable
    amount_range: str | None = None  # disclosure often range-based
    source_url: str | None = None


class CharitableRecord(BaseModel):
    """
    Non-negotiable charitable module — every field either populated or None with `reasons`.
    """

    total_given_raw: float | None = None
    total_given_pct_net_worth: float | None = None
    tax_benefit_estimate: float | None = None
    tax_benefit_pct_of_donation: float | None = None  # typically 0.37 marginal estimate
    primary_foundation: str | None = None
    board_control: bool | None = None
    investment_discretion: bool | None = None
    family_employed: bool | None = None
    shell_entities: list[str] = Field(default_factory=list)
    equity_positions_in_funded_sectors: list[str] = Field(default_factory=list)
    reasons: dict[str, str] = Field(
        default_factory=dict,
        description="Per-field explanation when value is None or incomplete.",
    )


class DossierSchema(BaseModel):
    frame_id: str
    entity_canonical_name: str
    entity_type: Literal[
        "corporate_exec",
        "politician",
        "influencer",
        "podcaster",
        "musician",
        "nonprofit",
        "other",
    ]
    contributions: list[Contribution] = Field(default_factory=list)
    expenditures: list[dict[str, Any]] = Field(default_factory=list)
    cases: list[Case] = Field(default_factory=list)
    statements: list[Statement] = Field(default_factory=list)
    policy_chains: list[PolicyChain] = Field(default_factory=list)
    sponsors: list[SponsorRecord] = Field(default_factory=list)
    charitable: CharitableRecord = Field(default_factory=CharitableRecord)
    sec_filings: list[dict[str, Any]] = Field(default_factory=list)
    social_metrics: dict[str, Any] | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    narrative_summary: str = ""
    legal_citations: dict[str, Any] | None = None
    revolving_door: dict[str, Any] | None = None
    fara_chain: dict[str, Any] | None = None
