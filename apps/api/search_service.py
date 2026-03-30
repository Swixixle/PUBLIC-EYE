"""
PUBLIC EYE conflict search — PostgreSQL FTS over receipts + coalition_maps.
Results are conflict bundles (volatility, two anchors, gap), not document lists.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

import psycopg2.extras

from front_page import _coalition_preview, _headline, _vol_copy
from receipt_store import _get_conn


def _interval_sql(date_range: str) -> str:
    dr = (date_range or "30d").strip().lower()
    if dr == "24h":
        return "INTERVAL '24 hours'"
    if dr == "7d":
        return "INTERVAL '7 days'"
    if dr == "90d":
        return "INTERVAL '90 days'"
    return "INTERVAL '30 days'"


def _named_entities_list(rec: dict[str, Any]) -> list[str]:
    raw = rec.get("named_entities")
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
        return out[:40]
    if isinstance(raw, str) and raw.strip():
        parts = re.split(r"[,;•]|\n", raw)
        return [p.strip() for p in parts if p.strip()][:40]
    return []


def _volatility_from_coalition(coal: dict[str, Any] | None) -> int:
    if not coal:
        return 0
    try:
        v = int(coal.get("divergence_score", 0))
    except (TypeError, ValueError):
        v = 0
    return max(0, min(100, v))


def build_search_result(
    receipt_id: str,
    receipt: dict[str, Any],
    coalition: dict[str, Any] | None,
    *,
    coalition_signed: bool = False,
    created_at: Any = None,
) -> dict[str, Any]:
    vol = _volatility_from_coalition(coalition)
    pa = (coalition or {}).get("position_a") if coalition else None
    pb = (coalition or {}).get("position_b") if coalition else None
    if not isinstance(pa, dict):
        pa = {}
    if not isinstance(pb, dict):
        pb = {}

    prev = _coalition_preview(coalition or {}) if coalition else {}
    sources_checked = receipt.get("sources_checked") or []
    if isinstance(sources_checked, list):
        n_sources = len(sources_checked)
    else:
        n_sources = 0
    claims = receipt.get("claims_verified")
    if isinstance(claims, list):
        n_articles = len(claims)
    else:
        n_art = receipt.get("articles")
        if isinstance(n_art, list):
            n_articles = len(n_art)
        else:
            n_articles = int(receipt.get("claims_extracted") or 0)

    dt_s = ""
    if created_at is not None:
        if isinstance(created_at, datetime):
            dt_s = created_at.date().isoformat()
        elif isinstance(created_at, date):
            dt_s = created_at.isoformat()
        elif hasattr(created_at, "isoformat"):
            try:
                dt_s = str(created_at)[:10]
            except Exception:
                dt_s = ""

    signed = bool(
        coalition_signed
        or (receipt.get("signature") or receipt.get("content_signature"))
    )

    return {
        "receipt_id": receipt_id,
        "headline": _headline(receipt),
        "article_topic": str(receipt.get("article_topic") or ""),
        "date": dt_s,
        "sources_searched": n_sources,
        "articles_found": n_articles,
        "signed": signed,
        "has_coalition": coalition is not None,
        "volatility": vol,
        "vol_copy": _vol_copy(vol),
        "position_a_label": str(pa.get("label") or ""),
        "position_b_label": str(pb.get("label") or ""),
        "position_a_summary": str(pa.get("summary") or ""),
        "position_b_summary": str(pb.get("summary") or ""),
        "irreconcilable_gap": str((coalition or {}).get("irreconcilable_gap") or ""),
        "coalition_a_count": prev.get("a_count", 0),
        "coalition_b_count": prev.get("b_count", 0),
        "coalition_a_countries": prev.get("a_countries", 0),
        "coalition_b_countries": prev.get("b_countries", 0),
        "named_entities": _named_entities_list(receipt),
    }


def _chains_have_outlet_type(coal: dict[str, Any] | None, outlet_type: str) -> bool:
    if not coal or outlet_type not in ("state", "private", "public_broadcaster"):
        return True
    for key in ("position_a", "position_b"):
        pos = coal.get(key)
        if not isinstance(pos, dict):
            continue
        for link in pos.get("chain") or []:
            if not isinstance(link, dict):
                continue
            if str(link.get("outlet_type") or "") == outlet_type:
                return True
    return False


_REGION_HINTS: dict[str, tuple[str, ...]] = {
    "middle_east": (
        "middle_east",
        "iran",
        "israel",
        "gulf",
        "syria",
        "lebanon",
        "yemen",
        "arab",
        "iraq",
        "palestin",
        "qat",
    ),
    "north_america": ("north_america", "united states", "u.s.", "usa", "canada", "mexico", "american"),
    "europe": ("europe", "european", "uk", "britain", "france", "germany", "russian", "eu"),
    "asia": ("asia", "china", "india", "japan", "korea", "pacific"),
    "latin_america": ("latin", "brazil", "argentin", "mexico", "south america"),
    "africa": ("africa", "nigeria", "kenya", "south africa"),
}


def _text_for_region_match(coal: dict[str, Any] | None) -> str:
    if not coal:
        return ""
    try:
        return json.dumps(coal)[:8000].lower()
    except Exception:
        return str(coal)[:4000].lower()


def _matches_region_filter(coal: dict[str, Any] | None, regions: set[str]) -> bool:
    if not regions:
        return True
    blob = _text_for_region_match(coal)
    for r in regions:
        hints = _REGION_HINTS.get(r, (r.replace("_", " "),))
        if any(h in blob for h in hints):
            return True
    return False


def _facet_regions_for_result(coal: dict[str, Any] | None) -> set[str]:
    if not coal:
        return set()
    blob = _text_for_region_match(coal)
    found: set[str] = set()
    for key, hints in _REGION_HINTS.items():
        if any(h in blob for h in hints):
            found.add(key)
    return found


def _facet_outlet_counts(coal: dict[str, Any] | None) -> dict[str, int]:
    counts = {"state": 0, "private": 0, "public_broadcaster": 0}
    if not coal:
        return counts
    for key in ("position_a", "position_b"):
        pos = coal.get(key)
        if not isinstance(pos, dict):
            continue
        for link in pos.get("chain") or []:
            if not isinstance(link, dict):
                continue
            ot = str(link.get("outlet_type") or "private")
            if ot in counts:
                counts[ot] += 1
    return counts


def compute_facets(
    flat_results: list[dict[str, Any]],
    coalitions: list[dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    by_vol = {"high": 0, "moderate": 0, "low": 0}
    by_region: dict[str, int] = {}
    by_ot = {"state": 0, "private": 0, "public_broadcaster": 0}

    for r in flat_results:
        v = int(r.get("volatility") or 0)
        if v >= 61:
            by_vol["high"] += 1
        elif v >= 26:
            by_vol["moderate"] += 1
        else:
            by_vol["low"] += 1

    if coalitions is None or len(coalitions) != len(flat_results):
        coals: list[dict[str, Any] | None] = [None] * len(flat_results)
    else:
        coals = coalitions
    for i, r in enumerate(flat_results):
        coal = coals[i] if i < len(coals) else None
        if coal:
            for reg in _facet_regions_for_result(coal):
                by_region[reg] = by_region.get(reg, 0) + 1
            otc = _facet_outlet_counts(coal)
            for k, v in otc.items():
                by_ot[k] += v
        else:
            blob = (
                str(r.get("position_a_label", ""))
                + str(r.get("position_b_label", ""))
                + str(r.get("irreconcilable_gap", ""))
                + str(r.get("headline", ""))
            ).lower()
            for key, hints in _REGION_HINTS.items():
                if any(h in blob for h in hints):
                    by_region[key] = by_region.get(key, 0) + 1

    return {
        "by_volatility": by_vol,
        "by_region": by_region,
        "by_outlet_type": by_ot,
    }


def run_search(
    q: str,
    *,
    volatility_min: int | None = None,
    volatility_max: int | None = None,
    date_range: str = "30d",
    outlet_type: str | None = None,
    region: str | None = None,
    sort: str = "volatility",
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    query_clean = (q or "").strip()
    if not query_clean:
        return {
            "query": q or "",
            "total": 0,
            "results": [],
            "facets": compute_facets([], []),
        }

    regions_set = {x.strip().lower() for x in (region or "").split(",") if x.strip()}
    vol_min = volatility_min
    vol_max = volatility_max
    interval = _interval_sql(date_range)
    outlet_f = (outlet_type or "").strip().lower() or None
    if outlet_f not in (None, "state", "private", "public_broadcaster"):
        outlet_f = None

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Volatility filters only apply when coalition exists (score stored there).
            vol_clauses: list[str] = []
            params: list[Any] = [query_clean, query_clean]
            if vol_min is not None:
                vol_clauses.append(
                    "(c.payload IS NOT NULL AND (COALESCE((c.payload->>'divergence_score')::int, 0) >= %s)"
                )
                params.append(vol_min)
            if vol_max is not None:
                vol_clauses.append(
                    "(c.payload IS NOT NULL AND (COALESCE((c.payload->>'divergence_score')::int, 0) <= %s)"
                )
                params.append(vol_max)
            vol_sql = ""
            if vol_clauses:
                vol_sql = " AND " + " AND ".join(vol_clauses)

            sql = f"""
                SELECT f.id, f.created_at, f.payload AS receipt_payload,
                       c.payload AS coalition_payload,
                       COALESCE(c.signed, FALSE) AS coalition_signed
                FROM frame_receipts f
                LEFT JOIN coalition_maps c ON c.receipt_id = f.id
                WHERE f.created_at >= NOW() - {interval}
                AND (
                  to_tsvector(
                    'english',
                    coalesce(f.payload->>'article_topic', '') || ' ' ||
                    coalesce(f.payload->'article'->>'title', '') || ' ' ||
                    coalesce(f.payload->>'narrative', '') || ' ' ||
                    coalesce(f.payload->>'query', '') || ' ' ||
                    coalesce((f.payload->'named_entities')::text, '')
                  ) @@ plainto_tsquery('english', %s)
                  OR (
                    c.id IS NOT NULL
                    AND to_tsvector(
                      'english',
                      coalesce(c.payload->>'contested_claim', '') || ' ' ||
                      coalesce(c.payload->'position_a'->>'label', '') || ' ' ||
                      coalesce(c.payload->'position_b'->>'label', '') || ' ' ||
                      coalesce(c.payload->>'irreconcilable_gap', '')
                    ) @@ plainto_tsquery('english', %s)
                  )
                )
                {vol_sql}
                ORDER BY f.created_at DESC
                LIMIT 2000
            """
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    built: list[dict[str, Any]] = []
    built_coals: list[dict[str, Any] | None] = []
    for row in rows:
        rid = str(row["id"])
        rp = row["receipt_payload"]
        cp = row["coalition_payload"]
        if isinstance(rp, str):
            rp = json.loads(rp)
        if isinstance(cp, str):
            cp = json.loads(cp)
        rec = dict(rp) if isinstance(rp, dict) else {}
        coal = dict(cp) if isinstance(cp, dict) else None

        if outlet_f and not _chains_have_outlet_type(coal, outlet_f):
            continue
        if regions_set and not _matches_region_filter(coal, regions_set):
            continue

        built.append(
            build_search_result(
                rid,
                rec,
                coal,
                coalition_signed=bool(row.get("coalition_signed")),
                created_at=row.get("created_at"),
            )
        )
        built_coals.append(coal)

    sort_key = (sort or "volatility").lower()
    if sort_key == "date":

        def sk(r: dict[str, Any]) -> tuple[str, int]:
            return (r.get("date") or "", int(r.get("volatility") or 0))

        idx_order = sorted(range(len(built)), key=lambda i: sk(built[i]), reverse=True)
    else:

        def sk2(r: dict[str, Any]) -> tuple[int, str]:
            return (int(r.get("volatility") or 0), r.get("date") or "")

        idx_order = sorted(range(len(built)), key=lambda i: sk2(built[i]), reverse=True)

    built = [built[i] for i in idx_order]
    built_coals = [built_coals[i] for i in idx_order]

    facets = compute_facets(built, built_coals)
    total = len(built)
    page = built[offset : offset + max(1, min(limit, 100))]

    return {
        "query": query_clean,
        "total": total,
        "results": page,
        "facets": facets,
    }


def run_suggest(q: str, *, limit: int = 10) -> dict[str, Any]:
    qc = (q or "").strip()
    if len(qc) < 2:
        return {"suggestions": []}
    pat = f"%{qc}%"
    conn = _get_conn()
    suggestions: list[str] = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT trim(coalesce(f.payload->>'article_topic', '')) AS t
                FROM frame_receipts f
                WHERE f.created_at >= NOW() - INTERVAL '120 days'
                  AND trim(coalesce(f.payload->>'article_topic', '')) ILIKE %s
                  AND length(trim(coalesce(f.payload->>'article_topic', ''))) > 2
                LIMIT %s
                """,
                (pat, limit * 3),
            )
            for (t,) in cur.fetchall():
                if t and t not in suggestions:
                    suggestions.append(str(t))
            need = limit * 3 - len(suggestions)
            if need > 0:
                cur.execute(
                    """
                    SELECT DISTINCT trim(coalesce(f.query, '')) AS t
                    FROM frame_receipts f
                    WHERE f.created_at >= NOW() - INTERVAL '120 days'
                      AND trim(coalesce(f.query, '')) ILIKE %s
                      AND length(trim(coalesce(f.query, ''))) > 2
                    LIMIT %s
                    """,
                    (pat, need),
                )
                for (t,) in cur.fetchall():
                    if t and t not in suggestions:
                        suggestions.append(str(t))
            if len(suggestions) < limit:
                cur.execute(
                    """
                    SELECT DISTINCT trim(coalesce(c.payload->>'contested_claim', '')) AS t
                    FROM coalition_maps c
                    INNER JOIN frame_receipts f ON f.id = c.receipt_id
                    WHERE f.created_at >= NOW() - INTERVAL '120 days'
                      AND trim(coalesce(c.payload->>'contested_claim', '')) ILIKE %s
                    LIMIT %s
                    """,
                    (pat, limit * 2),
                )
                for (t,) in cur.fetchall():
                    if t and t not in suggestions and len(suggestions) < limit * 2:
                        suggestions.append(str(t)[:200])
    finally:
        conn.close()

    return {"suggestions": suggestions[: max(1, min(limit, 25))]}
