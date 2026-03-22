# Frame

A cryptographic public record verification system.

Frame generates signed, tamper-evident receipts that show what public records say about a claim, a piece of media, or a public figure — and is explicit about what it could not find.

**Live demo:** https://frame-2yxu.onrender.com/demo  
**System brief:** https://frame-2yxu.onrender.com/pitch  
**Health:** https://frame-2yxu.onrender.com/health

---

## What it does

Frame queries public data sources — FEC campaign finance, Senate lobbying disclosures, IRS 990 filings, Wikidata, Meta Ad Library — and returns a signed receipt documenting what was found, what was inferred, and what could not be determined.

Every receipt is:
- **Signed** with Ed25519
- **Canonicalized** with JCS (RFC 8785) before signing
- **Independently verifiable** — the public key is in the receipt
- **Explicit about unknowns** — absence of findings is documented, not silently omitted

Frame does not issue verdicts. It issues receipts.

---

## Try it now

### Campaign finance (FEC)

```bash
# Find a candidate
curl "https://frame-2yxu.onrender.com/v1/fec-search?name=Ted%20Cruz"

# Generate signed receipt
curl -s -X POST https://frame-2yxu.onrender.com/v1/generate-receipt \
  -H "Content-Type: application/json" \
  -d '{"candidateId": "S2TX00312"}'
```

### Lobbying disclosures (Senate LDA)

```bash
curl -s -X POST https://frame-2yxu.onrender.com/v1/generate-lobbying-receipt \
  -H "Content-Type: application/json" \
  -d '{"name": "Exxon"}'
```

### Nonprofit financials (IRS 990)

```bash
curl -s -X POST https://frame-2yxu.onrender.com/v1/generate-990-receipt \
  -H "Content-Type: application/json" \
  -d '{"orgName": "Gates Foundation", "ein": "562618866"}'
```

### Public figure biography (Wikidata)

```bash
curl -s -X POST https://frame-2yxu.onrender.com/v1/generate-wikidata-receipt \
  -H "Content-Type: application/json" \
  -d '{"personName": "Tucker Carlson"}'
```

### Media verification (hash + chain of custody)

```bash
# Submit URL — returns job_id immediately
curl -s -X POST https://frame-2yxu.onrender.com/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"source_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/280px-PNG_transparency_demonstration_1.png"}'

# Poll for result
curl -s https://frame-2yxu.onrender.com/v1/jobs/{job_id}
```

### Verify any receipt

```bash
curl -s -X POST https://frame-2yxu.onrender.com/v1/verify-receipt \
  -H "Content-Type: application/json" \
  -d @receipt.json
```

Expected: `{"ok": true, "reasons": []}`

---

## What a receipt looks like

```json
{
  "schemaVersion": "1.0.0",
  "receiptId": "FRM-...",
  "subject": {
    "type": "politician",
    "identifier": "S2TX00312",
    "display_name": "TED CRUZ"
  },
  "claims": [
    {
      "statement": "Total career receipts: $174,208,411",
      "type": "observed",
      "implication_risk": "medium"
    }
  ],
  "evidence": [...],
  "unknowns": {
    "operational": [],
    "epistemic": [
      {
        "text": "Campaign finance totals reflect disclosed contributions; they do not establish improper conduct or policy influence.",
        "resolution_possible": false
      }
    ]
  },
  "narrative": "...",
  "signature": "...",
  "publicKey": "..."
}
```

The `unknowns` field is mandatory on every receipt. If it is empty, the adapter is not being honest.

---

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Liveness check |
| GET | `/demo` | Interactive search UI |
| GET | `/pitch` | Full system brief |
| GET | `/v1/fec-search?name=` | FEC candidate lookup |
| POST | `/v1/generate-receipt` | FEC campaign finance receipt |
| POST | `/v1/generate-lobbying-receipt` | Senate LDA lobbying receipt |
| POST | `/v1/generate-combined-receipt` | FEC + LDA cross-reference |
| POST | `/v1/generate-990-receipt` | IRS 990 nonprofit receipt |
| POST | `/v1/generate-wikidata-receipt` | Public figure biography receipt |
| POST | `/v1/generate-ad-library-receipt` | Meta Ad Library paid advertising |
| POST | `/v1/analyze-media` | SHA-256 hash + AI detection |
| POST | `/v1/sign-media-analysis` | Sign media analysis as receipt |
| POST | `/v1/verify-receipt` | Verify any signed receipt |
| POST | `/v1/jobs` | Submit async job, get job_id |
| GET | `/v1/jobs/{job_id}` | Poll job status and receipt |
| POST | `/v1/intake` | Unified intake (URL or file) |
| GET | `/v1/schema-baselines` | Schema baseline status |

---

## Architecture

```
intake (URL / file / text)
  → fetch (yt-dlp or direct HTTP)
  → SHA-256 hash
  → OCR (Tesseract)
  → entity extraction
  → adapter routing (FEC / LDA / 990 / Wikidata / Ad Library)
  → receipt assembly
  → JCS canonicalization (RFC 8785)
  → Ed25519 signing
  → signed receipt
```

**Signing:** Ed25519. Keys stored as base64 in environment. Public key embedded in every receipt.  
**Canonicalization:** JCS (RFC 8785). Not `JSON.stringify`.  
**Unknowns:** Split into `operational` (technical limits, resolvable) and `epistemic` (fundamental limits, permanent).  
**Claims:** Every claim carries `implication_risk: low | medium | high`. High-risk claims require a machine-generated `implication_note` stating what the fact does not establish.

Full architecture documentation: [`docs/CONTEXT.md`](docs/CONTEXT.md)  
Technical proof with curl outputs: [`docs/PROOF.md`](docs/PROOF.md)

---

## Stack

- **API:** Python FastAPI, deployed on Render
- **Signing:** Node.js (Ed25519 + JCS), called via subprocess
- **Frontend:** Vanilla HTML/JS at `/demo`
- **Types:** TypeScript (`packages/types/`)
- **Sources package:** TypeScript (`packages/sources/`)

---

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `FRAME_PRIVATE_KEY` | Yes | Ed25519 private key (base64) |
| `FRAME_KEY_FORMAT` | Yes | Set to `base64` |
| `FEC_API_KEY` | Yes | OpenFEC API key |
| `META_AD_LIBRARY_TOKEN` | No | Meta Ad Library access |
| `HIVE_API_KEY` | No | Hive AI detection |

---

## What Frame is not

- Not a fact-checker (implies verdict)
- Not an AI trust score (implies oracle)
- Not a misinformation detector (implies we decided)
- Not a competitor to C2PA (we cover what they can't reach)
