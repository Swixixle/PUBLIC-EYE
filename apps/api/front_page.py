"""
Server-rendered PUBLIC EYE front page — newspaper masthead + lead story.
Reader / Reporter modes (Reporter persists via localStorage in-page).
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any

from article_ingest import sanitize_title
from receipt_store import get_homepage_stats, list_recent_article_investigations


def _e(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


def _headline(rec: dict[str, Any]) -> str:
    art = rec.get("article") or {}
    url = ""
    if isinstance(art, dict):
        url = str(art.get("url") or "").strip()
    if isinstance(art, dict) and art.get("title"):
        return sanitize_title(str(art["title"]).strip(), url or "")
    for k in ("article_topic", "narrative", "query"):
        v = rec.get(k)
        if v:
            return sanitize_title(str(v).strip()[:240], url or "")
    return "Untitled"


def _vol_copy(score: Any) -> str:
    """Volatility label for search / UI (0–100 scale)."""
    if score is None:
        return ""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    if s >= 66:
        return "Parallel realities."
    if s >= 33:
        return "Contested."
    return "Calm."


def _unique_countries_from_position(pos: dict[str, Any] | None) -> int:
    if not isinstance(pos, dict):
        return 0
    countries: set[str] = set()
    for link in pos.get("chain") or []:
        if not isinstance(link, dict):
            continue
        c = str(link.get("country") or link.get("outlet_country") or "").strip().lower()
        if c:
            countries.add(c)
    for src in pos.get("anchor_outlets") or []:
        if isinstance(src, dict):
            c = str(src.get("country") or src.get("outlet_country") or "").strip().lower()
            if c:
                countries.add(c)
    return len(countries)


def _coalition_preview(coalition: dict[str, Any]) -> dict[str, int]:
    """Outlet and country counts for coalition cards (search + spec)."""
    if not coalition:
        return {"a_count": 0, "b_count": 0, "a_countries": 0, "b_countries": 0}
    a_count = int(coalition.get("position_a_outlet_count") or 0)
    b_count = int(coalition.get("position_b_outlet_count") or 0)
    pa = coalition.get("position_a")
    pb = coalition.get("position_b")
    if isinstance(pa, dict) and a_count == 0:
        a_count = len(pa.get("chain") or []) or len(pa.get("anchor_outlets") or [])
    if isinstance(pb, dict) and b_count == 0:
        b_count = len(pb.get("chain") or []) or len(pb.get("anchor_outlets") or [])
    a_count = max(a_count, len(coalition.get("position_a_sources") or []))
    b_count = max(b_count, len(coalition.get("position_b_sources") or []))
    a_countries = _unique_countries_from_position(pa if isinstance(pa, dict) else None)
    b_countries = _unique_countries_from_position(pb if isinstance(pb, dict) else None)
    for key, target in (
        ("position_a_country_count", "a"),
        ("position_b_country_count", "b"),
    ):
        raw = coalition.get(key)
        if raw is None:
            continue
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if target == "a" and a_countries == 0:
            a_countries = n
        elif target == "b" and b_countries == 0:
            b_countries = n
    return {
        "a_count": a_count,
        "b_count": b_count,
        "a_countries": a_countries,
        "b_countries": b_countries,
    }


def vol_color(vol: int) -> str:
    if vol <= 25:
        return "#2e7d32"
    if vol <= 60:
        return "#E65100"
    return "#B71C1C"


def _ts_aware(ts: Any) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _fmt_secondary_date(ts: Any) -> str:
    t = _ts_aware(ts)
    return f"{t.strftime('%b')} {t.day}, {t.year}"


def _row_volatility(r: dict[str, Any]) -> int | None:
    coal = r.get("coalition") or {}
    if isinstance(coal, dict) and coal.get("divergence_score") is not None:
        try:
            return max(0, min(100, int(coal["divergence_score"])))
        except (TypeError, ValueError):
            pass
    v = (r.get("receipt") or {}).get("volatility_score")
    if v is not None:
        try:
            return max(0, min(100, int(v)))
        except (TypeError, ValueError):
            pass
    return None


def _one_line_summary(rec: dict[str, Any], coal: dict[str, Any]) -> str:
    gap = str(coal.get("irreconcilable_gap") or "").strip()
    if gap:
        return gap[:220] + ("…" if len(gap) > 220 else "")
    narrative = str(rec.get("narrative") or "").strip()
    if narrative:
        return narrative[:220] + ("…" if len(narrative) > 220 else "")
    topic = str(rec.get("article_topic") or "").strip()
    if topic:
        return topic[:220] + ("…" if len(topic) > 220 else "")
    return ""


def _stats_bar_html(stats: dict[str, Any] | None) -> str:
    if not stats:
        return ""
    investigations = int(stats.get("investigations", 0))
    claims = int(stats.get("claims_traced", 0))
    signed = int(stats.get("receipts_signed", 0))
    if investigations == 0 and claims == 0:
        return ""

    def fmt(n: int) -> str:
        return f"{n:,}"

    return f"""
<div class="stats-bar" role="region" aria-label="Database activity">
    <div class="stat-item">
        <span class="stat-number">{fmt(investigations)}</span>
        <span class="stat-label">investigations</span>
    </div>
    <div class="stat-divider" aria-hidden="true">·</div>
    <div class="stat-item">
        <span class="stat-number">{fmt(claims)}</span>
        <span class="stat-label">claims traced</span>
    </div>
    <div class="stat-divider" aria-hidden="true">·</div>
    <div class="stat-item">
        <span class="stat-number">{fmt(signed)}</span>
        <span class="stat-label">signed receipts</span>
    </div>
</div>
"""


def build_front_page_payload() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    generated = now.isoformat()
    edition = now.strftime("%A, %B %d, %Y")

    stats = get_homepage_stats()

    try:
        rows = list_recent_article_investigations(limit=24)
    except Exception:
        rows = []

    if not rows:
        return {
            "generated_at": generated,
            "lead_story": None,
            "secondary_stories": [],
            "edition_date": edition,
            "empty": True,
            "stats": stats,
        }

    lead_row = rows[0]
    lead_rec = lead_row["receipt"]
    lead_coal = lead_row.get("coalition") or {}
    if not isinstance(lead_coal, dict):
        lead_coal = {}
    vol = _row_volatility(lead_row)

    lead_story = {
        "receipt_id": lead_row["receipt_id"],
        "headline": _headline(lead_rec),
        "volatility": vol,
        "summary": _one_line_summary(lead_rec, lead_coal),
    }

    secondary: list[dict[str, Any]] = []
    for r in rows[1:7]:
        if len(secondary) >= 6:
            break
        dv = _row_volatility(r)
        secondary.append(
            {
                "receipt_id": r["receipt_id"],
                "headline": _headline(r["receipt"]),
                "volatility": dv,
                "date": _fmt_secondary_date(r["created_at"]),
            },
        )

    return {
        "generated_at": generated,
        "lead_story": lead_story,
        "secondary_stories": secondary,
        "edition_date": edition,
        "empty": False,
        "stats": stats,
    }


def render_front_page(data: dict[str, Any]) -> str:
    lead = data.get("lead_story")
    secondaries = data.get("secondary_stories") or []
    empty = bool(data.get("empty") or lead is None)
    stats_bar_html = _stats_bar_html(data.get("stats"))

    featured_section = ""
    if lead and not empty:
        v_raw = lead.get("volatility")
        vol_row = ""
        if v_raw is not None:
            v = int(v_raw)
            vc = vol_color(v)
            vol_row = (
                f'<div class="fp-featured-vol-row">'
                f'<span class="fp-featured-vol-pill" style="border-color:{vc};color:{vc}">'
                f"{v} volatility</span></div>"
            )
        rid = _e(lead["receipt_id"])
        sum_line = _e(lead.get("summary") or "")
        featured_section = f"""
<section class="fp-featured" aria-label="Featured investigation">
  <hr class="rule-bold" />
  <div class="fp-featured-inner">
    {vol_row}
    <h2 class="fp-featured-hed">{_e(lead.get("headline") or "")}</h2>
    {f'<p class="fp-featured-sum">{sum_line}</p>' if sum_line else ''}
    <a class="fp-cta" href="/i/{rid}">Read investigation →</a>
  </div>
  <hr class="rule" />
</section>"""

    secondary_html = ""
    if secondaries:
        cards = []
        for s in secondaries:
            sid = _e(s.get("receipt_id"))
            vol_n = s.get("volatility")
            vol_block = ""
            if vol_n is not None:
                vn = int(vol_n)
                vc = vol_color(vn)
                vol_block = (
                    f'<div class="fp-sec-vol"><span style="color:{vc}">{vn}</span>'
                    f'<span class="fp-sec-vol-suffix"> / 100</span>'
                    f'<span class="fp-sec-vol-label">volatility</span></div>'
                )
            cards.append(
                f'<a class="fp-sec-card" href="/i/{sid}">'
                f"{vol_block}"
                f'<h3 class="fp-sec-hed">{_e(s.get("headline"))}</h3>'
                f'<div class="fp-sec-meta"><span>Open investigation</span><span>{_e(s.get("date"))}</span></div>'
                f"</a>"
            )
        secondary_html = (
            '<section class="fp-secondary"><h2 class="fp-rule-section"><span>Today\'s edition</span></h2>'
            f'<div class="fp-sec-grid">{"".join(cards)}</div></section>'
        )
    elif empty:
        secondary_html = (
            '<section class="fp-secondary fp-secondary-empty"><h2 class="fp-rule-section"><span>Today\'s edition</span></h2>'
            '<p class="fp-edition-empty">No investigations yet today.</p></section>'
        )

    fp_json = json.dumps(data, default=str).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PUBLIC EYE — Receipts, not verdicts</title>
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#111827">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="PUBLIC EYE">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=IBM+Plex+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">
<script>
  if ('serviceWorker' in navigator) {{
    navigator.serviceWorker.register('/sw.js');
  }}
</script>
<style>
:root {{
  --paper: #F7F4EF;
  --ink: #1a1a1a;
  --rule: rgba(26,26,26,0.2);
  --card: #FFFFFF;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body.fp-body {{
  font-family: "IBM Plex Sans", -apple-system, sans-serif;
  background: var(--paper);
  color: var(--ink);
  min-height: 100vh;
  line-height: 1.6;
}}
.fp-wrap {{ max-width: 900px; margin: 0 auto; padding: 0 48px 64px; }}
@media (max-width: 720px) {{ .fp-wrap {{ padding: 0 20px 48px; }} }}

.fp-hero-stack {{
  padding: 1.5rem 0 0.5rem;
  margin-bottom: 1.5rem;
  border-bottom: 3px double #1a1a1a;
}}

.masthead-top {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  max-width: 700px;
  margin: 0 auto 2.5rem;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #999;
  gap: 10px;
  flex-wrap: wrap;
}}

.fp-mode-masthead {{
  margin-left: auto;
  display: inline-flex;
  gap: 4px;
}}
.fp-mode-masthead button {{
  font-family: "IBM Plex Sans", sans-serif;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 6px 12px;
  border: 1px solid var(--rule);
  background: var(--card);
  cursor: pointer;
  border-radius: 2px;
}}
.fp-mode-masthead button.active {{
  background: var(--ink);
  color: var(--paper);
  border-color: var(--ink);
}}

.eye-hint {{
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #aaaaaa;
  margin: 0 0 0.75rem;
  text-align: center;
  transition: opacity 0.3s ease;
}}
.eye-group:hover .eye-hint {{
  opacity: 0;
}}

.eye-group {{
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  max-width: 420px;
  margin: 0 auto;
}}

.eye-container {{
  width: 380px;
  height: 180px;
  cursor: pointer;
  position: relative;
}}

.eye-svg-main {{
  width: 100%;
  height: 100%;
  overflow: visible;
  display: block;
}}

.eye-closed-arc {{
  fill: none;
  stroke: #111111;
  stroke-width: 3;
  stroke-linecap: round;
  transition: opacity 0.3s ease;
}}

.eye-lash-main {{
  stroke: #111111;
  stroke-width: 2;
  stroke-linecap: round;
  transition: opacity 0.2s ease;
}}

.eye-open-shape {{
  fill: var(--paper);
  stroke: #111111;
  stroke-width: 3;
  opacity: 0;
  transition: opacity 0.3s ease 0.05s;
}}

.eye-sclera {{
  fill: #fbfaf7;
  opacity: 0;
  transition: opacity 0.28s ease 0.06s;
}}

.eye-iris-fill {{
  opacity: 0;
  transition: opacity 0.25s ease 0.12s;
}}

.eye-limbal {{
  opacity: 0;
  transition: opacity 0.25s ease 0.14s;
}}

.eye-pupil-main {{
  fill: #0a0a0a;
  opacity: 0;
  transition: opacity 0.25s ease 0.18s;
}}

.eye-shine-main {{
  fill: #ffffff;
  opacity: 0;
  transition: opacity 0.2s ease 0.22s;
}}

.eye-twinkle-main {{
  fill: #111111;
  opacity: 0;
  transform-origin: 310px 45px;
  transition: opacity 0.15s ease 0.3s;
}}

.eye-group:hover .eye-twinkle-main {{
  opacity: 1;
  animation: fp-twinkle-pop 0.5s ease 0.3s forwards;
}}

.eye-group.eye-typing .eye-twinkle-main {{
  opacity: 1;
  animation: fp-twinkle-pop 0.5s ease 0.3s forwards;
}}

@keyframes fp-twinkle-pop {{
  0%   {{ opacity: 0; transform: scale(0) rotate(0deg); }}
  60%  {{ opacity: 1; transform: scale(1.3) rotate(15deg); }}
  100% {{ opacity: 1; transform: scale(1) rotate(0deg); }}
}}

.eye-group:hover .eye-closed-arc,
.eye-group:hover .eye-lash-main,
.eye-group.eye-typing .eye-closed-arc,
.eye-group.eye-typing .eye-lash-main {{
  opacity: 0;
}}

.eye-group:hover .eye-open-shape,
.eye-group:hover .eye-sclera,
.eye-group:hover .eye-iris-fill,
.eye-group:hover .eye-limbal,
.eye-group:hover .eye-pupil-main,
.eye-group:hover .eye-shine-main,
.eye-group.eye-typing .eye-open-shape,
.eye-group.eye-typing .eye-sclera,
.eye-group.eye-typing .eye-iris-fill,
.eye-group.eye-typing .eye-limbal,
.eye-group.eye-typing .eye-pupil-main,
.eye-group.eye-typing .eye-shine-main {{
  opacity: 1;
}}

.eye-group:hover .eye-shine-main,
.eye-group.eye-typing .eye-shine-main {{
  opacity: 0.92;
}}

.eye-group:hover .search-reveal {{
  opacity: 1;
  transform: translateY(0);
  pointer-events: all;
}}

.eye-group.eye-typing .search-reveal {{
  opacity: 1;
  pointer-events: auto;
}}

.search-reveal {{
  width: 380px;
  margin-top: 1.8rem;
  opacity: 0;
  transform: translateY(-8px);
  pointer-events: none;
  transition: opacity 0.25s ease 0.15s, transform 0.25s ease 0.15s;
  display: flex;
  border: 1px solid #000000;
  background: var(--paper);
  border-radius: 2px;
  overflow: hidden;
}}

.fp-search-input {{
  flex: 1;
  border: none;
  padding: 10px 14px;
  font-size: 12px;
  background: var(--paper);
  color: #1a1a1a;
  outline: none;
  font-family: inherit;
  letter-spacing: 0.02em;
}}

.fp-search-input::placeholder {{
  color: #aaa;
  font-size: 11px;
  letter-spacing: 0.04em;
}}

.fp-search-btn {{
  background: #1a1a1a;
  color: #ffffff;
  border: none;
  padding: 10px 18px;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  cursor: pointer;
  font-family: inherit;
  font-weight: 500;
  flex-shrink: 0;
}}

.fp-search-btn:hover {{
  background: #333;
}}

.fp-title-block {{
  text-align: center;
  margin-top: 2rem;
}}

.fp-title {{
  font-family: "Playfair Display", serif;
  font-size: clamp(2.5rem, 8vw, 4.5rem);
  font-weight: 900;
  letter-spacing: -0.02em;
  color: #000000 !important;
  line-height: 1;
  margin: 0;
  -webkit-font-smoothing: antialiased;
}}

.fp-title-rule {{
  width: 60px;
  height: 1.5px;
  background: #000000;
  margin: 1rem auto;
}}

.fp-title-sub {{
  font-size: 11px;
  color: #333333;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin: 0;
}}

@media (prefers-color-scheme: dark) {{
  .eye-closed-arc, .eye-lash-main {{ stroke: #e0e0e0; }}
  .eye-open-shape {{ fill: #1e1e1e; stroke: #e0e0e0; }}
  .eye-sclera {{ fill: #e8e4dc; }}
  .eye-pupil-main {{ fill: #050505; }}
  .eye-shine-main {{ fill: #f5f5f5; }}
  .search-reveal {{ border-color: #e0e0e0; background: #1a1a1a; }}
  .fp-search-input {{ background: #1a1a1a; color: #e0e0e0; }}
  .fp-search-input::placeholder {{ color: #666; }}
  .fp-search-btn {{ background: #e0e0e0; color: #1a1a1a; }}
  .fp-search-btn:hover {{ background: #ccc; }}
  .fp-title {{ color: #e0e0e0 !important; }}
  .fp-title-rule {{ background: #e0e0e0; }}
  .masthead-top {{ color: #666; }}
  .fp-title-sub {{ color: #888; }}
}}

@media (max-width: 480px) {{
  .eye-container {{ width: 280px; height: 133px; }}
  .search-reveal {{ width: 280px; }}
}}

.rule {{ border: none; border-top: 1px solid var(--rule); margin: 24px 0; }}
.rule-bold {{ border: none; border-top: 2px solid var(--ink); margin: 16px 0; opacity: 0.85; }}

.fp-featured-inner {{ max-width: 640px; margin: 0 auto; text-align: center; padding: 8px 0 12px; }}
.fp-featured-vol-row {{ margin-bottom: 12px; }}
.fp-featured-vol-pill {{
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 6px 12px;
  border: 2px solid;
  border-radius: 999px;
  background: var(--card);
}}
.fp-featured-hed {{
  font-family: "Playfair Display", serif;
  font-size: clamp(1.35rem, 3.5vw, 1.85rem);
  font-weight: 700;
  line-height: 1.2;
  margin: 0 0 12px;
}}
.fp-featured-sum {{ font-size: 15px; color: #444; line-height: 1.65; margin-bottom: 16px; }}
.fp-cta {{
  font-weight: 600;
  color: var(--ink);
  text-decoration: underline;
  text-underline-offset: 3px;
}}

.fp-rule-section {{
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 10px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  font-weight: 600;
  margin: 32px 0 20px;
}}
.fp-rule-section::before,
.fp-rule-section::after {{
  content: "";
  flex: 1;
  border-top: 1px solid rgba(26,26,26,0.3);
}}

.stats-bar {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    padding: 1rem 0 0.5rem;
    margin-bottom: 2rem;
    border-top: 1px solid #e0ddd6;
    border-bottom: 1px solid #e0ddd6;
}}

.stat-item {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
}}

.stat-number {{
    font-size: 1.4rem;
    font-weight: 700;
    color: #1a1a1a;
    letter-spacing: -0.02em;
    line-height: 1;
}}

.stat-label {{
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #999;
}}

.stat-divider {{
    color: #ccc;
    font-size: 1.2rem;
    line-height: 1;
}}

@media (prefers-color-scheme: dark) {{
    .stats-bar {{ border-color: #333; }}
    .stat-number {{ color: #e0e0e0; }}
    .stat-label {{ color: #888; }}
}}

@media (max-width: 480px) {{
    .stat-number {{ font-size: 1.1rem; }}
    .stat-label {{ font-size: 0.6rem; }}
}}

.fp-secondary {{ margin-bottom: 24px; }}
.fp-edition-empty {{ font-size: 15px; color: #555; margin-top: 8px; }}
.fp-sec-grid {{
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}}
@media (max-width: 640px) {{ .fp-sec-grid {{ grid-template-columns: 1fr; }} }}
.fp-sec-card {{
  display: block;
  background: var(--card);
  border: 1px solid rgba(26,26,26,0.15);
  border-radius: 4px;
  padding: 18px;
  text-decoration: none;
  color: inherit;
  transition: box-shadow 0.15s;
}}
.fp-sec-card:hover {{ box-shadow: 0 4px 20px rgba(0,0,0,0.06); }}
.fp-sec-vol {{ font-family: "Playfair Display", serif; font-size: 22px; font-weight: 700; }}
.fp-sec-vol-suffix {{ font-size: 16px; font-weight: 500; color: #666; }}
.fp-sec-vol-label {{
  display: block;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  font-weight: 600;
  color: #666;
  margin-top: 4px;
  font-family: "IBM Plex Sans", sans-serif;
}}
.fp-sec-hed {{ font-family: "Playfair Display", serif; font-size: 22px; font-weight: 700; margin: 12px 0; line-height: 1.25; }}
.fp-sec-meta {{ display: flex; justify-content: space-between; margin-top: 14px; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; color: #666; }}

.tool-links {{
  border-top: 1px solid #eee;
  padding: 1.5rem 0;
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  align-items: center;
  font-size: 0.8em;
}}
.tool-links-label {{ color: #999; text-transform: uppercase; letter-spacing: 0.05em; width: 100%; }}
@media (min-width: 640px) {{ .tool-links-label {{ width: auto; }} }}
.tool-links a {{ color: #555; text-decoration: none; border-bottom: 1px solid #ddd; }}
.tool-links a:hover {{ color: #1a1a1a; border-bottom-color: #1a1a1a; }}

.footer-rule {{ margin-top: 12px; padding-top: 16px; border-top: 1px solid var(--rule); font-size: 12px; color: #666; }}

body.fp-reporter-mode .reporter-only {{ display: block !important; }}
body.fp-reporter-mode .reader-focus {{ display: none !important; }}
.reporter-only {{ display: none; }}
</style>
</head>
<body class="fp-body">
<div class="fp-wrap">

<section class="fp-hero-stack" aria-label="Home hero">
  <div class="masthead-top">
    <span id="today-date"></span>
    <span>Receipts, not verdicts.</span>
    <div class="fp-mode fp-mode-masthead">
      <button type="button" id="fp-mode-reader" class="active">Reader</button>
      <button type="button" id="fp-mode-reporter">Reporter</button>
    </div>
  </div>

  <div class="eye-group">
    <p class="eye-hint">hover to investigate</p>
    <div class="eye-container" id="main-eye">
      <svg class="eye-svg-main" viewBox="0 0 380 180" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <defs>
          <clipPath id="fp-eye-opening">
            <path d="M10 90 Q95 10 190 10 Q285 10 370 90 Q285 170 190 170 Q95 170 10 90 Z"/>
          </clipPath>
          <radialGradient id="fp-iris-radial" cx="34%" cy="30%" r="69%" fx="28%" fy="24%">
            <stop offset="0%" stop-color="#c5f0e0"/>
            <stop offset="38%" stop-color="#3fa078"/>
            <stop offset="72%" stop-color="#1a5a42"/>
            <stop offset="100%" stop-color="#071a14"/>
          </radialGradient>
        </defs>
        <path class="eye-closed-arc" d="M10 90 Q95 20 190 20 Q285 20 370 90"/>
        <line class="eye-lash-main" x1="190" y1="20" x2="190" y2="4"/>
        <line class="eye-lash-main" x1="140" y1="30" x2="132" y2="15"/>
        <line class="eye-lash-main" x1="240" y1="30" x2="248" y2="15"/>
        <line class="eye-lash-main" x1="100" y1="52" x2="88" y2="40"/>
        <line class="eye-lash-main" x1="280" y1="52" x2="292" y2="40"/>
        <path class="eye-open-shape" d="M10 90 Q95 10 190 10 Q285 10 370 90 Q285 170 190 170 Q95 170 10 90 Z"/>
        <g clip-path="url(#fp-eye-opening)">
          <ellipse class="eye-sclera" cx="190" cy="90" rx="128" ry="62"/>
          <circle class="eye-iris-fill" cx="190" cy="90" r="50" fill="url(#fp-iris-radial)"/>
          <circle class="eye-limbal" cx="190" cy="90" r="50" fill="none" stroke="#020a08" stroke-width="1.35" stroke-opacity="0.55"/>
          <circle id="main-pupil" class="eye-pupil-main" cx="187" cy="86" r="16"/>
          <ellipse id="main-shine" class="eye-shine-main" cx="181" cy="80" rx="5.2" ry="3.6"/>
        </g>
        <path class="eye-twinkle-main" d="M 310 45 l3 7 l7 3 l-7 3 l-3 7 l-3-7 l-7-3 l7-3 z"/>
      </svg>
    </div>

    <div class="search-reveal">
      <input
        class="fp-search-input"
        type="text"
        id="fp-query"
        placeholder="Paste a URL here..."
        autocomplete="off"
        aria-label="Article URL, name, or topic"
      />
      <button type="button" class="fp-search-btn" onclick="fpSubmit()">INVESTIGATE</button>
    </div>
  </div>

  <div class="fp-title-block">
    <h1 class="fp-title">PUBLIC EYE</h1>
    <div class="fp-title-rule"></div>
    <p class="fp-title-sub">A front page for contested facts</p>
  </div>
</section>

{stats_bar_html}
{featured_section}
{secondary_html}

<div class="tool-links" aria-label="External research tools">
  <span class="tool-links-label">Verify further with:</span>
  <a href="https://www.courtlistener.com/" target="_blank" rel="noopener">CourtListener</a>
  <a href="https://www.opensecrets.org/" target="_blank" rel="noopener">OpenSecrets</a>
  <a href="https://www.propublica.org/datastore/" target="_blank" rel="noopener">ProPublica Data</a>
  <a href="https://www.documentcloud.org/" target="_blank" rel="noopener">DocumentCloud</a>
  <a href="https://www.bellingcat.com/" target="_blank" rel="noopener">Bellingcat</a>
  <a href="https://web.archive.org/" target="_blank" rel="noopener">Internet Archive</a>
  <a href="https://www.fec.gov/data/" target="_blank" rel="noopener">FEC Data</a>
</div>

<footer class="footer-rule">
  <a href="/health">System status</a> · <a href="/verify">Verify</a> · <a href="/pitch">System brief</a>
</footer>
</div>

<script id="fp-data" type="application/json">{fp_json}</script>
<script>
function fpSubmit() {{
  var query = document.getElementById('fp-query');
  var q = query ? query.value.trim() : '';
  if (!q) return;
  if (q.startsWith('http://') || q.startsWith('https://')) {{
    window.location.href = '/analyze?url=' + encodeURIComponent(q);
  }} else {{
    window.open('https://news.google.com/search?q=' + encodeURIComponent(q), '_blank');
  }}
}}

document.addEventListener('DOMContentLoaded', function() {{
  var input = document.getElementById('fp-query');
  var eyeGroup = document.querySelector('.eye-group');

  // --- Eye stays open while typing ---
  if (input && eyeGroup) {{
    input.addEventListener('input', function() {{
      eyeGroup.classList.toggle('eye-typing', input.value.length > 0);
    }});
    input.addEventListener('focus', function() {{
      eyeGroup.classList.add('eye-typing');
    }});
    input.addEventListener('blur', function() {{
      if (!input.value.length) eyeGroup.classList.remove('eye-typing');
    }});
    input.addEventListener('keydown', function(e) {{
      if (e.key === 'Enter') fpSubmit();
    }});
  }}

  // --- Main eye pupil tracks the cursor ---
  // Iris center (190,90) r=50; pupil r=16; max radial offset 34. Corneal highlight follows pupil (upper-left).
  var eyeSvg = document.querySelector('.eye-svg-main');
  var pupil  = document.getElementById('main-pupil');
  var shine  = document.getElementById('main-shine');
  var IRIS_R = 50, PUPIL_R = 16, MAX_TRAVEL = IRIS_R - PUPIL_R;
  var SHINE_OFFSET_X = -5, SHINE_OFFSET_Y = -6;
  var CX = 190, CY = 90;
  var REST_PUPIL_X = 187, REST_PUPIL_Y = 86;

  function movePupil(svgX, svgY) {{
    var dx = svgX - CX;
    var dy = svgY - CY;
    var dist = Math.sqrt(dx * dx + dy * dy);
    var travel = Math.min(dist / 3, MAX_TRAVEL);
    var angle = Math.atan2(dy, dx);
    var nx = CX + Math.cos(angle) * travel;
    var ny = CY + Math.sin(angle) * travel;
    pupil.setAttribute('cx', nx.toFixed(2));
    pupil.setAttribute('cy', ny.toFixed(2));
    shine.setAttribute('cx', (nx + SHINE_OFFSET_X).toFixed(2));
    shine.setAttribute('cy', (ny + SHINE_OFFSET_Y).toFixed(2));
  }}

  function screenToSvg(svgEl, clientX, clientY) {{
    var rect = svgEl.getBoundingClientRect();
    var scaleX = 380 / rect.width;
    var scaleY = 180 / rect.height;
    return {{
      x: (clientX - rect.left) * scaleX,
      y: (clientY - rect.top) * scaleY
    }};
  }}

  // Track on document-wide mousemove when eye is open (hover OR typing)
  document.addEventListener('mousemove', function(e) {{
    if (!eyeSvg || !pupil) return;
    var isOpen = (eyeGroup && (eyeGroup.matches(':hover') || eyeGroup.classList.contains('eye-typing')));
    if (!isOpen) {{
      pupil.setAttribute('cx', REST_PUPIL_X);
      pupil.setAttribute('cy', REST_PUPIL_Y);
      shine.setAttribute('cx', (REST_PUPIL_X + SHINE_OFFSET_X).toFixed(2));
      shine.setAttribute('cy', (REST_PUPIL_Y + SHINE_OFFSET_Y).toFixed(2));
      return;
    }}
    var pt = screenToSvg(eyeSvg, e.clientX, e.clientY);
    movePupil(pt.x, pt.y);
  }});

  var dateEl = document.getElementById('today-date');
  if (dateEl) {{
    dateEl.textContent = new Date().toLocaleDateString('en-US', {{
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
    }});
  }}

  var KEY = 'publicEyeMode';
  function setMode(rep) {{
    document.body.classList.toggle('fp-reporter-mode', rep);
    var a = document.getElementById('fp-mode-reader');
    var b = document.getElementById('fp-mode-reporter');
    if (a) a.classList.toggle('active', !rep);
    if (b) b.classList.toggle('active', rep);
    try {{ localStorage.setItem(KEY, rep ? 'reporter' : 'reader'); }} catch (err) {{}}
  }}
  try {{
    if (localStorage.getItem(KEY) === 'reporter') setMode(true);
  }} catch (err) {{}}
  var br = document.getElementById('fp-mode-reader');
  var bp = document.getElementById('fp-mode-reporter');
  if (br) br.onclick = function() {{ setMode(false); }};
  if (bp) bp.onclick = function() {{ setMode(true); }};
}});
</script>
<script>
(function keepWarm() {{
  setInterval(function() {{
    fetch('/health').catch(function() {{}});
  }}, 10 * 60 * 1000);
}})();
</script>
</body>
</html>"""
