-- Cached outlet dossiers (FEC, CourtListener, etc. — populated over time).
-- Applied via receipt_store.ensure_outlet_dossiers_table() on API startup.

CREATE TABLE IF NOT EXISTS outlet_dossiers (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug         TEXT NOT NULL UNIQUE,
    outlet_name  TEXT NOT NULL,
    payload      JSONB NOT NULL,
    signed       BOOLEAN DEFAULT FALSE,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outlet_dossiers_slug ON outlet_dossiers(slug);
