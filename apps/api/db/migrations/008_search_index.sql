-- Full-text search on receipt + coalition payloads (PUBLIC EYE conflict search).
-- Applied via receipt_store.ensure_search_fts_indexes() on startup.

CREATE INDEX IF NOT EXISTS idx_frame_receipts_fts ON frame_receipts
USING GIN (
  to_tsvector(
    'english',
    coalesce(payload->>'article_topic', '') || ' ' ||
    coalesce(payload->'article'->>'title', '') || ' ' ||
    coalesce(payload->>'narrative', '') || ' ' ||
    coalesce(payload->>'query', '') || ' ' ||
    coalesce((payload->'named_entities')::text, '')
  )
);

CREATE INDEX IF NOT EXISTS idx_coalition_maps_fts ON coalition_maps
USING GIN (
  to_tsvector(
    'english',
    coalesce(payload->>'contested_claim', '') || ' ' ||
    coalesce(payload->'position_a'->>'label', '') || ' ' ||
    coalesce(payload->'position_b'->>'label', '') || ' ' ||
    coalesce(payload->>'irreconcilable_gap', '')
  )
);
