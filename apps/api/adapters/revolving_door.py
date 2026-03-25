"""
Revolving door — public-record staff and LDA lobbying linkages. No impropriety asserted.
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

LDA_BASE = "https://lda.senate.gov/api/v1"
CONGRESS_MEMBER = "https://api.congress.gov/v3/member"


class GovernmentPosition(BaseModel):
    person_name: str
    title: str
    office: str
    start_year: int | None = None
    end_year: int | None = None
    source_url: str
    source: str  # "congress.gov" | "senate.gov" | "lda"


class LobbyingRegistration(BaseModel):
    person_name: str
    registrant_name: str
    client_names: list[str] = Field(default_factory=list)
    filing_year: int
    income_amount: float | None = None
    issues: list[str] = Field(default_factory=list)
    covered_official: str | None = None
    source_url: str


class RevolvingDoorEntry(BaseModel):
    person_name: str
    government_position: GovernmentPosition
    lobbying_registration: LobbyingRegistration
    gap_years: int | None = None
    committees_overlap: list[str] = Field(default_factory=list)
    pattern_description: str
    documented: bool = False


class RevolvingDoorResult(BaseModel):
    entity_name: str
    staff_found: list[GovernmentPosition] = Field(default_factory=list)
    lobbyists_found: list[LobbyingRegistration] = Field(default_factory=list)
    revolving_door_entries: list[RevolvingDoorEntry] = Field(default_factory=list)
    search_coverage: str
    disclaimer: str
    generated_at: str


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
        if isinstance(data, dict) and "entries" in data and isinstance(data["entries"], list):
            return data["entries"]
        return []
    except json.JSONDecodeError:
        return []


async def fetch_lda_registrations(entity_name: str) -> list[LobbyingRegistration]:
    """Senate LDA API — best-effort registration rows."""
    out: list[LobbyingRegistration] = []
    seen: set[str] = set()

    async def _get(path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(f"{LDA_BASE}{path}", params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("LDA request failed %s: %s", path, exc)
            return []
        if isinstance(data, dict) and "results" in data:
            return list(data["results"]) if isinstance(data["results"], list) else []
        if isinstance(data, list):
            return data
        return []

    # Filings search (params vary by API version)
    filings = await _get(
        "/filings/",
        {
            "search": entity_name,
            "format": "json",
            "limit": 10,
        },
    )
    filings_alt = await _get(
        "/filings/",
        {
            "q": entity_name,
            "format": "json",
            "limit": 10,
        },
    )
    rows = filings or filings_alt

    registrants = await _get(
        "/registrants/",
        {
            "search": entity_name,
            "format": "json",
            "limit": 10,
        },
    )
    if not registrants:
        registrants = await _get(
            "/registrants/",
            {
                "q": entity_name,
                "format": "json",
                "limit": 10,
            },
        )

    for batch in (rows, registrants):
        for row in batch:
            if not isinstance(row, dict):
                continue
            uid = str(row.get("uuid") or row.get("id") or row.get("filing_uuid") or "")[:80]
            key = uid or json.dumps(row, sort_keys=True, default=str)[:200]
            if key in seen:
                continue
            seen.add(key)

            reg = row.get("registrant") or row.get("registrant_name") or {}
            if isinstance(reg, str):
                registrant_name = reg[:500]
            elif isinstance(reg, dict):
                registrant_name = str(reg.get("name") or reg.get("title") or "unknown")[:500]
            else:
                registrant_name = "unknown"

            clients_raw = row.get("clients") or row.get("client") or []
            client_names: list[str] = []
            if isinstance(clients_raw, list):
                for c in clients_raw[:20]:
                    if isinstance(c, dict):
                        client_names.append(str(c.get("name") or c.get("client_name") or "")[:300])
                    elif isinstance(c, str):
                        client_names.append(c[:300])
            elif isinstance(clients_raw, dict):
                client_names.append(str(clients_raw.get("name") or "")[:300])

            lobbyist_name = entity_name
            lobs = row.get("lobbyists") or row.get("lobbyist") or []
            if isinstance(lobs, list) and lobs:
                first = lobs[0]
                if isinstance(first, dict):
                    fn = str(first.get("first_name") or first.get("firstName") or "").strip()
                    ln = str(first.get("last_name") or first.get("lastName") or "").strip()
                    if fn or ln:
                        lobbyist_name = f"{fn} {ln}".strip()
                    cov = first.get("covered_position") or first.get("covered_official_position")
                    if isinstance(cov, str):
                        covered = cov[:500]
                    elif isinstance(cov, dict):
                        covered = str(cov.get("title") or cov.get("name") or "")[:500]
                    else:
                        covered = None
                else:
                    covered = None
            else:
                covered = str(row.get("covered_official_position") or "")[:500] or None

            year = datetime.now(timezone.utc).year
            for yk in ("filing_year", "year", "filingYear", "report_year"):
                if row.get(yk) is not None:
                    try:
                        year = int(row[yk])
                        break
                    except (TypeError, ValueError):
                        pass

            income: float | None = None
            for ik in ("income", "income_amount", "total_income"):
                if row.get(ik) is not None:
                    try:
                        income = float(row[ik])
                        break
                    except (TypeError, ValueError):
                        pass

            issues: list[str] = []
            acts = row.get("lobbying_activities") or row.get("activities") or []
            if isinstance(acts, list):
                for a in acts[:15]:
                    if isinstance(a, dict):
                        ic = a.get("issue_code") or a.get("issue") or a.get("description")
                        if ic:
                            issues.append(str(ic)[:200])
                    elif isinstance(a, str):
                        issues.append(a[:200])

            source_url = "https://lda.senate.gov/filings/public/filing/search/"
            if uid:
                source_url = f"https://lda.senate.gov/filings/{uid}/"

            try:
                out.append(
                    LobbyingRegistration(
                        person_name=lobbyist_name[:300],
                        registrant_name=registrant_name,
                        client_names=[c for c in client_names if c][:20],
                        filing_year=year,
                        income_amount=income,
                        issues=issues[:30],
                        covered_official=covered,
                        source_url=source_url[:500],
                    )
                )
            except Exception:  # noqa: BLE001
                continue

    return out[:25]


async def fetch_congressional_staff(entity_name: str) -> list[GovernmentPosition]:
    """Congress.gov member search when API key set; optional LegiStorm HTML best-effort."""
    out: list[GovernmentPosition] = []
    key = os.environ.get("CONGRESS_API_KEY", "").strip()
    if key:
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                r = await client.get(
                    CONGRESS_MEMBER,
                    params={"query": entity_name, "format": "json", "limit": 5},
                    headers={"X-API-Key": key},
                )
                if r.status_code == 401:
                    r = await client.get(
                        CONGRESS_MEMBER,
                        params={
                            "query": entity_name,
                            "format": "json",
                            "limit": 5,
                            "api_key": key,
                        },
                    )
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Congress.gov member search failed: %s", exc)
            data = {}
        members = data.get("members") if isinstance(data, dict) else None
        if isinstance(members, list):
            for item in members[:3]:
                m = item.get("member") if isinstance(item, dict) and "member" in item else item
                if not isinstance(m, dict):
                    continue
                name = str(
                    m.get("name")
                    or m.get("directOrderName")
                    or m.get("honorificName")
                    or entity_name
                )[:300]
                chamber = str(m.get("chamber") or "").lower()
                state = str(m.get("state") or "")
                title = "Member of Congress"
                if "senate" in chamber:
                    title = "Senator"
                elif "house" in chamber:
                    title = "Representative"
                office = f"{title} — {state}".strip(" —") if state else title
                url = str(m.get("url") or m.get("memberUrl") or "")
                if not url.startswith("http"):
                    url = f"https://www.congress.gov{url}" if url.startswith("/") else "https://www.congress.gov/"
                out.append(
                    GovernmentPosition(
                        person_name=name,
                        title=title,
                        office=office,
                        start_year=None,
                        end_year=None,
                        source_url=url[:500],
                        source="congress.gov",
                    )
                )
                comms = m.get("committees") or m.get("committeeAssignments")
                if isinstance(comms, list):
                    for c in comms[:10]:
                        if isinstance(c, dict):
                            cn = str(c.get("name") or c.get("committeeName") or "")
                            if cn:
                                out.append(
                                    GovernmentPosition(
                                        person_name=name,
                                        title="Committee assignment (public record)",
                                        office=cn[:400],
                                        source_url=url[:500],
                                        source="congress.gov",
                                    )
                                )

    if not out:
        out.append(
            GovernmentPosition(
                person_name=entity_name,
                title="Office (search did not return structured member rows)",
                office=f"Context: {entity_name}",
                source_url="https://www.congress.gov/",
                source="congress.gov",
            )
        )

    # LegiStorm — best-effort HTML
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(
                "https://www.legistorm.com/person/search",
                params={"search_text": entity_name},
                headers={"User-Agent": "Frame-RevolvingDoor/1.0 (+https://getframe.dev)"},
            )
            if r.status_code == 200 and len(r.text) > 100:
                # Very light extraction — no conclusions
                for m in re.finditer(
                    r"class=[\"'][^\"']*name[^\"']*[\"'][^>]*>([^<]{3,80})<",
                    r.text,
                    re.I,
                ):
                    nm = m.group(1).strip()
                    if len(nm) > 3 and nm.lower() not in ("search", "results"):
                        out.append(
                            GovernmentPosition(
                                person_name=nm[:200],
                                title="Listed on LegiStorm search results page",
                                office="See source; manual verification recommended",
                                source_url="https://www.legistorm.com/",
                                source="lda",
                            )
                        )
                        break
    except Exception:  # noqa: BLE001
        pass

    return out[:30]


def _placeholder_gov(person_name: str, role: str, entity_name: str) -> GovernmentPosition:
    return GovernmentPosition(
        person_name=person_name,
        title=role[:300] or "Government role (public record)",
        office=f"Context tied to {entity_name}",
        source_url="https://www.congress.gov/",
        source="congress.gov",
    )


def _placeholder_lobby(person_name: str, role: str) -> LobbyingRegistration:
    y = datetime.now(timezone.utc).year
    return LobbyingRegistration(
        person_name=person_name,
        registrant_name="See lobbying registration filing",
        client_names=[],
        filing_year=y,
        issues=[],
        source_url="https://lda.senate.gov/",
    )


async def find_revolving_door_connections(
    entity_name: str,
    staff: list[GovernmentPosition],
    lobbyists: list[LobbyingRegistration],
) -> list[RevolvingDoorEntry]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return []
    sonnet = os.environ.get("CLAUDE_SONNET_MODEL", "claude-sonnet-4-20250514")
    prompt = f"""You are documenting staff movement between government and lobbying for public record research on {entity_name}.

Government positions found:
{json.dumps([s.model_dump() for s in staff], default=str)[:2000]}

Lobbying registrations found:
{json.dumps([l.model_dump() for l in lobbyists], default=str)[:2000]}

Identify individuals who appear in both lists or whose lobbying registration references this official's office or committees.

For each match, return JSON array:
[{{
    "person_name": "full name",
    "government_role": "their title in government",
    "lobbying_role": "their lobbying firm and clients",
    "committees_overlap": ["committee names that appear in both"],
    "gap_years": 2,
    "pattern_description": "documented sequence of positions held, no conclusions about intent"
}}]

Rules:
- Only document what is in the data above
- Do not infer or speculate beyond the records
- pattern_description must be factual sequence only
- Do not use: corruption, bribery, illegal, improper, caught
- Return empty array [] if no matches found
- Return valid JSON only, no markdown"""

    client = anthropic.AsyncAnthropic(api_key=key)
    try:
        msg = await client.messages.create(
            model=sonnet,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            getattr(b, "text", "") or "" for b in msg.content if getattr(b, "text", None)
        )
        rows = _extract_json_array(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("find_revolving_door_connections failed: %s", exc)
        return []

    entries: list[RevolvingDoorEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        person = str(row.get("person_name") or "").strip()
        if not person:
            continue
        gov_role = str(row.get("government_role") or "Government role (unspecified)")[:400]
        lob_role = str(row.get("lobbying_role") or "Lobbying registration (unspecified)")[:500]
        committees = row.get("committees_overlap")
        if not isinstance(committees, list):
            committees = []
        committees = [str(c)[:300] for c in committees if c][:20]
        gap = row.get("gap_years")
        gap_i: int | None = None
        if gap is not None:
            try:
                gap_i = int(gap)
            except (TypeError, ValueError):
                gap_i = None
        pat = str(
            row.get("pattern_description")
            or "Documented movement between listed government context and listed lobbying context."
        )[:2000]
        gov = _placeholder_gov(person, gov_role, entity_name)
        lob = _placeholder_lobby(person, lob_role)
        lob = lob.model_copy(
            update={
                "registrant_name": lob_role[:500]
                if len(lob_role) > 10
                else lob.registrant_name
            }
        )
        documented = bool(
            staff
            and lobbyists
            and any(person.lower() in s.person_name.lower() for s in staff)
        )
        try:
            entries.append(
                RevolvingDoorEntry(
                    person_name=person,
                    government_position=gov,
                    lobbying_registration=lob,
                    gap_years=gap_i,
                    committees_overlap=committees,
                    pattern_description=pat,
                    documented=documented,
                )
            )
        except Exception:  # noqa: BLE001
            continue
    return entries


class RevolvingDoorAdapter:
    """Aggregate LDA + Congress.gov + model-assisted linkage review."""

    async def analyze(self, entity_name: str) -> RevolvingDoorResult:
        lobbyists, staff = await asyncio.gather(
            fetch_lda_registrations(entity_name),
            fetch_congressional_staff(entity_name),
        )
        entries = await find_revolving_door_connections(entity_name, staff, lobbyists)
        search_coverage = (
            f"Searched: Senate LDA filings database, Congress.gov member records. "
            f"Found {len(staff)} government position records, "
            f"{len(lobbyists)} lobbying registrations. "
            f"LegiStorm staff data requires manual verification."
        )
        return RevolvingDoorResult(
            entity_name=entity_name,
            staff_found=staff,
            lobbyists_found=lobbyists,
            revolving_door_entries=entries,
            search_coverage=search_coverage,
            disclaimer=(
                "This documents publicly available staff movement records only. "
                "Lobbying is legal. Movement between government and lobbying is legal. "
                "No impropriety is asserted or implied."
            ),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
