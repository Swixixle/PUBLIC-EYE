"""
Server-rendered PUBLIC EYE search — conflict bundles, not document lists.
"""

from __future__ import annotations

import html
from typing import Any

from front_page import vol_color


def _e(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


def _sel(on: bool) -> str:
    return " selected" if on else ""


def _placeholder_examples() -> str:
    examples = [
        "Iran strikes",
        "Tucker Carlson",
        "Pfizer clinical trials",
        "Ukraine Bakhmut",
        "Fed interest rates",
    ]
    return " · ".join(examples)


def _base_styles() -> str:
    return """
:root {
  --paper: #F7F4EF;
  --ink: #1a1a1a;
  --rule: rgba(26,26,26,0.2);
  --card: #FFFFFF;
  --fight-bg: #111111;
  --fight-text: #F7F4EF;
  --side: #F0EDE8;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body.sp-body {
  font-family: "IBM Plex Sans", -apple-system, sans-serif;
  background: var(--paper);
  color: var(--ink);
  min-height: 100vh;
  line-height: 1.6;
}
.sp-wrap { max-width: 1100px; margin: 0 auto; padding: 0 40px 64px; }
@media (max-width: 720px) { .sp-wrap { padding: 0 18px 48px; } }

.sp-hero {
  text-align: center;
  padding: 28px 0 20px;
  border-bottom: 1px solid var(--rule);
}
.sp-hero h1 {
  font-family: "Playfair Display", serif;
  font-size: clamp(26px, 4vw, 36px);
  font-weight: 700;
  letter-spacing: -0.02em;
}
.sp-hero p.meta {
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #555;
  margin-top: 8px;
}
.sp-query-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 22px;
  max-width: 720px;
  margin-left: auto;
  margin-right: auto;
}
.sp-query-wrap {
  flex: 1 1 280px;
  display: flex;
  border: 1px solid var(--ink);
  background: var(--card);
}
.sp-query-wrap span.mag {
  padding: 14px 12px 14px 16px;
  font-size: 18px;
  opacity: 0.45;
}
.sp-query-wrap input[type="search"] {
  flex: 1;
  border: none;
  font-size: 18px;
  padding: 14px 14px 14px 0;
  font-family: inherit;
  background: transparent;
  min-width: 0;
}
.sp-query-wrap input:focus { outline: none; }
.sp-go {
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 14px 22px;
  background: var(--ink);
  color: var(--paper);
  border: 1px solid var(--ink);
  cursor: pointer;
}
.sp-ex {
  font-size: 12px;
  color: #666;
  margin-top: 10px;
  max-width: 720px;
  margin-left: auto;
  margin-right: auto;
  line-height: 1.5;
}
.sp-layout {
  display: grid;
  grid-template-columns: 1fr 220px;
  gap: 32px;
  margin-top: 28px;
  align-items: start;
}
@media (max-width: 900px) {
  .sp-layout { grid-template-columns: 1fr; }
  .sp-side { display: none; }
}

.sp-filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  font-size: 12px;
  margin: 16px 0 8px;
  color: #444;
}
.sp-filter-bar select {
  font-family: inherit;
  font-size: 12px;
  padding: 6px 8px;
  border: 1px solid var(--rule);
  background: var(--card);
  border-radius: 2px;
}

.sp-card {
  background: var(--card);
  border: 1px solid var(--rule);
  padding: 22px 22px 20px;
  margin-bottom: 20px;
}
.sp-rule-between {
  height: 1px;
  background: rgba(26,26,26,0.2);
  margin: 8px 0 20px;
}

.sp-vol-row {
  display: flex;
 flex-wrap: wrap;
  align-items: flex-end;
  gap: 16px 28px;
  margin-bottom: 10px;
}
.sp-vol-num {
  font-family: "Playfair Display", serif;
  font-size: 32px;
  font-weight: 900;
  line-height: 1;
}
.sp-vol-slash { font-size: 15px; color: #666; margin: 0 4px; }
.sp-vol-copy {
  font-size: 15px;
  font-style: italic;
  color: #444;
  max-width: 260px;
}

.sp-hed {
  font-family: "Playfair Display", serif;
  font-size: 20px;
  font-weight: 700;
  line-height: 1.2;
  margin: 6px 0 4px;
}
.sp-meta {
  font-size: 13px;
  color: #555;
  margin-bottom: 14px;
}

.sp-fight {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 10px;
  align-items: center;
  background: var(--fight-bg);
  color: var(--fight-text);
  padding: 14px 16px;
  margin: 12px 0;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
@media (max-width: 640px) {
  .sp-fight { grid-template-columns: 1fr; text-align: center; }
}
.sp-pos-label { font-weight: 700; font-size: 16px; letter-spacing: 0.02em; text-transform: none; }
.sp-pos-sum { font-size: 14px; letter-spacing: 0.02em; text-transform: none; font-weight: 400; margin-top: 6px; line-height: 1.45; }
.sp-vs { opacity: 0.5; font-size: 12px; text-align: center; }

.sp-gap {
  font-size: 14px;
  color: #333;
  margin: 12px 0;
  line-height: 1.55;
}
.sp-gap strong { font-weight: 600; }

.sp-coal {
  font-size: 13px;
  color: #555;
  margin-bottom: 12px;
}

.sp-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-top: 8px;
}
.sp-actions a {
  display: inline-block;
  font-size: 12px;
  font-weight: 600;
  padding: 8px 14px;
  border: 1px solid var(--ink);
  color: var(--ink);
  text-decoration: none;
  background: var(--card);
}
.sp-actions a.primary { background: var(--ink); color: var(--paper); }
.sp-signed { font-size: 12px; color: #2e7d32; font-weight: 600; }

.sp-empty {
  max-width: 560px;
  margin: 36px auto;
  padding: 28px;
  border: 1px solid var(--rule);
  background: var(--card);
}
.sp-empty h2 { font-family: "Playfair Display", serif; font-size: 20px; margin-bottom: 12px; }
.sp-empty ul { margin: 12px 0 0 18px; font-size: 16px; color: #444; }
.sp-empty a { color: #0d47a1; }

.sp-side {
  background: var(--side);
  border: 1px solid var(--rule);
  padding: 16px;
  font-size: 12px;
  position: sticky;
  top: 20px;
}
.sp-side h3 {
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin: 14px 0 8px;
  color: #555;
}
.sp-side h3:first-child { margin-top: 0; }
.sp-facet-row { margin: 4px 0; color: #333; }

.sp-topnav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 16px 40px;
  border-bottom: 1px solid var(--rule);
  background: rgba(247,244,239,0.96);
}
.sp-topnav a.brand {
  font-family: "Playfair Display", serif;
  font-size: 17px;
  font-weight: 700;
  color: var(--ink);
  text-decoration: none;
  letter-spacing: 0.04em;
}
.sp-mini-search form { display: inline-flex; gap: 0; align-items: center; }
.sp-mini-search input {
  width: 160px;
  max-width: 42vw;
  padding: 6px 10px;
  font-size: 12px;
  border: 1px solid var(--rule);
  font-family: inherit;
}
.sp-mini-search button {
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border: 1px solid var(--ink);
  background: var(--ink);
  color: var(--paper);
  cursor: pointer;
}

.sp-url-row {
  max-width: 720px;
  margin: 28px auto 0;
  padding-top: 20px;
  border-top: 1px solid var(--rule);
  text-align: center;
  font-size: 13px;
  color: #555;
}
.sp-url-row form { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 10px; }
.sp-url-row input[type="url"] {
  flex: 1 1 240px;
  max-width: 440px;
  padding: 10px 12px;
  border: 1px solid var(--rule);
  font-family: inherit;
  font-size: 14px;
}
.sp-url-row button {
  padding: 10px 18px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border: 1px solid var(--ink);
  background: var(--card);
  cursor: pointer;
}
"""


def _facet_sidebar(facets: dict[str, Any]) -> str:
    if not facets:
        return ""
    bv = facets.get("by_volatility") or {}
    br = facets.get("by_region") or {}
    bo = facets.get("by_outlet_type") or {}
    lines = ['<aside class="sp-side">', "<h3>By volatility</h3>"]
    lines.append(
        f'<div class="sp-facet-row">High (61–100) — {int(bv.get("high", 0))}</div>'
    )
    lines.append(
        f'<div class="sp-facet-row">Moderate (26–60) — {int(bv.get("moderate", 0))}</div>'
    )
    lines.append(f'<div class="sp-facet-row">Low (0–25) — {int(bv.get("low", 0))}</div>')
    if br:
        lines.append("<h3>By region</h3>")
        for k, v in sorted(br.items(), key=lambda x: -x[1]):
            lines.append(
                f'<div class="sp-facet-row">{_e(k.replace("_", " ").title())} — {int(v)}</div>'
            )
    lines.append("<h3>By outlet type (chain links)</h3>")
    lines.append(f'<div class="sp-facet-row">State — {int(bo.get("state", 0))}</div>')
    lines.append(f'<div class="sp-facet-row">Private — {int(bo.get("private", 0))}</div>')
    lines.append(
        f'<div class="sp-facet-row">Public broadcaster — {int(bo.get("public_broadcaster", 0))}</div>'
    )
    lines.append("</aside>")
    return "\n".join(lines)


def _result_card(r: dict[str, Any]) -> str:
    vol = int(r.get("volatility") or 0)
    vc = vol_color(vol)
    hl = _e(r.get("headline"))
    meta_parts = [
        r.get("date"),
        f'{int(r.get("sources_searched") or 0)} sources',
        f'{int(r.get("articles_found") or 0)} articles found',
    ]
    meta = _e("  ·  ".join(str(p) for p in meta_parts if p))
    pa = _e(r.get("position_a_label") or "—")
    pb = _e(r.get("position_b_label") or "—")
    sa = _e(r.get("position_a_summary") or "")
    sb = _e(r.get("position_b_summary") or "")
    gap = _e(r.get("irreconcilable_gap") or "")
    rid = _e(r.get("receipt_id"))
    signed_b = (
        '<span class="sp-signed">Signed</span>'
        if r.get("signed")
        else '<span style="font-size:12px;color:#888">Unsigned</span>'
    )
    coal_line = (
        f'Coalition: {int(r.get("coalition_a_count") or 0)} outlets in '
        f'{int(r.get("coalition_a_countries") or 0)} countries  ↔  '
        f'{int(r.get("coalition_b_count") or 0)} outlets in '
        f'{int(r.get("coalition_b_countries") or 0)} countries'
    )
    if not r.get("has_coalition"):
        coal_line = "No coalition map yet — open investigation for receipt detail."
    return f"""
<div class="sp-card">
  <div class="sp-vol-row">
    <div><span style="font-size:12px;letter-spacing:0.12em;text-transform:uppercase;color:#666">Volatility</span>
      <div><span class="sp-vol-num" style="color:{_e(vc)}">{vol}</span><span class="sp-vol-slash">/100</span></div>
    </div>
    <div class="sp-vol-copy">{_e(r.get("vol_copy") or "")}</div>
  </div>
  <div class="sp-rule-between"></div>
  <h2 class="sp-hed"><a href="/i/{rid}" style="color:inherit;text-decoration:none">{hl}</a></h2>
  <p class="sp-meta">{meta}</p>
  <div class="sp-fight">
    <div><div class="sp-pos-label">{pa}</div>
      <div class="sp-pos-sum">{sa}</div></div>
    <div class="sp-vs">vs</div>
    <div><div class="sp-pos-label">{pb}</div>
      <div class="sp-pos-sum">{sb}</div></div>
  </div>
  <p class="sp-gap"><strong>GAP:</strong> {gap}</p>
  <p class="sp-coal">{_e(coal_line)}</p>
  <div class="sp-actions">
    <a class="primary" href="/i/{rid}">Open investigation →</a>
    {signed_b}
  </div>
</div>
"""


def render_search_page(
    query: str,
    data: dict[str, Any],
    *,
    date_range: str = "30d",
    sort: str = "volatility",
    volatility_min: str = "",
    volatility_max: str = "",
) -> str:
    """Server HTML: hero + optional results (data from run_search)."""
    q = query or ""
    results = data.get("results") or []
    total = int(data.get("total") or 0)
    facets = data.get("facets") or {}

    filter_bar = ""
    if q:
        filter_bar = f"""
<div class="sp-filter-bar">
  <span>Filters:</span>
  <form method="get" action="/search" style="display:inline-flex;flex-wrap:wrap;gap:8px;align-items:center">
    <input type="hidden" name="q" value="{_e(q)}" />
    <label>Date <select name="date_range" onchange="this.form.submit()">
      <option value="24h" {"selected" if date_range=="24h" else ""}>24h</option>
      <option value="7d" {"selected" if date_range=="7d" else ""}>7d</option>
      <option value="30d" {"selected" if date_range=="30d" else ""}>30d</option>
      <option value="90d" {"selected" if date_range=="90d" else ""}>90d</option>
    </select></label>
    <label>Sort <select name="sort" onchange="this.form.submit()">
      <option value="volatility" {"selected" if sort=="volatility" else ""}>Volatility</option>
      <option value="date" {"selected" if sort=="date" else ""}>Date</option>
    </select></label>
    <label>Vol min <input type="number" name="volatility_min" min="0" max="100" step="1"
      value="{_e(volatility_min)}" style="width:52px;font-size:12px;padding:4px 6px;border:1px solid rgba(26,26,26,0.2)" /></label>
    <label>Vol max <input type="number" name="volatility_max" min="0" max="100" step="1"
      value="{_e(volatility_max)}" style="width:52px;font-size:12px;padding:4px 6px;border:1px solid rgba(26,26,26,0.2)" /></label>
    <button type="submit" class="sp-go" style="padding:6px 14px;font-size:12px">Apply</button>
  </form>
</div>
"""

    body_main = ""
    if q and total == 0:
        body_main = f"""
<div class="sp-empty">
  <h2>No conflicts found for &ldquo;{_e(q)}&rdquo;</h2>
  <p style="font-size:16px;color:#444;margin-bottom:8px">This could mean:</p>
  <ul>
    <li>No articles on this topic have been analyzed yet</li>
    <li>The story exists but outlets mostly agree (low volatility)</li>
    <li>Try broader terms</li>
  </ul>
  <p style="margin-top:18px;font-size:16px">
    <a href="#analyze-url">Analyze a specific article on this topic →</a><br><br>
    <a href="/">Search recent investigations on the front page →</a>
  </p>
  <p style="margin-top:20px;padding-top:16px;border-top:1px solid rgba(26,26,26,0.12);font-size:14px;color:#555">
    We haven&rsquo;t analyzed this yet.
    <a href="/">Run a broader search from the front page</a> or paste a URL below.
  </p>
</div>
"""
    elif q and results:
        cards = "\n".join(_result_card(r) for r in results)
        body_main = f"""
{filter_bar}
<div class="sp-layout">
  <div class="sp-main">
    <p style="font-size:14px;color:#666;margin-bottom:12px">{int(total)} conflict bundle(s) · query: <strong>{_e(q)}</strong></p>
    {cards}
  </div>
  {_facet_sidebar(facets)}
</div>
"""
    elif q:
        body_main = filter_bar + '<p style="margin-top:16px">No result rows.</p>'

    analyze_section = """
<div class="sp-url-row" id="analyze-url">
  <p>Or analyze a specific URL:</p>
  <form id="sp-analyze-form">
    <input type="url" name="url" id="sp-analyze-url" placeholder="Paste article URL…" required autocomplete="off" />
    <button type="submit">Analyze →</button>
  </form>
  <p id="sp-analyze-err" style="color:#B71C1C;font-size:13px;margin-top:8px;display:none"></p>
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e("PUBLIC EYE — Search conflicts" + (f": {q}" if q else ""))}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=IBM+Plex+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
<style>{_base_styles()}</style>
</head>
<body class="sp-body">
<nav class="sp-topnav">
  <a class="brand" href="/">PUBLIC EYE</a>
  <div class="sp-mini-search">
    <form action="/search" method="get">
      <input type="search" name="q" placeholder="Search conflicts…" value="{_e(q)}" aria-label="Search conflicts" />
      <button type="submit">Go</button>
    </form>
  </div>
</nav>
<div class="sp-wrap">
  <header class="sp-hero">
    <h1>PUBLIC EYE search</h1>
    <p class="meta">Conflicts, not documents · LexisNexis shows pages; this shows fights</p>
    <div class="sp-query-row" style="justify-content:center">
      <form method="get" action="/search" style="display:flex;flex:1 1 100%;max-width:720px;gap:0;flex-wrap:nowrap">
        <div class="sp-query-wrap" style="flex:1;min-width:0">
        <span class="mag" aria-hidden="true">⌕</span>
        <input type="search" name="q" placeholder="Search a claim, story, actor, or topic…"
          value="{_e(q)}" autocomplete="off" aria-label="Main search" />
        </div>
        <button type="submit" class="sp-go" style="flex-shrink:0">Search →</button>
      </form>
    </div>
    <p class="sp-ex">e.g. {_e(_placeholder_examples())}</p>
  </header>

  {body_main}

  {analyze_section}
</div>
<script>
(function() {{
  document.getElementById('sp-analyze-form').onsubmit = function(ev) {{
    ev.preventDefault();
    var inp = document.getElementById('sp-analyze-url');
    var err = document.getElementById('sp-analyze-err');
    err.style.display = 'none';
    var url = (inp.value || '').trim();
    fetch('/v1/analyze-article', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ url: url }})
    }}).then(function(r) {{
      return r.json().then(function(j) {{ return {{ ok: r.ok, j: j }}; }});
    }}).then(function(x) {{
      if (!x.ok) {{
        err.textContent = (x.j && x.j.detail) ? String(x.j.detail) : 'Request failed';
        err.style.display = 'block';
        return;
      }}
      var id = x.j.receipt_id || x.j.report_id;
      if (id) window.location.href = '/i/' + id;
    }}).catch(function() {{
      err.textContent = 'Network error';
      err.style.display = 'block';
    }});
    return false;
  }};
}})();
</script>
</body>
</html>
"""


