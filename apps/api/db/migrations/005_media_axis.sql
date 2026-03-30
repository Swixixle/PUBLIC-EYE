-- Per-receipt accuracy axis (anchored to verifiable record, not political left/right).
-- Applied via receipt_store.ensure_media_axis_table() on API startup.

CREATE TABLE IF NOT EXISTS media_axis (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_id   TEXT NOT NULL UNIQUE REFERENCES frame_receipts(id) ON DELETE CASCADE,
    axis_id      TEXT NOT NULL UNIQUE,
    payload      JSONB NOT NULL,
    signed       BOOLEAN DEFAULT FALSE,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_media_axis_receipt ON media_axis(receipt_id);
