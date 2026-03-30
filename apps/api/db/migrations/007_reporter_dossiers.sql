-- Cached reporter dossiers.
-- Applied via receipt_store.ensure_reporter_dossiers_table() on API startup.

CREATE TABLE IF NOT EXISTS reporter_dossiers (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    payload      JSONB NOT NULL,
    signed       BOOLEAN DEFAULT FALSE,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reporter_dossiers_slug ON reporter_dossiers(slug);
