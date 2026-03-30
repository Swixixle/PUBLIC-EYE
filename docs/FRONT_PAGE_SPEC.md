# PUBLIC EYE — Front Page Spec
# "A front page for contested facts"

## What this is

The PUBLIC EYE front page is a live editorial object.
It is not a list of recent analyses.
It is a newspaper whose lead story is always the most contested claim of the day.

Every element on the page answers one question:
"What is the world's most contested story right now, and who is fighting over it?"

---

## The product sentence

"PUBLIC EYE computes how volatile a story is, picks the two most irreconcilable
positions, shows you the anchor papers and their global coalitions, and lets you
verify every line via signed receipts."

Tagline: "A front page for contested facts."

---

## Page structure (top to bottom)

### 1. Masthead

```
PUBLIC EYE                                    [Reader] [Reporter]
A front page for contested facts.
Monday, March 30, 2026
```

- "PUBLIC EYE" in large serif (Playfair Display, 32px, bold)
- Tagline in small italic below, 13px
- Date in small caps, right-aligned
- Two mode buttons top right: [Reader] [Reporter]
  - Reader = default, clean view
  - Reporter = same page, reveals receipt links, source chains, dossier links
- Thin rule below the masthead, like a broadsheet header divider

### 2. Above the fold — THE LEAD STORY

This is the highest-divergence investigation from the last 24 hours.
If no new investigation exists, use the highest-divergence from the last 7 days.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VOLATILITY  87 / 100        Parallel realities.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  US STRIKES ON IRAN — WEEK FIVE

  [WESTERN PRESS]              [IRANIAN STATE]
  ┌──────────────────┐  vs  ┌──────────────────┐
  │ Nuclear deterrence│      │ Imperial resource │
  │ operation under  │      │ seizure under     │
  │ Article 51       │      │ military cover    │
  └──────────────────┘      └──────────────────┘

  THE GAP: One side treats the strikes as a reluctant
  response to a nuclear threat. The other treats the
  nuclear framing as cover for oil and regime change.
  These cannot both be the primary cause.

  [See full investigation →]   [Who's on each side ▾]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Layout details:
- VOLATILITY number: 48px, Playfair Display bold, colored by bucket
  (green 0-25, amber 26-60, red 61-100)
- Bucket copy ("Parallel realities.") in italic below, 14px
- Story headline: 28px, bold, serif, centered, all caps
- Two paper cards side by side with a thin "vs" between them
- Each card: outlet cluster name (e.g. "WESTERN PRESS") as label,
  one-paragraph position summary in the card body
- "THE GAP" in small caps, followed by the irreconcilable gap sentence
- Two CTAs: "See full investigation →" links to /i/{receipt_id}
  "Who's on each side ▾" expands the coalition chains inline

### 3. Today's edition — secondary stories

Below the lead, a grid of 3-4 more investigations from the last 48 hours.
Each card is a compressed version of the lead:

```
┌─────────────────────────────────────────────┐
│ VOLATILITY 66   Facts overlap, framing fights│
│                                              │
│ EPSTEIN FBI DOCUMENTS                        │
│                                              │
│ Institutional Transparency  vs  Manufactured │
│                                   Scandal    │
│                                              │
│ [Open] [Who's on each side]         Mar 30  │
└─────────────────────────────────────────────┘
```

Grid: 2 columns on desktop, 1 on mobile.
Each card links to /i/{receipt_id}.
Sorted by divergence_score descending.

### 4. The masthead rule for the edition

Below the secondary stories, a section divider:

```
━━━━━━━━━━━━━━  TODAY'S CONTESTED CLAIMS  ━━━━━━━━━━━━━━
```

This separates the "lead stories" (full coalition maps) from the
"contested claims" (individual stories that have been analyzed but
don't yet have full coalition maps — just divergence scores and
position summaries).

### 5. Analyze bar

At the bottom of every page:

```
┌─────────────────────────────────────────────────┐
│ Paste any article URL, podcast, or document...  │
│                              [Analyze] →        │
└─────────────────────────────────────────────────┘
```

Same behavior as current: POST to /v1/analyze-article,
redirect to /i/{receipt_id} with loading overlay.

---

## Two modes: Reader and Reporter

### Reader mode (default)

Shows:
- Volatility score and bucket copy
- Story headline
- Two anchor position cards
- Irreconcilable gap sentence
- "Who's on each side" collapsed (expand on click)
- What everyone agrees on
- What no one is really talking about
- Analyze bar

Hides:
- Receipt IDs
- Raw JSON links
- Dossier links
- Source chains with confidence ratings
- Verification section (accessible via "Receipt ↓" in header only)

### Reporter mode (toggle in header)

Reveals everything hidden in reader mode, plus:

```
REPORTER TOOLS
Receipt: 8449d4ca-9b30-4ef5-90e5-a9ada6635e91  [Copy] [Verify ↗] [Raw JSON ↗]
Signed: ✓ Ed25519  Schema: 1.0.0  Generated: 2026-03-30T08:28Z

Open in: [LexisNexis] [Google Pinpoint] [Bellingcat Toolkit]
(these are just deep-link templates to those tools with the story headline pre-filled)

Coalition map: [Full JSON ↗]  Divergence score method: [How is this calculated? ↗]
```

Each outlet in the coalition chain also expands to show:
- Link to the actual story they ran (if available)
- Accuracy score bar
- "Dossier →" link to /outlet/{slug}

Reporter mode persists in localStorage so journalists don't have to
toggle it every visit.

---

## Data sources for the front page

The front page is assembled from:

```python
# GET /v1/front-page
# Returns the data needed to render the front page

{
  "generated_at": "iso8601",
  "lead_story": {
    "receipt_id": "uuid",
    "headline": "string",        # from article.title or article_topic
    "volatility": 87,
    "vol_copy": "Parallel realities.",
    "position_a": {
      "label": "Western Press",
      "anchor_region": "western_anglophone",
      "summary": "one paragraph"
    },
    "position_b": {
      "label": "Iranian State",
      "anchor_region": "iranian_regional",
      "summary": "one paragraph"
    },
    "irreconcilable_gap": "string",
    "coalition_preview": {
      "a_count": 9,
      "b_count": 8,
      "a_countries": 6,
      "b_countries": 5
    }
  },
  "secondary_stories": [
    {
      "receipt_id": "uuid",
      "headline": "string",
      "volatility": 66,
      "vol_copy": "Facts overlap, framing fights.",
      "a_label": "Institutional Transparency",
      "b_label": "Manufactured Scandal",
      "date": "Mar 30"
    }
  ],
  "edition_date": "Monday, March 30, 2026"
}
```

### New endpoint to build

```
GET /v1/front-page
```

Logic:
1. Fetch receipts from last 7 days ordered by created_at DESC
2. For each receipt, check if coalition_map exists
3. Sort receipts that have coalition maps by divergence_score DESC
4. Lead story = highest divergence_score with coalition map
5. Secondary stories = next 3-4 with coalition maps
6. Return the assembled front-page payload

No new tables needed. Reads from existing frame_receipts and coalition_maps.

---

## Typography and visual style

### Fonts
- Headlines: Playfair Display (serif) — "IRAN STRIKES WEEK FIVE"
- Body / labels: IBM Plex Sans — readable, clean, slightly editorial
- Mono: IBM Plex Mono — receipt IDs, verification data (reporter mode only)
- Load from Google Fonts:
  `Playfair+Display:wght@400;700;900&family=IBM+Plex+Sans:wght@300;400;500`

### Color scheme

**Reader mode (primary):**
- Background: #F7F4EF (warm near-white, newsprint tone)
- Text: #1a1a1a (near-black ink)
- Accent: #1a1a1a with colored volatility numbers
- Volatility colors: #2e7d32 (green), #E65100 (amber/orange), #B71C1C (red)
  — use the FULL color, not a tinted version, for the volatility number
- Rules/dividers: #1a1a1a at 20% opacity
- Card backgrounds: #FFFFFF with 1px border #1a1a1a at 15% opacity

**The fight cards (always dark, regardless of mode):**
- Background: #111111
- Text: #F7F4EF
- This is the interruption — the fight inside the newspaper

**Reporter mode additions:**
- Verified badge background: #E8F5E9
- Receipt section background: #F5F5F5
- Mono text: #555

### Rules (broadsheet dividers)

Use horizontal rules to separate sections, like a broadsheet:
```css
.rule {
  border: none;
  border-top: 1px solid rgba(26,26,26,0.2);
  margin: 24px 0;
}
.rule-bold {
  border-top: 2px solid #1a1a1a;
  margin: 16px 0;
}
.rule-section {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 10px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: #1a1a1a;
  font-weight: 600;
}
.rule-section::before,
.rule-section::after {
  content: '';
  flex: 1;
  border-top: 1px solid rgba(26,26,26,0.3);
}
```

### Font sizes (larger than current)
- Volatility number: 52px, Playfair Display, weight 900
- Lead headline: 36px, Playfair Display, weight 700
- Secondary headline: 22px, Playfair Display, weight 700
- Position label: 11px, IBM Plex Sans, weight 600, letter-spacing 0.1em, uppercase
- Position summary: 14px, IBM Plex Sans, weight 400, line-height 1.7
- Gap sentence: 16px, IBM Plex Sans, weight 400, line-height 1.7
- Body: 15px, IBM Plex Sans, weight 400, line-height 1.7
- Labels/metadata: 11px, IBM Plex Sans, weight 500, uppercase, letter-spacing 0.1em

### Layout
- Max width: 900px, centered
- Padding: 0 48px on desktop, 0 20px on mobile
- Column gutter for two-up fight cards: 2px gap (thin rule between them)

---

## What to build in Cursor — in order

### Step 1: New endpoint GET /v1/front-page
In `apps/api/main.py` or a new `front_page_api.py`.
Reads from existing tables. No new tables.

### Step 2: New route GET / (landing page)
Replace the current React landing page route with a server-rendered
HTML page using the same pattern as investigation_page.py.

New file: `apps/api/front_page.py`
Function: `render_front_page(front_page_data: dict) -> str`

Wire in main.py:
```python
from front_page import render_front_page

@app.get("/", response_class=HTMLResponse)
async def front_page():
    data = await build_front_page_data()
    return HTMLResponse(render_front_page(data))
```

### Step 3: Update investigation_page.py
- Switch to light background (#F7F4EF)
- Fight cards stay dark (#111)
- Increase all font sizes per spec above
- Add Reader/Reporter mode toggle
- Reporter mode reveals receipt section and source links

### Step 4: Analyze bar on front page
Same component as current, styled to match the newspaper aesthetic.

---

## What NOT to build yet

- The actual LexisNexis / Pinpoint deep links (just placeholder buttons)
- The accuracy axis bars (next sprint after this)
- The outlet dossier pages (already stubbed, wire in reporter mode later)
- The meta-story feature
- Any authentication or user accounts

---

## Empty state

When there are no investigations with coalition maps:

```
━━━━━━━━━━━━━━  NO CONTESTED STORIES TODAY  ━━━━━━━━━━━━━━

The record is quiet. Paste a URL below to run the first
investigation of the day.
```

---

## The single most important thing

The front page must load fast and be readable by a non-technical person
in under 10 seconds without any explanation. If a civilian lands on it
and doesn't immediately understand "these two things are in conflict and
here's by how much" — the layout has failed.

Test it by showing it to someone who has never heard of PUBLIC EYE and
asking them: "What is this page telling you?" If they can answer in one
sentence, it's working.
