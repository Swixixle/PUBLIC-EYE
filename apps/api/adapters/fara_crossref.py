"""
FARA cross-reference — DOJ public records: registrants, foreign principals, dossier linkages.
No conclusions about intent or influence.
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

EFILE_BASE = "https://efile.fara.gov/api/v1"


class FARARegistrant(BaseModel):
    registrant_name: str
    registration_number: str
    registration_date: str | None = None
    address: str | None = None
    source_url: str


class ForeignPrincipal(BaseModel):
    principal_name: str
    country: str
    principal_type: str
    registrant_name: str
    registration_number: str
    source_url: str


class DossierConnection(BaseModel):
    principal_name: str
    connected_entity: str
    connection_type: str
    connection_description: str
    confidence: str
    source: str


class FARAChain(BaseModel):
    anchor_entity: str
    registrants: list[FARARegistrant] = Field(default_factory=list)
    foreign_principals: list[ForeignPrincipal] = Field(default_factory=list)
    dossier_connections: list[DossierConnection] = Field(default_factory=list)
    chain_description: str
    disclaimer: str
    generated_at: str


def _fara_reg_source_url(reg_number: str) -> str:
    return (
        "https://efile.fara.gov/pls/apex/f?"
        f"p=171:200:0::NO:RP,200:P200_REG_NUMBER:{reg_number}"
    )


def _infer_principal_type(name: str, country: str) -> str:
    n = (name or "").strip()
    low = n.lower()
    if any(
        low.endswith(x)
        for x in ("ministry", "embassy", "government", "government of")
    ):
        return "foreign_government"
    if low.endswith("party") or "party" in low:
        return "foreign_party"
    parts = n.replace(".", " ").split()
    if len(parts) <= 3 and re.match(r"^[A-Z][a-z]+(\s+[A-Z][a-z]+)+$", n.strip()):
        return "individual"
    if not n:
        return "unknown"
    return "foreign_entity"


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
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


async def _http_json(url: str, params: dict[str, Any] | None = None) -> Any:
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.get(url, params=params or {})
            r.raise_for_status()
            return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("FARA HTTP failed %s: %s", url, exc)
        return None


async def fetch_fara_registrants(entity_name: str) -> list[FARARegistrant]:
    """DOJ eFile FARA — try Search/json then legacy Registrants.json."""
    out: list[FARARegistrant] = []
    seen: set[str] = set()

    # Spec endpoints
    for path, pkey in (
        ("/Registrant/Search/json", "searchTerm"),
        ("/Agency/Search/json", "searchTerm"),
    ):
        data = await _http_json(f"{EFILE_BASE}{path}", {pkey: entity_name})
        rows = _normalize_fara_registrant_rows(data)
        for row in rows:
            fr = _row_to_fara_registrant(row)
            if fr and fr.registration_number not in seen:
                seen.add(fr.registration_number)
                out.append(fr)

    if not out:
        data = await _http_json(
            f"{EFILE_BASE}/Registrants.json",
            {"name": entity_name, "activeonly": "false"},
        )
        rows = _normalize_legacy_registrants(data)
        for row in rows:
            fr = _row_to_fara_registrant_legacy(row)
            if fr and fr.registration_number not in seen:
                seen.add(fr.registration_number)
                out.append(fr)

    return out[:20]


def _normalize_fara_registrant_rows(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    for key in ("results", "Results", "data", "REGISTRANTS"):
        v = data.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict) and "REGISTRANT" in v:
            r = v["REGISTRANT"]
            if isinstance(r, list):
                return [x for x in r if isinstance(x, dict)]
            if isinstance(r, dict):
                return [r]
    return []


def _normalize_legacy_registrants(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    reg = data.get("REGISTRANTS", {})
    if not isinstance(reg, dict):
        return []
    rlist = reg.get("REGISTRANT", [])
    if isinstance(rlist, dict):
        rlist = [rlist]
    if isinstance(rlist, list):
        return [x for x in rlist if isinstance(x, dict)]
    return []


def _row_to_fara_registrant(row: dict[str, Any]) -> FARARegistrant | None:
    name = (
        row.get("registrant_name")
        or row.get("RegistrantName")
        or row.get("REGISTRANTNAME")
        or row.get("name")
    )
    rid = str(
        row.get("registration_number")
        or row.get("RegistrationNumber")
        or row.get("REGISTRANTID")
        or row.get("id")
        or "",
    ).strip()
    if not name or not rid:
        return None
    addr = row.get("address") or row.get("ADDRESS")
    if isinstance(addr, dict):
        addr = json.dumps(addr, default=str)[:500]
    reg_date = str(row.get("registration_date") or row.get("REGDATE") or "")[:40] or None
    return FARARegistrant(
        registrant_name=str(name)[:500],
        registration_number=rid[:80],
        registration_date=reg_date,
        address=str(addr)[:500] if addr else None,
        source_url=_fara_reg_source_url(rid[:80]),
    )


def _row_to_fara_registrant_legacy(row: dict[str, Any]) -> FARARegistrant | None:
    name = row.get("REGISTRANTNAME") or row.get("registrant_name")
    rid = str(row.get("REGISTRANTID") or row.get("registration_number") or "").strip()
    if not name or not rid:
        return None
    addr = row.get("ADDRESS")
    if isinstance(addr, dict):
        addr = str(addr)[:500]
    reg_date = str(row.get("REGDATE") or "")[:40] or None
    url = (
        f"https://efile.fara.gov/ords/fara/f?p=181:200:0::NO:RP,200:P200_REG_NUMBER:{rid}"
    )
    return FARARegistrant(
        registrant_name=str(name)[:500],
        registration_number=rid[:80],
        registration_date=reg_date,
        address=str(addr)[:500] if addr else None,
        source_url=url[:500],
    )


async def fetch_foreign_principals(
    registration_number: str,
    registrant_name: str,
) -> list[ForeignPrincipal]:
    out: list[ForeignPrincipal] = []

    data = await _http_json(
        f"{EFILE_BASE}/ForeignPrincipal/Search/json",
        {"searchTerm": registrant_name},
    )
    rows: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key in ("results", "Results", "data"):
            v = data.get(key)
            if isinstance(v, list):
                rows = [x for x in v if isinstance(x, dict)]
                break

    if not rows:
        data = await _http_json(
            f"{EFILE_BASE}/ForeignPrincipals.json",
            {"foreignprincipalname": registrant_name},
        )
        if isinstance(data, dict):
            fp = data.get("FOREIGN_PRINCIPALS", {})
            if isinstance(fp, dict):
                plist = fp.get("FOREIGN_PRINCIPAL", [])
                if isinstance(plist, dict):
                    plist = [plist]
                if isinstance(plist, list):
                    rows = [x for x in plist if isinstance(x, dict)]

    for row in rows[:15]:
        pname = (
            row.get("ForeignPrincipalName")
            or row.get("FOREIGNPRINCIPALNAME")
            or row.get("principal_name")
            or row.get("name")
        )
        if not pname:
            continue
        country = str(row.get("Country") or row.get("COUNTRY") or "unknown")[:120]
        reg_name = str(
            row.get("RegistrantName")
            or row.get("REGISTRANTNAME")
            or registrant_name
        )[:500]
        reg_num = str(
            row.get("RegistrationNumber")
            or row.get("REGISTRANTID")
            or registration_number
        )[:80]
        ptype = _infer_principal_type(str(pname), country)
        out.append(
            ForeignPrincipal(
                principal_name=str(pname)[:500],
                country=country,
                principal_type=ptype,
                registrant_name=reg_name,
                registration_number=reg_num,
                source_url=_fara_reg_source_url(reg_num),
            )
        )

    return out[:30]


async def find_dossier_connections(
    anchor_entity: str,
    principals: list[ForeignPrincipal],
    existing_dossier_entities: list[str],
) -> list[DossierConnection]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or not principals:
        return []
    sonnet = os.environ.get("CLAUDE_SONNET_MODEL", "claude-sonnet-4-20250514")
    prompt = f"""You are documenting potential connections between foreign principals and known entities in a public records dossier on {anchor_entity}.

Foreign principals found via FARA registration:
{json.dumps([p.model_dump() for p in principals], default=str)[:2000]}

Entities already documented in this dossier:
{json.dumps(existing_dossier_entities)[:1000]}

Identify any factual connections between the foreign principals and the dossier entities. Connections may include: shared country of operation, documented financial relationships, organizational overlap, or name matches.

Return ONLY a JSON array:
[{{
    "principal_name": "name",
    "connected_entity": "entity from dossier",
    "connection_type": "shared_name|shared_country|financial_relationship|organizational",
    "connection_description": "factual description of the connection",
    "confidence": "confirmed|possible|speculative",
    "source": "basis for this connection"
}}]

Rules:
- Only document connections supported by the data provided
- confidence=confirmed only when both records explicitly reference each other
- confidence=speculative must include clear uncertainty language in description
- Return [] if no connections found
- No markdown, valid JSON only
- Do not use: corruption, illegal, improper, suspicious, foreign interference"""

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
        logger.warning("find_dossier_connections failed: %s", exc)
        return []

    out: list[DossierConnection] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                DossierConnection(
                    principal_name=str(row.get("principal_name") or "")[:500],
                    connected_entity=str(row.get("connected_entity") or "")[:500],
                    connection_type=str(row.get("connection_type") or "organizational")[
                        :80
                    ],
                    connection_description=str(row.get("connection_description") or "")[
                        :2000
                    ],
                    confidence=str(row.get("confidence") or "possible")[:40],
                    source=str(row.get("source") or "dossier cross-reference")[:500],
                )
            )
        except Exception:  # noqa: BLE001
            continue
    return out


async def build_chain_description(
    anchor_entity: str,
    registrants: list[FARARegistrant],
    principals: list[ForeignPrincipal],
    connections: list[DossierConnection],
) -> str:
    default = (
        f"No FARA registrations were found connecting to {anchor_entity} "
        "in the DOJ database at time of this receipt."
    )
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return default if not registrants else (
            f"FARA registration records were retrieved for public review; "
            f"see registrant and foreign principal lists for {anchor_entity}."
        )
    sonnet = os.environ.get("CLAUDE_SONNET_MODEL", "claude-sonnet-4-20250514")
    prompt = f"""Write a factual, documented sequence describing the FARA registration chain found for {anchor_entity}. Use only the data provided.

Registrants: {json.dumps([r.model_dump() for r in registrants], default=str)[:4000]}
Principals: {json.dumps([p.model_dump() for p in principals], default=str)[:4000]}
Connections: {json.dumps([c.model_dump() for c in connections], default=str)[:2000]}

Rules:
- Factual sequence only: who registered, on behalf of whom, from where
- No conclusions about intent, influence, or impropriety
- No words: corruption, illegal, improper, suspicious, concerning, foreign interference
- If no registrants found, state that clearly
- 3-5 sentences maximum
- Plain text only, no markdown"""

    client = anthropic.AsyncAnthropic(api_key=key)
    try:
        msg = await client.messages.create(
            model=sonnet,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            getattr(b, "text", "") or "" for b in msg.content if getattr(b, "text", None)
        ).strip()
        if text:
            return text[:4000]
    except Exception as exc:  # noqa: BLE001
        logger.warning("build_chain_description failed: %s", exc)
    return default if not registrants else (
        "Public DOJ FARA records list registrants and foreign principals above; "
        "see structured fields for documented registration details."
    )


class FARACrossRefAdapter:
    """Cross-reference FARA registrants and principals with dossier entities."""

    async def analyze(
        self,
        entity_name: str,
        existing_dossier_entities: list[str] | None = None,
    ) -> FARAChain:
        existing = list(existing_dossier_entities or [])
        registrants = await fetch_fara_registrants(entity_name)
        if registrants:
            principal_lists = await asyncio.gather(
                *[
                    fetch_foreign_principals(r.registration_number, r.registrant_name)
                    for r in registrants
                ]
            )
            principals = [p for sub in principal_lists for p in sub]
        else:
            principals = []

        # Dedupe principals by name + registrant
        seen_p: set[str] = set()
        uniq_principals: list[ForeignPrincipal] = []
        for p in principals:
            k = f"{p.principal_name}|{p.registration_number}"
            if k not in seen_p:
                seen_p.add(k)
                uniq_principals.append(p)

        connections = await find_dossier_connections(
            entity_name,
            uniq_principals,
            existing,
        )
        chain_desc = await build_chain_description(
            entity_name,
            registrants,
            uniq_principals,
            connections,
        )
        return FARAChain(
            anchor_entity=entity_name,
            registrants=registrants,
            foreign_principals=uniq_principals,
            dossier_connections=connections,
            chain_description=chain_desc,
            disclaimer=(
                "FARA registration is a legal disclosure requirement. "
                "Registration does not indicate wrongdoing. "
                "This documents public DOJ records only. "
                "No impropriety is asserted or implied."
            ),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
