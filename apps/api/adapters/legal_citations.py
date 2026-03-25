"""
Legal citation adapter — maps financial patterns in a dossier to applicable federal statutes,
public FEC enforcement records, and federal court opinions. Does not assert violations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import anthropic
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

FEC_BASE = "https://api.open.fec.gov/v1"
COURTLISTENER_SEARCH = "https://www.courtlistener.com/api/rest/v3/search/"


class StatuteReference(BaseModel):
    citation: str
    title: str
    summary: str
    url: str
    relevance: str


class EnforcementAction(BaseModel):
    case_id: str
    respondent: str
    year: int
    violation_type: str
    penalty_amount: float | None = None
    settlement: bool = False
    source_url: str
    relevance: str


class CourtCase(BaseModel):
    case_name: str
    docket: str
    court: str
    year: int
    summary: str
    source_url: str
    relevance: str


class LegalCitationResult(BaseModel):
    entity_name: str
    patterns_flagged: list[str] = Field(default_factory=list)
    statutes: list[StatuteReference] = Field(default_factory=list)
    enforcement_actions: list[EnforcementAction] = Field(default_factory=list)
    court_cases: list[CourtCase] = Field(default_factory=list)
    legal_disclaimer: str
    generated_at: str


CAMPAIGN_FINANCE_STATUTES: list[dict[str, Any]] = [
    {
        "citation": "52 U.S.C. § 30114",
        "title": "Personal Use of Campaign Funds",
        "summary": (
            "Prohibits use of campaign contributions for personal expenses not arising from candidacy."
        ),
        "url": "https://uscode.house.gov/view.xhtml?req=granule:USC:52:30114",
        "triggers": ["personal_use", "vendor_payment", "family_payment"],
    },
    {
        "citation": "52 U.S.C. § 30116",
        "title": "Contribution Limits",
        "summary": "Sets limits on contributions to candidates, parties, and PACs.",
        "url": "https://uscode.house.gov/view.xhtml?req=granule:USC:52:30116",
        "triggers": ["excess_contribution", "contribution_limit"],
    },
    {
        "citation": "52 U.S.C. § 30118",
        "title": "Corporate and Labor Contributions",
        "summary": "Prohibits direct corporate or union contributions to federal candidates.",
        "url": "https://uscode.house.gov/view.xhtml?req=granule:USC:52:30118",
        "triggers": ["corporate_contribution", "pac_structure"],
    },
    {
        "citation": "52 U.S.C. § 30122",
        "title": "Contributions in Name of Another",
        "summary": "Prohibits making contributions in another person's name (straw donor).",
        "url": "https://uscode.house.gov/view.xhtml?req=granule:USC:52:30122",
        "triggers": ["straw_donor", "dark_money", "anonymous_contribution"],
    },
    {
        "citation": "52 U.S.C. § 30104",
        "title": "Reporting Requirements",
        "summary": "Requires disclosure of contributions and expenditures above threshold amounts.",
        "url": "https://uscode.house.gov/view.xhtml?req=granule:USC:52:30104",
        "triggers": ["disclosure_gap", "unreported_contribution", "dark_money"],
    },
    {
        "citation": "2 U.S.C. § 1601",
        "title": "Lobbying Disclosure Act",
        "summary": "Requires registration and disclosure by lobbyists and lobbying firms.",
        "url": "https://uscode.house.gov/view.xhtml?req=granule:USC:2:1601",
        "triggers": ["lobbying", "revolving_door", "lda_registration"],
    },
    {
        "citation": "22 U.S.C. § 611",
        "title": "Foreign Agents Registration Act (FARA)",
        "summary": "Requires registration of agents acting on behalf of foreign principals.",
        "url": "https://uscode.house.gov/view.xhtml?req=granule:USC:22:611",
        "triggers": ["foreign_agent", "fara", "foreign_principal"],
    },
]


def _fec_api_key() -> str:
    return os.environ.get("FEC_API_KEY", "").strip() or "DEMO_KEY"


def _extract_json_array(text: str) -> list[Any]:
    raw = text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ("patterns", "pattern_ids", "items"):
                if k in data and isinstance(data[k], list):
                    return data[k]
        return []
    except json.JSONDecodeError:
        return []


async def fetch_fec_enforcement_actions(entity_name: str) -> list[EnforcementAction]:
    """Query OpenFEC legal enforcement search; return public enforcement records only."""
    key = _fec_api_key()
    url = f"{FEC_BASE}/legal/enforcement/"
    params: dict[str, Any] = {"q": entity_name, "api_key": key, "per_page": 5}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("FEC enforcement lookup failed: %s", exc)
        return []

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []

    out: list[EnforcementAction] = []
    for row in results[:5]:
        if not isinstance(row, dict):
            continue
        case_no = str(
            row.get("case_no")
            or row.get("case_number")
            or row.get("id")
            or row.get("mur_number")
            or ""
        ).strip()
        if not case_no:
            continue
        respondents = row.get("respondents") or row.get("respondent_names")
        if isinstance(respondents, list):
            resp = ", ".join(str(x) for x in respondents[:5] if x)[:500]
        else:
            resp = str(respondents or row.get("name") or "")[:500]
        year = 0
        for key in ("published_date", "close_date", "open_date", "doc_order_date"):
            d = row.get(key)
            if isinstance(d, str) and len(d) >= 4:
                m = re.search(r"(19|20)\d{2}", d)
                if m:
                    try:
                        year = int(m.group(0))
                    except ValueError:
                        year = 0
                    break
        if year == 0:
            year = datetime.now(timezone.utc).year
        penalty: float | None = None
        for pk in ("penalty_amount", "final_penalty", "civil_penalty"):
            if pk in row and row[pk] is not None:
                try:
                    penalty = float(row[pk])
                    break
                except (TypeError, ValueError):
                    pass
        vtype = str(row.get("violation_type") or row.get("category") or "enforcement matter")[
            :200
        ]
        settlement = bool(row.get("settlement") or row.get("is_settlement"))
        source_url = f"https://www.fec.gov/data/legal/enforcement/{case_no}/"
        out.append(
            EnforcementAction(
                case_id=case_no[:120],
                respondent=resp or entity_name,
                year=year,
                violation_type=vtype,
                penalty_amount=penalty,
                settlement=settlement,
                source_url=source_url,
                relevance=(
                    "Public enforcement record on file with the Commission; "
                    "pattern context only — no determination stated."
                ),
            )
        )
    return out


async def fetch_court_cases(entity_name: str) -> list[CourtCase]:
    """Federal opinion search via CourtListener (optional API token)."""
    token = os.environ.get("COURTLISTENER_API_KEY", "").strip()
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Token {token}"
    params = {
        "q": entity_name,
        "type": "o",
        "court": "federal",
        "order_by": "score desc",
        "page_size": 3,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                COURTLISTENER_SEARCH,
                params=params,
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("CourtListener federal search failed: %s", exc)
        return []

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []

    out: list[CourtCase] = []
    for row in results[:3]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("caseName") or row.get("case_name") or row.get("snippet") or "")[:500]
        if not name:
            continue
        docket = str(row.get("docketNumber") or row.get("docket_id") or "")[:120]
        court = str(row.get("court") or row.get("court_id") or "federal")[:200]
        year = 0
        df = row.get("dateFiled") or row.get("date_filed")
        if isinstance(df, str) and len(df) >= 4:
            m = re.search(r"(19|20)\d{2}", df)
            if m:
                try:
                    year = int(m.group(0))
                except ValueError:
                    year = 0
        if year == 0:
            year = datetime.now(timezone.utc).year
        abs_url = str(row.get("absolute_url") or "")
        source_url = (
            f"https://www.courtlistener.com{abs_url}" if abs_url.startswith("/") else abs_url
        )
        if not source_url.startswith("http"):
            source_url = f"https://www.courtlistener.com{abs_url}"
        summary = str(row.get("snippet") or row.get("syllabus") or name)[:800]
        out.append(
            CourtCase(
                case_name=name,
                docket=docket or "—",
                court=court,
                year=year,
                summary=summary,
                source_url=source_url,
                relevance=(
                    "Federal opinion indexed in public search results for this name; "
                    "applicable precedent may require independent review."
                ),
            )
        )
    return out


async def detect_legal_patterns(entity_name: str, dossier_summary: dict[str, Any]) -> list[str]:
    """Identify evidenced pattern tags via Sonnet (no legal conclusions)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return []
    sonnet = os.environ.get("CLAUDE_SONNET_MODEL", "claude-sonnet-4-20250514")
    payload = json.dumps(dossier_summary, default=str, ensure_ascii=False)[:4000]
    prompt = f"""You are reviewing a financial dossier for {entity_name}.

Dossier data: {payload}

Identify which of these patterns are present based on the data:
- personal_use (campaign funds used for personal expenses)
- excess_contribution (contribution amounts near or over legal limits)
- corporate_contribution (corporate PAC structure)
- dark_money (disbursements to nonprofits, LLCs, or undisclosed recipients)
- straw_donor (contributions routed through third parties)
- disclosure_gap (significant spending not in public filings)
- lobbying (registered lobbying activity)
- revolving_door (movement between government and lobbying)
- foreign_agent (FARA registration or foreign principal connections)
- vendor_payment (large payments to vendors with unclear services)
- family_payment (payments to family members or their entities)
- anonymous_contribution (contributions from anonymous or shell sources)

Return ONLY a JSON array of pattern strings that are actually evidenced in the data.
Empty array if none. No markdown. Do not use the word corruption. Do not assert illegality."""

    client = anthropic.AsyncAnthropic(api_key=key)
    try:
        msg = await client.messages.create(
            model=sonnet,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            getattr(b, "text", "") or "" for b in msg.content if getattr(b, "text", None)
        )
        arr = _extract_json_array(text)
        out: list[str] = []
        for x in arr:
            if isinstance(x, str) and x.strip():
                out.append(x.strip())
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("detect_legal_patterns failed: %s", exc)
        return []


class LegalCitationAdapter:
    """Attach statute references and public-record legal context to enrichment output."""

    async def analyze(self, entity_name: str, dossier: dict[str, Any]) -> LegalCitationResult:
        patterns = await detect_legal_patterns(entity_name, dossier)

        matched_statutes: list[StatuteReference] = []
        for statute in CAMPAIGN_FINANCE_STATUTES:
            triggers = statute.get("triggers") or []
            if not isinstance(triggers, list):
                continue
            matching = [t for t in triggers if t in patterns]
            if matching:
                matched_statutes.append(
                    StatuteReference(
                        citation=str(statute["citation"]),
                        title=str(statute["title"]),
                        summary=str(statute["summary"]),
                        url=str(statute["url"]),
                        relevance=f"Pattern identified in dossier data: {', '.join(matching)}",
                    )
                )

        enforcement, cases = await asyncio.gather(
            fetch_fec_enforcement_actions(entity_name),
            fetch_court_cases(entity_name),
        )

        return LegalCitationResult(
            entity_name=entity_name,
            patterns_flagged=patterns,
            statutes=matched_statutes,
            enforcement_actions=enforcement,
            court_cases=cases,
            legal_disclaimer="This documents applicable law only. No violation is asserted.",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
