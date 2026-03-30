# PUBLIC EYE — Media Axis & Outlet Dossier System
# Cursor Implementation Spec

## What this builds

A computationally-derived accuracy axis for news coverage, plus clickable outlet
and reporter dossiers with financial ties, lawsuit history, and coverage patterns.

The axis is NOT political left/right. It is accuracy-anchored:
- The RIGHT side of the axis = higher factual grounding on this specific story
- The LEFT side = lower factual grounding
- Position is DERIVED from evidence, not editorially assigned
- An outlet's position on the axis changes per story

"Whoever is more truthful is closer to the right." The axis measures
proximity to the verifiable record, not political ideology.

This means Fox News might be on the right side on one story and the left
on another. RT might score higher than CNN on a specific claim if the
verifiable record supports their framing. The system has no political
opinion. It has a methodology.

---

## The accuracy score (how position is computed)

Each outlet gets a per-story accuracy score (0–100) based on:

### 1. Claim verifiability (40% weight)
For each factual claim the outlet makes about this story:
- Does a cross-corroborated source confirm it?
- Does the outlet cite primary sources (documents, official records)?
- Are named claims attributed to named, verifiable sources?

Score: (verified claims / total claims) × 40

### 2. Omission penalty (30% weight)
Cross-reference what the outlet covers against the full confirmed
facts from the receipt. What confirmed facts did this outlet not mention?
Significant omissions that change the meaning of the story reduce the score.

Score: (1 - (significant_omissions / total_confirmed_facts)) × 30

### 3. Correction/retraction history (15% weight)
From the outlet dossier: documented corrections and retractions on
stories of this type. Outlets with high retraction rates on similar
stories get a baseline penalty.

Score: baseline_accuracy_rating × 15

### 4. Source quality (15% weight)
Primary sources (documents, official records, named on-record sources)
score higher than anonymous sources, "sources say", or other outlets.

Score: (primary_source_citations / total_citations) × 15

### Final score
accuracy_score = sum of four components (0–100)
Position on axis = accuracy_score
Right side = high score. Left side = low score.

The axis label is not "left/right" in the UI. It is:
- Right anchor: "More grounded in the verifiable record"
- Left anchor: "More interpretive / less sourced"

---

## New endpoints to build

### POST /v1/media-axis
Takes a receipt_id. Returns the accuracy-axis positioning for all
outlets that covered this story.

Request:
```json
{ "receipt_id": "uuid" }
```

Response:
```json
{
  "receipt_id": "uuid",
  "axis_id": "maxis-{first8}",
  "generated_at": "iso8601",
  "signed": true,
  "axis": {
    "label_high": "More grounded in the verifiable record",
    "label_low": "More interpretive / less verified",
    "outlets": [
      {
        "outlet": "Reuters",
        "country": "GB",
        "flag": "🇬🇧",
        "outlet_type": "private",
        "accuracy_score": 84,
        "axis_position": 0.84,
        "components": {
          "claim_verifiability": 36,
          "omission_penalty": 28,
          "correction_history": 12,
          "source_quality": 8
        },
        "verified_claims": ["Iran struck UAE facility on March 28"],
        "unverified_claims": ["Iran planning second wave — unconfirmed"],
        "omissions": ["Civilian casualty count not mentioned"],
        "story_url": "https://reuters.com/...",
        "story_headline": "Iran strikes Gulf industrial sites",
        "story_date": "2026-03-30"
      }
    ]
  },
  "most_accurate": { "outlet": "Reuters", "score": 84 },
  "least_accurate": { "outlet": "RT", "score": 31 },
  "spread": 53,
  "note": "Spread measures distance between most and least accurate outlets. Higher spread = more contested factual landscape."
}
```

### GET /v1/media-axis/{receipt_id}
Returns stored axis. 404 if not generated yet.

### GET /v1/outlet/{outlet_slug}
Returns the outlet dossier.

outlet_slug = url-safe outlet name, e.g. "reuters", "fox-news", "rt"

Response:
```json
{
  "outlet": "Fox News",
  "slug": "fox-news",
  "outlet_type": "private",
  "country": "US",
  "flag": "🇺🇸",
  "parent_company": "Fox Corporation",
  "ownership_chain": [
    { "entity": "Fox Corporation", "type": "parent", "public": true, "ticker": "FOX" },
    { "entity": "Rupert Murdoch", "role": "founder/chairman emeritus", "stake_pct": 39 },
    { "entity": "Lachlan Murdoch", "role": "CEO" }
  ],
  "political_donations": [
    { "recipient": "...", "amount": 0, "year": 0, "source": "FEC" }
  ],
  "lawsuits": [
    {
      "case": "Dominion Voting Systems v. Fox News",
      "type": "defamation",
      "outcome": "settled — $787.5M",
      "year": 2023,
      "source": "CourtListener",
      "case_id": "..."
    }
  ],
  "corrections_on_record": 0,
  "notable_retractions": [],
  "coverage_bias_notes": "Documented by MediaBiasFactCheck, AllSides. Not used for scoring — scored per-story from primary evidence.",
  "recent_investigations": [],
  "dossier_generated_at": "iso8601",
  "signed": true,
  "sources_used": ["FEC", "CourtListener", "SEC", "OpenCorporates"]
}
```

### GET /v1/reporter/{reporter_slug}
Returns the reporter dossier.

Response:
```json
{
  "name": "Julie Brown",
  "slug": "julie-brown",
  "current_outlet": "Miami Herald",
  "outlet_history": [
    { "outlet": "Miami Herald", "years": "2008–present" }
  ],
  "beat": "investigative, sex trafficking, Epstein",
  "known_for": ["Epstein investigation", "Harvey Weinstein coverage"],
  "awards": ["Polk Award 2019"],
  "lawsuits_involving": [],
  "financial_disclosures": [],
  "notable_corrections": [],
  "coverage_pattern_notes": "",
  "byline_links": [],
  "dossier_generated_at": "iso8601",
  "signed": true
}
```

---

## New DB tables

```sql
-- apps/api/db/migrations/005_media_axis.sql
CREATE TABLE IF NOT EXISTS media_axis (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  receipt_id      UUID NOT NULL UNIQUE REFERENCES frame_receipts(id),
  axis_id         TEXT NOT NULL UNIQUE,
  payload         JSONB NOT NULL,
  signed          BOOLEAN DEFAULT FALSE,
  generated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_media_axis_receipt ON media_axis(receipt_id);

-- apps/api/db/migrations/006_outlet_dossiers.sql
CREATE TABLE IF NOT EXISTS outlet_dossiers (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug            TEXT NOT NULL UNIQUE,
  outlet_name     TEXT NOT NULL,
  payload         JSONB NOT NULL,
  signed          BOOLEAN DEFAULT FALSE,
  generated_at    TIMESTAMPTZ DEFAULT NOW(),
  last_updated    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_outlet_slug ON outlet_dossiers(slug);

-- apps/api/db/migrations/007_reporter_dossiers.sql
CREATE TABLE IF NOT EXISTS reporter_dossiers (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug            TEXT NOT NULL UNIQUE,
  name            TEXT NOT NULL,
  payload         JSONB NOT NULL,
  signed          BOOLEAN DEFAULT FALSE,
  generated_at    TIMESTAMPTZ DEFAULT NOW(),
  last_updated    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_reporter_slug ON reporter_dossiers(slug);
```

---

## New files to create

### apps/api/media_axis_service.py

```python
"""
Computes per-story accuracy axis positioning for outlets.
Called by media_axis_api.py.

The axis is accuracy-anchored, not politically assigned.
Higher score = more grounded in the verifiable record on this story.
"""
```

Functions to implement:
- `compute_outlet_accuracy(outlet_data, receipt_claims, confirmed_facts) -> dict`
- `build_media_axis(receipt, coalition) -> dict`
- `get_outlet_baseline(outlet_name) -> float` — pulls from dossier if exists, else 0.5

### apps/api/outlet_dossier_service.py

```python
"""
Builds and caches outlet dossiers.
Pulls from: FEC (political donations by executives), CourtListener (lawsuits),
SEC (if public company), OpenCorporates (ownership chain).
Falls back to Claude synthesis when primary sources return nothing.
"""
```

Functions:
- `build_outlet_dossier(outlet_name) -> dict`
- `get_or_build_outlet_dossier(slug) -> dict`
- `_fetch_fec_donations(entity_name) -> list`
- `_fetch_courtlistener_cases(entity_name) -> list`
- `_fetch_ownership_chain(outlet_name) -> list`

### apps/api/reporter_dossier_service.py

```python
"""
Builds reporter dossiers.
Pulls from: CourtListener (cases involving reporter),
FEC (personal donations if public), news archive search.
"""
```

Functions:
- `build_reporter_dossier(name) -> dict`
- `get_or_build_reporter_dossier(slug) -> dict`

### apps/api/media_axis_api.py

```python
"""
Router for media axis endpoints.
Mount in main.py: app.include_router(media_axis_router, prefix="/v1")
"""
from fastapi import APIRouter
router = APIRouter()

# POST /v1/media-axis
# GET  /v1/media-axis/{receipt_id}
# GET  /v1/outlet/{slug}
# GET  /v1/reporter/{slug}
```

---

## Investigation page changes (investigation_page.py)

### 1. Outlet chips are now clickable

Each outlet chip in the chain opens a drawer below it showing:
- Accuracy score on this story (colored bar)
- Link to the actual story they ran (if available)
- One-line dossier preview: "Private · US · Settled defamation suit 2023"
- "Full dossier →" link to `/outlet/{slug}`

Implementation: JavaScript accordion, no page reload.

```javascript
function toggleOutletDrawer(slug) {
  var el = document.getElementById('outlet-' + slug);
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
```

### 2. Accuracy axis strip

Add a new section between the coalition chains and "What everyone agrees on":

```
ACCURACY ON THIS STORY
[Reuters ████████████████░░ 84]  More grounded →
[AP News  ███████████████░░░ 78]
[BBC      █████████████░░░░░ 71]
[RT       ████░░░░░░░░░░░░░░ 31]  ← Less sourced
[Xinhua   █████░░░░░░░░░░░░░ 38]
```

Each bar is clickable — opens outlet drawer.

### 3. Regional outlet expansion

When a country flag is clicked in the chain, it expands to show
additional outlets from that country/region that covered the story,
with their accuracy scores. These come from the media_axis payload.

```javascript
function toggleRegion(country_code) {
  var el = document.getElementById('region-' + country_code);
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
```

---

## The meta-story feature

This is the "story about the news" — a receipt where the SUBJECT is
coverage patterns rather than the event being covered.

New endpoint: `POST /v1/meta-story`

Request:
```json
{
  "topic": "Coverage of Iran strikes March 2026",
  "receipt_ids": ["uuid1", "uuid2", "uuid3"],
  "time_range": { "start": "2026-02-28", "end": "2026-03-30" }
}
```

This endpoint:
1. Loads all provided receipts + their coalition maps + media axis data
2. Runs a synthesis: what patterns emerge across this body of coverage?
3. Identifies: which outlets consistently land on which side, which outlets
   shifted positions over time, which facts appeared in all receipts vs
   disappeared from coverage
4. Produces a signed receipt where the subject is the coverage itself

The meta-story receipt has all the same fields as a regular receipt
(narrative, confirmed, what_nobody_is_covering, global_perspectives)
but the `receipt_type` is `"meta_story"` and it includes an additional
field:

```json
"source_receipts": ["uuid1", "uuid2", "uuid3"],
"coverage_period": { "start": "...", "end": "..." },
"pattern_findings": [
  "RT and PressTV consistently omitted civilian casualty figures across all 3 receipts",
  "Western outlets shifted from 'defensive operation' to 'contested legality' framing between week 1 and week 3",
  "No outlet in any receipt covered the environmental impact of petrochemical facility strikes"
]
```

---

## System prompt for media axis Claude call

```
You are a media accuracy analyst for PUBLIC EYE.

You receive:
- A list of confirmed facts from a signed receipt (the verifiable record)
- Coverage data for multiple outlets on this story

For each outlet, score it 0-100 on accuracy using these components:
1. Claim verifiability (0-40): what fraction of their factual claims
   are confirmed by the receipt's cross-corroborated sources?
2. Omission penalty (0-30): what confirmed facts did they not mention
   that materially change the meaning of the story?
3. Source quality (0-15): did they cite primary sources (documents,
   named on-record sources) or secondary/anonymous ones?
4. Baseline (0-15): reserved for correction history — set to 10 if unknown.

Return ONLY valid JSON. No prose outside the JSON object.
The axis is accuracy-anchored, not political. An outlet scores high
by being close to the verifiable record. Score each outlet independently.
Do not penalize outlets for framing or opinion. Only penalize for
factual claims that contradict the confirmed record, or significant
omissions of confirmed facts.
```

---

## Build order for Cursor

Do these in order. Do not skip ahead.

1. **Migration files** — create 005, 006, 007 SQL files
2. **`media_axis_service.py`** — scoring logic only, no DB calls yet
3. **`outlet_dossier_service.py`** — stub that returns Claude-synthesized
   dossier when primary sources return nothing (real adapters come later)
4. **`reporter_dossier_service.py`** — same stub approach
5. **`media_axis_api.py`** — router with all 4 endpoints
6. **Wire into `main.py`**:
   - `from media_axis_api import router as media_axis_router`
   - `app.include_router(media_axis_router, prefix="/v1")`
   - `ensure_media_axis_table()` in startup
7. **`investigation_page.py`** — add clickable outlet drawers and
   accuracy bar strip AFTER the backend endpoints are confirmed working
8. **Meta-story endpoint** — last, after everything else is stable

---

## What NOT to build yet

- Don't build the full OpenCorporates ownership chain integration yet
  (stub it with Claude synthesis)
- Don't build the GDELT coverage pattern analysis yet
- Don't build the reporter financial disclosure pipeline yet
- Don't add the meta-story UI to the investigation page yet
- Don't change the coalition map schema

The goal of this sprint is:
- Outlets are clickable with accuracy scores
- Outlet dossier pages exist at /outlet/{slug}
- Media axis is generated async after coalition map
- The investigation page shows accuracy bars

Everything else is the next sprint.

---

## Do not touch

- coalition_api.py
- coalition_service.py
- The existing signing pipeline
- receipt_store.py (except adding ensure_* calls for new tables)
- verify-receipt endpoint
- investigation_page.py until step 7
