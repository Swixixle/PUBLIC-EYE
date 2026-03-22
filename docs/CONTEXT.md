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
- **Podcast / video adapter:** `apps/api/adapters_podcast.py` — `yt-dlp` download, local **`openai-whisper` `base`** transcription, Claude claim extraction with timestamps + speakers, same source verification + `route_claim` + signing as media. **`POST /v1/analyze-podcast`** (JSON `url` or multipart `file`), **`POST /v1/analyze-and-verify-podcast`**. **`scripts/sign-media-analysis.ts`** supports `sourceType: "podcast"`, transcript source row (`whisper://local/{hash}`), narrative lines `At HH:MM:SS, speaker said: …`. **v1 cap: 30 minutes** of audio (`FRAME_PODCAST_MAX_SECONDS`). Requires **ffmpeg** on `PATH` for trim + acoustic fingerprint. Whisper **~140MB** model download on first run (slow cold start on free tier). **Spotify app links** not supported — use public RSS episode URLs or YouTube.

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

## Funding Notes
Brown Institute requires Columbia/Stanford affiliation — not eligible.
Better targets: Knight Foundation Prototype Fund, Mozilla Technology Fund,
investigative journalism fellowships, The Markup, Freedom of the Press Foundation.

## Session History
Built in one overnight session March 19-20 2026.
Started: broken 500 error, placeholder payload.
Ended: live FEC pipeline, cryptographic verification, full UI with evidence chain.

### Day 1 — Task 1.1 (split `unknowns` schema)
- **`packages/types/index.ts`:** `UnknownItem`, `UnknownsBlock`, helpers `emptyUnknowns`, `opUnknown`, `epiUnknown`, `mergeUnknowns`; **`FrameReceiptPayload.unknowns`** required on every signed payload.
- **`packages/sources/index.ts`:** All live receipt builders (`buildLiveFecReceipt`, `buildLiveLobbyingReceipt`, `buildLobbyingCrossReference`, `buildCombinedPoliticianReceipt`, `buildLive990Receipt`, `buildWikidataReceipt`) populate `unknowns` with adapter-appropriate operational/epistemic items.
- **`scripts/sign-media-analysis.ts`:** Media/podcast receipts include `unknowns` (OCR/HIVE/trim limits operational; boundary epistemic).
- **`apps/api/main.py`:** `SignedReceipt` includes optional **`unknowns`** (`UnknownItem` / `UnknownsBlock`) for `/v1/verify-receipt` compatibility.
- **`apps/web/demo-payload.json`:** Regenerated via **`npx tsx scripts/regen-demo-payload.ts`** (uses first PEM private key in `apps/api/.env`).
