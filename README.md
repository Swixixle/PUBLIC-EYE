# PUBLIC EYE

[![Live](https://img.shields.io/badge/live-frame--2yxu.onrender.com-brightgreen)](https://frame-2yxu.onrender.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Verify receipts](https://img.shields.io/badge/verify-receipts-blue)](https://frame-2yxu.onrender.com/verify)

**Paste a URL — an article, a clip, a feed. PUBLIC EYE pulls what the public record shows about that story: who’s covering it, how the framings fight, the sentence where the narratives can’t both be true, what nobody’s talking about — and it seals the finding in an Ed25519-signed receipt anyone can verify without asking you.**

→ **[Try it now](https://frame-2yxu.onrender.com)**  
→ **[Example investigation](https://frame-2yxu.onrender.com/i/8449d4ca-9b30-4ef5-90e5-a9ada6635e91)**  
→ **[Verify any receipt](https://frame-2yxu.onrender.com/verify)**

---

> **What this is not:** Not a fact-checker. Not a bias meter. Not a search engine. It doesn't tell you who's right. It maps what the record shows and — more importantly — what it doesn't.

---

![PUBLIC EYE investigation page — volatility, split, and verification](docs/screenshot.png)

---

## What happens when you submit a URL

1. Fetches and reads the article
2. Searches a range of global sources for coverage of the same story
3. Maps the framing gap — which outlets are most opposed and why, down to what each side emphasizes vs. buries
4. Scores the divergence — 0 means everyone agrees on the basics; 100 means parallel realities with no shared premise
5. Names the irreconcilable gap — the one thing that cannot be simultaneously true across both framings
6. Lists what nobody is covering — angles absent from all sources found
7. Signs everything with Ed25519 — the output is tamper-evident and independently verifiable by anyone

---

## How it was built and what broke along the way

This is a real system that has been stress-tested, not a demo. These are the actual failure modes encountered during development and what was done about them.

**GDELT returned zero results on most initial queries.** The first query strategy used the article author's name as a search term. GDELT indexes article content, not bylines — author-name queries almost always come back empty. The fix was a staged waterfall: headline keywords at 7 days, then 30 days, then core entities at 30 and 90 days, then NewsAPI as a final fallback. The pipeline now logs which stage succeeded on every request so production failures are diagnosable.

**The investigation page rendered nothing for weeks.** The analysis pipeline was generating complete signed receipts with 14+ traced claims, echo chamber scores, and global perspectives — but the investigation page template was only reading two fields from the receipt. Everything else was sitting in the database, signed and correct, invisible. This was a frontend rendering bug, not a pipeline bug.

**Verification rows were noise.** Early versions showed `actor_ledger: not_found — structural_heuristic` on every claim. This is technically accurate — the actor ledger runs a structural heuristic — but it communicates nothing useful to a reader. Those rows are now filtered. A claim with no meaningful verification says "No independent verification found" instead of pretending structural heuristics are evidence.

**The CourtListener adapter was deferred on every claim.** The adapter existed and was wired, but always returned `deferred` instead of running. It now runs on `rumored` claims specifically — allegations sourced to anonymous officials or secondary reports — where court record matches are most meaningful.

**Where it still breaks:**

- Low-coverage stories (regional news, non-English sources) often exhaust all GDELT stages and fall back to NewsAPI or produce partial receipts
- Entity resolution on ambiguous names sometimes picks the wrong person
- Audio transcription (YouTube, podcasts) fetches and transcribes correctly but the full investigation pipeline on transcript content is not yet confirmed end-to-end for long-form audio
- Cold starts on Render's free tier add 30–60 seconds to the first request after inactivity

**What a partial receipt means:** If comparative coverage cannot be found, the pipeline still produces a signed receipt — but with `volatility_score: null` and a note explaining why. A partial receipt is better than a failed request. The signature still proves the output is unaltered.

## The investigation page

Every analysis produces a permalink at `/i/{receipt_id}`. That page shows:

- The article headline
- A **VOLATILITY** score (green = calm, amber = contested, red = parallel realities)
- **Where the story splits** — the irreconcilable gap sentence, always visible
- Two anchor positions side by side with emphasis/minimization tags
- **Who's on each side** — chain of outlets by country with state/private/public badges
- What both sides agree happened
- What no one is covering
- Verification section: receipt ID, Ed25519 signature, signing key, raw JSON link, verifier link

---

## The verifier

`/verify?id={receipt_id}` — anyone can confirm a receipt hasn't been altered since it was generated. No login required. Explains the method in plain English. Links to raw JSON for offline verification with `openssl`.

---

## Run it locally (full stack)

**Requirements:** Python 3.11+, Postgres, Node ≥ 20

```bash
# 1. Install everything
npm ci && npm run build
pip install -r apps/api/requirements.txt

# 2. Configure environment
cp apps/api/.env.example apps/api/.env
# Required: FRAME_PRIVATE_KEY, FRAME_PUBLIC_KEY, FRAME_KEY_FORMAT=base64, DATABASE_URL, ANTHROPIC_API_KEY

# 3. Start the API
cd apps/api
uvicorn main:app --reload --port 8000

# 4. Start the web frontend (separate terminal)
cd apps/web
npm run dev
```

API at `http://localhost:8000` · Frontend at `http://localhost:5173`

---

## Run it with Docker

Postgres is included — no local DB install required.

```bash
git clone https://github.com/Swixixle/PUBLIC-EYE.git
cd PUBLIC-EYE

cp apps/api/.env.example apps/api/.env
# Edit apps/api/.env — set FRAME_PRIVATE_KEY, FRAME_PUBLIC_KEY, FRAME_KEY_FORMAT=base64,
# ANTHROPIC_API_KEY at minimum (see apps/api/.env.example)

docker compose up --build
```

API at `http://localhost:8000` · OpenAPI at `http://localhost:8000/docs`

The Compose file is `docker-compose.yml` at the repo root. The image build **context is the monorepo root** (so `FRAME_REPO_ROOT` can find `scripts/` and `packages/signing/` for receipt signing); the Dockerfile lives at `apps/api/Dockerfile`.

---

## Environment variables

**Required:**

```
FRAME_PRIVATE_KEY       Ed25519 private key (base64 PKCS#8 DER)
FRAME_PUBLIC_KEY        Matching public key
FRAME_KEY_FORMAT        Set to: base64
DATABASE_URL            PostgreSQL connection string
ANTHROPIC_API_KEY       For analysis and coalition mapping
```

**Optional:**

```
REDIS_URL               Enables background enrichment queue (ARQ)
GROQ_API_KEY            LLM fallback #1
GOOGLE_API_KEY          LLM fallback #2
OPENAI_API_KEY          LLM fallback #3
LLM_PROVIDER            Force a provider: anthropic | groq | google | openai | auto
FEC_API_KEY             Federal Election Commission data
CONGRESS_API_KEY        Congressional records
COURTLISTENER_API_KEY   Court documents
ASSEMBLYAI_API_KEY      Audio transcription
SEC_EDGAR_USER_AGENT    SEC filings
```

---

## Key endpoints

```
POST /v1/analyze-article        Analyze an article URL, returns receipt
GET  /r/{receipt_id}            Get a receipt as JSON
GET  /i/{receipt_id}            Server-rendered investigation page
GET  /verify                    Public verifier page
POST /v1/verify-receipt         Programmatic verification
POST /v1/coalition-map          Trigger coalition map (async)
GET  /v1/coalition-map/{id}     Poll coalition map result
GET  /v1/receipts/recent        Recent receipts
GET  /v1/status                 Health + public key
GET  /openapi.json              Full API spec (81 endpoints)
```

---

## How signing works

Every receipt before storage:

1. Build the semantic payload (claims, sources, narrative, perspectives)
2. Canonicalize with RFC 8785 JCS — deterministic key ordering, no whitespace variation
3. SHA-256 the canonical string → `content_hash`
4. Sign the hex digest with Ed25519 → `signature`
5. Store `public_key`, `signature`, and `content_hash` alongside the receipt

To verify: fetch the receipt, recompute the JCS hash, check the signature against the embedded public key. Pass = untouched. Fail = something changed after signing.

Pure Python JCS implementation: `apps/api/jcs_canonicalize.py` — no Node subprocess.

---

## Stack

| Layer | Tech |
| --- | --- |
| API | Python 3.11, FastAPI, PostgreSQL |
| Signing | Ed25519 + RFC 8785 JCS canonicalization |
| Coverage | GDELT (4-stage waterfall) → NewsAPI fallback |
| Legal records | CourtListener (activated on RUMORED claims) |
| LLM | Anthropic Claude, fallback to Groq / Gemini / OpenAI |
| Frontend | Server-rendered HTML from FastAPI (no JS framework) |
| Deployment | Render (API) + Netlify (web frontend) |
| Commit count | 182+ across active development |

---

## Repo layout

```
apps/
  api/              FastAPI — routes, signing, receipt storage, investigation HTML
  web/              Vite + React frontend

packages/
  types/            TypeScript receipt shapes
  sources/          FEC, LDA, 990, Wikidata data builders
  signing/          JCS + Ed25519 sign/verify
  narrative/        Governance and entity modeling

scripts/            CLI: signing, JCS, generation
docs/               System documentation (+ screenshot for README)
```

---

## Tests

```bash
# TypeScript (signing, JCS, narrative fixtures)
npm test

# End-to-end against a running API
npm run e2e

# Or manually
bash scripts/e2e-test.sh http://localhost:8000
```

Signing unit tests: `packages/signing/__tests__/`  
Curl-based verification walkthroughs: `docs/PROOF.md`

---

## Deploy

Deployed via `render.yaml`. API runs:

```
cd apps/api && uvicorn main:app --host 0.0.0.0 --port $PORT
```

Set all required environment variables in Render → service → Environment before deploying. The Vite frontend deploys to Netlify via `netlify.toml` — set `VITE_API_BASE_URL` to your API URL at build time.

---

## License

MIT — Copyright (c) 2026 Nikodemus Systems
