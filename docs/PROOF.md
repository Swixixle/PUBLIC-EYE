# FRAME — Proof of Build

This document is the technical evidence record for Frame.  
Every claim here is falsifiable against the live system.

---

## What is Frame?

Frame is a system that separates evidence from interpretation at scale  
and proves the separation cryptographically.

It generates signed, tamper-evident receipts documenting what public  
records say about a claim, a piece of media, or a public figure —  
and is explicit about what it could not find.

---

## Live System

**Base URL:** https://frame-2yxu.onrender.com  
**Status:** https://frame-2yxu.onrender.com/health

---

## How to Verify Any Receipt

Every Frame receipt contains a `signature` and `publicKey` field.  
To verify independently:

```bash
curl -s -X POST https://frame-2yxu.onrender.com/v1/verify-receipt \
  -H "Content-Type: application/json" \
  -d @your-receipt.json
```

Expected response: `{"ok": true, "reasons": []}`

The signing uses Ed25519 with JCS (RFC 8785) canonicalization.  
The public key is embedded in every receipt.  
Verification requires no trust in Frame's servers.

---

## Curl Proofs (Run These Now)

### 1. FEC Campaign Finance Receipt

```bash
# Search for candidate by name
curl -s "https://frame-2yxu.onrender.com/v1/fec-search?name=Ted%20Cruz"

# Generate signed receipt
curl -s -X POST https://frame-2yxu.onrender.com/v1/generate-receipt \
  -H "Content-Type: application/json" \
  -d '{"candidateId": "S2TX00312"}'
```

Expected: signed receipt with `signature` field, FEC totals, split unknowns.

### 2. Senate LDA Lobbying Receipt

```bash
curl -s -X POST https://frame-2yxu.onrender.com/v1/generate-lobbying-receipt \
  -H "Content-Type: application/json" \
  -d '{"name": "Exxon"}'
```

### 3. IRS 990 Nonprofit Receipt

```bash
curl -s -X POST https://frame-2yxu.onrender.com/v1/generate-990-receipt \
  -H "Content-Type: application/json" \
  -d '{"orgName": "Gates Foundation", "ein": "562618866"}'
```

Expected: receipt with $78B+ total assets from live ProPublica 990 data.

### 4. Public Figure Wikidata Receipt

```bash
curl -s -X POST https://frame-2yxu.onrender.com/v1/generate-wikidata-receipt \
  -H "Content-Type: application/json" \
  -d '{"personName": "Tucker Carlson"}'
```

### 5. Media Hash + Chain of Custody

```bash
# Submit URL as async job
curl -s -X POST https://frame-2yxu.onrender.com/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"source_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/280px-PNG_transparency_demonstration_1.png"}'

# Returns immediately with job_id — poll:
curl -s https://frame-2yxu.onrender.com/v1/jobs/[job_id_from_above]
```

Expected: receipt with `sha256` hash, `chain_of_custody` block, split unknowns.

### 6. Verify a Receipt

```bash
# Take any receipt from above and verify its signature
curl -s -X POST https://frame-2yxu.onrender.com/v1/verify-receipt \
  -H "Content-Type: application/json" \
  -d '[paste receipt JSON here]'
```

Expected: `{"ok": true, "reasons": []}`

### 7. Schema Baselines

```bash
curl -s https://frame-2yxu.onrender.com/v1/schema-baselines
```

Expected: baseline status for all 5 sources with hash and capture date.

---

## Architecture Claims and Where to Verify Them

| Claim | File | Verified By |
|-------|------|-------------|
| Ed25519 signing | `packages/signing/` | `npm test` — 5 passing |
| JCS canonicalization (RFC 8785) | `packages/signing/` | signing tests |
| Split unknowns schema | `packages/types/index.ts` | TypeScript types |
| implication_risk on all claims | `packages/types/implication-notes.ts` | `buildClaim()` enforces |
| Async job system | `apps/api/job_store.py` | curl proof above |
| FetchAdapter interface | `apps/api/adapters/fetch_adapter.py` | interface definition |
| Schema baselines | `apps/api/baselines/` | `/v1/schema-baselines` |

---

## Schema Baselines

Captured at startup. Verified on each subsequent start.  
Full baseline documents in `apps/api/baselines/`.

| Source | Purpose | Critical Fields |
|--------|---------|-----------------|
| fec | FEC campaign finance | candidate_id, total_receipts |
| lda | Senate LDA lobbying | registrant_name, client_name, amount |
| propublica_990 | IRS 990 nonprofits | ein, total_assets, total_revenue |
| wikidata | Public figure biography | id, labels, claims |
| meta_ad_library | Meta paid advertising | funding_entity, spend, page_name |

Run `GET /v1/schema-baselines` for current hashes and capture timestamps.

---

## Current Adapter Status

| Adapter | Data Source | Status | Requires |
|---------|------------|--------|---------|
| FEC | api.open.fec.gov | Live | FEC_API_KEY (Render) |
| LDA | lda.senate.gov | Live | None |
| 990 | ProPublica | Live | None |
| Wikidata | wikidata.org | Live | None |
| Ad Library | graph.facebook.com | Configured | META_AD_LIBRARY_TOKEN |
| Media Hash | SHA-256 | Live | None |
| AI Detection | thehive.ai | Configured | HIVE_API_KEY |
| OCR | Tesseract | Live | tesseract-ocr (system) |
| yt-dlp fetch | Social platforms | Live | None (yt-dlp in requirements) |

---

## Known Gaps (Honest)

- `META_AD_LIBRARY_TOKEN` — token expires; System User token recommended for production
- `HIVE_API_KEY` — not yet configured; AI detection returns `detector: none`
- Salience algorithm uses rule-based fallback until corpus reaches N=100 receipts
- Music dossier (Liner Notes) is specced but not yet built
- Schema monitoring captures baselines but Rule Change Receipt generation not yet implemented
- Job store is in-memory — resets on server restart (acceptable at current stage)

---

*Generated: [date]*  
*Repo: github.com/Swixixle/FRAME*
