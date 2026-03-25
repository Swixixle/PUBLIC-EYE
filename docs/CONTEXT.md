# Frame — Project Context

## The Mission
Cryptographic fact-checking with citations and no judgment. Works for lies and truths equally. 
Public figures are fair game — politicians, journalists, executives, ministers, celebrities. 
Every claim gets the same treatment: sourced, signed, tamper-evident, verifiable by anyone.

Not an attack tool. An epistemic infrastructure tool.

The goal is to work on any platform — TikTok, Instagram Reels, Facebook, X, news apps. 
Someone sees a claim in a video. They want to know if it's true. Frame gives them a 
cryptographic receipt with citations — no editorial, no spin, just the gap or alignment 
between the claim and the public record.

This works for good people too. If someone has a genuine record of charity, honesty, 
or public service — Frame proves that just as rigorously as it proves the opposite.

## What Frame Is
Frame turns claims by public figures into cryptographically signed receipts.
Each receipt contains:
- The claim (verbatim)
- Sourced neutral narrative sentences
- Primary source URLs (FEC, lobbying disclosures, IRS 990s, court records, scripture, etc.)
- **`unknowns`** — split into **`operational`** (timeouts, rate limits, missing keys — may resolve) and **`epistemic`** (intent, causation, limits of public record — not fixable by better infra). Each item is `{ text, resolution_possible }` (`true` operational, `false` epistemic).
- An Ed25519 signature proving the content hasn't been tampered with since signing

## Implication Risk

Every claims object carries `implication_risk: low | medium | high`.

- `low` — biographical, structural, or definitional facts
- `medium` — statistically unusual but not immediately alarming  
- `high` — facts that strongly imply a conclusion Frame does not assert

Claims with `implication_risk: high` always carry `implication_note` — 
a single deterministic sentence stating what the fact does not establish.
Notes are generated from IMPLICATION_NOTES lookup, not from an LLM.
They are signed into the receipt payload.

The UI surfaces `implication_note` as a tooltip on high-risk claims.
This is schema enforcement, not style guidance.

## Adapter manifest (`adapters_queried`)

Stage 2 enrichment records per-adapter outcomes in **`adapter_log`** (`enrichment/dispatch.py`) and flattens them into **`adapters_queried`** on the **signed receipt payload root** (`adapters_podcast.run_stage2_enrichment`). Each row: `source`, `entity`, `status` (`found` | `not_found` | `error`), `result_count`, `queried_at`, optional `note`. Same JCS hash as the rest of the receipt — not post-hoc. **`meta.adapters_dispatched`** remains a dedupe list of source ids for backward compatibility.

## Async Job System

All receipt generation can be submitted as background jobs.

**Submit:** `POST /v1/jobs` or `POST /v1/intake`  
Returns: `{ job_id, status, poll_url }` immediately.

**Poll:** `GET /v1/jobs/{job_id}`  
Returns: `{ status, receipt, processing_time_ms }` when complete.

Status values: `pending` → `processing` → `complete` | `failed`

The synchronous `/v1/generate-*` endpoints remain available and unchanged.
The job system wraps the same underlying adapter logic.

**Current limitation:** Job store is in-memory. Resets on server restart.
Acceptable at current stage — no persistent state required for the demo.

## Media UI

Located at `/demo` — **Media** tab.

Input: URL paste or file upload (image/video, max 50MB)

Processing: job system (`submitJobAndPoll`), 2-second polling for URL jobs; file path uses `POST /v1/analyze-media` then `POST /v1/sign-media-analysis`.

Output: receipt card with required sections.

Required sections in receipt card (in order):

1. WHAT WAS CHECKED
2. FILE FINGERPRINT (SHA-256, tamper-evident note)
3. AI DETECTION (shown if Hive ran with a score or error)
4. TEXT FOUND IN FILE (shown if OCR found text)
5. CHAIN OF CUSTODY
6. WHAT WE DON'T KNOW (mandatory — never hidden)
7. SOURCES CONSULTED
8. VERIFY (trust footer, collapsed by default)

The **WHAT WE DON'T KNOW** section is architecturally mandatory.
If it is empty, the adapter is lying.

Operational unknowns = technical failures (amber label)

Epistemic unknowns = fundamental limits (grey label)

## Environment Variables

### META_AD_LIBRARY_TOKEN

Required for: `POST /v1/generate-ad-library-receipt`

Setup:

1. Create a Meta developer account at https://developers.facebook.com/
2. Create an app — type: Business
3. Add the Marketing API product
4. Request `ads_read` permission
5. Generate a User Access Token with `ads_read` scope
6. Add as `META_AD_LIBRARY_TOKEN` in Render environment

Without this token: endpoint returns a partial receipt documenting
the absence of the token as an operational unknown. It does not fail.

Note: User Access Tokens expire. A System User token (via Business Manager)
is more stable for production. Add as a known gap until addressed.

## Schema baselines (Rule Change Receipt foundation)

**Module:** `apps/api/schema_monitor.py`  
**Storage:** `apps/api/baselines/baseline_{source_id}.json` (committed as evidence)

On **API startup**, Frame captures a **structural schema fingerprint** (field paths, types, cardinality — not values) for:

- `fec` — OpenFEC candidates
- `lda` — Senate LDA filings
- `propublica_990` — ProPublica nonprofit search
- `wikidata` — `wbsearchentities`
- `meta_ad_library` — adapter output from Meta Ad Library query

**GET `/v1/schema-baselines`** returns status, truncated hashes, capture time, and field counts for each source.

First capture is **genesis**; unchanged schema on later starts updates **`last_verified_at`**. If structure drifts, baseline is versioned and **`schema_changed`** is set — full **Rule Change Receipt** generation is **not** implemented yet (`compare_to_baseline` in `schema_monitor.py` is the drift hook).

See **`docs/PROOF.md`** for curl proofs including schema baselines.

## FetchAdapter

Interface: `apps/api/adapters/fetch_adapter.py`  
Contract: URL in → `FetchResult` (bytes + metadata + `ChainOfCustodyBlock`) out.

Implementations:
- `YtDlpAdapter` — social media (Instagram, TikTok, YouTube, etc.)
- `DirectHttpAdapter` — direct URLs, images, documents

Router: `apps/api/adapters/router.py` selects adapter by URL pattern.

Chain of custody block is signed into every media receipt:
retrieval_timestamp, server_ip, tls_verified, http_status, fetch_adapter_version.

Platform changes replace the implementation only. The interface contract,
the signing pipeline, and the receipt schema are untouched.

The verification is live. Anyone can check it. Anyone can re-verify independently.

## Architecture — Current
packages/types — shared interfaces (FrameReceiptPayload, SourceRecord, NarrativeSentence)
packages/signing — Ed25519 + JCS canonicalization (RFC 8785)
packages/narrative — governance rules, banned words, domain whitelist
packages/sources — data adapters (FEC live, others stubbed)
packages/entity — disambiguation
apps/api — FastAPI: /v1/verify-receipt, /v1/generate-receipt
apps/web — static demo UI
apps/macos — FrameCapture.app + `scripts/frame-capture.sh` (screen region → signed receipt URL)
apps/extension — Chrome/Brave MV3 extension (toolbar + context menu → analyze → sign → receipt tab)
scripts/generate-keys.ts — key generation (--write-env flag)
scripts/seed-demo.ts — signs Manchin fixture for demo
scripts/generate-receipt.ts — called by API to sign live FEC receipts
scripts/test-fec.ts — local FEC API testing
scripts/frame-capture.sh — macOS: region capture → POST /v1/analyze-and-verify → clipboard + notification

## Architecture — Planned Extensions
The schema is already general. Sources accept any URL. Claims accept any statement.
FEC is just one adapter. Everything below plugs into the same signing pipeline.

Claim intake layer (next major build):
- POST /v1/intake — accepts a text claim or video URL
- Claim classifier — routes to correct adapter(s) based on claim type
- Video transcription via Whisper — extract claims from video automatically
- Claim extraction — identify specific falsifiable claims from transcript

Adapter roadmap (in priority order):
1. FEC — DONE (live, any senator by candidate ID)
2. Senate LDA lobbying disclosures — NEXT (lda.senate.gov/api/v1/, no key required)
3. IRS 990 — nonprofit financials, foundation money flows (ProPublica Nonprofit Explorer API)
4. Congress.gov voting record — (API key pending)
5. Biblical concordance — public domain, for claims made in name of religion
6. Wikipedia/Wikidata — basic biography, stated positions, known affiliations
7. Court records — PACER (harder but public)
8. Existing fact-check databases — PolitiFact, Snopes APIs

Media / disinformation layer (extends roadmap):
7. Hive AI detection — set HIVE_API_KEY in Render to enable (https://thehive.ai)
8. OCR text extraction — Tesseract or Google Vision, extracts claims from screenshots
9. Media hash ledger — store file hashes to track viral spread across accounts

Distribution layer (future):
- Shareable receipt URLs — **DONE** (`GET /receipt/:id`, `receiptUrl` on signed responses)
- macOS menu bar capture — **DONE** (`scripts/frame-capture.sh`, `apps/macos/FrameCapture.app`; menu bar via Platypus or SwiftBar)
- Browser extension — **DONE** (`apps/extension/` — toolbar popup, “Verify with Frame” on images, receipt tab)
- Open embed format — receipt card that travels with the claim

## Live URLs
- API: https://frame-2yxu.onrender.com
- Demo UI: https://delightful-cucurucho-b09e70.netlify.app
- GitHub: https://github.com/Swixixle/FRAME

## Current Build Status
- Ed25519 signing pipeline: COMPLETE (5/5 tests passing)
- JCS canonicalization (RFC 8785): COMPLETE
- Tamper detection: COMPLETE
- Live FEC adapter: COMPLETE
- POST /v1/verify-receipt: COMPLETE and working on Render
- POST /v1/generate-receipt: COMPLETE locally, PEM key format issue on Render in progress
- Demo UI with evidence chain, source links, rabbit hole: COMPLETE on Netlify
- POST /v1/analyze-media: COMPLETE — SHA-256 + perceptual hash (pHash-DCT-64bit), Claude vision OCR, claim classification with type/entities, primary source URL suggestion, source verification and content snapshotting (SHA-256 of page at retrieval time), Hive AI detection (requires HIVE_API_KEY)
- POST /v1/sign-media-analysis: COMPLETE — signs full media analysis as Frame receipt including verified source hashes
- GET /v1/ledger: COMPLETE — SQLite-backed perceptual hash ledger, exact + Hamming distance matching, first-seen timestamps
- Media upload UI: COMPLETE — drag and drop on /demo, shows claim type, entities, source verification status, content hash, page title
- Chrome/Brave extension: COMPLETE — `apps/extension/` (MV3, no build step; toolbar + image context menu → receipt tab)
- Persistent ledger: SQLite at /tmp/frame_ledger.db (resets on redeploy until Render Pro + PostgreSQL)
- Known gap: source URLs are Claude suggestions — some return 404/403. Need URL resolver that only signs verified sources.
- Known gap: ledger resets on redeploy. Fix: Render Pro PostgreSQL (swap DATABASE_URL, same code)
- Combined media pipeline: hash → detect → verify sources → ledger → sign → verify
- **Gap 3 (OCR → router → adapters):** `apps/api/router.py` + `adapters_media.py` — after Claude extracts claims, `route_claim()` selects fec / irs990 (ProPublica) / lda / congress / wikidata; results on each claim as `adapterResults`; `sign-media-analysis.ts` adds adapter rows to `sources[]` with `metadata.adapterData`. **`POST /v1/analyze-and-verify`** = analyze + route + sign in one call. **`CONGRESS_API_KEY`** required for Congress.gov bill search (free at api.congress.gov).
- **Gap 4 (entity behavioral ledger):** SQLite table `entity_receipts` — each verified media receipt appends rows per (claim × entity) from `extractedClaimObjects`. **`GET /v1/entity/{name}`**, **`GET /v1/entity/{name}/summary`**, **`GET /v1/entities`**. **`GET /entity/{name}`** serves `apps/web/entity.html` (Cinzel baroque frame). Demo UI links “View entity record →” after analyze-and-verify when entities are present.
- **Podcast / video adapter:** `apps/api/adapters_podcast.py` — `yt-dlp` download, local **`faster-whisper` `base`** transcription, Claude claim extraction with timestamps + speakers, same source verification + `route_claim` + signing as media. **`POST /v1/analyze-podcast`** (JSON `url` or multipart `file`), **`POST /v1/analyze-and-verify-podcast`**. **`scripts/sign-media-analysis.ts`** supports `sourceType: "podcast"`, transcript source row (`whisper://local/{hash}`), narrative lines `At HH:MM:SS, speaker said: …`. **v1 cap: 30 minutes** of audio (`FRAME_PODCAST_MAX_SECONDS`). Requires **ffmpeg** on `PATH` for trim + acoustic fingerprint. First run may download model weights (slow cold start on free tier). **Spotify app links** not supported — use public RSS episode URLs or YouTube.
- **Meta Ad Library (“was it paid for”):** `apps/api/adapters/meta_ad_library.py` — Graph API `ads_archive` for political and issue ads; spend ranges normalized; epistemic unknowns for disclosure limits. **`POST /v1/generate-ad-library-receipt`**, **`receipt_type: "ad_library"`** on **`POST /v1/jobs`**. Demo: **Ad Spend** mode on `/demo`. Requires **`META_AD_LIBRARY_TOKEN`** (`ads_read`); without token, signed receipt still returned with operational unknown.

## Immediate Next Task
Fix FRAME_PRIVATE_KEY format on Render so /v1/generate-receipt works in production.
Key stored as base64 in Render env vars. FRAME_KEY_FORMAT=base64.

## After That
Build Senate LDA lobbying adapter:
https://lda.senate.gov/api/v1/
No API key required.
Cross-reference with FEC candidate ID: who lobbied this senator, how much, 
on what issues, in what timeframe relative to their votes.

## Key Technical Notes
- FEC candidate ID for Manchin: S0WV00090
- FEC candidate ID for Sanders: S4VT00033
- FEC API base URL: https://api.open.fec.gov/v1/
- Private key in Render: base64 format, FRAME_KEY_FORMAT=base64
- Local keys in apps/api/.env (gitignored)
- demo-payload.json is hand-authored Manchin fossil fuel fixture
- seed-demo.ts regenerates demo-payload.json from local keys

## Session History
Built in one overnight session March 19-20 2026.
Started: broken 500 error, placeholder payload.
Ended: live FEC pipeline, cryptographic verification, full UI with evidence chain.

### Task 3.2 — README + polish + E2E
- **`README.md`:** rewritten for 60-second clarity; curl proofs; API table; stack; env vars.
- **`scripts/e2e-test.sh`:** production smoke tests (health, demo, pitch, receipts, verify, jobs, schema baselines, FEC job poll).
- **`docs/DOMAIN.md`:** custom-domain checklist.
- **`render.yaml` / `requirements.txt`:** audited for media pipeline deps.

### Task 3.1 — Schema baseline capture + PROOF.md
- **`apps/api/schema_monitor.py`:** path normalization, recursive `_extract_schema`, `fingerprint_schema` (full + critical hashes), `capture_baseline` / `save_baseline` / `compare_to_baseline`, JSON storage under **`apps/api/baselines/`**.
- **Startup:** `capture_schema_baselines` runs FEC, LDA, ProPublica 990, Wikidata, Meta Ad Library adapter samples; failures still record error-shaped baselines.
- **`GET /v1/schema-baselines`:** admin view of capture status and truncated hashes.
- **`docs/PROOF.md`:** falsifiable curl proofs + architecture table; **`npm run proof:date`** stamps the generated date line.

### Task 1.4 — FetchAdapter + pitch deck
- **`apps/api/adapters/`:** `FetchAdapter` ABC, `YtDlpAdapter`, `DirectHttpAdapter`, `get_adapter_for_url`. `httpx` for direct HTTP.
- **`_run_job` `source_url`:** real fetch → Frame-shaped payload → `scripts/sign-payload.ts` (Ed25519). `AdapterUnavailableError` → partial receipt with operational unknowns.
- **`GET /pitch`:** serves `apps/web/pitch.html` (React 18 + Babel CDN, 9 tabs, roundtable, receipt mockup).

### Task 1.3 — Async job system
- **`apps/api/job_store.py`:** in-memory jobs (`pending` → `processing` → `complete` | `failed`); resets on restart.
- **`POST /v1/jobs`**, **`GET /v1/jobs/{job_id}`**, **`POST /v1/intake`:** submit work, poll for signed receipt or result payload. Same adapter logic as synchronous **`/v1/generate-*`** via extracted **`_generate_*_sync`** helpers + async wrappers for background tasks.
- **`apps/web/index.html`:** **`submitJobAndPoll()`** helper (uses `API_BASE`; no change to existing flows yet).
- **Note:** Deploy API to Render for **`/v1/jobs`** on production; signing still requires **`FRAME_PRIVATE_KEY`** (or Render env) for FEC/990/etc. jobs.

### Task 1.2 — `implication_risk` + `implication_note` on claims
- **`packages/types`:** `ImplicationRisk`, `ClaimEvidenceType`, `ClaimRecord` fields; `buildClaim()`; `IMPLICATION_NOTES` / `getImplicationNote()` (`implication-notes.ts`).
- **`packages/sources/index.ts`**, **`scripts/sign-media-analysis.ts`**, **`manchin-payload`:** all claims use `buildClaim()` with category-appropriate risk.
- **`apps/api/implication_notes.py`** + **`ClaimRecord`** in **`main.py`** (Pydantic `model_validator`: high ⇒ note required).
- **`docs/CONTEXT.md`:** Implication Risk section.

### Day 1 — Task 1.1 (split `unknowns` schema)
- **`packages/types/index.ts`:** `UnknownItem`, `UnknownsBlock`, helpers `emptyUnknowns`, `opUnknown`, `epiUnknown`, `mergeUnknowns`; **`FrameReceiptPayload.unknowns`** required on every signed payload.
- **`packages/sources/index.ts`:** All live receipt builders (`buildLiveFecReceipt`, `buildLiveLobbyingReceipt`, `buildLobbyingCrossReference`, `buildCombinedPoliticianReceipt`, `buildLive990Receipt`, `buildWikidataReceipt`) populate `unknowns` with adapter-appropriate operational/epistemic items.
- **`scripts/sign-media-analysis.ts`:** Media/podcast receipts include `unknowns` (OCR/HIVE/trim limits operational; boundary epistemic).
- **`apps/api/main.py`:** `SignedReceipt` includes optional **`unknowns`** (`UnknownItem` / `UnknownsBlock`) for `/v1/verify-receipt` compatibility.
- **`apps/web/demo-payload.json`:** Regenerated via **`npx tsx scripts/regen-demo-payload.ts`** (uses first PEM private key in `apps/api/.env`).

---

## What Frame Is Not

Read this when scope starts drifting.

Frame is a receipt system for claims and evidence. It proves what was observed,
from what sources, at what time, signed by whom. It works for true things and
false things equally. It is epistemic infrastructure, not an arbiter.

- Not a fact-checker (implies verdict)
- Not an AI trust score (implies oracle)  
- Not a misinformation detector (implies we decided)
- Not a competitor to C2PA (we cover what they can't reach)

---

## Maturity Ladder

**Frame Core (built):** Public records. FEC, LDA, 990s, Wikidata.
Subject classes: politicians, nonprofits, public figures.

**Frame Media (in progress):** Media provenance for untagged content.
SHA-256 hash, OCR, Whisper, Hive AI detection, yt-dlp fetch.
Subject classes: social media clips, screenshots, uploaded files.

**Frame Network (not yet started):** Distribution tracking.
Perceptual hashing, hash ledger, repost mapping.
Do not build until Media tier is stable.

---

## Frames + dossiers (apps/api)

Parallel to `/v1/*` receipts: **`POST /frames`** creates a signed `Frame` (Ed25519 over SHA-256 of `claim + claimant_name + timestamp`), enqueues enrichment (ARQ + Redis when `REDIS_URL` set, else in-process `asyncio`). **`GET /frames/{id}`** returns enrichment status; **`GET /frames/{id}/dossier`** returns `202` while pending, else `DossierSchema` JSON. Modules: `cache/redis.py`, `models/*`, `enrichment/*`, `entity/resolver.py`, `dossier/assemble.py`, `worker.py`. Env keys: see `apps/api/.env.example`. Demo seed: `npx tsx scripts/seed-frames-demo.ts` (`API_BASE` optional).

## Known Gaps (current)

- `HIVE_API_KEY` not yet configured — AI detection returns `detector: none`
- `META_AD_LIBRARY_TOKEN` — User token expires; System User token recommended
- Salience algorithm (Layer Zero) uses rule-based fallback until corpus N=100
- Music dossier (Liner Notes) specced but not built
- Rule Change Receipt generation not yet implemented (baselines captured, monitoring not wired)
- Job store is in-memory — resets on server restart
- Browser extension is a skeleton only
- Custom domain not yet configured

---

## Subject Class Map

| Subject Class | Tier | Adapters | Status |
|--------------|------|----------|--------|
| politician | Core | FEC, LDA, Wikidata | Built |
| nonprofit | Core | 990, Wikidata | Built |
| public_figure | Core | Wikidata | Built |
| social_media_clip | Media | yt-dlp, SHA-256, OCR, Ad Library | Built |
| screenshot | Media | SHA-256, OCR, Ad Library | Built |
| artist | Music | AcoustID, Librosa, Rights | Specced |
| recording | Music | LibrosaAnalysis, SimilarSongs | Specced |
| corporation | Future | SEC EDGAR, PACER | Not started |
| court_case | Future | PACER | Not started |

## Rabbit Hole — Sister Product

Rabbit Hole is a consumer-facing forensic genealogy tool. Same cryptographic spine as Frame. Different entry point: Frame is for journalists and institutions; Rabbit Hole is for anyone who fell down a rabbit hole at 2am and wanted a map.

Tagline: *There is enough O2 even miles down the Rabbit Hole.*

Architecture: six depth layers, each a self-contained information jurisdiction. They stack. They do not bleed into each other. The full spec lives in `docs/RABBIT_HOLE_CONTEXT.md`.

### What's built (as of March 25, 2026)
- `GET /v1/depth-map` — all six layers, sealed floor on Layer 6 (jurisdiction adapters not yet built)
- `POST /v1/surface` — Layer 1, Anthropic-powered, graceful 503 when credits offline
- `GET /v1/surface/slenderman` — inoculation baseline, no API key required
- `POST /v1/pattern-match` — Layer 5, keyword + structural heuristics against signed pattern library
- `GET /v1/pattern-lib` — full public pattern library with `unsigned_count` transparency field
- `POST /v1/dispute` — real endpoint, public, append-only dispute log
- `GET /v1/dispute/{pattern_id}` — public dispute list per pattern
- `GET /v1/actor/{slug}` + events — append-only actor ledger, Eric Knudsen seeded
- `POST /v1/verify-receipt` — shared verification endpoint for both Frame and Rabbit Hole receipts
- `apps/web` depth map UI — six layers rendered, tier badges, sealed floor visual, dispute inline form, Layer X of 6 navigation header

### What's next
- Fix `apps/web` branding: "Frame · Depth map" → "Rabbit Hole" *(done March 25, 2026)*
- Add tagline and opening disclaimer to page header *(done March 25, 2026 — copy in `docs/RABBIT_HOLE_CONTEXT.md` § Tone & Voice)*
- Add Slenderman baseline as pre-populated example on page load
- Build signing pipeline for actor ledger events (same HALO-ANCHORS pattern)
- Seed pattern library with 5 historical patterns before any current-events patterns ship
- Dispute endpoint needs status update endpoint (`PATCH /v1/dispute/{dispute_id}`)
- Layers 2, 3, 4 adapters not yet built
- Comparative jurisdiction layer (Layer 6) requires international source adapters
