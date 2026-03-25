"""
Parallel enrichment → Claude (sonnet structure, opus narrative) → persist dossier.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import anthropic

from db import save_dossier
from enrichment import (
    charitable,
    courtlistener,
    dark_money,
    denominator,
    fara,
    fec,
    geographic,
    opensecrets,
    sec,
    socialblade,
    statements,
    voting_record,
)
from models.dossier import (
    Case,
    CharitableRecord,
    Contribution,
    DossierSchema,
    Statement,
)
from models.entity import ResolvedEntity

from adapters.fara_crossref import FARACrossRefAdapter
from adapters.revolving_door import RevolvingDoorAdapter

logger = logging.getLogger(__name__)

AUDITOR_SYSTEM = """You are a neutral forensic auditor for public-record alignment. You output structured factual records only: no verdict, no spin, no moral judgment. Do not use adjectives except where they denote measurable quantities (e.g. "three", "$1.2M"). Every assertion must map to a cited source id or be placed in `unknowns`. If data is missing, say so explicitly. Never infer intent from patterns alone."""


def _collect_dossier_entity_names(
    raw_bundle: dict[str, Any],
    entity: ResolvedEntity,
    dossier: DossierSchema,
) -> list[str]:
    """Names and labels from the dossier and raw bundle for FARA cross-reference."""
    names: set[str] = {entity.canonical_name.strip()}
    if entity.organization and str(entity.organization).strip():
        names.add(str(entity.organization).strip()[:300])
    for c in dossier.contributions:
        if c.contributor_name:
            names.add(c.contributor_name.strip()[:300])
        if c.recipient_committee:
            names.add(c.recipient_committee.strip()[:300])
    for s in dossier.sponsors:
        if s.sponsor_name:
            names.add(s.sponsor_name.strip()[:300])
    for stmt in dossier.statements:
        t = (stmt.text or "").strip()
        if len(t) > 3:
            names.add(t[:200])
    fc = raw_bundle.get("fec_contributions")
    if isinstance(fc, list):
        for row in fc[:30]:
            if not isinstance(row, dict):
                continue
            for k in ("contributor_name", "recipient_committee"):
                v = row.get(k)
                if v and len(str(v)) > 2:
                    names.add(str(v).strip()[:300])
    return sorted({n for n in names if len(n) > 1})[:80]


def _should_run_legal_citations(raw_bundle: dict[str, Any]) -> bool:
    fec = raw_bundle.get("fec_totals")
    dm = raw_bundle.get("dark_money") or {}
    career = 0.0
    if isinstance(fec, dict):
        try:
            career = float(fec.get("career_total_receipts") or 0)
        except (TypeError, ValueError):
            career = 0
    has_dm = False
    if isinstance(dm, dict) and dm:
        rs = dm.get("risk_summary") if isinstance(dm.get("risk_summary"), dict) else {}
        try:
            dc = int(rs.get("disbursement_count", 0) or 0)
        except (TypeError, ValueError):
            dc = 0
        try:
            td = float(rs.get("total_disbursed") or 0)
        except (TypeError, ValueError):
            td = 0.0
        has_dm = bool(dm.get("disbursements") or dc > 0 or td > 0)
    return bool(fec) or has_dm or career > 0


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


def _coerce_unknowns_to_list(value: Any) -> list[str]:
    """Sonnet sometimes returns unknowns as a dict; DossierSchema requires list[str]."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, dict):
        return [f"{k}: {v}" for k, v in value.items()]
    return [str(value)]


def _coerce_sonnet_dossier_payload(data: dict[str, Any]) -> None:
    """
    Sonnet sometimes returns social_metrics as [] (list) or sources as a mix of dicts and
    bare strings (e.g. 'fec'). DossierSchema expects social_metrics: dict|None and
    sources: list[dict].
    """
    sm = data.get("social_metrics")
    if isinstance(sm, list):
        data["social_metrics"] = {}
    src = data.get("sources")
    if isinstance(src, list):
        data["sources"] = [s for s in src if isinstance(s, dict)]


def _coerce_contributions(raw: list[Any]) -> list[dict[str, Any]]:
    """
    Normalize contribution dicts from Claude's JSON.
    Claude sometimes uses different field names.
    Map any variant to the canonical Contribution schema.
    """
    out: list[dict[str, Any]] = []
    for c in (raw or []):
        if not isinstance(c, dict):
            continue
        try:
            amt = float(c.get("amount") or 0.0)
        except (TypeError, ValueError):
            amt = 0.0
        normalized: dict[str, Any] = {
            "contributor_name": (
                c.get("contributor_name") or
                c.get("contributor") or
                c.get("name") or
                "unknown"
            ),
            "recipient_committee": (
                c.get("recipient_committee") or
                c.get("committee") or
                c.get("recipient") or
                c.get("committee_name") or
                "unknown"
            ),
            "amount": amt,
            "transaction_date": c.get("transaction_date") or c.get("date"),
            "election_cycle": c.get("election_cycle") or c.get("cycle"),
            "fec_url": c.get("fec_url"),
        }
        out.append(normalized)
    return out


async def _run_labeled(
    label: str,
    coro: Any,
    sources: list[dict[str, Any]],
    unknowns: list[str],
) -> tuple[str, Any]:
    try:
        val = await coro
        sources.append({"id": label, "status": "ok"})
        return label, val
    except Exception as exc:  # noqa: BLE001
        msg = f"failed: {exc}"
        sources.append({"id": label, "status": f"failed: {msg}"})
        unknowns.append(f"{label} enrichment failed: {msg}")
        logger.exception("%s failed", label)
        return label, None


NARRATIVE_SUMMARY_TIER_FALLBACK = (
    "Structured public-record fields below replace the long-form narrative for this tier."
)


async def assemble_dossier(
    frame_id: str,
    entity: ResolvedEntity,
    *,
    opus_narrative: bool = True,
) -> DossierSchema:
    sources: list[dict[str, Any]] = []
    unknowns: list[str] = []

    jobs: list[Any] = [
        _run_labeled(
            "charitable",
            charitable.get_charitable_record(entity.canonical_name, ein=entity.ein),
            sources,
            unknowns,
        ),
        _run_labeled(
            "courtlistener",
            courtlistener.search_cases(entity.canonical_name),
            sources,
            unknowns,
        ),
        _run_labeled(
            "statements",
            statements.search_statements(entity.canonical_name),
            sources,
            unknowns,
        ),
    ]

    if entity.type in ("politician", "corporate_exec"):
        jobs.extend(
            [
                _run_labeled(
                    "fec_contributions",
                    fec.get_contributions(entity.canonical_name),
                    sources,
                    unknowns,
                ),
                _run_labeled(
                    "fec_expenditures",
                    fec.get_expenditures(entity.canonical_name),
                    sources,
                    unknowns,
                ),
                _run_labeled(
                    "fec_totals",
                    fec.get_candidate_totals(entity.canonical_name),
                    sources,
                    unknowns,
                ),
                _run_labeled(
                    "opensecrets",
                    opensecrets.get_summary(entity.canonical_name),
                    sources,
                    unknowns,
                ),
            ]
        )

    if entity.type == "corporate_exec":
        jobs.append(
            _run_labeled(
                "sec_search",
                sec.search_company(entity.canonical_name),
                sources,
                unknowns,
            )
        )
        if entity.sec_cik:
            jobs.append(
                _run_labeled(
                    "sec_filings",
                    sec.get_filings_for_cik(entity.sec_cik),
                    sources,
                    unknowns,
                )
            )

    if entity.type in ("influencer", "podcaster"):
        jobs.append(
            _run_labeled(
                "socialblade",
                socialblade.get_channel_metrics(entity.canonical_name),
                sources,
                unknowns,
            )
        )

    labeled = await asyncio.gather(*jobs)
    raw_bundle: dict[str, Any] = {"entity": entity.model_dump(), "frame_id": frame_id}
    for label, val in labeled:
        raw_bundle[label] = val

    fec_totals = raw_bundle.get("fec_totals")
    if fec_totals:
        print(f"[dossier] fec_totals for {entity.canonical_name}: {fec_totals}")
    else:
        print(f"[dossier] fec_totals empty for {entity.canonical_name}")

    if fec_totals and isinstance(fec_totals, dict) and fec_totals.get("candidate_id"):
        sources[:] = [
            s
            for s in sources
            if not (
                s.get("id") == "fec_totals"
                and s.get("status") == "ok"
                and set(s.keys()) == {"id", "status"}
            )
        ]
        sources.append(
            {
                "id": "fec_totals",
                "status": "ok",
                "candidate_id": fec_totals.get("candidate_id"),
                "career_total_receipts": fec_totals.get(
                    "career_total_receipts"
                ),
                "most_recent_cycle": fec_totals.get("most_recent_cycle"),
                "fec_url": fec_totals.get("fec_url"),
            }
        )

    # Dark money trace — runs after fec_totals resolves so we have candidate_id
    dark_money_result: dict[str, Any] = {}
    if entity.type in ("politician", "corporate_exec"):
        fec_tot = raw_bundle.get("fec_totals")
        candidate_id = None
        if isinstance(fec_tot, dict):
            candidate_id = fec_tot.get("candidate_id")
        if not candidate_id and entity.fec_candidate_id:
            candidate_id = entity.fec_candidate_id
        if candidate_id:
            try:
                dark_money_result = await dark_money.run_dark_money_trace(
                    candidate_id=candidate_id,
                    entity_name=entity.canonical_name,
                )
                print(
                    f"[dossier] dark_money trace complete for "
                    f"{entity.canonical_name}: "
                    f"{dark_money_result.get('risk_summary', {}).get('disbursement_count', 0)} "
                    f"disbursements, "
                    f"${dark_money_result.get('risk_summary', {}).get('total_disbursed', 0):,.0f} total"
                )
            except Exception as dm_exc:
                print(f"[dossier] dark_money trace failed: {dm_exc}")
                unknowns.append(
                    f"Dark money trace failed: {str(dm_exc)[:150]}"
                )

    raw_bundle["dark_money"] = dark_money_result

    # Extended enrichment for politicians
    if entity.type in ("politician",):
        fec_tot = raw_bundle.get("fec_totals") or {}

        # Voting record
        try:
            voting = await voting_record.run_voting_record(
                entity.canonical_name,
            )
            raw_bundle["voting_record"] = voting
            print(
                f"[dossier] voting_record for "
                f"{entity.canonical_name}: "
                f"{len(voting.get('recent_votes', []))} votes"
            )
        except Exception as ve:
            unknowns.append(
                f"Voting record lookup failed: {str(ve)[:150]}"
            )

        # FARA check
        try:
            fara_result = await fara.run_fara_check(
                entity.canonical_name,
            )
            raw_bundle["fara"] = fara_result
            is_agent = fara_result.get(
                "is_registered_foreign_agent", False,
            )
            print(
                f"[dossier] fara for "
                f"{entity.canonical_name}: "
                f"registered_foreign_agent={is_agent}"
            )
        except Exception as fe:
            unknowns.append(
                f"FARA check failed: {str(fe)[:150]}"
            )

        # Denominator context
        try:
            denom = await denominator.run_denominator(
                entity.canonical_name,
                fec_tot if isinstance(fec_tot, dict) else {},
            )
            raw_bundle["denominator"] = denom
            ctx = denom.get("denominator_context", {})
            stmts = ctx.get("context_statements", [])
            if stmts:
                print(
                    f"[dossier] denominator for "
                    f"{entity.canonical_name}: "
                    f"{stmts[0]}"
                )
        except Exception as de:
            unknowns.append(
                f"Denominator computation failed: "
                f"{str(de)[:150]}"
            )

        # Geographic donor analysis
        try:
            committee_id = (
                raw_bundle.get("dark_money", {})
                .get("disbursements", {})
                .get("committee_id", "")
            )
            home_state = fec_tot.get("state", "") if isinstance(fec_tot, dict) else ""
            if committee_id and home_state:
                geo = await geographic.run_geographic_analysis(
                    entity_name=entity.canonical_name,
                    home_state=home_state,
                    committee_id=committee_id,
                )
                raw_bundle["geographic"] = geo
                home_pct = geo.get("home_state_pct", 0)
                print(
                    f"[dossier] geographic for "
                    f"{entity.canonical_name}: "
                    f"{home_pct}% from home state "
                    f"{home_state}"
                )
            else:
                raw_bundle["geographic"] = {
                    "operational_unknown": (
                        "committee_id or home_state "
                        "not available for geographic analysis"
                    ),
                }
        except Exception as ge:
            unknowns.append(
                f"Geographic analysis failed: {str(ge)[:150]}"
            )

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    sonnet_model = os.environ.get("CLAUDE_SONNET_MODEL", "claude-sonnet-4-20250514")
    opus_model = os.environ.get("CLAUDE_OPUS_MODEL", "claude-opus-4-5")

    dossier: DossierSchema | None = None

    if key:
        client = anthropic.AsyncAnthropic(api_key=key)
        user_prompt = (
            "Given the following JSON enrichment bundle, output ONLY valid JSON matching "
            "DossierSchema fields: frame_id, entity_canonical_name, entity_type, contributions, "
            "expenditures, cases, statements, policy_chains, sponsors, charitable, sec_filings, "
            "social_metrics, sources, unknowns, narrative_summary (empty string for now). "
            "Map lists of dicts into Contribution/Case/Statement models where applicable.\n\n"
            + json.dumps(raw_bundle, default=str, ensure_ascii=False)
        )
        try:
            msg = await client.messages.create(
                model=sonnet_model,
                max_tokens=8192,
                system=AUDITOR_SYSTEM,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "text", None))
            data = _extract_json_object(text)
            data["unknowns"] = _coerce_unknowns_to_list(data.get("unknowns"))
            if "contributions" in data and isinstance(
                data["contributions"], list
            ):
                data["contributions"] = _coerce_contributions(
                    data["contributions"]
                )
            _coerce_sonnet_dossier_payload(data)
            dossier = DossierSchema.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Claude sonnet dossier structuring failed: %s", exc)
            unknowns.append(f"sonnet structuring: {exc}")

    if dossier is None:
        contributions: list[Contribution] = []
        raw_c = raw_bundle.get("fec_contributions")
        if isinstance(raw_c, list):
            for x in raw_c:
                if isinstance(x, Contribution):
                    contributions.append(x)
                elif isinstance(x, dict):
                    try:
                        contributions.append(Contribution.model_validate(x))
                    except Exception:  # noqa: BLE001
                        continue
        ch = CharitableRecord()
        if isinstance(raw_bundle.get("charitable"), CharitableRecord):
            ch = raw_bundle["charitable"]
        elif isinstance(raw_bundle.get("charitable"), dict):
            try:
                ch = CharitableRecord.model_validate(raw_bundle["charitable"])
            except Exception:  # noqa: BLE001
                pass

        cases: list[Case] = []
        cl = raw_bundle.get("courtlistener")
        if isinstance(cl, list):
            for i, row in enumerate(cl[:20]):
                if isinstance(row, dict):
                    cases.append(
                        Case(
                            name=str(row.get("caseName") or row.get("absolute_url") or f"case-{i}"),
                            court=str(row.get("court") or "") or None,
                            source_url=str(row.get("absolute_url") or "") or None,
                        )
                    )

        stmts: list[Statement] = []
        st = raw_bundle.get("statements")
        if isinstance(st, list):
            for row in st[:20]:
                if isinstance(row, dict):
                    stmts.append(
                        Statement(
                            text=str(row.get("title") or row.get("description") or "")[:2000],
                            source_url=str(row.get("url") or "") or None,
                        )
                    )

        dossier = DossierSchema(
            frame_id=frame_id,
            entity_canonical_name=entity.canonical_name,
            entity_type=entity.type,
            contributions=contributions,
            expenditures=list(raw_bundle["fec_expenditures"])
            if isinstance(raw_bundle.get("fec_expenditures"), list)
            else [],
            cases=cases,
            statements=stmts,
            charitable=ch,
            sec_filings=list(raw_bundle["sec_filings"])
            if isinstance(raw_bundle.get("sec_filings"), list)
            else [],
            social_metrics=raw_bundle.get("socialblade")
            if isinstance(raw_bundle.get("socialblade"), dict)
            else None,
            sources=sources,
            unknowns=unknowns,
            narrative_summary="",
        )

    narrative = ""
    if key and opus_narrative:
        try:
            client = anthropic.AsyncAnthropic(api_key=key)
            opus_context_extra = ""
            if fec_totals and isinstance(fec_totals, dict):
                try:
                    cr = float(fec_totals.get("career_total_receipts") or 0)
                except (TypeError, ValueError):
                    cr = 0.0
                if cr > 0:
                    opus_context_extra = (
                        f"\n\nFEC career total receipts: ${cr:,.0f} "
                        f"over {fec_totals.get('cycles_found')} election cycles. "
                        f"Most recent cycle: {fec_totals.get('most_recent_cycle')}. "
                        f"FEC profile: {fec_totals.get('fec_url')}"
                    )
            msg2 = await client.messages.create(
                model=opus_model,
                max_tokens=4096,
                system=AUDITOR_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": "Write only the field narrative_summary: chronological, complete, "
                        "no omissions, no adjectives unless measurements. Respond with a JSON object "
                        "with a single key narrative_summary.\n\n"
                        + opus_context_extra
                        + dossier.model_dump_json(),
                    }
                ],
            )
            text2 = "".join(b.text for b in msg2.content if getattr(b, "text", None))
            try:
                nj = _extract_json_object(text2)
                narrative = str(nj.get("narrative_summary", ""))
            except Exception:  # noqa: BLE001
                narrative = text2[:8000]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Claude opus narrative failed: %s", exc)
            unknowns.append(f"opus narrative: {exc}")
    elif not opus_narrative:
        narrative = NARRATIVE_SUMMARY_TIER_FALLBACK

    if narrative:
        dossier.narrative_summary = narrative

    dossier.sources = sources
    dossier.unknowns = list(dict.fromkeys([*dossier.unknowns, *unknowns]))

    if _should_run_legal_citations(raw_bundle):
        try:
            from adapters.legal_citations import LegalCitationAdapter

            legal_adapter = LegalCitationAdapter()
            legal_result = await legal_adapter.analyze(
                entity.canonical_name,
                raw_bundle,
            )
            dossier.legal_citations = legal_result.model_dump(mode="json")
        except Exception as legal_exc:  # noqa: BLE001
            logger.warning("Legal citation adapter failed: %s", legal_exc)

    try:
        revolving_door_adapter = RevolvingDoorAdapter()
        revolving_result = await revolving_door_adapter.analyze(entity.canonical_name)
        dossier.revolving_door = revolving_result.model_dump(mode="json")
    except Exception as rd_exc:  # noqa: BLE001
        logger.warning("Revolving door adapter failed: %s", rd_exc)

    try:
        existing_entities = _collect_dossier_entity_names(raw_bundle, entity, dossier)
        fara_adapter = FARACrossRefAdapter()
        fara_result = await fara_adapter.analyze(
            entity.canonical_name,
            existing_dossier_entities=existing_entities,
        )
        dossier.fara_chain = fara_result.model_dump(mode="json")
    except Exception as fara_exc:  # noqa: BLE001
        logger.warning("FARA cross-reference adapter failed: %s", fara_exc)

    await save_dossier(dossier)
    return dossier
