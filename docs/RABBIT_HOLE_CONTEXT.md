# Rabbit Hole — product context

Rabbit Hole is the consumer-facing depth-map product in this repository. It shares the cryptographic receipt spine and `POST /v1/verify-receipt` with Frame; the entry point and primary UI differ (six depth layers, surface trace, pattern library, dispute log, actor ledger).

**Architecture:** Six depth layers, each a self-contained information jurisdiction. They stack. They do not bleed into each other. Server: `apps/api/depth_map.py`, `GET /v1/depth-map`. Client: `apps/web/src/components/DepthMap.jsx`.

## Tone & Voice

Rabbit Hole shows what the cited record states and what it does not state. It does not issue verdicts, moral judgments, or recommendations about what you should do or believe. Every surfaced line ties to a source id or to an explicit unknown; if something is missing from the record, the interface says so. This is a navigational map of public material at retrieval time, not legal advice, medical advice, personal advice, or proof of anyone's intent.
