"""
SEC EDGAR — public filings (Form 4, 10-K, 13-G). No API key.

Follows https://www.sec.gov/os/webmaster-faq#code-support — identify via User-Agent.
"""

from __future__ import annotations

import os
import re
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urlencode

import httpx

# SEC returns 403 if User-Agent is missing or generic; include a reachable identity string.
DEFAULT_SEC_USER_AGENT = "FRAME-EDGAR/1.0 (open-source@frame.dev)"

EFTS_SEARCH = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS_TMPL = "https://data.sec.gov/submissions/CIK{cik_padded}.json"
FACTS_TMPL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
ARCHIVES_DATA_TMPL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/"


def _ua() -> str:
    return (
        os.environ.get("SEC_EDGAR_USER_AGENT")
        or os.environ.get("SEC_USER_AGENT")
        or DEFAULT_SEC_USER_AGENT
    ).strip()


def _headers() -> dict[str, str]:
    return {"User-Agent": _ua(), "Accept-Encoding": "gzip, deflate"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def pad_cik(cik: str) -> str:
    s = re.sub(r"\D", "", cik)
    if not s:
        raise ValueError("Invalid CIK")
    return s.zfill(10)


def cik_int_str(cik_padded: str) -> str:
    return str(int(cik_padded, 10))


def search_entity(name: str) -> list[dict[str, Any]]:
    """
    Full-text search EDGAR index; returns up to 5 distinct CIKs with names and form types seen.
    """
    q = (name or "").strip()
    if not q:
        return []
    params = {
        "q": q,
        "dateRange": "custom",
        "startdt": "2000-01-01",
        "forms": "4,10-K,SC-13G",
    }
    url = f"{EFTS_SEARCH}?{urlencode(params, quote_via=quote_plus)}"
    with httpx.Client(timeout=45.0, headers=_headers(), follow_redirects=True) as client:
        r = client.get(url)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response else 0
            if code in (403, 429):
                raise RuntimeError(
                    "SEC EDGAR search returned "
                    f"HTTP {code}. Set SEC_EDGAR_USER_AGENT to a descriptive User-Agent with "
                    "contact information (https://www.sec.gov/os/webmaster-faq#code-support)."
                ) from exc
            raise
        data = r.json()
    hits = (data.get("hits") or {}).get("hits") or []
    by_cik: dict[str, dict[str, Any]] = {}
    for h in hits:
        src = h.get("_source") or {}
        score = float(h.get("_score") or 0.0)
        forms = [src.get("form")] + (src.get("root_forms") or [])
        forms = [f for f in forms if f]
        for raw_cik in src.get("ciks") or []:
            cik = pad_cik(str(raw_cik))
            disp = (src.get("display_names") or [None])[0]
            if cik not in by_cik:
                by_cik[cik] = {
                    "cik": cik,
                    "company_name": disp or f"CIK {cik}",
                    "filing_types_found": set(),
                    "max_score": score,
                }
            else:
                by_cik[cik]["max_score"] = max(by_cik[cik]["max_score"], score)
                if disp and by_cik[cik]["company_name"].startswith("CIK "):
                    by_cik[cik]["company_name"] = disp
            by_cik[cik]["filing_types_found"].update(forms)
    ranked = sorted(by_cik.values(), key=lambda x: -x["max_score"])[:5]
    for row in ranked:
        row["filing_types_found"] = sorted(row["filing_types_found"])
    return ranked


def _text_el(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    if el.text and el.text.strip():
        return el.text.strip()
    child = el.find(".//{*}value")
    if child is not None and child.text:
        return child.text.strip()
    return None


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if tag.startswith("{") else tag


def _find_first(parent: ET.Element, name: str) -> ET.Element | None:
    for el in parent.iter():
        if _local_tag(el.tag) == name:
            return el
    return None


def _find_all_children(parent: ET.Element, name: str) -> list[ET.Element]:
    out: list[ET.Element] = []
    for el in parent:
        if _local_tag(el.tag) == name:
            out.append(el)
    return out


def parse_form4_xml(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    owner_el = _find_first(root, "reportingOwner")
    owner_name = None
    if owner_el is not None:
        rid = _find_first(owner_el, "reportingOwnerId")
        if rid is not None:
            name_el = _find_first(rid, "rptOwnerName")
            owner_name = _text_el(name_el)
    issuer_el = _find_first(root, "issuer")
    issuer_name = None
    if issuer_el is not None:
        issuer_name = _text_el(_find_first(issuer_el, "issuerName"))
    period_el = _find_first(root, "periodOfReport")
    period = _text_el(period_el)
    transactions: list[dict[str, Any]] = []
    nd_table = _find_first(root, "nonDerivativeTable")
    if nd_table is not None:
        for tx in _find_all_children(nd_table, "nonDerivativeTransaction"):
            sec = _find_first(tx, "securityTitle")
            title = _text_el(sec)
            td = _find_first(tx, "transactionDate")
            tdate = _text_el(td) if td is not None else None
            ta = _find_first(tx, "transactionAmounts")
            shares_v, price_v, ad_code = None, None, None
            if ta is not None:
                shares_v = _text_el(_find_first(ta, "transactionShares"))
                price_v = _text_el(_find_first(ta, "transactionPricePerShare"))
                code_el = _find_first(ta, "transactionAcquiredDisposedCode")
                ad_code = _text_el(code_el)
            code_el2 = _find_first(tx, "transactionCoding")
            tx_code = _text_el(_find_first(code_el2, "transactionCode")) if code_el2 is not None else None
            transactions.append(
                {
                    "security": title,
                    "transaction_date": tdate,
                    "shares": shares_v,
                    "price_per_share": price_v,
                    "acquired_or_disposed": ad_code,
                    "transaction_code": tx_code,
                },
            )
    return {
        "reporting_owner": owner_name,
        "issuer": issuer_name,
        "period_of_report": period,
        "transactions": transactions,
    }


def _form4_index_and_xml_url(cik_padded: str, accession: str) -> tuple[str, str] | None:
    accession_nodash = accession.replace("-", "")
    cik_i = cik_int_str(cik_padded)
    idx_url = f"{ARCHIVES_DATA_TMPL.format(cik_int=cik_i, accession_nodash=accession_nodash)}index.json"
    with httpx.Client(timeout=30.0, headers=_headers(), follow_redirects=True) as client:
        ir = client.get(idx_url)
        if ir.status_code != 200:
            return None
        index = ir.json()
    items = ((index.get("directory") or {}).get("item")) or []
    xml_name = None
    for it in items:
        nm = it.get("name") or ""
        low = nm.lower()
        if low.endswith(".xml") and ("form4" in low or "form_4" in low or "wk-form4" in low):
            xml_name = nm
            break
    if not xml_name:
        for it in items:
            nm = it.get("name") or ""
            if nm.lower().endswith(".xml"):
                xml_name = nm
                break
    if not xml_name:
        return None
    xml_url = f"{ARCHIVES_DATA_TMPL.format(cik_int=cik_i, accession_nodash=accession_nodash)}{xml_name}"
    return idx_url, xml_url


def get_form4_filings(cik: str, limit: int = 10) -> list[dict[str, Any]]:
    cik_padded = pad_cik(cik)
    url = SUBMISSIONS_TMPL.format(cik_padded=cik_padded)
    with httpx.Client(timeout=45.0, headers=_headers(), follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        sub = r.json()
    recent = (sub.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accs = recent.get("accessionNumber") or []
    prim = recent.get("primaryDocument") or []
    out: list[dict[str, Any]] = []
    for i, f in enumerate(forms):
        if f != "4":
            continue
        if len(out) >= limit:
            break
        accession = accs[i] if i < len(accs) else ""
        fdate = dates[i] if i < len(dates) else ""
        primary = prim[i] if i < len(prim) else ""
        idx_xml = _form4_index_and_xml_url(cik_padded, accession)
        row: dict[str, Any] = {
            "filing_date": fdate,
            "accession_number": accession,
            "primary_document": primary,
            "parsed": None,
            "edgar_viewer_url": (
                f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={cik_int_str(cik_padded)}"
                f"&accession_number={accession}&xbrl_type=v"
            ),
        }
        if idx_xml:
            _idx_url, xml_url = idx_xml
            row["filing_index_url"] = _idx_url
            row["form4_xml_url"] = xml_url
            try:
                with httpx.Client(timeout=30.0, headers=_headers(), follow_redirects=True) as xc:
                    xr = xc.get(xml_url)
                    if xr.status_code == 200:
                        row["parsed"] = parse_form4_xml(xr.text)
            except (ET.ParseError, httpx.HTTPError, ValueError):
                row["parsed"] = None
        out.append(row)
    return out


def _latest_fact_usd(fact_block: dict[str, Any] | None) -> dict[str, Any] | None:
    if not fact_block:
        return None
    units = fact_block.get("units") or {}
    series = units.get("USD") or units.get("shares") or []
    if not series and units:
        series = next(iter(units.values()))
    if not isinstance(series, list) or not series:
        return None
    best = max(series, key=lambda x: x.get("end") or "")
    return {
        "val": best.get("val"),
        "end": best.get("end"),
        "fy": best.get("fy"),
        "fp": best.get("fp"),
    }


def get_company_facts(cik: str) -> dict[str, Any]:
    cik_padded = pad_cik(cik)
    url = FACTS_TMPL.format(cik_padded=cik_padded)
    with httpx.Client(timeout=45.0, headers=_headers(), follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        facts = r.json()
    entities = facts.get("facts") or {}
    # US-GAAP tags (issuer-dependent availability)
    gaap = entities.get("us-gaap") or {}
    assets = _latest_fact_usd(gaap.get("Assets"))
    revenue = _latest_fact_usd(
        gaap.get("Revenues") or gaap.get("RevenueFromContractWithCustomerExcludingAssessedTax"),
    )
    net_income = _latest_fact_usd(gaap.get("NetIncomeLoss") or gaap.get("ProfitLoss"))
    return {
        "cik": cik_padded,
        "entity_name": facts.get("entityName"),
        "facts": {
            "total_assets": assets,
            "revenue": revenue,
            "net_income": net_income,
        },
        "source_url": url,
    }


def sec_edgar_probe(name: str | None, cik: str | None) -> dict[str, Any]:
    """Raw bundle for POST /v1/sec-edgar (unsigned)."""
    picked_name: str | None = None
    picked_cik: str | None = None
    search_hits: list[dict[str, Any]] = []
    if cik and cik.strip():
        picked_cik = pad_cik(cik.strip())
        picked_name = None
    elif name and name.strip():
        search_hits = search_entity(name.strip())
        if not search_hits:
            return {
                "entity": None,
                "cik": None,
                "form4_filings": [],
                "company_facts": None,
                "confidence_tier": "no_match",
                "search_hits": [],
            }
        top = search_hits[0]
        picked_cik = top["cik"]
        picked_name = top.get("company_name")
    else:
        raise ValueError("Provide name or cik")
    form4 = get_form4_filings(picked_cik, limit=10)
    try:
        facts = get_company_facts(picked_cik)
    except httpx.HTTPError:
        facts = None
    return {
        "entity": picked_name,
        "cik": picked_cik,
        "form4_filings": form4,
        "company_facts": facts,
        "confidence_tier": "aggregated_registry",
        "search_hits": search_hits,
    }


def build_sec_receipt_payload(entity_name: str) -> dict[str, Any]:
    """
    Frame-shaped unsigned receipt: SEC EDGAR search + Form 4 + company facts for top CIK.
    """
    bundle = sec_edgar_probe(entity_name.strip(), None)
    if bundle.get("cik") is None:
        return {
            "schemaVersion": "1.0.0",
            "receiptId": str(uuid.uuid4()),
            "createdAt": _now_iso(),
            "claims": [
                {
                    "id": "claim-1",
                    "statement": f"No SEC EDGAR registrant match for search: {entity_name.strip()}",
                    "type": "observed",
                    "implication_risk": "low",
                },
            ],
            "sources": [
                {
                    "id": "sec-efts-search",
                    "adapter": "edgar",
                    "url": EFTS_SEARCH,
                    "title": "SEC EDGAR full-text search (EFTS)",
                    "retrievedAt": _now_iso(),
                },
            ],
            "narrative": [
                {
                    "text": (
                        f"No CIK-level EDGAR match was returned for {entity_name.strip()} "
                        "in the Form 4 / 10-K / SC 13-G index slice queried."
                    ),
                    "sourceId": "sec-efts-search",
                },
            ],
            "unknowns": {
                "operational": [
                    {
                        "text": "EFTS search returned zero hits for this name in the requested form filter.",
                        "resolution_possible": True,
                    },
                ],
                "epistemic": [
                    {
                        "text": (
                            "Individuals may not appear as issuers; insider filings attach to issuer CIKs, "
                            "not personal names."
                        ),
                        "resolution_possible": False,
                    },
                ],
            },
            "contentHash": "",
        }
    cik = bundle["cik"]
    entity = bundle.get("entity") or f"CIK {cik}"
    form4 = bundle.get("form4_filings") or []
    facts = bundle.get("company_facts") or {}
    sources: list[dict[str, Any]] = [
        {
            "id": "sec-submissions",
            "adapter": "edgar",
            "url": SUBMISSIONS_TMPL.format(cik_padded=cik),
            "title": f"SEC company submissions JSON (CIK {cik})",
            "retrievedAt": _now_iso(),
            "externalRef": cik,
        },
    ]
    if facts and facts.get("source_url"):
        fblock = facts.get("facts") or {}
        sources.append(
            {
                "id": "sec-company-facts",
                "adapter": "edgar",
                "url": facts["source_url"],
                "title": f"SEC XBRL company facts (CIK {cik})",
                "retrievedAt": _now_iso(),
                "externalRef": cik,
                "metadata": {
                    "total_assets_val": (fblock.get("total_assets") or {}).get("val"),
                    "revenue_val": (fblock.get("revenue") or {}).get("val"),
                    "net_income_val": (fblock.get("net_income") or {}).get("val"),
                },
            },
        )
    narrative: list[dict[str, str]] = []
    nid = 0
    for row in form4[:5]:
        sid = f"sec-form4-{row.get('accession_number', nid)}"
        nid += 1
        if row.get("form4_xml_url"):
            sources.append(
                {
                    "id": sid,
                    "adapter": "edgar",
                    "url": row["form4_xml_url"],
                    "title": f"Form 4 XML {row.get('accession_number')}",
                    "retrievedAt": _now_iso(),
                    "externalRef": row.get("accession_number"),
                },
            )
        parsed = row.get("parsed") or {}
        owner = parsed.get("reporting_owner") or "Unknown insider"
        issuer = parsed.get("issuer") or entity
        txs = parsed.get("transactions") or []
        if txs:
            t0 = txs[0]
            line = (
                f"Form 4 filed {row.get('filing_date')}: {owner} at {issuer}; "
                f"transaction on {t0.get('transaction_date')}: "
                f"{t0.get('shares')} shares, "
                f"price {t0.get('price_per_share')}, code {t0.get('transaction_code')} "
                f"({t0.get('acquired_or_disposed')} acquired/disposed)."
            )
        else:
            line = f"Form 4 filed {row.get('filing_date')} (accession {row.get('accession_number')}); XML parse unavailable or no non-derivative rows extracted."
        narrative.append({"text": line, "sourceId": sid if row.get("form4_xml_url") else "sec-submissions"})

    if not narrative:
        narrative.append(
            {
                "text": f"CIK {cik} ({entity}) has no recent Form 4 filings in the submissions index slice retrieved.",
                "sourceId": "sec-submissions",
            },
        )

    fa = ((facts or {}).get("facts") or {}).get("total_assets") or {}
    rev = ((facts or {}).get("facts") or {}).get("revenue") or {}
    ni = ((facts or {}).get("facts") or {}).get("net_income") or {}
    if fa.get("val") is not None or rev.get("val") is not None:
        narrative.append(
            {
                "text": (
                    f"Latest reported assets (USD, end {fa.get('end')}): {fa.get('val')}; "
                    f"revenue: {rev.get('val')}; net income: {ni.get('val')}."
                ),
                "sourceId": "sec-company-facts" if any(s["id"] == "sec-company-facts" for s in sources) else "sec-submissions",
            },
        )

    return {
        "schemaVersion": "1.0.0",
        "receiptId": str(uuid.uuid4()),
        "createdAt": _now_iso(),
        "claims": [
            {
                "id": "claim-1",
                "statement": f"SEC EDGAR filings retrieved for {entity} (CIK {cik})",
                "type": "observed",
                "implication_risk": "medium",
            },
        ],
        "sources": sources,
        "narrative": narrative,
        "unknowns": {
            "operational": [
                {
                    "text": "SEC EDGAR may rate-limit or block clients without a descriptive User-Agent.",
                    "resolution_possible": True,
                },
            ],
            "epistemic": [
                {
                    "text": (
                        "Form 4 narrative reflects filed transactions only; it does not establish "
                        "materiality, intent, or valuation impact."
                    ),
                    "resolution_possible": False,
                },
            ],
        },
        "contentHash": "",
    }
