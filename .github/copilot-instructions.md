# Frame — Copilot / agent instructions

Frame is a transparency tool: political claims become **cryptographically signed receipts** that cite filings (money, votes, lobbying) with **neutral** language.

## The three rules (never break)

1. **Every narrative sentence must have a `sourceId`** that exists in the `sources` array.
2. **No judgment adjectives** in narrative or UI copy tied to receipts: e.g. corrupt, suspicious, troubling, criminal, fraudulent, unethical, scandal, shady, bribery, etc. Describe what a filing shows; do not moralize.
3. **Use JCS (RFC 8785)** for canonical JSON before any cryptographic hash. In TypeScript use the **`canonicalize` npm package**. **Never** use `JSON.stringify` for hashing or signature payloads.

## Repo layout (high level)

- `packages/types` — shared types.
- `packages/signing` — Ed25519 signing; JCS-only hashing.
- `packages/narrative` — banned words + source URL domain allowlist + narrative validation.
- `packages/entity` — entity disambiguation with a confidence floor.
- `packages/sources` — FEC, OpenSecrets, ProPublica, lobbying, EDGAR adapters (stubs / normalization).
- `apps/api` — FastAPI verification (delegates JCS to Node + `scripts/jcs-stringify.mjs`).
- `apps/web` — static demo page.

When adding features, keep adapters and narrative validation in sync with these rules.
