"""
investigation_page.py  (v4 — human-first, beloved)

Changes from v3:
- Volatility: 0-25 green, 26-60 amber (#e8a020), 61-100 red. Amber is clearly yellow-orange.
- "Why this number?" inline explainer link
- Two anchor cards as hero, chains collapsed behind "Who's on each side" toggle
- Chain preview: "Backed by N outlets in N countries" before expand
- Human language throughout: "Where the story splits", "What no one is talking about",
  "What everyone agrees on", "Who's on each side"
- Empty state copy that sounds like a person
- coalition_map label replaced with "who's on each side" in UI
- JS-powered accordion for chains (no page reload)
"""

from __future__ import annotations
import html
from collections import defaultdict
from typing import Any


_OUTLET_TYPE_ORDER = ("state", "public_broadcaster", "private")
_OUTLET_TYPE_LABEL = {
    "state": "State-affiliated media",
    "public_broadcaster": "Public broadcasters",
    "private": "Private / independent",
}


def _e(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


def _vol_theme(vol: int) -> tuple[str, str, str, str, str]:
    """Returns (pill_bg, pill_border, accent, short_copy, bucket_label)"""
    if vol <= 25:
        return "#0a2218", "#0d3d2a", "#3ecf8e", \
               "Most outlets agree on the basics.", "Low"
    elif vol <= 60:
        return "#2a1c04", "#3d2a06", "#e8a020", \
               "Same facts, different spin.", "Moderate"
    else:
        return "#2e0a0a", "#3d0e0e", "#e05050", \
               "Parallel realities.", "High"


def _pills(items: list, color: str) -> str:
    palette = {
        "green": ("#0a2218", "#3ecf8e", "#0d2e20"),
        "red":   ("#2e0a0a", "#e05050", "#3d0e0e"),
        "amber": ("#2a1c04", "#e8a020", "#3d2a06"),
        "blue":  ("#0a1a2e", "#5b9fff", "#0d2240"),
        "gray":  ("#1a1a1a", "#9e9a93", "#222"),
    }
    bg, fg, border = palette.get(color, palette["gray"])
    return "".join(
        f'<span style="display:inline-block;padding:3px 10px;border-radius:20px;'
        f'font-size:11px;font-weight:500;background:{bg};color:{fg};'
        f'border:0.5px solid {border};margin:2px 3px 2px 0">{_e(item)}</span>'
        for item in items
    )


def _outlet_badge(otype: str) -> str:
    m = {
        "state":              ("#2e0a0a", "#e05050", "STATE"),
        "public_broadcaster": ("#0a2218", "#3ecf8e", "PUBLIC"),
        "private":            ("#0a1a2e", "#5b9fff", "PRIVATE"),
    }
    bg, fg, label = m.get(otype, ("#1a1a1a", "#9e9a93", "—"))
    return (f'<span style="font-size:9px;letter-spacing:0.07em;padding:1px 5px;'
            f'border-radius:3px;background:{bg};color:{fg};font-weight:600">{label}</span>')


def _chain_preview(chain: list) -> str:
    """Short summary: 'Backed by 6 outlets in 4 countries'"""
    if not chain:
        return "No outlets mapped yet"
    countries = len(set(c.get("country","") for c in chain if c.get("country")))
    return f"Backed by {len(chain)} outlet{'s' if len(chain)!=1 else ''} in {countries} countr{'ies' if countries!=1 else 'y'}"


def _one_outlet_row(item: dict) -> str:
    conf = item.get("alignment_confidence", "medium")
    dot = {"high": "#3ecf8e", "medium": "#e8a020", "low": "#5a5752"}.get(conf, "#5a5752")
    note = item.get("alignment_note", "")
    return (
        f'<div style="display:flex;gap:10px;align-items:flex-start;'
        f'padding:8px 0;border-bottom:0.5px solid rgba(255,255,255,0.04)">'
        f'<div style="flex:1;min-width:0">'
        f'<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:3px">'
        f'<span style="font-size:13px;font-weight:500;color:#f0ede8">'
        f'{_e(item.get("outlet",""))}</span>'
        f'{_outlet_badge(item.get("outlet_type",""))}</div>'
        f'<div style="font-size:12px;color:#9e9a93;line-height:1.5">{_e(note)}</div>'
        f'</div>'
        f'<div style="width:6px;height:6px;border-radius:50%;background:{dot};'
        f'flex-shrink:0;margin-top:6px"></div>'
        f'</div>'
    )


def _chain_items_html(chain: list, side_prefix: str) -> str:
    """Group outlets by country (click to expand), then by media type on this story."""
    if not chain:
        return '<div style="font-size:12px;color:#5a5752;padding:12px 0">No outlets mapped yet.</div>'

    by_country: dict[str, list] = defaultdict(list)
    for item in chain:
        if not isinstance(item, dict):
            continue
        c = str(item.get("country") or "").strip() or "Unknown region"
        by_country[c].append(item)

    blocks: list[str] = []
    for cidx, (country, items) in enumerate(sorted(by_country.items(), key=lambda x: x[0].lower())):
        flag = ""
        for it in items:
            if isinstance(it, dict) and it.get("flag"):
                flag = str(it.get("flag", ""))
                break
        by_type: dict[str, list] = defaultdict(list)
        for it in items:
            if not isinstance(it, dict):
                continue
            ot = str(it.get("outlet_type") or "private").strip()
            if ot not in _OUTLET_TYPE_LABEL:
                ot = "private"
            by_type[ot].append(it)

        type_sections: list[str] = []
        for otype in _OUTLET_TYPE_ORDER:
            typed = by_type.get(otype)
            if not typed:
                continue
            label = _OUTLET_TYPE_LABEL[otype]
            inner = "".join(_one_outlet_row(x) for x in typed)
            type_sections.append(
                f'<div style="margin-bottom:14px">'
                f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;'
                f'color:#5a5752;margin-bottom:6px">{_e(label)}</div>'
                f'<div style="padding-left:2px">{inner}</div>'
                f"</div>"
            )
        for otype, typed in sorted(by_type.items()):
            if otype in _OUTLET_TYPE_ORDER:
                continue
            inner = "".join(_one_outlet_row(x) for x in typed)
            type_sections.append(
                f'<div style="margin-bottom:14px">'
                f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;'
                f'color:#5a5752;margin-bottom:6px">{_e(otype)}</div>'
                f'<div style="padding-left:2px">{inner}</div>'
                f"</div>"
            )

        nid = f"side-{side_prefix}-country-{cidx}"
        n_out = len(items)
        blocks.append(
            f'<details class="country-acc" id="{nid}" style="border:0.5px solid rgba(255,255,255,0.06);'
            f'border-radius:10px;background:rgba(0,0,0,0.25);margin-bottom:10px;overflow:hidden">'
            f'<summary style="list-style:none;cursor:pointer;padding:12px 14px;display:flex;'
            f'align-items:center;gap:8px;flex-wrap:wrap;user-select:none">'
            f'<span style="font-size:16px;line-height:1">{flag}</span>'
            f'<span style="font-size:13px;font-weight:600;color:#f0ede8">{_e(country)}</span>'
            f'<span class="country-chev" style="font-size:11px;color:#e8a020">▾</span>'
            f'<span style="font-size:11px;color:#5a5752;margin-left:auto">'
            f'{n_out} outlet{"s" if n_out != 1 else ""} · {_e(str(len(by_type)))} type{"s" if len(by_type) != 1 else ""}'
            f"</span>"
            f"</summary>"
            f'<div style="padding:4px 14px 14px 14px;border-top:0.5px solid rgba(255,255,255,0.05)">'
            f'{"".join(type_sections)}'
            f"</div>"
            f"</details>"
        )

    hint = (
        '<p style="font-size:11px;color:#5a5752;line-height:1.5;margin:0 0 10px 0">'
        "Tap a country to see how outlets there break down by kind of organization "
        "on this story.</p>"
    )
    return hint + "".join(blocks)


def render_investigation_page(receipt: dict, coalition: dict | None) -> str:
    rid         = receipt.get("receipt_id") or receipt.get("report_id", "")
    rtype       = receipt.get("receipt_type", "article_analysis")
    signed      = receipt.get("signed", False)
    timestamp   = receipt.get("generated_at") or receipt.get("timestamp", "")
    signature   = receipt.get("signature", "")
    public_key  = receipt.get("public_key", "")
    schema_ver  = receipt.get("schema_version", "pre-1.0")
    narrative   = receipt.get("narrative") or receipt.get("article_topic", "")
    article     = receipt.get("article", {}) or {}
    a_title     = article.get("title", "") if isinstance(article, dict) else ""
    a_url       = article.get("url",   "") if isinstance(article, dict) else ""
    a_pub       = article.get("publication", "") if isinstance(article, dict) else ""
    confirmed   = receipt.get("confirmed", [])
    what_nobody = receipt.get("what_nobody_is_covering", [])

    contested_claim = irreconcilable_gap = coalition_note = ""
    divergence_score = 0
    what_both = []
    pos_a = pos_b = {}

    if coalition:
        contested_claim    = coalition.get("contested_claim", "")
        divergence_score   = int(coalition.get("divergence_score", 0))
        irreconcilable_gap = coalition.get("irreconcilable_gap", "")
        what_both          = coalition.get("what_both_acknowledge", [])
        pos_a              = coalition.get("position_a", {})
        pos_b              = coalition.get("position_b", {})
        coalition_note     = coalition.get("coalition_map_note", "")

    vol = min(100, max(0, divergence_score))
    pill_bg, pill_border, accent, vol_copy, vol_bucket = _vol_theme(vol)

    signed_badge = (
        '<span style="display:inline-flex;align-items:center;gap:5px;padding:3px 10px;'
        'border-radius:20px;font-size:11px;font-weight:600;'
        'background:#0a2218;color:#3ecf8e;border:0.5px solid #0d3d2a">✓ Signed</span>'
        if signed else
        '<span style="display:inline-flex;align-items:center;gap:5px;padding:3px 10px;'
        'border-radius:20px;font-size:11px;font-weight:600;'
        'background:#2e0a0a;color:#e05050;border:0.5px solid #3d0e0e">✗ Unsigned</span>'
    )

    a_label   = pos_a.get("label",        "Position A") if pos_a else "Position A"
    b_label   = pos_b.get("label",        "Position B") if pos_b else "Position B"
    a_anchor  = pos_a.get("anchor_region","").replace("_"," ") if pos_a else ""
    b_anchor  = pos_b.get("anchor_region","").replace("_"," ") if pos_b else ""
    a_summary = pos_a.get("summary", "")  if pos_a else ""
    b_summary = pos_b.get("summary", "")  if pos_b else ""
    a_em      = pos_a.get("emphasizes",[]) if pos_a else []
    b_em      = pos_b.get("emphasizes",[]) if pos_b else []
    a_mn      = pos_a.get("minimizes", []) if pos_a else []
    b_mn      = pos_b.get("minimizes", []) if pos_b else []
    a_chain   = pos_a.get("chain",     []) if pos_a else []
    b_chain   = pos_b.get("chain",     []) if pos_b else []

    nobody_html = "".join(
        f'<div style="display:flex;gap:10px;padding:9px 14px;border-radius:8px;'
        f'background:rgba(232,160,32,0.06);margin-bottom:6px;'
        f'border:0.5px solid rgba(232,160,32,0.14)">'
        f'<span style="color:#e8a020;flex-shrink:0;margin-top:1px">◈</span>'
        f'<span style="font-size:13px;color:#e8a020;line-height:1.5">{_e(w)}</span></div>'
        for w in what_nobody[:6]
    )

    confirmed_html = "".join(
        f'<div style="display:flex;gap:10px;padding:9px 0;'
        f'border-bottom:0.5px solid rgba(255,255,255,0.05)">'
        f'<div style="width:5px;height:5px;border-radius:50%;background:#00c8b4;'
        f'flex-shrink:0;margin-top:6px"></div>'
        f'<div><div style="font-size:13px;color:#f0ede8;line-height:1.4">'
        f'{_e(c.get("title","") if isinstance(c,dict) else str(c))}</div>'
        f'<div style="font-size:11px;color:#5a5752;margin-top:2px">'
        f'{_e(c.get("outlet","") if isinstance(c,dict) else "")} · '
        f'{_e(c.get("date","")   if isinstance(c,dict) else "")}</div></div></div>'
        for c in confirmed[:5]
    ) if confirmed else ""

    both_html = "".join(
        f'<div style="font-size:13px;color:#9e9a93;padding:6px 0;'
        f'border-bottom:0.5px solid rgba(255,255,255,0.05)">'
        f'<span style="color:#5a5752;margin-right:10px">—</span>{_e(w)}</div>'
        for w in what_both
    )

    receipt_rows = "".join(
        f'<div style="display:grid;grid-template-columns:140px 1fr;gap:12px;'
        f'padding:9px 0;border-bottom:0.5px solid rgba(255,255,255,0.05)">'
        f'<div style="font-size:10px;letter-spacing:0.07em;text-transform:uppercase;'
        f'color:#5a5752">{k}</div>'
        f'<div style="font-family:monospace;font-size:12px;color:{c};'
        f'word-break:break-all;line-height:1.5">{_e(v)}</div></div>'
        for k, v, c in [
            ("Receipt ID",     rid,   "#9e9a93"),
            ("Type",           rtype, "#9e9a93"),
            ("Signed",
             "true — Ed25519 signature present" if signed else "false",
             "#3ecf8e" if signed else "#e05050"),
            ("Timestamp",      timestamp,  "#9e9a93"),
            ("Schema version", schema_ver, "#9e9a93"),
            ("Signing key",
             (public_key[:28] + "…") if public_key else "—", "#9e9a93"),
        ]
    )

    # ── No-coalition empty state ─────────────────────────────────
    no_coalition_html = """
<div style="padding:32px 24px;border:0.5px solid rgba(255,255,255,0.07);
            border-radius:12px;background:#111;text-align:center;margin-bottom:40px">
  <div style="font-size:15px;color:#5a5752;line-height:1.7">
    We don't see enough disagreement here to map a split story yet.
  </div>
  <div style="font-size:12px;color:#3a3a3a;margin-top:8px">
    Coalition analysis runs in the background — check back in a minute.
  </div>
</div>"""

    # ── Coalition section ────────────────────────────────────────
    coalition_section = no_coalition_html
    if coalition:
        a_preview = _chain_preview(a_chain)
        b_preview = _chain_preview(b_chain)
        a_chain_html = _chain_items_html(a_chain, "a")
        b_chain_html = _chain_items_html(b_chain, "b")

        coalition_section = f"""
<!-- VOLATILITY PILL -->
<div style="margin-bottom:24px">
  <div style="display:inline-flex;align-items:center;gap:12px;
              padding:10px 20px;border-radius:28px;
              background:{pill_bg};border:0.5px solid {pill_border}">
    <span style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;
                 color:{accent};font-weight:600">VOLATILITY</span>
    <span style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;
                 color:#f0ede8;line-height:1;letter-spacing:-0.02em">{vol}</span>
    <span style="font-size:12px;color:{accent};opacity:0.6">/ 100</span>
  </div>
  <div style="display:flex;align-items:center;gap:8px;margin-top:8px;padding-left:2px">
    <span style="font-size:13px;color:#9e9a93">{_e(vol_copy)}</span>
    <button onclick="toggleWhyNumber()" style="font-size:11px;color:#5a5752;
            background:none;border:none;cursor:pointer;padding:0;
            text-decoration:underline;text-underline-offset:3px">
      Why this number?
    </button>
  </div>
  <div id="why-number" style="display:none;margin-top:10px;padding:12px 16px;
       border-radius:8px;background:#111;border:0.5px solid rgba(255,255,255,0.08);
       font-size:12px;color:#9e9a93;line-height:1.6;max-width:520px">
    The volatility score measures how far apart the two most opposed outlet clusters
    are on this story — based on what each side emphasizes vs. minimizes, and how
    confidently they hold those positions. It's not a vibe: it's calculated from the
    actual emphasis and omission tags in the source analysis. 0 = everyone agrees.
    100 = parallel realities with no shared premise.
  </div>
</div>

<!-- IRRECONCILABLE GAP — always visible -->
<div style="margin-bottom:32px;padding:18px 22px;
            border-left:3px solid {accent};
            background:{pill_bg};border-radius:0 10px 10px 0">
  <div style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;
              color:{accent};margin-bottom:8px;font-weight:600">Where the story splits</div>
  <div style="font-size:15px;color:#f0ede8;line-height:1.7">{_e(irreconcilable_gap)}</div>
</div>

<!-- TWO ANCHOR CARDS -->
<div style="display:flex;gap:1px;background:rgba(255,255,255,0.06);
            border-radius:14px;overflow:hidden;margin-bottom:24px">

  <!-- SIDE A -->
  <div style="flex:1;background:#0e0e0e;padding:24px 22px">
    <div style="font-size:10px;letter-spacing:0.1em;text-transform:uppercase;
                color:#5b9fff;margin-bottom:8px">{_e(a_anchor)}</div>
    <div style="font-family:Syne,sans-serif;font-size:19px;font-weight:700;
                color:#f0ede8;margin-bottom:10px;line-height:1.2">{_e(a_label)}</div>
    <div style="font-size:13px;color:#9e9a93;line-height:1.6;margin-bottom:16px">
      {_e(a_summary)}</div>
    <div style="margin-bottom:10px">
      <div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;
                  color:#5a5752;margin-bottom:5px">Emphasizes</div>
      {_pills(a_em, "green")}
    </div>
    <div>
      <div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;
                  color:#5a5752;margin-bottom:5px">Minimizes</div>
      {_pills(a_mn, "red")}
    </div>
  </div>

  <!-- VS -->
  <div style="display:flex;align-items:center;justify-content:center;
              background:#0e0e0e;padding:0 4px;min-width:36px">
    <span style="background:#111;border:0.5px solid rgba(255,255,255,0.1);
                 border-radius:20px;padding:5px 8px;
                 font-size:10px;font-weight:700;color:#5a5752">VS</span>
  </div>

  <!-- SIDE B -->
  <div style="flex:1;background:#0e0e0e;padding:24px 22px">
    <div style="font-size:10px;letter-spacing:0.1em;text-transform:uppercase;
                color:#e05050;margin-bottom:8px">{_e(b_anchor)}</div>
    <div style="font-family:Syne,sans-serif;font-size:19px;font-weight:700;
                color:#f0ede8;margin-bottom:10px;line-height:1.2">{_e(b_label)}</div>
    <div style="font-size:13px;color:#9e9a93;line-height:1.6;margin-bottom:16px">
      {_e(b_summary)}</div>
    <div style="margin-bottom:10px">
      <div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;
                  color:#5a5752;margin-bottom:5px">Emphasizes</div>
      {_pills(b_em, "green")}
    </div>
    <div>
      <div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;
                  color:#5a5752;margin-bottom:5px">Minimizes</div>
      {_pills(b_mn, "red")}
    </div>
  </div>
</div>

<!-- WHO'S ON EACH SIDE — collapsed by default -->
<div style="margin-bottom:40px">
  <div style="display:flex;gap:12px;flex-wrap:wrap">

    <!-- Side A toggle -->
    <div style="flex:1;min-width:240px;border:0.5px solid rgba(255,255,255,0.08);
                border-radius:12px;background:#111;overflow:hidden">
      <button onclick="toggleChain('chain-a')"
              style="width:100%;padding:14px 18px;background:none;border:none;
                     cursor:pointer;text-align:left;
                     border-bottom:0.5px solid rgba(255,255,255,0.06)">
        <div style="font-size:10px;letter-spacing:0.1em;text-transform:uppercase;
                    color:#5b9fff;margin-bottom:3px">Who's on this side</div>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div style="font-size:13px;font-weight:600;color:#f0ede8">{_e(a_label)}</div>
          <div style="font-size:12px;color:#5a5752;display:flex;align-items:center;gap:6px">
            <span>{_e(a_preview)}</span>
            <span id="chain-a-arrow" style="transition:transform 0.2s">▾</span>
          </div>
        </div>
      </button>
      <div id="chain-a" style="display:none;padding:4px 18px 12px">
        {a_chain_html}
      </div>
    </div>

    <!-- Side B toggle -->
    <div style="flex:1;min-width:240px;border:0.5px solid rgba(255,255,255,0.08);
                border-radius:12px;background:#111;overflow:hidden">
      <button onclick="toggleChain('chain-b')"
              style="width:100%;padding:14px 18px;background:none;border:none;
                     cursor:pointer;text-align:left;
                     border-bottom:0.5px solid rgba(255,255,255,0.06)">
        <div style="font-size:10px;letter-spacing:0.1em;text-transform:uppercase;
                    color:#e05050;margin-bottom:3px">Who's on this side</div>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div style="font-size:13px;font-weight:600;color:#f0ede8">{_e(b_label)}</div>
          <div style="font-size:12px;color:#5a5752;display:flex;align-items:center;gap:6px">
            <span>{_e(b_preview)}</span>
            <span id="chain-b-arrow" style="transition:transform 0.2s">▾</span>
          </div>
        </div>
      </button>
      <div id="chain-b" style="display:none;padding:4px 18px 12px">
        {b_chain_html}
      </div>
    </div>
  </div>
</div>

<!-- WHAT EVERYONE AGREES ON -->
{"<div style='margin-bottom:40px'><div style='font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:#5a5752;margin-bottom:10px'>What everyone agrees on</div><div style='border:0.5px solid rgba(255,255,255,0.08);border-radius:10px;background:#111;padding:4px 18px'>" + both_html + "</div></div>" if both_html else ""}

<!-- CONTESTED CLAIM (de-emphasized, after the main fight) -->
<div style="margin-bottom:40px">
  <div style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;
              color:#5a5752;margin-bottom:10px">The specific claim in dispute</div>
  <div style="padding:12px 18px;border-left:2px solid rgba(255,255,255,0.1);
              font-size:13px;color:#5a5752;line-height:1.7;font-style:italic">
    {_e(contested_claim)}
  </div>
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(a_title or "Investigation")} — PUBLIC EYE</title>
<meta name="description" content="{_e((irreconcilable_gap or narrative)[:160])}">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  html{{scroll-behavior:smooth}}
  body{{
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    background:#080808;color:#f0ede8;min-height:100vh;
    background:radial-gradient(ellipse 80% 20% at 50% 0%,
      rgba(0,200,180,0.03) 0%,transparent 100%),#080808;
  }}
  a{{color:#00c8b4;text-decoration:none}}
  a:hover{{opacity:.8}}
  button:hover{{opacity:.85}}
  details.country-acc > summary::-webkit-details-marker {{ display: none; }}
  details.country-acc > summary {{ list-style: none; }}
  details.country-acc .country-chev {{
    transition: transform 0.2s ease;
    display: inline-block;
  }}
  details.country-acc[open] > summary .country-chev {{
    transform: rotate(180deg);
  }}
</style>
</head>
<body>

<header style="display:flex;align-items:center;justify-content:space-between;
               padding:16px 36px;border-bottom:0.5px solid rgba(255,255,255,0.06);
               position:sticky;top:0;z-index:20;
               background:rgba(8,8,8,0.93);backdrop-filter:blur(16px)">
  <a href="/" style="font-family:Syne,sans-serif;font-size:14px;font-weight:800;
                      letter-spacing:0.14em;text-transform:uppercase;color:#f0ede8">
    PUBLIC<span style="color:#00c8b4">EYE</span>
  </a>
  <div style="display:flex;align-items:center;gap:14px">
    {signed_badge}
    <a href="#verification" style="font-size:11px;color:#5a5752;letter-spacing:0.04em">
      Receipt ↓
    </a>
  </div>
</header>

<div style="max-width:880px;margin:0 auto;padding:0 36px">

<!-- HOOK -->
<div style="padding:52px 0 32px">
  {f'<div style="margin-bottom:10px"><a href="{_e(a_url)}" target="_blank" rel="noopener" style="font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:#5a5752">{_e(a_pub)} ↗</a></div>' if a_url else ""}
  <h1 style="font-family:Syne,sans-serif;font-size:clamp(22px,3.8vw,38px);
              font-weight:800;line-height:1.1;letter-spacing:-0.02em;color:#f0ede8;
              margin-bottom:0;max-width:700px">
    {_e(a_title or "Untitled Investigation")}
  </h1>
</div>

<div style="height:0.5px;background:rgba(255,255,255,0.07);margin-bottom:36px"></div>

{coalition_section}

<!-- SUMMARY (after the fight) -->
{f'<div style="margin-bottom:40px;padding:16px 20px;border:0.5px solid rgba(255,255,255,0.07);border-radius:10px;background:#111"><div style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:#5a5752;margin-bottom:8px">Summary</div><p style="font-size:14px;color:#9e9a93;line-height:1.7">{_e(narrative[:300])}{"…" if len(narrative)>300 else ""}</p></div>' if narrative else ""}

<!-- WHAT NO ONE IS REALLY TALKING ABOUT -->
{f'<div style="margin-bottom:40px"><div style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:#5a5752;margin-bottom:12px">What no one is really talking about</div>{nobody_html}</div>' if nobody_html else ""}

<!-- CROSS-CORROBORATED -->
{f'<div style="margin-bottom:40px"><div style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:#5a5752;margin-bottom:12px">Cross-corroborated</div><div style="border:0.5px solid rgba(255,255,255,0.08);border-radius:10px;background:#111;padding:4px 18px">{confirmed_html}</div></div>' if confirmed_html else ""}

<div style="height:0.5px;background:rgba(255,255,255,0.07);margin-bottom:40px"></div>

<!-- VERIFICATION -->
<div id="verification" style="margin-bottom:60px">
  <div style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;
              color:#5a5752;margin-bottom:12px">Verification</div>
  <div style="border:0.5px solid rgba(255,255,255,0.08);border-radius:12px;
              background:#111;overflow:hidden">
    <div style="padding:16px 20px;border-bottom:0.5px solid rgba(255,255,255,0.06);
                display:flex;align-items:center;justify-content:space-between;
                flex-wrap:wrap;gap:10px">
      <div>
        <div style="font-size:14px;font-weight:500;color:#f0ede8;margin-bottom:3px">
          Cryptographically signed
        </div>
        <div style="font-size:12px;color:#5a5752">
          Ed25519 · JCS canonical payload · independently verifiable
        </div>
      </div>
      {signed_badge}
    </div>
    <div style="padding:6px 20px">{receipt_rows}</div>
    {f'<div style="padding:12px 20px;border-top:0.5px solid rgba(255,255,255,0.06);background:rgba(255,255,255,0.01)"><div style="font-size:10px;letter-spacing:0.07em;text-transform:uppercase;color:#5a5752;margin-bottom:5px">Ed25519 Signature</div><div style="font-family:monospace;font-size:11px;color:#5a5752;word-break:break-all;line-height:1.6">{_e(signature)}</div></div>' if signature else ""}
    <div style="padding:14px 20px;border-top:0.5px solid rgba(255,255,255,0.06);
                display:flex;gap:8px;flex-wrap:wrap">
      <a href="/verify?id={_e(rid)}"
         style="font-size:11px;padding:7px 16px;border-radius:6px;
                border:0.5px solid rgba(255,255,255,0.12);color:#9e9a93">
        Verify independently ↗
      </a>
      <a href="/r/{_e(rid)}" target="_blank"
         style="font-size:11px;padding:7px 16px;border-radius:6px;
                border:0.5px solid rgba(255,255,255,0.12);color:#9e9a93">
        Raw JSON ↗
      </a>
    </div>
  </div>
</div>

<div style="padding-bottom:48px;display:flex;align-items:center;
            justify-content:space-between;flex-wrap:wrap;gap:12px;
            border-top:0.5px solid rgba(255,255,255,0.06);padding-top:24px">
  <div style="font-size:11px;color:#5a5752">PUBLIC EYE · Receipts, not verdicts.</div>
  <a href="/verify?id={_e(rid)}" style="font-size:11px;color:#5a5752">
    Independent verification ↗
  </a>
</div>

</div>

<script>
function toggleWhyNumber() {{
  var el = document.getElementById('why-number');
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}}

function toggleChain(id) {{
  var el = document.getElementById(id);
  var arrow = document.getElementById(id + '-arrow');
  var open = el.style.display !== 'none';
  el.style.display = open ? 'none' : 'block';
  if (arrow) arrow.style.transform = open ? '' : 'rotate(180deg)';
}}
</script>

</body>
</html>"""
