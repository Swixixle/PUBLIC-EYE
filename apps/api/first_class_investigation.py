"""
First-class journalist and outlet investigations for PUBLIC EYE slim pipeline.
GDELT (byline corpus + narrative echo) augments the journalist receipt; no NewsAPI,
Meta Ad Library, or proportionality — public-record adapters otherwise.

- AdapterResult: structured per-adapter outcome (no sentinel/exception ambiguity in downstream).
- latency_ms on every data_sources row (signed payload).
- run_adapter: CancelledError re-raised so parent task cancellation does not orphan work.
- Independent adapters use _parallel_adapters (global budget, explicit cancel + gather cleanup);
  votes run after member resolve (sequential).
- Layer B (``layer_b``): Perplexity Sonar web research with explicit ``layer`` / ``layer_note`` on
  each row (cited, not signed); entrypoints in ``perplexity_adapter`` (impl: ``perplexity_layer_b``).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable
from datetime import datetime, timezone
from typing import Any

from adapter_result_run import AdapterResult, run_adapter
from adapters import sec_edgar
from adapters_media import fetch_congress_bills, fetch_fec_by_name, fetch_irs990_by_name, fetch_lda_by_name
from enrichment.voting_record import get_recent_votes, search_member_by_name
from journalist_dossier_article import _fetch_fec_schedule_a_individual, _quoted_sources_payload

logger = logging.getLogger(__name__)

ANALYZE_ADAPTER_TIMEOUT = 8.0
GLOBAL_INVESTIGATION_TIMEOUT = 10.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _courtlistener_slim(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slim: list[dict[str, Any]] = []
    for r in (rows or [])[:5]:
        if not isinstance(r, dict):
            continue
        slim.append(
            {
                "case_name": r.get("case_name"),
                "court": r.get("court"),
                "date_filed": r.get("date_filed"),
                "url": r.get("url") or r.get("source_url"),
            },
        )
    return slim


def _investigation_meta_from_results(wall_time_ms: float, results: list[AdapterResult]) -> dict[str, Any]:
    adapters: dict[str, Any] = {}
    for r in results:
        if r.timed_out:
            status = "timeout"
        elif r.ok:
            status = "ok"
        else:
            status = "error"
        adapters[r.adapter] = {
            "status": status,
            "latency_ms": round(r.latency_ms, 1),
            "error_type": type(r.error).__name__ if r.error is not None else None,
        }
    return {"wall_time_ms": round(wall_time_ms, 1), "adapters": adapters}


def _log_investigation_meta(meta: dict[str, Any]) -> None:
    logger.info(
        "investigation_meta wall_time_ms=%s adapters=%s",
        meta.get("wall_time_ms"),
        list((meta.get("adapters") or {}).keys()),
    )


async def _parallel_adapters(
    steps: list[tuple[str, Awaitable[AdapterResult]]],
    *,
    budget_s: float = GLOBAL_INVESTIGATION_TIMEOUT,
) -> tuple[AdapterResult, ...]:
    """Run adapter awaitables under a global wall-clock budget.

    On ``asyncio.TimeoutError``: cancel outstanding tasks, ``await gather(..., return_exceptions=True)``
    for cleanup, then return structured ``AdapterResult`` rows (including synthetic timeouts for
    cancelled work). On ``asyncio.CancelledError``: same cleanup, then re-raise.
    """
    if not steps:
        return ()

    t_start = time.monotonic()

    def _synth_timeout(name: str) -> AdapterResult:
        return AdapterResult(
            adapter=name,
            ok=False,
            timed_out=True,
            source_error=True,
            detail=f"global_budget_timeout_after_{budget_s}s",
            latency_ms=round((time.monotonic() - t_start) * 1000, 1),
        )

    tasks = [asyncio.create_task(aw, name=name) for name, aw in steps]
    try:
        gathered = await asyncio.wait_for(asyncio.gather(*tasks), timeout=budget_s)
        return tuple(gathered)
    except asyncio.CancelledError:
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    except asyncio.TimeoutError:
        for t in tasks:
            if not t.done():
                t.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        out: list[AdapterResult] = []
        for i, (name, _) in enumerate(steps):
            item = outcomes[i]
            if isinstance(item, asyncio.CancelledError):
                out.append(_synth_timeout(name))
            elif isinstance(item, Exception):
                out.append(
                    AdapterResult(
                        adapter=name,
                        ok=False,
                        source_error=True,
                        error=item,
                        detail=str(item)[:300],
                        latency_ms=round((time.monotonic() - t_start) * 1000, 1),
                    ),
                )
            else:
                out.append(item)
        return tuple(out)


async def _fetch_courtlistener(name: str, limit: int = 5) -> AdapterResult:
    q = (name or "").strip()
    if len(q) < 2:
        return AdapterResult(
            adapter="courtlistener",
            ok=True,
            value=[],
            rows_returned=0,
            latency_ms=0.0,
        )
    from adapters import courtlistener as cl

    result = await run_adapter(
        cl.search_opinions(q[:200], limit=limit),
        adapter="courtlistener",
        timeout=ANALYZE_ADAPTER_TIMEOUT,
    )
    if result.ok:
        slim = _courtlistener_slim(result.value if isinstance(result.value, list) else [])
        result.value = slim
        result.rows_returned = len(slim)
    return result


async def build_journalist_investigation_record(
    *,
    display_name: str,
    publication: str,
    article_url: str,
    article_topic: str | None,
    article_text: str | None,
    named_entities: list[Any] | None,
    linked_article_analysis_id: str,
) -> dict[str, Any]:
    """Assemble raw journalist investigation dict (unsigned)."""
    t_wall0 = time.monotonic()
    name = (display_name or "").strip()
    data_sources: list[dict[str, Any]] = []
    rid = str(uuid.uuid4())
    base: dict[str, Any] = {
        "report_id": rid,
        "receipt_type": "journalist_investigation",
        "generated_at": _now_iso(),
        "subject": {"display_name": name or None, "publication": (publication or "").strip() or None},
        "linked_article_analysis_id": linked_article_analysis_id,
        "linked_article_url": article_url,
        "data_sources": data_sources,
        "fec_donations": None,
        "courtlistener_opinions": None,
        "congress_member": None,
        "congress_votes": None,
        "congress_bills": None,
        "sec_edgar": None,
        "lda_filings": None,
        "quoted_sources": [],
        "layer_b": None,
        "byline_corpus": None,
        "narrative_echo": None,
    }

    if not name:
        base["quoted_sources"] = _quoted_sources_payload(article_text, named_entities, "")
        data_sources.append(
            AdapterResult(adapter="journalist_subject", ok=False, detail="no_byline", latency_ms=0.0).to_source_record(),
        )
        wall_ms = (time.monotonic() - t_wall0) * 1000
        subj = AdapterResult(adapter="journalist_subject", ok=False, detail="no_byline", latency_ms=0.0)
        base["investigation_meta"] = _investigation_meta_from_results(wall_ms, [subj])
        _log_investigation_meta(base["investigation_meta"])
        return base

    votes_r: AdapterResult | None = None
    (
        fec_r,
        cl_r,
        mem_r,
        bills_r,
        sec_r,
        lda_r,
    ) = await _parallel_adapters(
        [
            (
                "fec_schedule_a",
                run_adapter(
                    lambda: _fetch_fec_schedule_a_individual(name, limit=8),
                    adapter="fec_schedule_a",
                    timeout=ANALYZE_ADAPTER_TIMEOUT,
                ),
            ),
            ("courtlistener", _fetch_courtlistener(name)),
            (
                "propublica_congress_member",
                run_adapter(
                    lambda: search_member_by_name(name),
                    adapter="propublica_congress_member",
                    timeout=ANALYZE_ADAPTER_TIMEOUT,
                ),
            ),
            (
                "congress_gov",
                run_adapter(
                    lambda: fetch_congress_bills(name[:200]),
                    adapter="congress_gov",
                    timeout=ANALYZE_ADAPTER_TIMEOUT,
                ),
            ),
            (
                "sec_edgar",
                run_adapter(
                    lambda: sec_edgar.search_entity(name[:120]),
                    adapter="sec_edgar",
                    timeout=ANALYZE_ADAPTER_TIMEOUT,
                ),
            ),
            (
                "lda",
                run_adapter(lambda: fetch_lda_by_name(name), adapter="lda", timeout=ANALYZE_ADAPTER_TIMEOUT),
            ),
        ],
    )

    if fec_r.ok:
        if isinstance(fec_r.value, list):
            fec_r.rows_returned = len(fec_r.value)
            base["fec_donations"] = list(fec_r.value)
        else:
            fec_r.ok = False
            fec_r.source_error = True
            fec_r.detail = "fec_schedule_a_non_list_response"
            base["fec_donations"] = None
    else:
        base["fec_donations"] = None
    data_sources.append(fec_r.to_source_record())

    base["courtlistener_opinions"] = cl_r.value if cl_r.ok else None
    data_sources.append(cl_r.to_source_record())

    mem = mem_r.value if mem_r.ok else None
    if not mem_r.ok:
        base["congress_member"] = None
        base["congress_votes"] = None
        data_sources.append(mem_r.to_source_record())
    elif isinstance(mem, dict) and mem.get("error"):
        base["congress_member"] = None
        base["congress_votes"] = None
        mem_r.ok = False
        mem_r.source_error = True
        mem_r.detail = str(mem.get("error"))[:300]
        data_sources.append(mem_r.to_source_record())
    elif isinstance(mem, dict) and mem.get("member_id"):
        base["congress_member"] = mem
        mem_r.rows_returned = 1
        data_sources.append(mem_r.to_source_record())
        mid = str(mem.get("member_id") or "")
        votes_r = await run_adapter(
            lambda: get_recent_votes(mid, limit=10),
            adapter="propublica_congress_votes",
            timeout=ANALYZE_ADAPTER_TIMEOUT,
        )
        if votes_r.ok:
            votes_r.rows_returned = len(votes_r.value or []) if isinstance(votes_r.value, list) else 0
        base["congress_votes"] = votes_r.value if votes_r.ok else None
        data_sources.append(votes_r.to_source_record())
    else:
        base["congress_member"] = None
        base["congress_votes"] = None
        mem_r.detail = "no_member_match"
        mem_r.rows_returned = 0
        data_sources.append(mem_r.to_source_record())

    if bills_r.ok:
        bills = bills_r.value or {}
        base["congress_bills"] = bills if isinstance(bills, dict) else bills
        err = bills.get("error") if isinstance(bills, dict) else None
        if err == "missing_api_key":
            bills_r.ok = False
            bills_r.source_error = False
            bills_r.detail = "missing_CONGRESS_API_KEY"
        elif isinstance(bills, dict) and bills.get("bills"):
            bills_r.rows_returned = len(bills.get("bills") or [])
        else:
            bills_r.detail = "no_bills"
            bills_r.rows_returned = 0
    else:
        base["congress_bills"] = None
    data_sources.append(bills_r.to_source_record())

    if sec_r.ok:
        nent = len((sec_r.value or {}).get("entities") or []) if isinstance(sec_r.value, dict) else 0
        sec_r.rows_returned = nent
        sec_r.detail = None if nent else "no_entity_hits"
    base["sec_edgar"] = sec_r.value if sec_r.ok else None
    data_sources.append(sec_r.to_source_record())

    if lda_r.ok and isinstance(lda_r.value, dict):
        lda_r.rows_returned = int(
            lda_r.value.get("filingCount") or len(lda_r.value.get("filings") or []),
        )
    base["lda_filings"] = lda_r.value if lda_r.ok else None
    data_sources.append(lda_r.to_source_record())

    meta_rows = [fec_r, cl_r, mem_r, bills_r, sec_r, lda_r]
    if votes_r is not None:
        meta_rows.append(votes_r)
    wall_ms = (time.monotonic() - t_wall0) * 1000
    base["investigation_meta"] = _investigation_meta_from_results(wall_ms, meta_rows)
    _log_investigation_meta(base["investigation_meta"])

    base["quoted_sources"] = _quoted_sources_payload(article_text, named_entities, name)
    from perplexity_adapter import build_journalist_layer_b

    layer_b = await build_journalist_layer_b(
        name=name,
        topic=article_topic or "",
        publication=publication,
        quoted_sources=base["quoted_sources"],
    )
    base["layer_b"] = layer_b

    GDELT_TIMEOUT = 12.0
    from adapters.gdelt import get_narrative_echo_score, search_byline_corpus

    async def _gdelt_byline() -> list[dict[str, Any]]:
        return await search_byline_corpus(name, publication, max_results=50)

    topic_t = (article_topic or "").strip()
    tasks: list[Awaitable[AdapterResult]] = [
        run_adapter(_gdelt_byline, adapter="gdelt_byline_corpus", timeout=GDELT_TIMEOUT),
    ]
    if topic_t:

        async def _gdelt_echo() -> dict[str, Any]:
            return await get_narrative_echo_score(topic_t, hours=48)

        tasks.append(run_adapter(_gdelt_echo, adapter="gdelt_narrative_echo", timeout=GDELT_TIMEOUT))

    gdelt_results = await asyncio.gather(*tasks)
    bc_r = gdelt_results[0]
    base["byline_corpus"] = bc_r.value if bc_r.ok else None
    if topic_t:
        echo_r = gdelt_results[1]
        base["narrative_echo"] = echo_r.value if echo_r.ok else None
    else:
        base["narrative_echo"] = None

    return base


async def build_outlet_investigation_record(
    *,
    outlet_display: str,
    domain: str,
    linked_article_analysis_id: str,
    article_url: str,
) -> dict[str, Any]:
    """Assemble raw outlet investigation dict (unsigned)."""
    from publisher_registry import lookup_domain, parent_company_for_domain

    t_wall0 = time.monotonic()
    data_sources: list[dict[str, Any]] = []
    rid = str(uuid.uuid4())
    dom = (domain or "").strip().lower().replace("www.", "")
    pub = lookup_domain(dom) if dom else {}
    outlet_name = str(pub.get("name") or outlet_display or dom or "unknown").strip()
    parent = parent_company_for_domain(dom) if dom else None
    sec_query = (parent or outlet_name)[:120]

    base: dict[str, Any] = {
        "report_id": rid,
        "receipt_type": "outlet_investigation",
        "generated_at": _now_iso(),
        "subject": {
            "outlet": outlet_name,
            "domain": dom or None,
            "parent_company": parent,
            "registry_match": bool(pub),
        },
        "linked_article_analysis_id": linked_article_analysis_id,
        "linked_article_url": article_url,
        "data_sources": data_sources,
        "courtlistener_opinions": None,
        "sec_edgar": None,
        "fec_snapshot": None,
        "lda_filings": None,
        "irs990": None,
        "layer_b": None,
    }

    cl_r, sec_r, fec_r, lda_r, irs_r = await _parallel_adapters(
        [
            ("courtlistener", _fetch_courtlistener(outlet_name[:200])),
            (
                "sec_edgar",
                run_adapter(
                    lambda: sec_edgar.search_entity(sec_query),
                    adapter="sec_edgar",
                    timeout=ANALYZE_ADAPTER_TIMEOUT,
                ),
            ),
            (
                "fec",
                run_adapter(
                    lambda: fetch_fec_by_name(outlet_name[:100]),
                    adapter="fec",
                    timeout=ANALYZE_ADAPTER_TIMEOUT,
                ),
            ),
            (
                "lda",
                run_adapter(
                    lambda: fetch_lda_by_name(outlet_name),
                    adapter="lda",
                    timeout=ANALYZE_ADAPTER_TIMEOUT,
                ),
            ),
            (
                "irs990",
                run_adapter(
                    lambda: fetch_irs990_by_name(outlet_name),
                    adapter="irs990",
                    timeout=ANALYZE_ADAPTER_TIMEOUT,
                ),
            ),
        ],
    )

    base["courtlistener_opinions"] = cl_r.value if cl_r.ok else None
    data_sources.append(cl_r.to_source_record())

    if sec_r.ok:
        nent = len((sec_r.value or {}).get("entities") or []) if isinstance(sec_r.value, dict) else 0
        sec_r.rows_returned = nent
        sec_r.detail = None if nent else "no_entity_hits"
    base["sec_edgar"] = sec_r.value if sec_r.ok else None
    data_sources.append(sec_r.to_source_record())

    base["fec_snapshot"] = fec_r.value if fec_r.ok else None
    data_sources.append(fec_r.to_source_record())

    if lda_r.ok and isinstance(lda_r.value, dict):
        lda_r.rows_returned = int(
            lda_r.value.get("filingCount") or len(lda_r.value.get("filings") or []),
        )
    base["lda_filings"] = lda_r.value if lda_r.ok else None
    data_sources.append(lda_r.to_source_record())

    base["irs990"] = irs_r.value if irs_r.ok else None
    data_sources.append(irs_r.to_source_record())

    from perplexity_adapter import build_outlet_layer_b

    layer_b = await build_outlet_layer_b(
        outlet_name=outlet_name,
        domain=dom,
        registry_match=bool(pub),
    )
    base["layer_b"] = layer_b

    wall_ms = (time.monotonic() - t_wall0) * 1000
    base["investigation_meta"] = _investigation_meta_from_results(wall_ms, [cl_r, sec_r, fec_r, lda_r, irs_r])
    _log_investigation_meta(base["investigation_meta"])

    return base
