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
