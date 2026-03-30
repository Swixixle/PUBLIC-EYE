# PUBLIC EYE — Master Build Spec

Everything remaining **in build order**, seven sprints, with a test at the end of each. **Sequence matters:** later work assumes honest, source-grounded data in the chain.

---

## Principles (what to take vs defer)

**Take (core product ideas — map directly onto this codebase):**

- **Adversarial critic before signing** — a second model whose **only** job is to *attack* the receipt (unsupported claims, overconfidence, missed contradictions, speculative leaps). It does **not** rewrite the artifact; it produces structured critique attached to the receipt / UI.
- **Claim-level verification** — extract atomic claims; check each against **actual** source documents; badge **supported / disputed / not found** (and similar statuses). Makes “receipts, not verdicts” legible at the claim row.
- **Local news layer** — the story where a small paper in Indiana quietly reinforces position A while nobody else surfaces it. Surfaces **structural** blind spots, not just national chains.
- **Volatility as an epistemic guardrail** — do not present a clean, neutral “what is happening” when divergence is very high; show **contested narrative** framing and route readers to the split.

**Leave (explicitly not immediate):**

- A **“20–50 local outlets crawler”** at scale — **later sprint**. When local echo ships, start with a **small curated list** + light checks (RSS/sitemap/keyword), not a broad crawler milestone.
- **Blocking signing** on ungrounded or weakly grounded claims — **too aggressive for now**. **Flag** them in UI and in metadata; keep the signature as “this payload wasn’t altered,” separate from epistemic confidence.

**Architectural lesson from Sprint 1A:** coalition maps draw **structure** from `global_perspectives`, but alignment notes can only cite text that exists on the receipt. Today the **primary URL is usually the only article actually fetched**; other outlets are **inferred** from framing data. Honest “BBC said X” requires **BBC’s article** (or a snippet) in the receipt’s source catalog — that is **Sprint 1B.0** below, not more prompt tinkering alone.

**Do today:** **Sprint 1A** (kill “likely” / speculative coalition language) — smallest change, highest leverage; everything else builds on honest chain text.

**Sprint 2** (critic agent) is the capability external evaluators tend to care about: an adversarial pass that makes “receipts not verdicts” **technical**, not only philosophical.

**Sprint 3** (front page) is what turns the system from a tool into a **publication**. *(Much of this already exists in-repo — see “What exists” below; treat Sprint 3 as polish / tokens / motion parity with this spec where gaps remain.)*

---

## Repo alignment (read before copying SQL)

- `frame_receipts.id` is **`TEXT`**, not UUID. New tables should use  
  `receipt_id TEXT NOT NULL REFERENCES frame_receipts(id) ON DELETE CASCADE`.
- Coalition DELETE/regen endpoints should use `receipt_store` / existing DB helpers, not ad-hoc connection patterns.

---

## What exists and works right now

- `POST /v1/analyze-article` — fetches article, generates receipt with global perspectives
- `POST /v1/coalition-map` + `GET /v1/coalition-map/{id}` — async coalition map with divergence score, two anchor positions, outlet chains
- `GET /i/{receipt_id}` — server-rendered investigation page (light bg, dark fight cards, volatility pill, gap strip, collapsible chains, Reader/Reporter toggle)
- `GET /search` + `GET /v1/search` — conflict bundle search with FTS, facets, sidebar
- `GET /verify` — public verifier page
- `GET /` + `GET /v1/front-page` — newspaper-style front page (Sprint 3 largely implemented; refine per tokens/animations below)
- `POST /v1/media-axis` — accuracy scoring per outlet (stub, needs grounding)
- `GET /v1/outlet/{slug}` + `GET /v1/reporter/{slug}` — dossier stubs
- Ed25519 signing, JCS / schema versioning (see repo for current stack)
- PostgreSQL receipt store, `coalition_maps`, `media_axis` tables

---

## Sprint 1 — Ground everything in real sources (do this first)

### 1A. Fix coalition map “likely” language

**Problem:** Coalition alignment notes say “British broadcaster *likely* emphasizes…”  
That is hallucinated prediction, not a finding. Remove that class of language.

**File:** `apps/api/coalition_service.py`

Change the system prompt. Find the section describing `alignment_note` and replace with:

```
For each outlet in the chain, alignment_note must be ONE of:

A) If the outlet appears in the receipt's sources list:
   Write one sentence summarizing what they actually reported.
   Set story_url to their article URL.
   Set alignment_confidence to high or medium based on how directly
   their coverage supports the position.

B) If the outlet did NOT appear in the sources searched:
   Set alignment_note to: "Not found in sources searched for this receipt."
   Set story_url to "".
   Set alignment_confidence to "low".

Banned language: "likely", "probably", "would", "tends to", "typically",
"generally", "expected to", "consistent with their editorial line".
If you don't have evidence from the sources, say you don't have evidence.
```

Change the user message construction to include the full sources array (adapt field names to the article-analysis receipt: e.g. `sources_checked`, `article`, `claims_verified`, or a normalized `sources` list if you add one):

```python
sources_text = ""
if receipt.get("sources"):
    lines = []
    for s in receipt.get("sources", []):
        if isinstance(s, dict):
            outlet = s.get("outlet","") or s.get("publication","")
            title  = s.get("title","")
            url    = s.get("url","") or s.get("link","")
            date   = s.get("date","") or s.get("published_at","")
            lines.append(f"- {outlet}: '{title}' ({date}) {url}")
    sources_text = "Sources actually found for this story:\n" + "\n".join(lines)

user_msg = f"""Receipt narrative: {narrative}

Most irreconcilable pair: {most_irreconcilable}

Global perspectives:
{json.dumps(gp, indent=2)}

{sources_text}

Return coalition map JSON. Every alignment_note must be grounded in
the sources above or must state 'Not found in sources searched for this receipt.'
"""
```

**File:** `apps/api/investigation_page.py`

Update chain row rendering so “not found” notes and optional `story_url` links are visually distinct (use current font scale from the page):

```python
note = item.get("alignment_note", "")
not_found = "not found in sources" in note.lower()
story_url = item.get("story_url", "")

if not_found:
    note_color = "#5a5752"
    note_style = "font-style:italic"
    link_html = ""
elif story_url:
    note_color = "#9e9a93"
    note_style = ""
    link_html = f'<a href="{_e(story_url)}" target="_blank" rel="noopener" ...>Read coverage ↗</a>'
else:
    ...
```

**Coalition API:** Add `DELETE /v1/coalition-map/{receipt_id}` (or equivalent) so existing maps can be regenerated after prompt changes — implement via `receipt_store` / DB layer.

---

### 1B.0 Multi-source ingestion (`analyze-article`)

**Problem:** `global_perspectives` describes how ecosystems *frame* a topic; it is not a substitute for **retrieved article text** from each outlet. After Sprint 1A, many chain rows correctly say *Not found in sources searched for this receipt* because only the user-pasted article was ever loaded.

**Goal:** After extracting **article_topic**, **named_entities**, and claims from the primary article, **discover and fetch 3–5 additional URLs** (different domains / known outlets where possible), normalize them into a **`sources`** (or `supporting_articles`) array on the receipt, then run **global_perspectives** / coalition generation as today. Coalition `_sources_catalog_text` (and claim verification in 1B.1) can then ground *“Outlet Y reported Z”* in real excerpts.

**Where:** `apps/api/main.py` — `POST /v1/analyze-article` pipeline, after successful extract + before or after first signing pass (design choice: fetch **before** final signed payload so the stored receipt lists fetched URLs). Prefer a small dedicated module, e.g. `apps/api/source_expansion.py`, callable from `analyze-article`.

**Behavior (v1):**

1. **Query construction** — from `article_topic` + top `named_entities` (and optional geography hints), build 1–3 short search queries (no bloated keyword dumps).
2. **Discovery** — use an existing allowed mechanism (e.g. web search API, curated RSS/sitemap for major outlets, or site-restricted patterns). Must be **explicitly rate-limited** and **optional**: if keys missing or discovery fails, receipt still completes with primary article only (degraded mode).
3. **Fetch** — reuse `ArticleFetcher` / `fetch_article` (same as primary). **Dedupe by canonical URL**; exclude the primary URL; cap **3–5** additional articles; cap total extra **chars** or **tokens** to control latency and cost.
4. **Persist** — each item: `{ "publication"|"outlet", "title", "url", "fetched_summary"|excerpt, optional "published_date" }`. Merge into receipt field **`sources`** (list of dicts) so `_sources_catalog_text` in `coalition_service.py` picks them up without further prompt hacks.
5. **Honesty** — if a candidate URL fails fetch, **omit** it or store `{ "url", "error": "fetch_failed" }` (do not invent body text). Coalition model continues to use “not found” when no usable text.

**Non-goals (v1):** crawling 20–50 locals; paywall bypass; guaranteeing one article per coalition chain member.

**Acceptance:** For a typical geopolitical story, stored receipt has **`len(sources) >= 3`** including primary representation in catalog lines; coalition regen shows **at least one** additional outlet row with a non–not-found **alignment_note** + **story_url** when discovery returns a matching domain (exact count is data-dependent).

---

### 1B.1 Claim-level verification

**Problem:** The receipt summarizes “what we know,” but individual claims are not checked against the actual source documents.

**Policy:** **Never block signing** solely because some claims are `not_found` or disputed. Persist statuses and **surface badges** on the investigation page (and later search cards).

**New table:** `apps/api/db/migrations/009_claims.sql`  
Use **`receipt_id TEXT`** referencing `frame_receipts(id)`:

```sql
CREATE TABLE IF NOT EXISTS claims (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  receipt_id       TEXT NOT NULL REFERENCES frame_receipts(id) ON DELETE CASCADE,
  claim_text       TEXT NOT NULL,
  claim_type       TEXT NOT NULL,
  status           TEXT NOT NULL,
  supporting_quote TEXT,
  supporting_source TEXT,
  supporting_url   TEXT,
  confidence       REAL,
  generated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_claims_receipt ON claims(receipt_id);
```

**New file:** `apps/api/claim_verifier.py` — extract atomic claims, verify each against sources, async job pattern mirroring coalition-map.

**Endpoints (example):** `POST /v1/verify-claims`, `GET /v1/claims/{receipt_id}`.

**Investigation UI:** Badge rows in “what everyone agrees on” / disputed sections using statuses (`see spec snippets in original plan for _claim_badge`).

---

## Sprint 2 — Adversarial critic agent

**Problem:** One model generates the receipt; nothing systematically attacks it before seal.

**New file:** `apps/api/critic_agent.py` — second Claude call: **find problems only**; no rewrite.

Store critic output and score; **receipt remains signed**; integrity vs epistemic warning are separate (yellow / orange UI states as in original spec).

**New table:** `010_critic_reviews.sql` with `receipt_id TEXT NOT NULL REFERENCES frame_receipts(id)`.

**Endpoints:** `POST /v1/critic-review`, `GET /v1/critic-review/{receipt_id}`.

---

## Sprint 3 — Front page

**Goal:** Publication-grade masthead, lead story by divergence, secondary grid, analyze bar.

**Status:** `front_page.py`, `GET /v1/front-page`, `GET /` already land in-repo. Use this sprint to match **design tokens**, **motion** (CSS keyframes), and copy parity with the structure below.

Design tokens, fonts, hero layout, and motion — align with `docs/FRONT_PAGE_SPEC.md` and this section’s structure in any older draft you keep locally.

---

## Sprint 4 — Volatility as epistemic guardrail

**In `investigation_page.py`:**

- **`divergence_score >= 80`:** Replace neutral “what is happening” framing with **CONTESTED NARRATIVE**; border + explainer; promote “what everyone agrees on” when present.
- **`divergence_score <= 25`:** Short-circuit copy for chains; de-emphasize fight cards; keep verification visible.
- **Between:** current default layout.

---

## Sprint 5 — Local news layer (phased)

**Not immediate:** No milestone for crawling dozens of locals.

**Phase 1 (this sprint when scheduled):** `local_sources_service.py` + **small curated JSON** of regional outlets; on analyze-article, resolve geography hints, **light** RSS/sitemap/keyword checks; `local_echo` field on receipt; **LOCAL ECHO** section on investigation page.

**Phase 2 (later):** expand coverage count, smarter matching — still **curated-first**, not a blind 20–50 outlet crawler as a gate.

---

## Sprint 6 — Outlet and reporter dossiers (wire real data)

Stub endpoints exist. Priority sources: CourtListener, FEC, SEC EDGAR where relevant, OpenCorporates, then **clearly labeled** Claude synthesis for gaps.

---

## Sprint 7 — Search page improvements

- Autocomplete (`/v1/search/suggest`, debounced)
- Empty-state CTA → analyze / topic flow
- Volatility slider
- Claim conflict counts on cards when claim verification exists
- Optional: surface low critic scores (“high uncertainty”) in results

---

## Build order for Cursor

**Do in this sequence. Do not bundle unrelated sprints.**

1. **Sprint 1A** — coalition “likely” fix + sources in prompt + DELETE coalition map + investigation row UX  
2. **Sprint 1B.0** — multi-source ingestion on `analyze-article` (3–5 fetched URLs → `sources` for coalition + downstream)  
3. **Sprint 1B.1** — claims table + verifier + badges (**flag only**, no signing block)  
4. **Sprint 2** — critic agent + storage + UI badge states  
5. **Sprint 3** — front page polish (tokens, motion, gaps vs this doc)  
6. **Sprint 4** — volatility guardrail in `investigation_page.py`  
7. **Sprint 5** — local echo **phase 1** (curated + light checks)  
8. **Sprint 6** — dossier real data  
9. **Sprint 7** — search improvements  

**Between sprints:** deploy, run the sprint test, confirm, then start the next.

---

## What stays unchanged

- Signing pipeline semantics (integrity of the payload)  
- `receipt_store` patterns  
- Core `coalition_maps` shape (evolve via additive fields where needed)  
- Investigation page structure (**extend**, don’t gratuitously restructure)  
- Search API contract (`/v1/search` conflict bundles)  
- Verifier page purpose  

---

## Tests (run after each sprint)

### Sprint 1A

```bash
# Regenerate coalition map; ensure banned tokens absent from alignment_note
curl -X DELETE ".../v1/coalition-map/{receipt_id}"
curl -X POST ".../v1/coalition-map" -d '{"receipt_id":"..."}'
# ... wait for job ...
curl ".../v1/coalition-map/{receipt_id}" | python3 -c "
import sys,json
d=json.load(sys.stdin)
notes=[i.get('alignment_note','') for pos in ['position_a','position_b']
       for i in (d.get(pos) or {}).get('chain',[])]
bad=[n for n in notes if any(w in n.lower() for w in ['likely','probably','would','tends','typically','generally'])]
print('BAD NOTES:', bad if bad else 'None — PASS')
"
```

### Sprint 1B.0

```bash
# After analyze-article on a fresh URL, receipt JSON should list multiple sources
curl -s ".../r/{receipt_id}" | python3 -c "
import sys,json
r=json.load(sys.stdin)
src=r.get('sources') or []
print('sources_count:', len(src))
for s in src[:8]:
  if isinstance(s, dict):
    print(' -', (s.get('publication') or s.get('outlet') or '?'), (s.get('url') or '')[:72])
"
# Expect sources_count >= 3 when expansion is enabled and discovery succeeds
```

### Sprint 1B.1

```bash
curl ".../v1/claims/{receipt_id}" | python3 -m json.tool | head -40
```

### Sprint 2

```bash
curl ".../v1/critic-review/{receipt_id}" | python3 -m json.tool
```

### Sprint 3

```bash
open "https://your-host/"
# Lead story reflects high-divergence coalition from window; page is newspaper layout
```

---

*Derived from an external draft; merged with PUBLIC EYE repo constraints and the Take/Leave product rules above.*
