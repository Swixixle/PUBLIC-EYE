# FRAME — PROJECT CONTEXT
## A document for anyone picking this up cold

---

## WHAT THIS IS

Frame is epistemic infrastructure. It turns claims, public records, and institutional data into cryptographically signed, human-readable receipts that cannot be quietly revised after the fact. It is not a fact-checker that tells you what to believe. It is a record machine that tells you what the sources confirm, what they cannot confirm, and where to look next.

Rabbit Hole is Frame's sister product. Where Frame starts from a claim or a public figure, Rabbit Hole starts from a narrative — a conspiracy theory, a legend, a rumor, a myth — and traces how it originated, mutated, spread, and calcified into belief.

Both products share the same cryptographic spine. Both are built to be read by a West Virginia voter, parsed by an AI summarizer in Singapore, and cited by a policy analyst in Brussels. The writing discipline required to serve all three simultaneously is the same: short sentences, no idioms, every number explained, every claim sourced in the same breath.

### For journalists and funders (non-technical)

Frame is a machine that reads public records and produces a document you can verify. Ask it about Citizens United and it doesn't give you a summary — it pulls the actual court opinions, traces the legal thread from Buckley v. Valeo in 1976 through the 2010 decision, shows you what Congress said, and tells you exactly what it couldn't find and where you'd look for it. Every document it produces is cryptographically signed. The gaps it named, the caveats it flagged, the disclaimer that says "this is inference, not fact" — all of it is sealed inside the signature. You can't strip it out. A news organization, a foreign government, an AI summarizer downstream — none of them can quietly remove the parts that complicate the story. The record is the record.

---

## THE CORE INSIGHT

Every other fact-checking tool tells you a verdict. Frame tells you the record. The difference is this: a verdict can be disputed, pressured, softened, or revised. A cryptographically signed record with a content hash cannot be quietly changed after publication. The gaps it named are on record. The unknowns it flagged are sealed inside the hash. The disclaimer is part of the signed payload — not appended after, not strippable by a downstream AI summarizer.

This is the thing that makes Frame not Wikipedia, not Snopes, not PolitiFact. Those systems produce conclusions. Frame produces verifiable provenance chains.

---

## REPOS AND DEPLOYMENT

- **GitHub:** https://github.com/Swixixle/FRAME (monorepo — Frame and Rabbit Hole both live here)
- **API (Render):** https://frame-2yxu.onrender.com
- **UI (Netlify):** https://delightful-cucurucho-b09e70.netlify.app
- **Local working directory:** `~/FRAME`

**Before touching any code in a new session:**
1. `curl -sS https://frame-2yxu.onrender.com/health` — confirm 200
2. `cd ~/FRAME && git pull`
3. Read this file and `docs/RABBIT_HOLE_CONTEXT.md` in full

---

## MONOREPO STRUCTURE

```
FRAME/
├── apps/
│   ├── api/                    — FastAPI (Python), the brain
│   └── web/                    — React/Vite, the face
├── packages/
│   ├── types/                  — Shared TypeScript types
│   ├── signing/                — Ed25519 signing, key loading, receipt helpers
│   ├── sources/                — FEC, LDA, narrative generation, three-layer journalist
│   ├── adapters/               — Surface, spread, origin, actor, pattern (Rabbit Hole)
│   ├── actor-ledger/           — Append-only ledger of named entities
│   ├── pattern-lib/            — Signed library of 11 narrative spread patterns
│   └── dispute-log/            — Append-only dispute log
├── scripts/
│   └── jcs-stringify.mjs       — Node subprocess for JCS canonicalization
└── docs/
    ├── CONTEXT.md              — This file
    └── RABBIT_HOLE_CONTEXT.md  — Rabbit Hole specific context
```

**Render start command:**
```
cd ../.. && npm run build && cd apps/api && uvicorn main:app --host 0.0.0.0 --port $PORT
```

**Node bridge:** Python API spawns Node subprocesses for TypeScript signing and adapter logic. This is intentional — the signing library (`@noble/ed25519`) lives in Node. Python calls it via subprocess.

---

## TECH STACK

| Layer | Technology |
|-------|------------|
| API | FastAPI (Python 3.11+) |
| UI | React + Vite |
| Signing | Ed25519 + JCS canonicalization (RFC 8785), `@noble/ed25519` |
| Package management | npm workspaces |
| Deployment | Render (API), Netlify (UI) |
| LLM | Anthropic Claude (Sonnet for Frame narrative, Haiku for Rabbit Hole surface) |

---

## CRYPTOGRAPHIC SIGNING — HOW IT WORKS

Every Frame receipt and Rabbit Hole report is signed using Ed25519. The process:

1. Build the payload as a structured object
2. Canonicalize using JCS (RFC 8785) — field order is deterministic, no whitespace variation
3. Compute SHA-256 hex of the canonical UTF-8 bytes → `content_hash`
4. Sign the `content_hash` string (as UTF-8) with the Ed25519 private key → `signature`
5. Attach `content_hash`, `signature`, `public_key` (base64 SPKI), `signed: true` to the response

**Key format in Render:** `FRAME_KEY_FORMAT=base64`. The private key is base64-encoded PKCS#8 DER. Python's `frame_crypto.py` decodes it, tries UTF-8 PEM, falls back to `load_der_private_key`. Node's `frame-env-key.ts` handles the same format via `loadFramePrivateKeyFromEnv()`.

**Critical:** The disclaimer text in Layer C of three-layer receipts is inside the content hash. It cannot be stripped by downstream systems without invalidating the signature.

**Verification endpoint:** `POST /v1/verify-receipt` — shared between Frame and Rabbit Hole.

---

## ENVIRONMENT VARIABLES

| Variable | Purpose | Status |
|----------|---------|--------|
| `ANTHROPIC_API_KEY` | LLM calls | Set, funded |
| `ANTHROPIC_SURFACE_MODEL` | Rabbit Hole surface layer model | `claude-haiku-4-5-20251001` |
| `FRAME_PRIVATE_KEY` | Ed25519 private key, base64 PKCS#8 DER | Set |
| `FRAME_PUBLIC_KEY` | Ed25519 public key, base64 SPKI DER | Set |
| `FRAME_KEY_FORMAT` | Key encoding format | `base64` |
| `FEC_API_KEY` | OpenFEC API | Set (DEMO_KEY fallback) |
| `CONGRESS_API_KEY` | Congress.gov | Set |
| `COURTLISTENER_API_KEY` | CourtListener judicial opinions + citation lookup | Set |
| `GOVINFO_API_KEY` | GovInfo search (Congressional Record, FR, statutes) | Set |
| `ASSEMBLYAI_API_KEY` | Podcast/audio transcription | Needs verification |
| `SEC_EDGAR_USER_AGENT` | SEC policy requires contact email | Needs setting |
| `HIVE_API_KEY` | AI content detection | Not set, feature disabled |
| `META_AD_LIBRARY_TOKEN` | Meta ad library | Not set |

---

## FRAME — PRODUCT DETAIL

### What it produces

A **Frame Receipt** is a signed document containing:
- The claim or subject being investigated
- Sourced narrative sentences — findings, context, gaps, significance
- Primary source URLs (FEC, LDA, SEC EDGAR, CourtListener, IRS 990s, Wikidata)
- `unknowns` — operational (data not available) and epistemic (data exists but cannot establish intent)
- `content_hash` — SHA-256 of the JCS-canonical payload
- `signature` — Ed25519 signature over the hash
- `significance` — extracted top-level field, displayable without parsing the full narrative

### The Journalist Character — The Frame Record

Frame receipts are written by a defined AI journalist character. The character spec:

**Identity:** No employer. No advertiser. No career to protect. Writes only from what primary sources confirm.

**Audience:** Simultaneously — a first-generation American voter with a high school education, an AI summarizer, a policy analyst in Brussels, a journalist in Nairobi. All four receive the same truth from the same text.

**Voice rules:**
- One idea per sentence
- Every number gets a plain-language translation
- No idioms, no cultural references that don't translate
- Active voice always
- Name the institution, the person, the amount, the date — never "significant funds"
- When something is unknown, name the specific document that would contain it

**Output structure — every receipt:**
- **FINDINGS:** What the sources directly confirm. Specific figures, dates, parties, amounts.
- **CONTEXT:** What these figures mean relative to normal baselines or historical patterns.
- **GAPS:** What the sources cannot show. Specific named documents or databases.
- **SIGNIFICANCE:** The accountability question the data raises. Written so an editor could publish it directly.

**Hard constraints — cannot be overridden by any prompt:**
- Cannot soften a confirmed figure
- Cannot omit a detected gap
- Cannot imply causation the sources do not support
- Cannot use hedging language when data is clear
- Cannot use certain language when data is ambiguous — must name the ambiguity
- Layer C disclaimer is always inside the signed hash

**Model:** `claude-sonnet-4-20250514` for Frame narrative. Never Haiku for Frame.

### Three-Layer Receipt — the full architecture

The most important structural concept. Every deep receipt has three layers with different epistemic weight:

**Layer A — The Verified Record**
What primary sources directly confirm. Signed. No inference. Sources listed with retrieval timestamps.
- `lede` — one sentence, the single most important confirmed fact
- `findings` — numbers, dates, parties in plain language
- `gaps` — specific missing documents named
- `sources[]` — every claim anchored to a URL

**Layer B — The Historical Thread**
How we got here. Sourced from CourtListener, Caselaw Access Project, GovInfo, scholarly adapters. Every claim cites its source.
- `origins[]` — first documented instance of this pattern/law/entity
- `mutations[]` — how it changed, who changed it, when, under what justification
- `precedents[]` — prior instances with documented outcomes
- `sourcing_completeness` — `"full"` | `"partial"` | `"inferred"` | `"unavailable"`

Layer B being empty is honest behavior when primary legal sources aren't available. Do not fill it with inferred history.

**Layer C — Pattern Analysis**
Explicitly labeled inference. Never presented as fact.
- `analogues[]` — historical comparisons with documented outcomes
- `techniques[]` — named propaganda or influence techniques where documented
- `disclaimer` — **"The following analysis is documented pattern inference, not verified fact. The reader should weigh it accordingly. Primary sources for this analysis are listed below."** — this exact string, always, inside the hash
- `confidence` — `"documented"` | `"probable"` | `"speculative"`

The power of this structure: Layer C cannot be stripped without invalidating the signature. A downstream AI that summarizes this receipt cannot remove the caveat. It is cryptographically inseparable from the claim.

### Frame API Endpoints

```
POST /v1/generate-receipt          — FEC receipt by candidateId
POST /v1/generate-sec-receipt      — SEC EDGAR receipt by entity name
POST /v1/deep-receipt              — Three-layer receipt, any query
POST /v1/sec-edgar                 — SEC EDGAR probe
POST /v1/scholarly                 — Academic source search
POST /v1/courtlistener             — Judicial opinion search
POST /v1/govinfo                   — GovInfo legislative search (CREC / FR / STATUTE)
POST /v1/verify-receipt            — Verify any signed receipt
GET  /v1/status                   — Which env keys are set (values never exposed)
GET  /v1/receipts/report/{id}      — Report receipt stub (PostgreSQL pending)
```

### Frame Data Adapters (Python, `apps/api/adapters/`)

| Adapter | Source | What it gets |
|---------|--------|-------------|
| `fec.py` | OpenFEC API | Candidate profiles, fundraising totals by cycle |
| `sec_edgar.py` | SEC EDGAR EFTS + data.sec.gov | Entity search, Form 4 filings, company facts |
| `scholarly.py` | OpenAlex, Semantic Scholar, CrossRef | Open access academic papers, citation counts |
| `courtlistener.py` | CourtListener API v3 + v4 | Opinion search, dockets, **citation-lookup** for U.S. Reports cites, landmark pulls in deep-receipt |
| `govinfo.py` | GovInfo API | Congressional Record, Federal Register, statutes (Layer B) |

**SEC EDGAR known limitation:** Name search for politicians resolves poorly — EDGAR is company-centric. Fallback searches Form 4 filings to find entities a person filed as reporting owner. For politicians, FEC is the primary source; EDGAR is supplementary.

**Scholarly known limitation:** Niche local history topics return low-relevance results. Ring 3 quality gate (relevance scoring against query) is a known gap, not yet built.

---

## RABBIT HOLE — PRODUCT DETAIL

### What it produces

A forensic genealogy of a narrative — how a conspiracy theory, legend, myth, or promoted rumor originated, mutated, spread, and calcified into belief. Six depth layers. Five-ring extended report.

**Tagline:** *"There is enough O2 even miles down the Rabbit Hole."*

### Six Depth Layers

| Layer | Name | Status |
|-------|------|--------|
| 1 | Surface — What is this, who believes it, when did it emerge | Live, Anthropic API |
| 2 | Spread — How it traveled across platforms | Heuristic only, no real external data yet |
| 3 | Origin — Where it first appeared in documented record | Heuristic + scholarly adapters |
| 4 | Actor — Who is associated with its propagation | Ledger + dynamic lookup chain |
| 5 | Pattern — Which documented spread patterns it matches | 11 signed patterns |
| 6 | Comparative Jurisdiction — How other cultures/legal systems treat it | Not built — sealed floor |

Layer 6 displays as "International source adapters not yet built" in the UI. This is intentional honesty, not a placeholder.

### Five-Ring Extended Report

| Ring | Content |
|------|---------|
| 1 | Surface summary — what, who, when, cultural substrate |
| 2 | Spread analysis — platform velocity, amplification vectors |
| 3 | Origin sourcing — historical record, academic sources |
| 4 | Actor layer — ledger entries, dynamic lookup results |
| 5 | Pattern matches — signed pattern library matches with dispute log |

Ring 4 uses fast ledger-only path in `POST /v1/report`. Full external source stack available at `POST /v1/actor-layer` (slow, outbound HTTP).

### Actor Ledger

Seeded entries: `eric-knudsen`, `bloody-mary`, `bell-witch`, `resurrection-mary`, `roswell-incident`, `ancient-astronaut-theory`, `vlad-dracula`, `strigoi`, `osiris`, `mothman`, `spring-heeled-jack`, `kenneth-arnold`, `roswell-mac-brazel`, `betty-barney-hill`, `peter-plogojowitz`, `mercy-brown`, `quetzalcoatl`, `anansi`, `prometheus`, `medusa`, `kali`, `wendigo`, `black-eyed-children`, `scp-foundation`

Dynamic lookup chain for entities not in ledger: Internet Archive → Chronicling America (parallel) → Wikidata → Wikipedia (4000 char extract cap) → web inference. Relevance score ≥ 2 required. Max 3 dynamic candidates per narrative.

### Pattern Library (11 patterns, all signed)

1. `coordinated-lateral-spread-v1`
2. `astroturf-grassroots-v1`
3. `big-lie-repetition-v1`
4. `manufactured-grassroots-v1`
5. `appeal-to-ancient-wisdom-v1`
6. `regional-legend-mutation-v1`
7. `documented-witness-amplification-v1`
8. `retraction-amplification-v1`
9. `syncretism-pattern-v1`
10. `witness-chain-self-reference-v1`
11. `clinical-fiction-as-fact-v1`

### Rabbit Hole API Endpoints

```
GET  /v1/depth-map
POST /v1/surface
GET  /v1/surface/slenderman          — inoculation baseline, no key needed
POST /v1/spread
POST /v1/origin
POST /v1/actor-layer                 — full source stack, slow
POST /v1/pattern-match
GET  /v1/pattern-lib
POST /v1/dispute
GET  /v1/dispute/{pattern_id}
PATCH /v1/dispute/{id}               — NOT BUILT (RECEIVED → UNDER_REVIEW → RESOLVED)
GET  /v1/actor/{slug}
GET  /v1/actor/{slug}/events
POST /v1/actor/{slug}/events
POST /v1/report                      — five-ring report, signed
POST /v1/verify-receipt              — shared with Frame
```

### Rabbit Hole Source Adapters (TypeScript, `packages/adapters/src/sources/`)

| Adapter | Source | Coverage |
|---------|--------|----------|
| `internet-archive.ts` | Internet Archive full-text search | Folklore keywords, year filter |
| `chronicling-america.ts` | Library of Congress newspapers | 1770–1963 |
| `jstor.ts` | JSTOR open access | Often returns HTML, logged as not_found |
| `mysterious-universe.ts` | Paranormal RSS | Community signal |
| `anomalist.ts` | Paranormal RSS | Community signal |
| `cryptomundo.ts` | Paranormal RSS | Community signal |
| `coast-to-coast.ts` | Paranormal RSS | Community signal |
| `singular-fortean.ts` | Paranormal RSS | Community signal |
| `fortean-times.ts` | Paranormal RSS | Community signal |

**AssemblyAI:** Wired for podcast/YouTube transcription with speaker diarization. Confidence tiers from per-utterance scores. Falls back to Whisper if no key.

**Rabbit Nudges:** 🐇 inline links throughout UI. Absent = "No further verified sourcing available" — not silence. Absence is data.

---

## KNOWN GAPS — IN PRIORITY ORDER

### Infrastructure
- In-memory job store resets on redeploy — needs PostgreSQL (`DATABASE_URL` in `render.yaml`, code supports it, not yet provisioned)
- Layer 6 not built — international source adapters needed
- `PATCH /v1/dispute/{id}` not built

### Frame
- Rule Change Receipt not implemented — baselines captured, drift detection not wired
- Source URL verification — LLM occasionally suggests URLs that 404
- `POST /frames` dossier enrichment pipeline (ARQ + Redis) not tested in production
- Congressional voting record cross-reference with FEC not built
- SEC and LDA receipt narrative not yet upgraded to four-section Sonnet prompt (FEC is done, others pending)

### Research adapters — shipped (deep-receipt Layer B)
| Adapter | Source | Status |
|---------|--------|--------|
| `courtlistener.py` | CourtListener REST v3/v4 | **Live** — `judicial_opinions` (search), **`landmark_opinions`** (registry + **citation-lookup** for e.g. 558 U.S. 310, 424 U.S. 1), full opinion text cap; `POST /v1/courtlistener`. |
| `govinfo.py` | GovInfo search API | **Live** — targeted queries → `legislative_records` + `POST /v1/govinfo`; CREC results filtered client-side. |

### Research Adapters Not Yet Built
| Adapter | Source | Value |
|---------|--------|-------|
| Caselaw Access Project | 6.7M digitized cases | Deep legal history |
| USASpending.gov | Federal contracts and grants | Follow the money |
| OpenStates | State legislature APIs | Sub-federal accountability |
| OFAC sanctions list | Treasury | Sanctions verification |
| House/Senate financial disclosure | Separate from EDGAR | Better for politicians than EDGAR |
| CourtListener — Podcast Index | podcastindex.org | Audio narrative sourcing |

---

## WHAT GOOD LOOKS LIKE

A Frame deep receipt on "Citizens United" should eventually contain:

**Where it is today:** `POST /v1/deep-receipt` combines **landmark citation resolution** (CourtListener **v4 citation-lookup** for reporter cites such as **558 U.S. 310**, **424 U.S. 1**) with **search hits**, **GovInfo** legislative rows, and **scholarship**. On matching queries, Layer B can place **Buckley**, **Austin**, and **Citizens United** in chronological thread with **real opinion URLs** and **`source_type: "landmark_opinion"`**; `sourcing_completeness` may read **`"full"`** when the model and sources align. Stochastic ordering still varies by run; **GovInfo** CREC relevance is query-tuned, not perfect.

**Layer A:** FEC data showing who gave what to which PACs after 2010, with exact figures, exact dates, exact committee names. Gaps naming the specific Form 3 filings that would show individual contributor details.

**Layer B (north star):** The actual text of *Citizens United v. FEC* (558 U.S. 310) from CourtListener. *Buckley v. Valeo* (1976). *First National Bank of Boston v. Bellotti* (1978). The actual Congressional Record entries where legislators responded (GovInfo). Scholarly papers on campaign finance effects post-2010 with citation counts.

**Layer C:** Documented analogues — the 1886 Santa Clara County case that established corporate personhood (documented, not speculated). Named techniques from the propaganda research literature. Disclaimer inside the hash. Confidence level: documented or probable, with sources listed.

**Why this matters:** One precise accountability question a citizen, a judge, or a journalist could ask based only on what the record shows.

**Where to look next:** Two specific public records a citizen could pull themselves.

That is the product. Everything being built is in service of that output being possible for any query — not just Citizens United, but tens of thousands of queries we have not thought to include, for situations that have not happened yet.

---

## HOW THE DEVELOPER WHO BUILT THIS THINKS

- Builds in steps, not sessions
- Systems thinker — sees the whole architecture before the parts
- Wants direct pushback, not validation
- Scope expands fast — flag it when it happens
- The connective tissue between tools is real architecture, not vision
- Absence of evidence is itself evidence — this is baked into the product philosophy
- The signing infrastructure is not a feature. It is the point.

---

*This document should be updated at the end of every significant session. If you found this in a bottle, start with the health check, read Rabbit Hole context, then look at the known gaps list. Layer B is no longer empty for flagship legal-finance queries; next wins are voting records, lobbying depth, and cross-source linking named in known gaps.*
