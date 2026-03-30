"""
Server-rendered PUBLIC EYE front page — newspaper masthead + lead story.
Reader / Reporter modes (Reporter persists via localStorage in-page).
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from receipt_store import list_receipts_with_coalition_since


def _e(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


def _headline(rec: dict[str, Any]) -> str:
    art = rec.get("article") or {}
    if isinstance(art, dict) and art.get("title"):
        return str(art["title"]).strip()
    for k in ("article_topic", "narrative", "query"):
        v = rec.get(k)
        if v:
            return str(v).strip()[:240]
    return "Untitled"


def _vol_copy(vol: int) -> str:
    if vol <= 25:
        return "Most outlets agree on the basics."
    if vol <= 60:
        return "Same facts, different spin."
    return "Parallel realities."


def vol_color(vol: int) -> str:
    if vol <= 25:
        return "#2e7d32"
    if vol <= 60:
        return "#E65100"
    return "#B71C1C"


def _coalition_preview(coal: dict[str, Any]) -> dict[str, int]:
    pa = coal.get("position_a") or {}
    pb = coal.get("position_b") or {}

    def countries(chain: list) -> int:
        if not chain:
            return 0
        return len({str(x.get("country") or "").strip() for x in chain if x.get("country")})

    ca = pa.get("chain") if isinstance(pa, dict) else []
    cb = pb.get("chain") if isinstance(pb, dict) else []
    if not isinstance(ca, list):
        ca = []
    if not isinstance(cb, list):
        cb = []
    return {
        "a_count": len(ca),
        "b_count": len(cb),
        "a_countries": countries(ca),
        "b_countries": countries(cb),
    }


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
    return f"{t.strftime('%b')} {t.day}"


def build_front_page_payload() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    generated = now.isoformat()
    edition = now.strftime("%A, %B %d, %Y")

    try:
        rows = list_receipts_with_coalition_since(days=7, limit=300)
    except Exception:
        rows = []

    if not rows:
        return {
            "generated_at": generated,
            "lead_story": None,
            "secondary_stories": [],
            "edition_date": edition,
            "empty": True,
        }

    cut_24 = now - timedelta(hours=24)
    pool_24 = [r for r in rows if _ts_aware(r["created_at"]) >= cut_24]
    pool = pool_24 if pool_24 else rows

    def divergence(r: dict[str, Any]) -> int:
        v = int((r.get("coalition") or {}).get("divergence_score", 0))
        return max(0, min(100, v))

    pool_sorted = sorted(pool, key=divergence, reverse=True)
    lead_row = pool_sorted[0]
    lead_rec = lead_row["receipt"]
    lead_coal = lead_row["coalition"]
    vol = divergence(lead_row)
    pa = lead_coal.get("position_a") or {}
    pb = lead_coal.get("position_b") or {}
    if not isinstance(pa, dict):
        pa = {}
    if not isinstance(pb, dict):
        pb = {}

    lead_story: dict[str, Any] = {
        "receipt_id": lead_row["receipt_id"],
        "headline": _headline(lead_rec),
        "volatility": vol,
        "vol_copy": _vol_copy(vol),
        "position_a": {
            "label": str(pa.get("label") or "Position A"),
            "anchor_region": str(pa.get("anchor_region") or ""),
            "summary": str(pa.get("summary") or ""),
        },
        "position_b": {
            "label": str(pb.get("label") or "Position B"),
            "anchor_region": str(pb.get("anchor_region") or ""),
            "summary": str(pb.get("summary") or ""),
        },
        "irreconcilable_gap": str(lead_coal.get("irreconcilable_gap") or ""),
        "coalition_preview": _coalition_preview(lead_coal),
        "what_both": lead_coal.get("what_both_acknowledge") or [],
        "what_nobody": _lead_what_nobody(lead_rec),
        "coalition": lead_coal,
        "article_url": (lead_rec.get("article") or {}).get("url")
        if isinstance(lead_rec.get("article"), dict)
        else "",
        "signed": bool(lead_rec.get("signed")),
        "schema_version": str(lead_rec.get("schema_version") or "pre-1.0"),
        "generated_at_receipt": str(
            lead_rec.get("generated_at") or lead_rec.get("timestamp") or "",
        ),
    }

    lead_id = lead_row["receipt_id"]
    secondary: list[dict[str, Any]] = []
    for r in pool_sorted[1:6]:
        if r["receipt_id"] == lead_id:
            continue
        if len(secondary) >= 4:
            break
        c = r["coalition"]
        if not isinstance(c, dict):
            continue
        pa2 = c.get("position_a") or {}
        pb2 = c.get("position_b") or {}
        if not isinstance(pa2, dict):
            pa2 = {}
        if not isinstance(pb2, dict):
            pb2 = {}
        dv = divergence(r)
        secondary.append(
            {
                "receipt_id": r["receipt_id"],
                "headline": _headline(r["receipt"]),
                "volatility": dv,
                "vol_copy": _vol_copy(dv),
                "a_label": str(pa2.get("label") or "Side A"),
                "b_label": str(pb2.get("label") or "Side B"),
                "date": _fmt_secondary_date(r["created_at"]),
            },
        )

    return {
        "generated_at": generated,
        "lead_story": lead_story,
        "secondary_stories": secondary,
        "edition_date": edition,
        "empty": False,
    }


def _lead_what_nobody(rec: dict[str, Any]) -> list[str]:
    raw = list(rec.get("what_nobody_is_covering") or [])
    if raw:
        return [str(x) for x in raw[:6]]
    syn = rec.get("synthesis") or {}
    if isinstance(syn, dict):
        wns = syn.get("what_nobody_is_saying") or []
        if isinstance(wns, list):
            return [str(x) for x in wns[:6]]
    return []


def _lead_chains_html(coal: dict[str, Any]) -> str:
    pa = coal.get("position_a") or {}
    pb = coal.get("position_b") or {}
    if not isinstance(pa, dict):
        pa = {}
    if not isinstance(pb, dict):
        pb = {}
    ca = pa.get("chain") or []
    cb = pb.get("chain") or []
    if not isinstance(ca, list):
        ca = []
    if not isinstance(cb, list):
        cb = []

    def rows(chain: list) -> str:
        parts = []
        for item in chain[:24]:
            if not isinstance(item, dict):
                continue
            parts.append(
                f'<div class="fp-chain-row">'
                f'<span class="fp-chain-flag">{item.get("flag") or ""}</span>'
                f'<div class="fp-chain-body"><div class="fp-chain-out">{_e(item.get("outlet"))}</div>'
                f'<div class="fp-chain-meta">{_e(item.get("country"))}</div></div></div>'
            )
        return "".join(parts) or '<div class="fp-chain-empty">—</div>'

    a_lab = _e(pa.get("label") or "Side A")
    b_lab = _e(pb.get("label") or "Side B")
    return (
        f'<details class="fp-coalition">'
        f'<summary>Who\'s on each side ▾</summary>'
        f'<div class="fp-chain-grid">'
        f'<div class="fp-chain-col"><div class="fp-chain-col-label">{a_lab}</div>{rows(ca)}</div>'
        f'<div class="fp-chain-col"><div class="fp-chain-col-label fp-chain-b">{b_lab}</div>{rows(cb)}</div>'
        f"</div></details>"
    )


def render_front_page(data: dict[str, Any]) -> str:
    edition = _e(data.get("edition_date") or "")
    lead = data.get("lead_story")
    secondaries = data.get("secondary_stories") or []
    empty = data.get("empty") or lead is None

    lead_section = ""
    reporter_block = ""
    reader_extras = ""
    coalition_details = ""

    if lead and not empty:
        v = int(lead["volatility"])
        vc = vol_color(v)
        pa = lead["position_a"]
        pb = lead["position_b"]
        pv = lead.get("coalition_preview") or {}
        headline_upper = _e((lead.get("headline") or "").upper())
        rid = _e(lead["receipt_id"])
        coal = lead.get("coalition") or {}
        if isinstance(coal, dict):
            coalition_details = _lead_chains_html(coal)

        lead_section = f"""
<section class="fp-lead" aria-label="Lead story">
  <hr class="rule-bold" />
  <div class="fp-vol-row">
    <div>
      <span class="fp-vol-num" style="color:{vc}">{v}</span>
      <span class="fp-vol-slash"> / 100</span>
      <p class="fp-vol-tag">VOLATILITY</p>
    </div>
    <p class="fp-vol-copy">{_e(lead.get("vol_copy") or "")}</p>
  </div>
  <hr class="rule" />
  <h1 class="fp-lead-hed">{headline_upper}</h1>
  <div class="fp-fight-wrap">
    <div class="fp-fight-grid">
      <div class="fp-fight-card">
        <div class="fp-pos-label">{_e((pa.get("anchor_region") or "").replace("_", " ").upper() or (pa.get("label") or "")[:48])}</div>
        <div class="fp-pos-hed">{_e(pa.get("label") or "")}</div>
        <p class="fp-pos-sum">{_e(pa.get("summary") or "")}</p>
      </div>
      <div class="fp-vs">vs</div>
      <div class="fp-fight-card">
        <div class="fp-pos-label">{_e((pb.get("anchor_region") or "").replace("_", " ").upper() or (pb.get("label") or "")[:48])}</div>
        <div class="fp-pos-hed">{_e(pb.get("label") or "")}</div>
        <p class="fp-pos-sum">{_e(pb.get("summary") or "")}</p>
      </div>
    </div>
  </div>
  <div class="fp-gap-block">
    <div class="fp-gap-label">The gap</div>
    <p class="fp-gap-text">{_e(lead.get("irreconcilable_gap") or "")}</p>
  </div>
  <div class="fp-cta-row">
    <a class="fp-cta" href="/i/{rid}">See full investigation →</a>
    <span class="fp-preview-line">{int(pv.get("a_count", 0))} vs {int(pv.get("b_count", 0))} outlets · {int(pv.get("a_countries", 0))} + {int(pv.get("b_countries", 0))} countries</span>
  </div>
  {coalition_details}
  <hr class="rule" />
</section>"""

        reporter_block = f"""
<div class="reporter-only fp-reporter-tools">
  <h3 class="fp-reporter-hed">Reporter tools</h3>
  <p class="fp-mono">Receipt: <span id="fp-rid">{rid}</span>
    <button type="button" class="fp-btn" onclick="navigator.clipboard.writeText(document.getElementById('fp-rid').textContent.trim())">Copy</button>
    <a class="fp-btn" href="/verify?id={rid}" target="_blank" rel="noopener">Verify ↗</a>
    <a class="fp-btn" href="/r/{rid}" target="_blank" rel="noopener">Raw JSON ↗</a>
  </p>
  <p class="fp-mono-sub">Signed: {'yes — Ed25519' if lead.get('signed') else 'no'} · Schema: {_e(lead.get('schema_version'))} · Generated: {_e(lead.get('generated_at_receipt'))}</p>
  <p class="fp-open-in">Open in:
    <span class="fp-btn fp-btn-ghost fp-btn-disabled">LexisNexis</span>
    <span class="fp-btn fp-btn-ghost fp-btn-disabled">Google Pinpoint</span>
    <span class="fp-btn fp-btn-ghost fp-btn-disabled">Bellingcat Toolkit</span>
  </p>
  <p class="fp-mono-sub">Coalition: <a href="/v1/coalition-map/{rid}">Full JSON ↗</a> · <a href="/pitch">System brief ↗</a></p>
</div>"""

        what_both = lead.get("what_both") or []
        if isinstance(what_both, list) and what_both:
            li = "".join(f"<li>{_e(x)}</li>" for x in what_both if x)
            reader_extras += f'<section class="fp-section reader-focus"><h2 class="fp-section-hed">What everyone agrees on</h2><ul class="fp-list">{li}</ul></section>'
        wn = lead.get("what_nobody") or []
        if isinstance(wn, list) and wn:
            li = "".join(f"<li>{_e(x)}</li>" for x in wn if x)
            reader_extras += f'<section class="fp-section reader-focus"><h2 class="fp-section-hed">What no one is really talking about</h2><ul class="fp-list fp-list-warn">{li}</ul></section>'

    secondary_html = ""
    if secondaries:
        cards = []
        for s in secondaries:
            sid = _e(s.get("receipt_id"))
            vc = vol_color(int(s.get("volatility", 0)))
            cards.append(
                f'<a class="fp-sec-card" href="/i/{sid}">'
                f'<div class="fp-sec-vol"><span style="color:{vc}">{int(s.get("volatility", 0))}</span> / 100'
                f'<span class="fp-sec-copy">{_e(s.get("vol_copy"))}</span></div>'
                f'<h3 class="fp-sec-hed">{_e(s.get("headline"))}</h3>'
                f'<div class="fp-sec-vs">{_e(s.get("a_label"))} <span class="fp-sec-vs-mid">vs</span> {_e(s.get("b_label"))}</div>'
                f'<div class="fp-sec-meta"><span>Open investigation</span><span>{_e(s.get("date"))}</span></div>'
                f"</a>"
            )
        secondary_html = (
            f'<section class="fp-secondary"><h2 class="fp-rule-section"><span>Today\'s edition</span></h2>'
            f'<div class="fp-sec-grid">{"".join(cards)}</div></section>'
        )

    empty_html = ""
    if empty:
        empty_html = """
<section class="fp-empty">
  <h2 class="fp-rule-section"><span>No contested stories today</span></h2>
  <p class="fp-empty-copy">The record is quiet. Paste a URL below to run the first investigation of the day.</p>
</section>"""

    contested_rule = ""
    if not empty:
        contested_rule = '<h2 class="fp-rule-section reporter-only"><span>Today\'s contested claims</span></h2><p class="fp-contested-placeholder reporter-only">More analyses without full coalition maps will appear here.</p>'

    fp_json = json.dumps(data, default=str).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PUBLIC EYE — A front page for contested facts</title>
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
  --fight-bg: #111111;
  --fight-text: #F7F4EF;
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

.fp-masthead {{
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 28px 0 12px;
  border-bottom: 1px solid var(--rule);
}}
.fp-brand {{ flex: 1; min-width: 200px; }}
.fp-brand h1 {{
  font-family: "Playfair Display", serif;
  font-size: 32px;
  font-weight: 700;
  letter-spacing: -0.02em;
}}
.fp-tagline {{
  font-size: 13px;
  font-style: italic;
  color: #444;
  margin-top: 4px;
}}
.fp-mast-right {{ text-align: right; }}
.fp-date {{
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  font-weight: 600;
  color: #555;
}}
.fp-mode {{
  display: inline-flex;
  gap: 4px;
  margin-top: 10px;
}}
.fp-mode button {{
  font-family: "IBM Plex Sans", sans-serif;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 8px 14px;
  border: 1px solid var(--rule);
  background: var(--card);
  cursor: pointer;
  border-radius: 2px;
}}
.fp-mode button.active {{
  background: var(--ink);
  color: var(--paper);
  border-color: var(--ink);
}}

.rule {{ border: none; border-top: 1px solid var(--rule); margin: 24px 0; }}
.rule-bold {{ border: none; border-top: 2px solid var(--ink); margin: 16px 0; opacity: 0.85; }}

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

.fp-vol-row {{
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 20px 32px;
  margin: 8px 0 4px;
}}
.fp-vol-num {{
  font-family: "Playfair Display", serif;
  font-size: 52px;
  font-weight: 900;
  line-height: 1;
}}
.fp-vol-slash {{ font-size: 22px; font-weight: 500; color: #666; }}
.fp-vol-tag {{ font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 600; color: #666; margin-top: 4px; }}
.fp-vol-copy {{ font-size: 14px; font-style: italic; flex: 1; min-width: 200px; }}

.fp-lead-hed {{
  font-family: "Playfair Display", serif;
  font-size: 36px;
  font-weight: 700;
  text-align: center;
  line-height: 1.15;
  margin: 20px 0 24px;
  letter-spacing: 0.02em;
}}

.fp-fight-wrap {{ margin: 8px 0 20px; }}
.fp-fight-grid {{
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 2px;
  background: rgba(26,26,26,0.2);
  border-radius: 4px;
  overflow: hidden;
}}
@media (max-width: 640px) {{
  .fp-fight-grid {{ grid-template-columns: 1fr; }}
  .fp-vs {{ display: none; }}
}}
.fp-fight-card {{
  background: var(--fight-bg);
  color: var(--fight-text);
  padding: 22px 20px;
  min-height: 140px;
}}
.fp-pos-label {{
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #b0a99f;
  margin-bottom: 8px;
}}
.fp-pos-hed {{ font-family: "Playfair Display", serif; font-size: 18px; font-weight: 700; margin-bottom: 10px; }}
.fp-pos-sum {{ font-size: 14px; line-height: 1.7; color: #e8e4dc; }}
.fp-vs {{
  background: var(--fight-bg);
  color: #777;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 0 8px;
}}

.fp-gap-block {{ margin: 20px 0 12px; }}
.fp-gap-label {{
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 8px;
}}
.fp-gap-text {{ font-size: 16px; line-height: 1.7; max-width: 720px; }}

.fp-cta-row {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
  margin-top: 16px;
}}
.fp-cta {{
  font-weight: 600;
  color: var(--ink);
  text-decoration: underline;
  text-underline-offset: 3px;
}}
.fp-preview-line {{ font-size: 13px; color: #555; }}

.fp-coalition {{
  margin-top: 16px;
  background: var(--fight-bg);
  color: var(--fight-text);
  border-radius: 6px;
  border: 1px solid rgba(26,26,26,0.15);
  overflow: hidden;
}}
.fp-coalition summary {{
  cursor: pointer;
  list-style: none;
  padding: 14px 16px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
.fp-coalition summary::-webkit-details-marker {{ display: none; }}
.fp-chain-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2px;
  background: rgba(247,244,239,0.12);
}}
@media (max-width: 640px) {{ .fp-chain-grid {{ grid-template-columns: 1fr; }} }}
.fp-chain-col {{ background: var(--fight-bg); padding: 12px 14px 16px; }}
.fp-chain-col-label {{ font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: #7eb8ff; margin-bottom: 8px; }}
.fp-chain-col-label.fp-chain-b {{ color: #ff8a80; }}
.fp-chain-row {{ display: flex; gap: 8px; padding: 6px 0; border-bottom: 1px solid rgba(247,244,239,0.08); }}
.fp-chain-flag {{ font-size: 14px; line-height: 1.4; }}
.fp-chain-out {{ font-size: 13px; font-weight: 500; }}
.fp-chain-meta {{ font-size: 11px; color: #9e9a93; }}
.fp-chain-empty {{ color: #777; font-size: 12px; padding: 8px 0; }}

.fp-secondary {{ margin-bottom: 24px; }}
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
.fp-sec-copy {{ display: block; font-size: 12px; font-style: italic; font-family: "IBM Plex Sans", sans-serif; font-weight: 400; color: #555; margin-top: 4px; }}
.fp-sec-hed {{ font-family: "Playfair Display", serif; font-size: 22px; font-weight: 700; margin: 12px 0; line-height: 1.25; }}
.fp-sec-vs {{ font-size: 14px; line-height: 1.5; color: #333; }}
.fp-sec-vs-mid {{ text-transform: uppercase; font-size: 11px; color: #888; margin: 0 6px; }}
.fp-sec-meta {{ display: flex; justify-content: space-between; margin-top: 14px; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; color: #666; }}

.fp-section {{ margin: 28px 0; }}
.fp-section-hed {{
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 12px;
}}
.fp-list {{ list-style: disc; padding-left: 1.25rem; font-size: 15px; line-height: 1.65; }}
.fp-list-warn {{ color: #5d4037; }}

.fp-empty {{ margin: 32px 0; }}
.fp-empty-copy {{ font-size: 15px; max-width: 520px; margin-top: 12px; }}

.fp-analyze {{
  margin-top: 40px;
  padding: 20px 22px;
  border: 1px solid rgba(26,26,26,0.18);
  background: var(--card);
  border-radius: 4px;
}}
.fp-analyze label {{ display: block; font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 10px; }}
.fp-analyze-row {{ display: flex; flex-wrap: wrap; gap: 10px; }}
.fp-analyze input[type="url"] {{
  flex: 1;
  min-width: 200px;
  padding: 12px 14px;
  border: 1px solid rgba(26,26,26,0.2);
  border-radius: 2px;
  font-family: "IBM Plex Sans", sans-serif;
  font-size: 15px;
}}
.fp-analyze button {{
  font-family: "IBM Plex Sans", sans-serif;
  font-weight: 600;
  font-size: 13px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 12px 22px;
  background: var(--ink);
  color: var(--paper);
  border: none;
  border-radius: 2px;
  cursor: pointer;
}}
.fp-analyze-err {{ color: #B71C1C; font-size: 13px; margin-top: 10px; display: none; }}

body.fp-reporter-mode .reporter-only {{ display: block !important; }}
body.fp-reporter-mode .reader-focus {{ display: none !important; }}
.reporter-only {{ display: none; }}

.fp-reporter-tools {{
  margin: 20px 0;
  padding: 18px;
  background: #F5F5F5;
  border: 1px solid rgba(26,26,26,0.12);
  border-radius: 4px;
}}
.fp-reporter-hed {{ font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 12px; }}
.fp-mono {{ font-family: "IBM Plex Mono", monospace; font-size: 12px; color: #333; line-height: 1.7; }}
.fp-mono-sub {{ font-family: "IBM Plex Mono", monospace; font-size: 11px; color: #555; margin-top: 8px; }}
.fp-btn {{
  display: inline-block;
  margin-left: 8px;
  padding: 4px 10px;
  font-size: 11px;
  border: 1px solid #999;
  background: #fff;
  border-radius: 2px;
  cursor: pointer;
  text-decoration: none;
  color: var(--ink);
}}
.fp-btn-ghost {{ opacity: 0.6; cursor: not-allowed; }}
.fp-open-in {{ margin-top: 12px; font-size: 13px; }}
.fp-contested-placeholder {{ font-size: 14px; color: #555; margin-bottom: 24px; }}

.footer-rule {{ margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--rule); font-size: 12px; color: #666; }}
</style>
</head>
<body class="fp-body">
<div class="fp-wrap">
  <header class="fp-masthead">
    <div class="fp-brand">
      <h1>PUBLIC EYE</h1>
      <p class="fp-tagline">A front page for contested facts.</p>
    </div>
    <div class="fp-mast-right">
      <div class="fp-date">{edition}</div>
      <form action="/search" method="get" class="fp-header-search" style="margin-top:8px;display:flex;gap:6px;justify-content:flex-end;align-items:center">
        <input type="search" name="q" placeholder="Search conflicts…" autocomplete="off" aria-label="Search conflicts"
          style="width:min(200px,38vw);padding:6px 10px;font-size:12px;border:1px solid var(--rule);font-family:inherit;background:var(--card)" />
        <button type="submit" style="padding:6px 12px;font-size:10px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;border:1px solid var(--ink);background:var(--ink);color:var(--paper);cursor:pointer">Go</button>
      </form>
      <div class="fp-mode">
        <button type="button" id="fp-mode-reader" class="active">Reader</button>
        <button type="button" id="fp-mode-reporter">Reporter</button>
      </div>
    </div>
  </header>

  {reporter_block}
  {empty_html}
  {lead_section}
  {reader_extras}
  {secondary_html}
  {contested_rule}

  <section class="fp-analyze">
    <label for="fp-analyze-url">Analyze</label>
    <form id="fp-analyze-form" class="fp-analyze-row" action="/analyze" method="get">
      <input type="url" id="fp-analyze-url" name="url" placeholder="Paste any article URL…" required autocomplete="off" />
      <button type="submit">Analyze →</button>
    </form>
    <p id="fp-analyze-err" class="fp-analyze-err"></p>
  </section>

  <footer class="footer-rule">Receipts, not verdicts. <a href="/health">System status</a> · <a href="/verify">Verify</a></footer>
</div>

<script id="fp-data" type="application/json">{fp_json}</script>
<script>
(function() {{
  var KEY = 'publicEyeMode';
  function setMode(rep) {{
    document.body.classList.toggle('fp-reporter-mode', rep);
    document.getElementById('fp-mode-reader').classList.toggle('active', !rep);
    document.getElementById('fp-mode-reporter').classList.toggle('active', rep);
    try {{ localStorage.setItem(KEY, rep ? 'reporter' : 'reader'); }} catch (e) {{}}
  }}
  try {{
    if (localStorage.getItem(KEY) === 'reporter') setMode(true);
  }} catch (e) {{}}
  document.getElementById('fp-mode-reader').onclick = function() {{ setMode(false); }};
  document.getElementById('fp-mode-reporter').onclick = function() {{ setMode(true); }};

}})();
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
