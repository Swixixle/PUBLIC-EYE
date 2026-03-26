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

When the API serves `apps/web/index.html` at **`/demo`**, the bundled app is **Rabbit Hole** (depth map). Frame **media** flows (upload, Hive, OCR, signing) remain available via **`POST /v1/analyze-media`**, **`POST /v1/analyze-and-verify`**, and related routes — see main.py. A static legacy layout may exist as **`apps/web/frame-legacy.html`**.

Input (Frame media routes): URL paste or file upload (image/video, max 50MB)

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
packages/types — shared interfaces (receipts, depth map, actor layer, pattern results, `sources_checked` incl. **deferred**)
packages/signing — Ed25519 + JCS canonicalization (RFC 8785)
packages/sources — FEC, lobbying, 990, Wikidata, combined flows (see package exports)
packages/adapters — TypeScript depth-layer helpers (surface, spread, origin, actor, pattern, jurisdiction) for Node-backed actor pipeline
packages/actor-ledger — `ledger.json` + types for Rabbit Hole Layer 4
packages/pattern-lib — signed pattern catalog
packages/dispute-log — append-only dispute records
packages/narrative — governance rules (where used)
apps/api — FastAPI: receipts, media, jobs, frames/dossiers router, Rabbit Hole depth routes (`/v1/surface`, `/v1/spread`, `/v1/origin`, `/v1/actor-layer`, `/v1/report`, pattern + dispute + actor ledger)
apps/web — Vite/React **Rabbit Hole** UI (`DepthMap`); `frame-legacy.html` retains a static Frame-style snapshot where needed
apps/macos — FrameCapture.app + `scripts/frame-capture.sh`
apps/extension — Chrome/Brave MV3 extension (toolbar + context menu → analyze → sign)
scripts — receipt generation, `run-actor-layer.mjs`, signing, seed scripts (see `scripts/`)

## Architecture — Planned Extensions

The receipt schema is general; **most “next” work is in Known Gaps** (Rule Change Receipts, Rabbit Hole Layer 6, dispute workflow, music dossier, stronger viral graph).

**Still valuable / not exhaustive:**
- Richer **claim intake** from arbitrary text (beyond current media/podcast flows): classifier + adapter fan-out
- **PACER / courts**, **embeddable receipt card** for third-party sites
- **Fact-check APIs** as optional citations (PolitiFact, Snopes-style) — same neutral receipt rules apply

**Already in the tree (do not re-list as greenfield):** FEC, LDA/lobbying receipts, 990, Wikidata, Congress (with key), media OCR + Whisper + optional Hive, pHash ledger, Rabbit Hole layers 1–5, five-ring report.

## Live URLs
- API: https://frame-2yxu.onrender.com
- Demo UI: https://delightful-cucurucho-b09e70.netlify.app
- GitHub: https://github.com/Swixixle/FRAME

## Session Start Checklist

Do this before changing code in a new session:

1. **`GET /health`** on the Render API (or open `/health` in browser) — confirm deploy is live and not mid-rollout.
2. **`ANTHROPIC_API_KEY`** — confirm the account has quota; Rabbit Hole Layer 1 (`POST /v1/surface`) fails soft or degrades when credits are exhausted.
3. **`git pull`** on `main` — handoff docs and API move quickly; start from latest.
4. **Read `docs/CONTEXT.md` and `docs/RABBIT_HOLE_CONTEXT.md`** end-to-end — they are the single picture of what is built vs. still missing.

## Current Build Status

**Frame core**
- Ed25519 signing + JCS (RFC 8785): COMPLETE
- `POST /v1/verify-receipt`: COMPLETE (production)
- Live FEC, lobbying, 990, Wikidata, combined, Ad Library receipt routes: COMPLETE (`scripts/` + `main.py`)
- `POST /v1/generate-receipt` on Render: COMPLETE when `FRAME_PRIVATE_KEY` and `FRAME_KEY_FORMAT` match (typically `base64`)
- Async jobs: COMPLETE (`POST /v1/jobs`, `GET /v1/jobs/{job_id}`) — store is in-memory
- Media stack: `POST /v1/analyze-media`, sign, analyze-and-verify, podcast analyze routes, `GET /v1/ledger` (pHash SQLite): COMPLETE
- Router on OCR claims (`route_claim` → FEC / 990 / LDA / Congress / Wikidata): COMPLETE; **`CONGRESS_API_KEY`** for Congress.gov
- Entity behavioral ledger: COMPLETE (`entity_receipts`, `GET /v1/entity/...`, `entity.html`)
- Chrome/Brave extension: COMPLETE (`apps/extension/`)
- Schema baselines: COMPLETE (`GET /v1/schema-baselines`)

**Rabbit Hole (March 25, 2026)**
- Depth map API + UI: COMPLETE
- `POST /v1/surface`, `GET /v1/surface/slenderman`: COMPLETE (`ANTHROPIC_API_KEY` for live surface)
- `POST /v1/spread`, `POST /v1/origin`: COMPLETE
- `POST /v1/actor-layer`: COMPLETE — Node subprocess, full archive/RSS/Wikidata stack + `packages/actor-ledger`
- `POST /v1/report`: COMPLETE — five-ring parallel report, merged `sources_checked`
- Report Ring 4 **fast path**: COMPLETE — `actor_layer_fast.py` (ledger-only; external adapters **`deferred`**, detail points to `POST /v1/actor-layer`)
- Pattern + dispute APIs + actor ledger HTTP: COMPLETE
- Web: Rabbit Hole shell, DepthMap, receipt manifest, `sources_checked` including **deferred** badges: COMPLETE

**Operational limits (not “missing code”)**
- Suggested media source URLs may 404/403; verifier records what was retrievable
- SQLite ledgers reset on hobby redeploy unless DB is externalized
- Optional keys: `HIVE_API_KEY`, `META_AD_LIBRARY_TOKEN`, `ANTHROPIC_API_KEY`

## Immediate Next Task

1. After each deploy: **`curl`/browser `GET /health`** and smoke **`POST /v1/report`** — Ring 4 should finish quickly and show **`deferred`** rows for IA/CA/RSS/Wikidata-class adapters; use **`POST /v1/actor-layer`** when full corroboration is required.  
2. Pick one product thread: **Layer 6 jurisdiction adapters**, **dispute `PATCH` workflow**, or **Rule Change Receipt** automation — see Known Gaps.

## After That

Deepen whichever thread you select above; do not start Layer 6 until Rabbit Hole layers 1–5 are stable in production Telemetry.

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

### March 25, 2026 — Rabbit Hole depth stack + library report
- **Types** — actor layer / `sources_checked`, **`deferred`** status for adapters not run in a given context.
- **`packages/adapters`** — TypeScript depth helpers; actor layer parallel lookups (Internet Archive, Chronicling America, JSTOR check, RSS-style sources, Wikidata/Wikipedia paths).
- **Node** — `scripts/run-actor-layer.mjs` drives full Layer 4 against `packages/actor-ledger/ledger.json`.
- **API** — `POST /v1/actor-layer` (full stack); `POST /v1/spread`, `POST /v1/origin`; **`POST /v1/report`** (five rings in parallel, merged manifest + unknowns).
- **Performance** — `apps/api/actor_layer_fast.py`: report Ring 4 uses ledger word-boundary match only (no outbound HTTP to archives/RSS/wikidata); `sources_checked` marks those adapters **`deferred`** with pointer to **`POST /v1/actor-layer`**.
- **Web** — `DepthMap` / manifest: **`sources_checked`** panel, **`deferred`** styling; Rabbit Hole title/meta on `index.html`.
- **Docs** — this file + `docs/RABBIT_HOLE_CONTEXT.md` aligned as session handoff.

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

**Frame Network (partial):** Perceptual hash ledger (`GET /v1/ledger`) and file hashing are built; cross-platform **repost graph** / viral lineage mapping is not.

---

## Frames + dossiers (apps/api)

Parallel to `/v1/*` receipts: **`POST /frames`** creates a signed `Frame` (Ed25519 over SHA-256 of `claim + claimant_name + timestamp`), enqueues enrichment (ARQ + Redis when `REDIS_URL` set, else in-process `asyncio`). **`GET /frames/{id}`** returns enrichment status; **`GET /frames/{id}/dossier`** returns `202` while pending, else `DossierSchema` JSON. Modules: `cache/redis.py`, `models/*`, `enrichment/*`, `entity/resolver.py`, `dossier/assemble.py`, `worker.py`. Env keys: see `apps/api/.env.example`. Demo seed: `npx tsx scripts/seed-frames-demo.ts` (`API_BASE` optional).

## Known Gaps (current)

**Infra / keys**
- Optional: `HIVE_API_KEY`, `META_AD_LIBRARY_TOKEN`, `ANTHROPIC_API_KEY` — features degrade gracefully when unset or expired (use System User token for Meta when possible)
- Job store is in-memory — resets on server restart
- pHash / SQLite paths may reset on hobby redeploy until storage is external

**Frame**
- Rule Change Receipt: baselines captured; automated drift → signed “rule change” receipt not wired
- Music dossier (Liner Notes) specced, not built
- Custom domain for `frame-2yxu.onrender.com` optional (`docs/DOMAIN.md`)

**Rabbit Hole**
- Layer 6 (jurisdiction / comparative) adapters not built — depth map shows sealed floor
- Dispute workflow: no `PATCH` / moderation status API yet
- Actor ledger: append API exists; **signed sealed ledger** pattern (HALO-style) not fully productized
- Report `POST /v1/report` Ring 4 is **ledger-first**; operators must call **`POST /v1/actor-layer`** for full archive/RSS/Wikidata corroboration (UI copy and `sources_checked` **`deferred`** rows document this)
- Slenderman: static baseline via GET; optional UX for auto-prefill on first load

**Research**
- Salience / Layer Zero remains rule-heavy until corpus thresholds are met

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

Consumer-facing **depth map**: same verification spine as Frame (`POST /v1/verify-receipt`), different primary UX — narrative in, five runnable layers out, plus pattern/dispute/actor ledger.

**Tagline:** *There is enough O2 even miles down the Rabbit Hole.*

**Authoritative detail:** `docs/RABBIT_HOLE_CONTEXT.md` (endpoints table, Layer 4 dual path, adapter list, UI components).

**Layers 1–5 (shipped):** `POST /v1/surface`, `/v1/spread`, `/v1/origin`, **`/v1/actor-layer`** (full Node stack), `/v1/pattern-match`; **`POST /v1/report`** runs 1–5 in parallel for a single library report. **Report Ring 4** uses the Python **fast path** (`actor_layer_fast`) so production stays fast; **`sources_checked`** marks archive/RSS/Wikidata-class adapters as **`deferred`** — full stack is **`POST /v1/actor-layer`**.

**Supporting routes:** `GET /v1/depth-map`, `GET /v1/surface/slenderman`, `GET /v1/pattern-lib`, `POST /v1/dispute`, `GET /v1/dispute/{pattern_id}`, `GET/POST /v1/actor/...`.

**Web:** `apps/web` Vite app — `DepthMap` + submit/processing/receipt views, **`sources_checked`** manifest (including **deferred**).

**Layer 6:** Sealed in metadata until jurisdiction adapters exist.

**Next priorities:** See **Known Gaps** (Layer 6, dispute PATCH, optional Slenderman prefill, actor ledger signing polish).

---

## Three-layer receipts and Layer B

Deep receipts (`POST /v1/deep-receipt`) structure output into **Layer A** (verified primary record), **Layer B** (historical thread), and **Layer C** (explicitly labeled inference). Layer A can be strong when live adapters return data (e.g. OpenFEC, CourtListener as the stack ingests them). **Layer B** depends on threaded legal and historical material—court opinions, dockets, legislation, GovInfo, and scholarly/caselaw hops—not on rhetoric. When that substrate is thin or unmapped into the bundle, the historical thread stays empty regardless of Layer A quality.

## Handoff

The most important thing to build next is always the thing that makes Layer B less empty.
