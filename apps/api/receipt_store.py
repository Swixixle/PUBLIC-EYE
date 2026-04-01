"""
Receipt persistence layer.
Stores generated receipts for retrieval by ID (permalink: GET /r/:receipt_id).
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import psycopg2
import psycopg2.extras


def _get_conn() -> Any:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(url)


def _infer_receipt_type(receipt: dict[str, Any]) -> str:
    t = receipt.get("receipt_type")
    if t:
        return str(t)
    if receipt.get("deep_receipt_id"):
        return "deep_receipt"
    if receipt.get("claims_verified") is not None:
        return "article_analysis"
    if receipt.get("rings"):
        return "five_ring_report"
    if receipt.get("query") is not None and (
        receipt.get("synthesis") is not None
        or receipt.get("articles") is not None
        or receipt.get("timeline_synthesis") is not None
    ):
        return "query_synthesis"
    return "unknown"


def ensure_table() -> None:
    """Create receipts table if it doesn't exist."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS frame_receipts (
                    id TEXT PRIMARY KEY,
                    receipt_type TEXT NOT NULL,
                    query TEXT,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    source_url TEXT,
                    source_type TEXT
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS frame_receipts_created_at
                ON frame_receipts (created_at DESC)
            """)
        conn.commit()
    finally:
        conn.close()


def ensure_coalition_maps_table() -> None:
    """Coalition map artifacts (async secondary analysis per receipt)."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS coalition_maps (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    receipt_id TEXT NOT NULL UNIQUE
                        REFERENCES frame_receipts(id) ON DELETE CASCADE,
                    coalition_id TEXT NOT NULL UNIQUE,
                    payload JSONB NOT NULL,
                    signed BOOLEAN DEFAULT FALSE,
                    signature TEXT,
                    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_coalition_receipt "
                "ON coalition_maps (receipt_id)"
            )
        conn.commit()
    finally:
        conn.close()


def ensure_search_fts_indexes() -> None:
    """
    GIN full-text indexes on receipt + coalition payloads (see db/migrations/008).

    Drops existing FTS indexes first so a corrected expression (e.g. named_entities
    cast precedence) replaces a bad index from an older deploy; CREATE INDEX IF NOT
    EXISTS alone would leave the stale definition in place.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS idx_frame_receipts_fts")
            cur.execute("DROP INDEX IF EXISTS idx_coalition_maps_fts")
            cur.execute(
                """
                CREATE INDEX idx_frame_receipts_fts ON frame_receipts
                USING GIN (
                  to_tsvector(
                    'english',
                    coalesce(payload->>'article_topic', '') || ' ' ||
                    coalesce(payload->'article'->>'title', '') || ' ' ||
                    coalesce(payload->>'narrative', '') || ' ' ||
                    coalesce(payload->>'query', '') || ' ' ||
                    coalesce((payload->'named_entities')::text, '')
                  )
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX idx_coalition_maps_fts ON coalition_maps
                USING GIN (
                  to_tsvector(
                    'english',
                    coalesce(payload->>'contested_claim', '') || ' ' ||
                    coalesce(payload->'position_a'->>'label', '') || ' ' ||
                    coalesce(payload->'position_b'->>'label', '') || ' ' ||
                    coalesce(payload->>'irreconcilable_gap', '')
                  )
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


def get_coalition_map(receipt_id: str) -> dict[str, Any] | None:
    """Return stored coalition map API payload, or None."""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT payload FROM coalition_maps WHERE receipt_id = %s",
                (receipt_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            payload = row["payload"]
            if isinstance(payload, dict):
                return payload
            if isinstance(payload, str):
                return json.loads(payload)
            return dict(payload) if payload is not None else None
    finally:
        conn.close()


def save_coalition_map(payload: dict[str, Any]) -> None:
    """Upsert full coalition map response JSON."""
    rid = str(payload.get("receipt_id", "")).strip()
    cid = str(payload.get("coalition_id", "")).strip()
    if not rid or not cid:
        raise ValueError("receipt_id and coalition_id required")
    signed = bool(payload.get("signed"))
    signature = payload.get("signature")
    generated = payload.get("generated_at") or None
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO coalition_maps
                    (receipt_id, coalition_id, payload, signed, signature, generated_at)
                VALUES (%s, %s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()))
                ON CONFLICT (receipt_id) DO UPDATE SET
                    coalition_id = EXCLUDED.coalition_id,
                    payload = EXCLUDED.payload,
                    signed = EXCLUDED.signed,
                    signature = EXCLUDED.signature,
                    generated_at = EXCLUDED.generated_at
                """,
                (
                    rid,
                    cid,
                    psycopg2.extras.Json(payload),
                    signed,
                    signature,
                    generated,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def delete_coalition_map(receipt_id: str) -> bool:
    """Remove stored coalition map for a receipt (e.g. to regenerate after prompt changes)."""
    rid = str(receipt_id).strip()
    if not rid:
        return False
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coalition_maps WHERE receipt_id = %s", (rid,))
            deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    finally:
        conn.close()


def store_receipt(receipt: dict[str, Any]) -> str:
    """
    Store a receipt. Returns the canonical receipt_id.
    """
    rid = (
        receipt.get("receipt_id")
        or receipt.get("report_id")
        or receipt.get("deep_receipt_id")
        or str(uuid.uuid4())
    )
    receipt = {**receipt, "receipt_id": rid}
    receipt_type = _infer_receipt_type(receipt)
    query_val = str(
        receipt.get("query")
        or receipt.get("url")
        or receipt.get("narrative")
        or receipt.get("article", {}).get("url")
        or "",
    )
    source_url = (
        receipt.get("url")
        or receipt.get("source_url")
        or (receipt.get("article") or {}).get("url")
    )
    source_type = receipt.get("source_type")

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO frame_receipts
                    (id, receipt_type, query, payload, source_url, source_type)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                    SET payload = EXCLUDED.payload,
                        receipt_type = EXCLUDED.receipt_type,
                        query = EXCLUDED.query,
                        source_url = EXCLUDED.source_url,
                        source_type = EXCLUDED.source_type
                """,
                (
                    rid,
                    receipt_type,
                    query_val,
                    psycopg2.extras.Json(receipt),
                    source_url,
                    source_type,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return rid


def get_receipt(receipt_id: str) -> dict[str, Any] | None:
    """Retrieve a receipt by ID."""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT payload FROM frame_receipts WHERE id = %s",
                (receipt_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            payload = row["payload"]
            if isinstance(payload, dict):
                return payload
            if isinstance(payload, str):
                return json.loads(payload)
            return dict(payload) if payload is not None else None
    finally:
        conn.close()


def ensure_media_axis_table() -> None:
    """Per-receipt accuracy axis (verifiable-record–anchored, not political)."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS media_axis (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    receipt_id TEXT NOT NULL UNIQUE
                        REFERENCES frame_receipts(id) ON DELETE CASCADE,
                    axis_id TEXT NOT NULL UNIQUE,
                    payload JSONB NOT NULL,
                    signed BOOLEAN DEFAULT FALSE,
                    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_axis_receipt "
                "ON media_axis (receipt_id)"
            )
        conn.commit()
    finally:
        conn.close()


def ensure_outlet_dossiers_table() -> None:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS outlet_dossiers (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    slug TEXT NOT NULL UNIQUE,
                    outlet_name TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    signed BOOLEAN DEFAULT FALSE,
                    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_outlet_dossiers_slug "
                "ON outlet_dossiers (slug)"
            )
        conn.commit()
    finally:
        conn.close()


def ensure_reporter_dossiers_table() -> None:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS reporter_dossiers (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    signed BOOLEAN DEFAULT FALSE,
                    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_reporter_dossiers_slug "
                "ON reporter_dossiers (slug)"
            )
        conn.commit()
    finally:
        conn.close()


def get_media_axis(receipt_id: str) -> dict[str, Any] | None:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT payload FROM media_axis WHERE receipt_id = %s",
                (receipt_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            p = row["payload"]
            if isinstance(p, dict):
                return p
            if isinstance(p, str):
                return json.loads(p)
            return dict(p) if p is not None else None
    finally:
        conn.close()


def save_media_axis(payload: dict[str, Any]) -> None:
    rid = str(payload.get("receipt_id", "")).strip()
    aid = str(payload.get("axis_id", "")).strip()
    if not rid or not aid:
        raise ValueError("receipt_id and axis_id required")
    signed = bool(payload.get("signed"))
    gen = payload.get("generated_at")
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO media_axis (receipt_id, axis_id, payload, signed, generated_at)
                VALUES (%s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()))
                ON CONFLICT (receipt_id) DO UPDATE SET
                    axis_id = EXCLUDED.axis_id,
                    payload = EXCLUDED.payload,
                    signed = EXCLUDED.signed,
                    generated_at = EXCLUDED.generated_at
                """,
                (rid, aid, psycopg2.extras.Json(payload), signed, gen),
            )
        conn.commit()
    finally:
        conn.close()


def get_stored_outlet_dossier(slug: str) -> dict[str, Any] | None:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT payload FROM outlet_dossiers WHERE slug = %s",
                (slug,),
            )
            row = cur.fetchone()
            if not row:
                return None
            p = row["payload"]
            if isinstance(p, dict):
                return p
            if isinstance(p, str):
                return json.loads(p)
            return dict(p) if p is not None else None
    finally:
        conn.close()


def upsert_outlet_dossier(slug: str, outlet_name: str, payload: dict[str, Any]) -> None:
    signed = bool(payload.get("signed"))
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO outlet_dossiers (slug, outlet_name, payload, signed, last_updated)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (slug) DO UPDATE SET
                    outlet_name = EXCLUDED.outlet_name,
                    payload = EXCLUDED.payload,
                    signed = EXCLUDED.signed,
                    last_updated = NOW()
                """,
                (slug, outlet_name, psycopg2.extras.Json(payload), signed),
            )
        conn.commit()
    finally:
        conn.close()


def get_stored_reporter_dossier(slug: str) -> dict[str, Any] | None:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT payload FROM reporter_dossiers WHERE slug = %s",
                (slug,),
            )
            row = cur.fetchone()
            if not row:
                return None
            p = row["payload"]
            if isinstance(p, dict):
                return p
            if isinstance(p, str):
                return json.loads(p)
            return dict(p) if p is not None else None
    finally:
        conn.close()


def upsert_reporter_dossier(slug: str, name: str, payload: dict[str, Any]) -> None:
    signed = bool(payload.get("signed"))
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reporter_dossiers (slug, name, payload, signed, last_updated)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    payload = EXCLUDED.payload,
                    signed = EXCLUDED.signed,
                    last_updated = NOW()
                """,
                (slug, name, psycopg2.extras.Json(payload), signed),
            )
        conn.commit()
    finally:
        conn.close()


def list_receipts_with_coalition_since(
    days: int = 7,
    limit: int = 300,
) -> list[dict[str, Any]]:
    """
    Receipts that have a coalition_map row, created within the last `days` days.
    Ordered by created_at descending (newest first — caller re-sorts by divergence).
    Each item: receipt_id, created_at (datetime), receipt (dict), coalition (dict).
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT f.id, f.created_at, f.payload AS receipt_payload,
                       c.payload AS coalition_payload
                FROM frame_receipts f
                INNER JOIN coalition_maps c ON c.receipt_id = f.id
                WHERE f.created_at >= NOW() - make_interval(days => %s)
                ORDER BY f.created_at DESC
                LIMIT %s
                """,
                (days, limit),
            )
            out: list[dict[str, Any]] = []
            for row in cur.fetchall():
                rp = row["receipt_payload"]
                cp = row["coalition_payload"]
                if isinstance(rp, str):
                    rp = json.loads(rp)
                if isinstance(cp, str):
                    cp = json.loads(cp)
                out.append(
                    {
                        "receipt_id": str(row["id"]),
                        "created_at": row["created_at"],
                        "receipt": dict(rp) if isinstance(rp, dict) else {},
                        "coalition": dict(cp) if isinstance(cp, dict) else {},
                    }
                )
            return out
    finally:
        conn.close()


def list_recent_article_investigations(
    limit: int = 24,
) -> list[dict[str, Any]]:
    """
    Most recent article analyses (investigation receipts), newest first.
    Each item: receipt_id, created_at, receipt (full payload), coalition (dict or {}).
    Coalition is joined when a coalition_map row exists.
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT f.id, f.created_at, f.payload AS receipt_payload,
                       c.payload AS coalition_payload
                FROM frame_receipts f
                LEFT JOIN coalition_maps c ON c.receipt_id = f.id
                WHERE f.receipt_type = 'article_analysis'
                ORDER BY f.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            out: list[dict[str, Any]] = []
            for row in cur.fetchall():
                rp = row["receipt_payload"]
                cp = row.get("coalition_payload")
                if isinstance(rp, str):
                    rp = json.loads(rp)
                if isinstance(cp, str):
                    cp = json.loads(cp)
                if not isinstance(rp, dict):
                    continue
                coalition: dict[str, Any] = dict(cp) if isinstance(cp, dict) else {}
                out.append(
                    {
                        "receipt_id": str(row["id"]),
                        "created_at": row["created_at"],
                        "receipt": rp,
                        "coalition": coalition,
                    }
                )
            return out
    finally:
        conn.close()


def get_homepage_stats() -> dict[str, int]:
    """
    Live counts for the homepage stats bar (read-only, no joins).
    Uses frame_receipts + JSONB payload; returns zeros if DB unavailable.
    """
    zero = {"investigations": 0, "claims_traced": 0, "receipts_signed": 0}
    try:
        conn = _get_conn()
    except Exception:
        return zero
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM frame_receipts
                WHERE receipt_type = %s
                """,
                ("article_analysis",),
            )
            investigations = int(cur.fetchone()[0] or 0)

            cur.execute(
                """
                SELECT COALESCE(SUM((payload->>'claims_extracted')::bigint), 0)
                FROM frame_receipts
                WHERE receipt_type = %s
                  AND payload ? 'claims_extracted'
                  AND (payload->>'claims_extracted') ~ '^[0-9]+$'
                """,
                ("article_analysis",),
            )
            claims_traced = int(cur.fetchone()[0] or 0)

            cur.execute(
                """
                SELECT COUNT(*) FROM frame_receipts
                WHERE receipt_type = %s
                  AND payload->>'signed' = 'true'
                """,
                ("article_analysis",),
            )
            receipts_signed = int(cur.fetchone()[0] or 0)

        return {
            "investigations": investigations,
            "claims_traced": claims_traced,
            "receipts_signed": receipts_signed,
        }
    except Exception:
        return zero
    finally:
        conn.close()


def list_recent_receipts(limit: int = 20) -> list[dict[str, Any]]:
    """List recent receipts for a feed/history view (metadata only)."""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, receipt_type, query, source_url, source_type, created_at
                FROM frame_receipts
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            ts = r.get("created_at")
            if hasattr(ts, "isoformat"):
                r["created_at"] = ts.isoformat()
        return rows
    finally:
        conn.close()


def ensure_drift_tables() -> None:
    """Phase 3: drift_snapshots + drift_schedule (Postgres)."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS drift_snapshots (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    original_receipt_id TEXT NOT NULL,
                    snapshot_receipt_id TEXT,
                    article_url TEXT NOT NULL,
                    snapshot_taken_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    hours_since_original INTEGER NOT NULL,
                    drift_score DOUBLE PRECISION,
                    drift_summary TEXT,
                    framing_before JSONB,
                    framing_after JSONB,
                    new_outlets_added TEXT[],
                    outlets_dropped TEXT[],
                    consensus_formed TEXT[],
                    newly_contested TEXT[],
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_drift_original ON drift_snapshots(original_receipt_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_drift_url ON drift_snapshots(article_url)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS drift_schedule (
                    receipt_id TEXT PRIMARY KEY,
                    article_url TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    next_check_at TIMESTAMPTZ,
                    checkpoints_done INTEGER[] DEFAULT '{}'
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


def schedule_drift_analysis(receipt_id: str, article_url: str) -> None:
    rid = (receipt_id or "").strip()
    url = (article_url or "").strip()
    if not rid or not url:
        return
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO drift_schedule (receipt_id, article_url, next_check_at)
                VALUES (%s, %s, NOW() + INTERVAL '24 hours')
                ON CONFLICT (receipt_id) DO UPDATE SET
                    article_url = EXCLUDED.article_url,
                    next_check_at = COALESCE(drift_schedule.next_check_at, EXCLUDED.next_check_at)
                """,
                (rid, url),
            )
        conn.commit()
    finally:
        conn.close()


def insert_drift_snapshot(
    original_receipt_id: str,
    snapshot_receipt_id: str | None,
    article_url: str,
    hours_since_original: int,
    drift: dict[str, Any],
) -> str:
    """Persist one drift snapshot row."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO drift_snapshots (
                    original_receipt_id, snapshot_receipt_id, article_url,
                    hours_since_original, drift_score, drift_summary,
                    framing_before, framing_after,
                    new_outlets_added, outlets_dropped,
                    consensus_formed, newly_contested
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING id::text
                """,
                (
                    original_receipt_id,
                    snapshot_receipt_id,
                    article_url,
                    hours_since_original,
                    drift.get("drift_score"),
                    drift.get("drift_summary"),
                    psycopg2.extras.Json(drift.get("framing_before") or {}),
                    psycopg2.extras.Json(drift.get("framing_after") or {}),
                    drift.get("outlets_added") or [],
                    drift.get("outlets_dropped") or [],
                    drift.get("consensus_formed") or [],
                    drift.get("newly_contested") or [],
                ),
            )
            row = cur.fetchone()
            sid = str(row[0]) if row else ""
        conn.commit()
        return sid
    finally:
        conn.close()


def list_drift_snapshots(original_receipt_id: str) -> list[dict[str, Any]]:
    rid = (original_receipt_id or "").strip()
    if not rid:
        return []
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    hours_since_original,
                    drift_score,
                    drift_summary,
                    new_outlets_added,
                    outlets_dropped,
                    consensus_formed,
                    newly_contested,
                    snapshot_taken_at,
                    framing_before,
                    framing_after
                FROM drift_snapshots
                WHERE original_receipt_id = %s
                ORDER BY snapshot_taken_at ASC
                """,
                (rid,),
            )
            rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            ts = d.get("snapshot_taken_at")
            if hasattr(ts, "isoformat"):
                d["snapshot_taken_at"] = ts.isoformat()
            out.append(
                {
                    "hours_since_original": d.get("hours_since_original"),
                    "drift_score": float(d["drift_score"]) if d.get("drift_score") is not None else 0.0,
                    "drift_summary": d.get("drift_summary") or "",
                    "new_outlets_added": list(d.get("new_outlets_added") or []),
                    "outlets_dropped": list(d.get("outlets_dropped") or []),
                    "consensus_formed": list(d.get("consensus_formed") or []),
                    "newly_contested": list(d.get("newly_contested") or []),
                    "snapshot_taken_at": d.get("snapshot_taken_at"),
                    "framing_before": d.get("framing_before"),
                    "framing_after": d.get("framing_after"),
                }
            )
        return out
    finally:
        conn.close()
