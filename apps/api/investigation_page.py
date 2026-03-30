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
    """Returns (pill_bg, pill_border, accent, short_copy, bucket_label) — dark-slab accents."""
    if vol <= 25:
        return "#0a2218", "#0d3d2a", "#2e7d32", \
               "Most outlets agree on the basics.", "Low"
    elif vol <= 60:
        return "#2a1c04", "#3d2a06", "#E65100", \
               "Same facts, different spin.", "Moderate"
    else:
        return "#2e0a0a", "#3d0e0e", "#B71C1C", \
               "Parallel realities.", "High"


def _vol_display_num_color(vol: int) -> str:
    """Full saturation volatility color on dark fight cards (matches front page spec)."""
    if vol <= 25:
        return "#66bb6a"
    if vol <= 60:
        return "#FF9800"
    return "#ef5350"


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
        f'font-size:12px;font-weight:500;background:{bg};color:{fg};'
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
    return (f'<span style="font-size:12px;letter-spacing:0.07em;padding:1px 5px;'
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
    note = str(item.get("alignment_note", "") or "")
    story_url = str(item.get("story_url") or "").strip()
    not_found = "not found in sources" in note.lower()
    if not_found:
        note_color = "#5a5752"
        note_style = "font-style:italic"
        link_html = ""
    elif story_url:
        note_color = "#9e9a93"
        note_style = ""
        link_html = (
            f'<a href="{_e(story_url)}" target="_blank" rel="noopener" '
            f'style="font-size:13px;color:#5eead4;margin-top:4px;display:block;'
            f'text-decoration:underline;text-underline-offset:3px">Read coverage ↗</a>'
        )
    else:
        note_color = "#9e9a93"
        note_style = ""
        link_html = ""
    return (
        f'<div style="display:flex;gap:10px;align-items:flex-start;'
        f'padding:8px 0;border-bottom:0.5px solid rgba(255,255,255,0.04)">'
        f'<div style="flex:1;min-width:0">'
        f'<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:3px">'
        f'<span style="font-size:16px;font-weight:500;color:#f0ede8">'
        f'{_e(item.get("outlet",""))}</span>'
        f'{_outlet_badge(item.get("outlet_type",""))}</div>'
        f'<div style="font-size:15px;color:{note_color};line-height:1.5;{note_style}">'
        f'{_e(note)}</div>{link_html}'
        f'</div>'
        f'<div style="width:6px;height:6px;border-radius:50%;background:{dot};'
        f'flex-shrink:0;margin-top:6px"></div>'
        f'</div>'
    )


def _chain_items_html(chain: list, side_prefix: str) -> str:
    """Group outlets by country (click to expand), then by media type on this story."""
    if not chain:
        return '<div style="font-size:16px;color:#5a5752;padding:12px 0">No outlets mapped yet.</div>'

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
                f'<div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;'
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
                f'<div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;'
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
            f'<span style="font-size:15px;font-weight:600;color:#f0ede8">{_e(country)}</span>'
            f'<span class="country-chev" style="font-size:13px;color:#e8a020">▾</span>'
            f'<span style="font-size:13px;color:#5a5752;margin-left:auto">'
            f'{n_out} outlet{"s" if n_out != 1 else ""} · {_e(str(len(by_type)))} type{"s" if len(by_type) != 1 else ""}'
            f"</span>"
            f"</summary>"
            f'<div style="padding:4px 14px 14px 14px;border-top:0.5px solid rgba(255,255,255,0.05)">'
            f'{"".join(type_sections)}'
            f"</div>"
            f"</details>"
        )

    hint = (
        '<p style="font-size:16px;color:#5a5752;line-height:1.5;margin:0 0 10px 0">'
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
        'border-radius:20px;font-size:13px;font-weight:600;'
        'background:#E8F5E9;color:#2e7d32;border:1px solid #a5d6a7">✓ Signed</span>'
        if signed else
        '<span style="display:inline-flex;align-items:center;gap:5px;padding:3px 10px;'
        'border-radius:20px;font-size:13px;font-weight:600;'
        'background:#ffebee;color:#B71C1C;border:1px solid #ffcdd2">✗ Unsigned</span>'
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
        f'<div style="display:flex;gap:10px;padding:10px 14px;border-radius:6px;'
        f'background:rgba(230,81,0,0.07);margin-bottom:8px;'
        f'border:1px solid rgba(230,81,0,0.18)">'
        f'<span style="color:#E65100;flex-shrink:0;margin-top:1px">◈</span>'
        f'<span style="font-size:18px;color:#5d4037;line-height:1.5">{_e(w)}</span></div>'
        for w in what_nobody[:6]
    )

    confirmed_html = "".join(
        f'<div style="display:flex;gap:10px;padding:10px 0;'
        f'border-bottom:1px solid rgba(26,26,26,0.08)">'
        f'<div style="width:5px;height:5px;border-radius:50%;background:#00695c;'
        f'flex-shrink:0;margin-top:8px"></div>'
        f'<div><div style="font-size:18px;color:#1a1a1a;line-height:1.45">'
        f'{_e(c.get("title","") if isinstance(c,dict) else str(c))}</div>'
        f'<div style="font-size:15px;color:#666;margin-top:2px">'
        f'{_e(c.get("outlet","") if isinstance(c,dict) else "")} · '
        f'{_e(c.get("date","")   if isinstance(c,dict) else "")}</div></div></div>'
        for c in confirmed[:5]
    ) if confirmed else ""

    both_html = "".join(
        f'<div style="font-size:18px;color:#333;padding:8px 0;'
        f'border-bottom:1px solid rgba(26,26,26,0.08)">'
        f'<span style="color:#888;margin-right:10px">—</span>{_e(w)}</div>'
        for w in what_both
    )

    receipt_rows = "".join(
        f'<div style="display:grid;grid-template-columns:140px 1fr;gap:12px;'
        f'padding:9px 0;border-bottom:1px solid rgba(26,26,26,0.1)">'
        f'<div style="font-size:13px;letter-spacing:0.07em;text-transform:uppercase;'
        f'color:#666">{k}</div>'
        f'<div style="font-family:&quot;IBM Plex Mono&quot;,monospace;font-size:13px;color:{c};'
        f'word-break:break-all;line-height:1.5">{_e(v)}</div></div>'
        for k, v, c in [
            ("Receipt ID",     rid,   "#444"),
            ("Type",           rtype, "#444"),
            ("Signed",
             "true — Ed25519 signature present" if signed else "false",
             "#2e7d32" if signed else "#B71C1C"),
            ("Timestamp",      timestamp,  "#444"),
            ("Schema version", schema_ver, "#444"),
            ("Signing key",
             (public_key[:28] + "…") if public_key else "—", "#444"),
        ]
    )

    # ── No-coalition empty state (on paper) ─────────────────────
    no_coalition_html = """
<div class="inv-paper-card" style="padding:28px 24px;text-align:center;margin-bottom:32px">
  <div style="font-size:18px;color:#444;line-height:1.7">
    We don't see enough disagreement here to map a split story yet.
  </div>
  <div style="font-size:16px;color:#888;margin-top:8px">
    Coalition analysis runs in the background — check back in a minute.
  </div>
</div>"""

    # ── Coalition section ────────────────────────────────────────
    coalition_fight_html = ""
    coalition_tail_html = ""
    coalition_section = no_coalition_html
    if coalition:
        a_preview = _chain_preview(a_chain)
        b_preview = _chain_preview(b_chain)
        a_chain_html = _chain_items_html(a_chain, "a")
        b_chain_html = _chain_items_html(b_chain, "b")

        vnum = _vol_display_num_color(vol)
        coalition_fight_html = f"""
<!-- VOLATILITY PILL -->
<div style="margin-bottom:24px">
  <div style="display:inline-flex;align-items:center;gap:12px;
              padding:10px 20px;border-radius:28px;
              background:{pill_bg};border:0.5px solid {pill_border}">
    <span style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;
                 color:{accent};font-weight:600">VOLATILITY</span>
    <span style="font-family:'Playfair Display',serif;font-size:52px;font-weight:900;
                 color:{vnum};line-height:1;letter-spacing:-0.02em">{vol}</span>
    <span style="font-size:14px;color:{accent};opacity:0.75">/ 100</span>
  </div>
  <div style="display:flex;align-items:center;gap:8px;margin-top:8px;padding-left:2px">
    <span style="font-size:16px;color:#9e9a93">{_e(vol_copy)}</span>
    <button onclick="toggleWhyNumber()" style="font-size:13px;color:#5a5752;
            background:none;border:none;cursor:pointer;padding:0;
            text-decoration:underline;text-underline-offset:3px">
      Why this number?
    </button>
  </div>
  <div id="why-number" style="display:none;margin-top:10px;padding:12px 16px;
       border-radius:8px;background:rgba(0,0,0,0.35);border:0.5px solid rgba(255,255,255,0.08);
       font-size:16px;color:#c8c4bc;line-height:1.6;max-width:520px">
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
  <div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;
              color:{accent};margin-bottom:8px;font-weight:600">Where the story splits</div>
  <div style="font-size:16px;color:#F7F4EF;line-height:1.65">{_e(irreconcilable_gap)}</div>
</div>

<!-- TWO ANCHOR CARDS -->
<div style="display:flex;gap:1px;background:rgba(247,244,239,0.12);
            border-radius:14px;overflow:hidden;margin-bottom:24px">

  <!-- SIDE A -->
  <div style="flex:1;background:#141414;padding:24px 22px">
    <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                color:#7eb8ff;margin-bottom:8px">{_e(a_anchor)}</div>
    <div style="font-family:'Playfair Display',serif;font-size:22px;font-weight:700;
                color:#F7F4EF;margin-bottom:10px;line-height:1.2">{_e(a_label)}</div>
    <div style="font-size:18px;color:#9e9a93;line-height:1.6;margin-bottom:16px">
      {_e(a_summary)}</div>
    <div style="margin-bottom:10px">
      <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                  color:#5a5752;margin-bottom:5px">Emphasizes</div>
      {_pills(a_em, "green")}
    </div>
    <div>
      <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                  color:#5a5752;margin-bottom:5px">Minimizes</div>
      {_pills(a_mn, "red")}
    </div>
  </div>

  <!-- VS -->
  <div style="display:flex;align-items:center;justify-content:center;
              background:#141414;padding:0 4px;min-width:36px">
    <span style="background:#111;border:0.5px solid rgba(255,255,255,0.1);
                 border-radius:20px;padding:5px 8px;
                 font-size:12px;font-weight:700;color:#5a5752">VS</span>
  </div>

  <!-- SIDE B -->
  <div style="flex:1;background:#141414;padding:24px 22px">
    <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                color:#ff8a80;margin-bottom:8px">{_e(b_anchor)}</div>
    <div style="font-family:'Playfair Display',serif;font-size:22px;font-weight:700;
                color:#F7F4EF;margin-bottom:10px;line-height:1.2">{_e(b_label)}</div>
    <div style="font-size:18px;color:#9e9a93;line-height:1.6;margin-bottom:16px">
      {_e(b_summary)}</div>
    <div style="margin-bottom:10px">
      <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                  color:#5a5752;margin-bottom:5px">Emphasizes</div>
      {_pills(b_em, "green")}
    </div>
    <div>
      <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
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
        <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                    color:#5b9fff;margin-bottom:3px">Who's on this side</div>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div style="font-size:15px;font-weight:600;color:#f0ede8">{_e(a_label)}</div>
          <div style="font-size:15px;color:#5a5752;display:flex;align-items:center;gap:6px">
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
        <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                    color:#e05050;margin-bottom:3px">Who's on this side</div>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div style="font-size:15px;font-weight:600;color:#f0ede8">{_e(b_label)}</div>
          <div style="font-size:15px;color:#5a5752;display:flex;align-items:center;gap:6px">
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
"""

        coalition_tail_html = (
            (
                "<div class=\"inv-paper-block\" style='margin-bottom:32px'>"
                "<div style='font-size:13px;letter-spacing:0.12em;text-transform:uppercase;"
                "color:#555;margin-bottom:10px'>What everyone agrees on</div>"
                "<div class='inv-paper-card' style='padding:4px 18px'>" + both_html + "</div></div>"
            )
            if both_html
            else ""
        )
        coalition_tail_html += f"""
<div class="inv-paper-block" style="margin-bottom:32px">
  <div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;
              color:#555;margin-bottom:10px">The specific claim in dispute</div>
  <div class="inv-paper-card" style="padding:14px 18px;border-left:3px solid rgba(26,26,26,0.2);
              font-size:18px;color:#555;line-height:1.7;font-style:italic">
    {_e(contested_claim)}
  </div>
</div>
"""
        coalition_section = (
            f'<div class="inv-fight-slab">{coalition_fight_html}</div>'
            + coalition_tail_html
        )
    else:
        coalition_section = no_coalition_html

    reporter_strip = f"""
<div class="reporter-only inv-reporter-tools">
  <h3 class="inv-rt-hed">Reporter tools</h3>
  <p class="inv-mono">Receipt: <span id="inv-rid">{_e(rid)}</span>
    <button type="button" class="inv-btn" onclick="navigator.clipboard.writeText(document.getElementById('inv-rid').textContent.trim())">Copy</button>
    <a class="inv-btn" href="/v1/coalition-map/{_e(rid)}">Coalition JSON ↗</a>
    <a class="inv-btn" href="{_e(a_url)}" target="_blank" rel="noopener">Source ↗</a>
  </p>
  <p class="inv-mono-sub">Open in:
    <span class="inv-btn inv-btn-ghost">LexisNexis</span>
    <span class="inv-btn inv-btn-ghost">Google Pinpoint</span>
    <span class="inv-btn inv-btn-ghost">Bellingcat Toolkit</span>
  </p>
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(a_title or "Investigation")} — PUBLIC EYE</title>
<meta name="description" content="{_e((irreconcilable_gap or narrative)[:160])}">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  html{{scroll-behavior:smooth}}
  body.inv-body{{
    font-family:"IBM Plex Sans",-apple-system,sans-serif;
    font-size:18px;
    background:#F7F4EF;color:#1a1a1a;min-height:100vh;
  }}
  a{{color:#0d47a1;text-decoration:underline;text-underline-offset:3px}}
  a:hover{{opacity:.85}}
  button:hover{{opacity:.85}}
  .inv-fight-slab{{
    background:#111;color:#F7F4EF;padding:28px 24px 32px;border-radius:8px;margin-bottom:8px;
    border:1px solid rgba(26,26,26,0.18);
  }}
  .inv-paper-card{{background:#fff;border:1px solid rgba(26,26,26,0.15);border-radius:4px;}}
  .reporter-only{{display:none;}}
  body.inv-reporter-mode .reporter-only{{display:block !important;}}
  body.inv-reporter-mode .inv-reader-soft{{display:none !important;}}
  .inv-mode{{display:inline-flex;gap:4px;margin-left:12px;}}
  .inv-mode button{{
    font-family:"IBM Plex Sans",sans-serif;font-size:12px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;
    padding:6px 12px;border:1px solid rgba(26,26,26,0.2);background:#fff;cursor:pointer;border-radius:2px;
  }}
  .inv-mode button.active{{background:#1a1a1a;color:#F7F4EF;border-color:#1a1a1a;}}
  .inv-reporter-tools{{margin:24px 0;padding:18px;background:#F5F5F5;border:1px solid rgba(26,26,26,0.12);border-radius:4px;}}
  .inv-rt-hed{{font-size:13px;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:10px;}}
  .inv-mono{{font-family:"IBM Plex Mono",monospace;font-size:14px;line-height:1.65;color:#333;}}
  .inv-mono-sub{{font-family:"IBM Plex Mono",monospace;font-size:13px;color:#555;margin-top:8px;}}
  .inv-btn{{display:inline-block;margin-left:6px;padding:3px 8px;font-size:12px;border:1px solid #999;background:#fff;border-radius:2px;cursor:pointer;text-decoration:none;color:#1a1a1a;}}
  .inv-btn-ghost{{opacity:0.55;cursor:default;}}
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
<body class="inv-body">

<header style="display:flex;align-items:center;justify-content:space-between;
               flex-wrap:wrap;gap:12px;
               padding:16px 36px;border-bottom:1px solid rgba(26,26,26,0.2);
               position:sticky;top:0;z-index:20;
               background:rgba(247,244,239,0.96);backdrop-filter:blur(12px)">
  <a href="/" style="font-family:'Playfair Display',serif;font-size:18px;font-weight:700;
                      letter-spacing:0.06em;color:#1a1a1a;text-decoration:none">
    PUBLIC EYE
  </a>
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
    <form action="/search" method="get" style="display:inline-flex;gap:6px;align-items:center;margin-right:4px">
      <input type="search" name="q" placeholder="Conflicts…" autocomplete="off" aria-label="Search conflicts"
        style="width:min(140px,32vw);padding:5px 8px;font-size:12px;border:1px solid rgba(26,26,26,0.2);font-family:inherit" />
      <button type="submit" style="padding:5px 10px;font-size:12px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;border:1px solid #1a1a1a;background:#1a1a1a;color:#F7F4EF;cursor:pointer">Go</button>
    </form>
    <span class="inv-reader-soft">{signed_badge}</span>
    <div class="inv-mode">
      <button type="button" id="inv-mode-reader" class="active">Reader</button>
      <button type="button" id="inv-mode-reporter">Reporter</button>
    </div>
    <a href="#verification-full" style="font-size:13px;color:#555;letter-spacing:0.04em;text-decoration:none" class="reporter-only">
      Receipt ↓
    </a>
    <a href="#verification" style="font-size:13px;color:#555;letter-spacing:0.04em;text-decoration:none" class="inv-reader-soft inv-receipt-jump">
      Receipt ↓
    </a>
  </div>
</header>

<div style="max-width:900px;margin:0 auto;padding:0 36px 48px">

<!-- HOOK -->
<div style="padding:40px 0 24px">
  {f'<div style="margin-bottom:10px"><a href="{_e(a_url)}" target="_blank" rel="noopener" style="font-size:13px;letter-spacing:0.06em;text-transform:uppercase;color:#666">{_e(a_pub)} ↗</a></div>' if a_url else ""}
  <h1 style="font-family:'Playfair Display',serif;font-size:clamp(26px,4vw,38px);
              font-weight:700;line-height:1.15;letter-spacing:-0.02em;color:#1a1a1a;
              margin-bottom:0;max-width:720px">
    {_e(a_title or "Untitled Investigation")}
  </h1>
</div>

<div style="height:1px;background:rgba(26,26,26,0.2);margin-bottom:28px"></div>

{coalition_section}

<!-- SUMMARY (after the fight) -->
{f'<div class="inv-paper-card inv-reader-soft" style="margin-bottom:32px;padding:18px 22px"><div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#555;margin-bottom:8px">Summary</div><p style="font-size:18px;color:#333;line-height:1.7">{_e(str(narrative)[:400])}{"…" if len(str(narrative))>400 else ""}</p></div>' if narrative else ""}

<!-- WHAT NO ONE IS REALLY TALKING ABOUT -->
{f'<div class="inv-reader-soft" style="margin-bottom:32px"><div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#555;margin-bottom:12px">What no one is really talking about</div>{nobody_html}</div>' if nobody_html else ""}

<!-- CROSS-CORROBORATED -->
{f'<div class="reporter-only" style="margin-bottom:32px"><div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#555;margin-bottom:12px">Cross-corroborated</div><div class="inv-paper-card" style="padding:4px 18px">{confirmed_html}</div></div>' if confirmed_html else ""}

<div style="height:1px;background:rgba(26,26,26,0.2);margin-bottom:32px"></div>

{reporter_strip}

<!-- VERIFICATION (reader: one-line access) -->
<div id="verification" class="inv-reader-soft" style="margin-bottom:28px;padding:16px 18px;background:#fff;border:1px solid rgba(26,26,26,0.12);border-radius:6px">
  <p style="font-size:18px;line-height:1.65;color:#333">
    {signed_badge}
    <span style="margin-left:6px">This investigation is backed by a signed, verifiable receipt.</span>
    <a href="/verify?id={_e(rid)}" style="font-weight:600;margin-left:4px">Verify independently ↗</a>
    <span style="color:#666"> · Use <strong>Reporter</strong> mode for IDs, raw JSON, and research links.</span>
  </p>
</div>

<!-- VERIFICATION (reporter: full chain) -->
<div id="verification-full" class="reporter-only" style="margin-bottom:48px">
  <div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;
              color:#555;margin-bottom:12px">Verification</div>
  <div style="border:1px solid rgba(26,26,26,0.15);border-radius:8px;
              background:#fff;overflow:hidden">
    <div style="padding:16px 20px;border-bottom:1px solid rgba(26,26,26,0.1);
                display:flex;align-items:center;justify-content:space-between;
                flex-wrap:wrap;gap:10px">
      <div>
        <div style="font-size:18px;font-weight:600;color:#1a1a1a;margin-bottom:3px">
          Cryptographically signed
        </div>
        <div style="font-size:16px;color:#666">
          Ed25519 · JCS canonical payload · independently verifiable
        </div>
      </div>
      {signed_badge}
    </div>
    <div style="padding:8px 20px">{receipt_rows}</div>
    {f'<div style="padding:12px 20px;border-top:1px solid rgba(26,26,26,0.08);background:#fafafa"><div style="font-size:13px;letter-spacing:0.07em;text-transform:uppercase;color:#666;margin-bottom:5px">Ed25519 Signature</div><div style="font-family:&quot;IBM Plex Mono&quot;,monospace;font-size:13px;color:#555;word-break:break-all;line-height:1.6">{_e(signature)}</div></div>' if signature else ""}
    <div style="padding:14px 20px;border-top:1px solid rgba(26,26,26,0.08);
                display:flex;gap:8px;flex-wrap:wrap">
      <a href="/verify?id={_e(rid)}"
         style="font-size:13px;padding:8px 14px;border-radius:4px;
                border:1px solid rgba(26,26,26,0.2);color:#333;text-decoration:none">
        Verify independently ↗
      </a>
      <a href="/r/{_e(rid)}" target="_blank"
         style="font-size:13px;padding:8px 14px;border-radius:4px;
                border:1px solid rgba(26,26,26,0.2);color:#333;text-decoration:none">
        Raw JSON ↗
      </a>
    </div>
  </div>
</div>

<div style="padding-bottom:40px;display:flex;align-items:center;
            justify-content:space-between;flex-wrap:wrap;gap:12px;
            border-top:1px solid rgba(26,26,26,0.2);padding-top:20px">
  <div style="font-size:13px;color:#666">PUBLIC EYE · Receipts, not verdicts.</div>
  <a href="/verify?id={_e(rid)}" class="reporter-only" style="font-size:13px;color:#666;text-decoration:none">Independent verification ↗</a>
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

(function() {{
  var KEY = 'publicEyeMode';
  function setMode(rep) {{
    document.body.classList.toggle('inv-reporter-mode', rep);
    var r = document.getElementById('inv-mode-reader');
    var p = document.getElementById('inv-mode-reporter');
    if (r) r.classList.toggle('active', !rep);
    if (p) p.classList.toggle('active', rep);
    try {{ localStorage.setItem(KEY, rep ? 'reporter' : 'reader'); }} catch (e) {{}}
  }}
  try {{
    if (localStorage.getItem(KEY) === 'reporter') setMode(true);
  }} catch (e) {{}}
  var br = document.getElementById('inv-mode-reader');
  var bp = document.getElementById('inv-mode-reporter');
  if (br) br.onclick = function() {{ setMode(false); }};
  if (bp) bp.onclick = function() {{ setMode(true); }};
}})();
</script>

</body>
</html>"""
