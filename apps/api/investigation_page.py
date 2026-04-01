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
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus, urlparse

from echo_chamber import compute_echo_chamber_score, merge_sources_for_echo


_SURFACE_ADAPTER_IDS = frozenset({"surface", "layer_surface", "surface_adapter"})
_DEFERRED_NOISE_ADAPTER_KEYS = frozenset({"courtlistener", "congress", "fec"})
_SKIP_VERIFICATION_ADAPTERS = frozenset({"actor_ledger"})
_GOOGLE_NEWS_SEARCH = "https://news.google.com/search?q="
_WIKI_SEARCH = "https://en.wikipedia.org/wiki/Special:Search?search="

REVISION_TYPES: dict[str, tuple[str, str, str]] = {
    "REVERSED": ("REVERSED", "#b71c1c", "#ffebee"),
    "SOFTENED": ("SOFTENED", "#e65100", "#fff3e0"),
    "STRENGTHENED": ("STRENGTHENED", "#1b5e20", "#e8f5e9"),
    "CLARIFIED": ("CLARIFIED", "#0d47a1", "#e3f2fd"),
    "CONTRADICTED": ("CONTRADICTED BY RECORD", "#4a148c", "#f3e5f5"),
    "UNKNOWN": ("CHANGED", "#555", "#f5f5f5"),
}

OUTLET_HOMEPAGES: dict[str, str] = {
    "AP News": "https://apnews.com",
    "Reuters": "https://www.reuters.com",
    "BBC": "https://www.bbc.com/news",
    "New York Times": "https://www.nytimes.com",
    "Washington Post": "https://www.washingtonpost.com",
    "The Guardian": "https://www.theguardian.com",
    "Fox News": "https://www.foxnews.com",
    "Der Spiegel": "https://www.spiegel.de/international",
    "Le Monde": "https://www.lemonde.fr",
    "Al Jazeera": "https://www.aljazeera.com",
    "ProPublica": "https://www.propublica.org",
    "NaturalNews.com": "https://www.naturalnews.com",
    "Washington Examiner": "https://www.washingtonexaminer.com",
    "Miami Herald": "https://www.miamiherald.com",
    "Dawn": "https://www.dawn.com",
    "The Hindu": "https://www.thehindu.com",
    "Hindustan Times": "https://www.hindustantimes.com",
    "Euronews": "https://www.euronews.com",
    "El País": "https://elpais.com",
}

_OUTLET_TYPE_ORDER = ("state", "public_broadcaster", "private")
_OUTLET_TYPE_LABEL = {
    "state": "State-affiliated media",
    "public_broadcaster": "Public broadcasters",
    "private": "Private / independent",
}

OUTLET_DOMAINS: dict[str, str] = {
    "cnn": "cnn.com",
    "fox news": "foxnews.com",
    "msnbc": "msnbc.com",
    "bbc": "bbc.com",
    "reuters": "reuters.com",
    "ap news": "apnews.com",
    "associated press": "apnews.com",
    "new york times": "nytimes.com",
    "nyt": "nytimes.com",
    "washington post": "washingtonpost.com",
    "the guardian": "theguardian.com",
    "daily mail": "dailymail.co.uk",
    "times of israel": "timesofisrael.com",
    "al jazeera": "aljazeera.com",
    "rt": "rt.com",
    "tass": "tass.com",
    "xinhua": "xinhuanet.com",
    "global times": "globaltimes.cn",
    "press tv": "presstv.ir",
    "presstv": "presstv.ir",
    "der spiegel": "spiegel.de",
    "le monde": "lemonde.fr",
    "dawn": "dawn.com",
    "haaretz": "haaretz.com",
    "indianapolis star": "indystar.com",
    "indystar": "indystar.com",
    "chicago tribune": "chicagotribune.com",
    "los angeles times": "latimes.com",
    "new york post": "nypost.com",
    "politico": "politico.com",
    "axios": "axios.com",
    "the hill": "thehill.com",
    "npr": "npr.org",
}


def _e(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


def _outlet_homepage_url(outlet: str) -> str | None:
    o = (outlet or "").strip()
    if not o:
        return None
    if o in OUTLET_HOMEPAGES:
        return OUTLET_HOMEPAGES[o]
    ol = o.lower()
    for k, v in OUTLET_HOMEPAGES.items():
        if k.lower() == ol:
            return v
    return None


def _outlet_link_html(outlet: str) -> str:
    o_str = str(outlet).strip()
    if not o_str:
        return ""
    url = _outlet_homepage_url(o_str) or f"{_GOOGLE_NEWS_SEARCH}{quote_plus(o_str)}"
    return (
        f'<a href="{_e(url)}" target="_blank" rel="noopener" class="outlet-link">{_e(o_str)}</a>'
    )


def _claim_subject_link_html(subject: str) -> str:
    s = (subject or "").strip()
    if not s:
        return ""
    return (
        f'<a href="{_GOOGLE_NEWS_SEARCH}{quote_plus(s)}" target="_blank" rel="noopener" '
        f'class="claim-subject-link">{_e(s)}</a>'
    )


def _claim_body_link_html(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    enc = quote_plus(t[:150])
    return (
        f'<a href="{_GOOGLE_NEWS_SEARCH}{enc}" target="_blank" rel="noopener" '
        f'class="claim-text-link">{_e(t)}</a>'
    )


def _name_wiki_link(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return ""
    return (
        f'<a href="{_WIKI_SEARCH}{quote_plus(n)}" target="_blank" rel="noopener" '
        f'class="entity-ref-link">{_e(n)}</a>'
    )


def _courtlistener_absolute_url(path_or_url: str) -> str:
    u = (path_or_url or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if u.startswith("/"):
        return f"https://www.courtlistener.com{u}"
    return u


def _vol_theme(vol: int) -> tuple[str, str, str, str, str]:
    """Returns (pill_bg, pill_border, accent, short_copy, bucket_label) — light-slab coalition UI."""
    if vol <= 25:
        return "#F0FFF4", "#0d3d2a", "#2e7d32", \
               "Most outlets agree on the basics.", "Low"
    elif vol <= 60:
        return "#FFFBF0", "#3d2a06", "#E65100", \
               "Same facts, different spin.", "Moderate"
    else:
        return "#FFF5F5", "#3d0e0e", "#B71C1C", \
               "Parallel realities.", "High"


def _vol_display_num_color(vol: int) -> str:
    """Full saturation volatility color on dark fight cards (matches front page spec)."""
    if vol <= 25:
        return "#66bb6a"
    if vol <= 60:
        return "#FF9800"
    return "#ef5350"


def _safe_list(val: Any) -> list:
    return val if isinstance(val, list) else []


def _fmt_generated_at(ts: Any) -> str:
    if not ts:
        return "—"
    s = str(ts).strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
        return dt.strftime("%B %d, %Y · %H:%M UTC")
    except ValueError:
        return s


_ECHO_COMPONENT_BASIS: dict[str, str] = {
    "claim_overlap": "similar wording across source notes",
    "source_diversity": "outlet and geographic diversity",
    "coalition_balance": "two-sided balance of sources",
    "primary_source_distance": "concentration on a few domains",
    "framing_variation": "similar framing across outlets",
}


def _echo_chamber_basis_plain_language(
    echo: dict[str, Any],
    gp_raw: dict[str, Any] | None,
) -> str:
    """Plain-language basis for the echo score; avoids opaque labels like 'mixed'."""
    conf: dict[str, Any] = {}
    if isinstance(gp_raw, dict):
        raw = gp_raw.get("confidence_breakdown")
        conf = raw if isinstance(raw, dict) else {}
    pet = str(conf.get("primary_evidence_type") or "").strip().lower()
    if pet and pet != "mixed":
        return pet.replace("_", " ")
    components = echo.get("components") if isinstance(echo.get("components"), dict) else {}
    ranked = sorted(
        ((k, float(v)) for k, v in components.items() if isinstance(v, (int, float))),
        key=lambda x: -x[1],
    )
    if not ranked:
        return "source independence and clustering in the cited coverage"
    parts = [_ECHO_COMPONENT_BASIS.get(k, k.replace("_", " ")) for k, _ in ranked[:2]]
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} and {parts[1]}"


def _echo_chamber_standalone_html(
    echo: dict[str, Any],
    gp_raw: dict[str, Any] | None = None,
) -> str:
    """Echo block for article_analysis when no coalition map (score /20 components)."""
    if not isinstance(echo, dict):
        return ""
    try:
        score = float(echo.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    label = str(echo.get("label", "") or "").lower()
    interp = str(echo.get("interpretation", "") or "")
    components = echo.get("components") if isinstance(echo.get("components"), dict) else {}
    rounded = int(round(score))
    if score < 30:
        pill_bg, border_c, accent = "#F0FFF4", "#22C55E", "#15803d"
    elif score <= 60:
        pill_bg, border_c, accent = "#FFFBF0", "#F59E0B", "#b45309"
    else:
        pill_bg, border_c, accent = "#FFF5F5", "#EF4444", "#b91c1c"
    comp_rows = "".join(
        f'<div style="display:flex;justify-content:space-between;'
        f'padding:6px 0;border-bottom:1px solid rgba(0,0,0,0.05);font-size:14px">'
        f'<span style="color:#6B7280">{_e(k.replace("_", " ").title())}</span>'
        f'<span style="font-weight:600;color:#111827">{_e(v)}/20</span></div>'
        for k, v in components.items()
    )
    basis_phrase = _echo_chamber_basis_plain_language(echo, gp_raw)
    echo_conf_note = (
        f'<div class="echo-conf-note">Analysis grounded in: '
        f'{_e(basis_phrase)}</div>'
    )
    return f"""
<div class="inv-paper-card inv-reader-soft" style="margin-bottom:28px;padding:20px 22px;
            border:1px solid rgba(26,26,26,0.12)">
  <div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;
              color:#555;margin-bottom:12px">Echo chamber score</div>
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap">
    <div style="display:inline-flex;align-items:center;gap:8px;padding:8px 16px;
                border-radius:20px;background:{pill_bg};border:1px solid {border_c}55">
      <span style="font-family:'Playfair Display',serif;font-size:32px;font-weight:900;
                   color:#111827">{rounded}</span>
      <span style="font-size:14px;color:{accent}">/ 100</span>
      <span style="font-size:13px;font-weight:600;color:{accent};text-transform:capitalize">
        — {_e(label or "—")}
      </span>
    </div>
    <a href="/methodology#echo-chamber" style="font-size:13px;color:#9CA3AF">How this is calculated →</a>
  </div>
  <p style="font-size:17px;color:#444;line-height:1.65;margin-bottom:16px">{_e(interp)}</p>
  {echo_conf_note}
  <div style="border-top:1px solid rgba(0,0,0,0.06);padding-top:12px">
    <div style="font-size:12px;letter-spacing:0.1em;text-transform:uppercase;
                color:#9CA3AF;font-weight:600;margin-bottom:8px">Components</div>
    {comp_rows or '<div style="font-size:14px;color:#888">No component breakdown stored.</div>'}
  </div>
</div>"""


def _status_color(status: str) -> str:
    s = (status or "").lower()
    if s == "found":
        return "#15803d"
    if s == "not_found":
        return "#b45309"
    if s == "deferred":
        return "#6b7280"
    return "#57534e"


def _claim_text_dedupe_key(raw: str) -> str:
    t = unicodedata.normalize("NFKC", str(raw or ""))
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def _deduplicate_claims(claims: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        key = _claim_text_dedupe_key(str(c.get("claim", "") or ""))
        if not key:
            result.append(c)
            continue
        if key not in seen:
            seen.add(key)
            result.append(c)
    return result


def _adapter_is_surface(adapter_name: str) -> bool:
    n = (adapter_name or "").strip().lower().replace(" ", "_").replace("-", "_")
    return n in _SURFACE_ADAPTER_IDS


def _verification_result_dict(v: dict[str, Any]) -> dict[str, Any]:
    """Unwrap result payload (dict, JSON string, or ring-shaped { content: ... })."""
    raw: Any = v.get("result")
    if isinstance(raw, str) and raw.strip():
        s = raw.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                raw = json.loads(s)
            except json.JSONDecodeError:
                return {}
    if not isinstance(raw, dict):
        return {}
    inner = raw.get("content")
    if isinstance(inner, dict) and any(
        k in inner
        for k in ("what", "who", "when", "cultural_substrate", "absent_fields", "what_confidence_tier")
    ):
        return inner
    return raw


def _flat_adapter_brief(result: dict[str, Any]) -> str:
    w = result.get("what")
    if isinstance(w, str) and w.strip():
        return w.strip()
    who = result.get("who")
    if isinstance(who, list):
        names: list[str] = []
        for item in who:
            if isinstance(item, dict):
                n = str(item.get("name", "") or "").strip()
                if n:
                    names.append(n)
            elif item:
                names.append(str(item).strip())
        if names:
            return ", ".join(names)
    elif who:
        return str(who).strip()
    when = result.get("when")
    if isinstance(when, dict):
        ea = str(when.get("earliest_appearance", "") or "").strip()
        if ea:
            return ea
        src = str(when.get("source", "") or "").strip()
        if src:
            return src
    return ""


def _adapter_key(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "_").replace("-", "_")


def _is_generic_surface_what(what: str) -> bool:
    w = (what or "").strip().lower()
    if not w:
        return True
    prefixes = (
        "a proper name",
        "a reference to a person",
        "a named individual",
        "pete hegseth is a named",
        "reference to pete hegseth",
    )
    if any(w.startswith(p) for p in prefixes):
        return True
    if "only a name" in w or "only the name" in w:
        return True
    if "no additional context" in w and "name only" in w:
        return True
    if "without additional descriptive context" in w:
        return True
    return False


def _who_entry_name(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("name", "") or "").strip()
    return str(item).strip() if item else ""


def _name_likely_organization(name: str) -> bool:
    n = (name or "").lower()
    hints = (
        "department",
        "ministry",
        "university",
        "college",
        " inc",
        " llc",
        " ltd",
        "corporation",
        "fund",
        "foundation",
        "committee",
        "commission",
        "agency",
        "bureau",
        "office of",
        "bbc",
        "cnn",
        "association",
        "society",
        "institute",
        "organization",
        "organisation",
        "parliament",
        "congress ",
        "court ",
        "times",
        "tribune",
        "herald",
        "news",
        "press",
        "group",
        "the white house",
        "pentagon",
    )
    return any(h in n for h in hints)


def _surface_result_meaningful(result: dict[str, Any], subject: str) -> bool:
    if not result:
        return False
    subj_k = _claim_text_dedupe_key(subject)
    what = str(result.get("what", "") or "").strip()
    if what and not _is_generic_surface_what(what):
        return True
    cs = str(result.get("cultural_substrate", "") or "").strip()
    if cs:
        return True
    when = result.get("when", {})
    if isinstance(when, dict):
        ea = str(when.get("earliest_appearance", "") or "").strip()
        if ea and ea not in _WHEN_SKIP:
            return True
    who = result.get("who")
    if isinstance(who, list):
        names = [_who_entry_name(x) for x in who if _who_entry_name(x)]
        if len(names) > 1:
            return True
        if len(names) == 1:
            nm = names[0]
            if _name_likely_organization(nm):
                return True
            if subj_k and _claim_text_dedupe_key(nm) != subj_k:
                return True
    return False


def _should_omit_verification_row(
    adapter: str, status: str, result: dict[str, Any], subject: str
) -> bool:
    ad = _adapter_key(adapter)
    st = (status or "").lower()
    if ad in _DEFERRED_NOISE_ADAPTER_KEYS and st == "deferred":
        return True
    if _adapter_is_surface(adapter):
        cs = str(result.get("cultural_substrate") or "").strip()
        if not _surface_result_meaningful(result, subject) and not cs:
            return True
        return False
    return False


def _brief_has_reader_value(
    brief_plain: str, surface_block: str, st_l: str, v: dict[str, Any]
) -> bool:
    if surface_block:
        return True
    if st_l == "searched_none_found":
        return True
    if st_l == "error" and str(v.get("detail", "") or "").strip():
        return True
    b = (brief_plain or "").strip()
    if not b:
        return False
    bl = b.lower()
    if bl == "structural_heuristic":
        return False
    m = re.match(r"^(.+?)\s*\(\s*structural_heuristic\s*\)\s*$", b, re.I | re.DOTALL)
    if m:
        core = m.group(1).strip()
        if not core or _is_generic_surface_what(core):
            return False
    if _is_generic_surface_what(b):
        return False
    return True


def _courtlistener_verification_html(status: str, result: dict[str, Any]) -> str:
    st_l = (status or "").lower()
    if st_l == "searched_none_found":
        return (
            '<div class="verification-row verification-courtlistener">'
            '<span style="font-weight:600">courtlistener</span>: '
            '<span style="color:#6b7280;font-weight:600">searched — no opinions matched</span>'
            '<div class="court-snippet">'
            "Federal court opinions were searched on CourtListener; nothing in the index "
            "matched this claim closely enough to list here."
            "</div></div>"
        )
    case_name = str(result.get("case_name") or "Unknown case")
    court = str(result.get("court") or "")
    date_filed = str(result.get("date_filed") or "")
    url = str(result.get("url") or "")
    full_url = _courtlistener_absolute_url(url)
    snippet = str(result.get("snippet") or result.get("summary") or "")[:300]
    matches = 0
    try:
        matches = int(result.get("matches_count") or 0)
    except (TypeError, ValueError):
        matches = 0
    extra = max(0, matches - 1)
    link = (
        f'<a href="{_e(full_url)}" target="_blank" rel="noopener" '
        f'class="court-case-link">{_e(case_name)}</a>'
        if full_url
        else _e(case_name)
    )
    meta_parts = [p for p in (court, date_filed) if p]
    meta = (
        f'<div class="court-meta">{" · ".join(_e(p) for p in meta_parts)}</div>'
        if meta_parts
        else ""
    )
    snip = f'<div class="court-snippet">“{_e(snippet)}”</div>' if snippet else ""
    more = ""
    if extra > 0:
        more = (
            f'<div class="court-meta">{extra} additional match'
            f'{"" if extra == 1 else "es"} in search results</div>'
        )
    return (
        f'<div class="verification-row verification-courtlistener">'
        f'<span style="font-weight:600">courtlistener</span>: '
        f'<span style="color:#15803d;font-weight:600">found in court record</span>'
        f'<div class="court-result">{link}{meta}{snip}{more}</div></div>'
    )


_WHEN_SKIP = frozenset({
    "not specified",
    "not determinable from source text",
    "Not inferable from input",
    "Not determinable from input",
    "not specified in source text",
    "absent",
})
_WHEN_SOURCE_SKIP = frozenset({
    "input text",
    "source text only",
    "Input text contains name only",
    "Input contains name only",
    "absent",
    "input text contains name only",
})


def _format_surface_result(
    result: dict[str, Any],
    claim_subject: str = "",
) -> str:
    """Format a surface adapter verification result into readable HTML."""
    parts: list[str] = []
    subj = (claim_subject or "").strip()

    who_list = result.get("who", [])
    if isinstance(who_list, list):
        who_names: list[str] = []
        for w in who_list:
            if isinstance(w, dict):
                n = str(w.get("name", "") or "").strip()
                if n:
                    who_names.append(n)
            elif w:
                who_names.append(str(w).strip())
        if who_names:
            linked_who = ", ".join(_name_wiki_link(n) for n in who_names)
            parts.append(f'<span class="surface-field"><b>Who:</b> {linked_who}</span>')

    what = str(result.get("what", "") or "").strip()
    if what:
        parts.append(f'<span class="surface-field"><b>What:</b> {_e(what)}</span>')

    when = result.get("when", {})
    if isinstance(when, dict):
        earliest = str(when.get("earliest_appearance", "") or "").strip()
        when_source = str(when.get("source", "") or "").strip()
        conf_when = str(when.get("confidence_tier", "") or "").strip()
        if earliest and earliest not in _WHEN_SKIP:
            wiki_q = f"{subj} {earliest}".strip()
            when_linked = (
                f'<a href="{_WIKI_SEARCH}{quote_plus(wiki_q)}" target="_blank" rel="noopener" '
                f'class="entity-ref-link">{_e(earliest)}</a>'
            )
            line = (
                f"{when_linked} ({_e(conf_when)})" if conf_when else when_linked
            )
            parts.append(f'<span class="surface-field"><b>When:</b> {line}</span>')
        elif when_source and when_source not in _WHEN_SOURCE_SKIP:
            wiki_q2 = f"{subj} {when_source}".strip()
            ws_linked = (
                f'<a href="{_WIKI_SEARCH}{quote_plus(wiki_q2)}" target="_blank" rel="noopener" '
                f'class="entity-ref-link">{_e(when_source)}</a>'
            )
            parts.append(f'<span class="surface-field"><b>When:</b> {ws_linked}</span>')

    substrate = str(result.get("cultural_substrate", "") or "").strip()
    if substrate:
        sq = quote_plus(substrate[:80])
        sub_linked = (
            f'<a href="{_GOOGLE_NEWS_SEARCH}{sq}" target="_blank" rel="noopener" '
            f'class="entity-ref-link">{_e(substrate)}</a>'
        )
        parts.append(
            f'<span class="surface-field surface-substrate"><b>Context:</b> {sub_linked}</span>'
        )

    tier = str(
        result.get("what_confidence_tier", "") or result.get("confidence_tier", "") or ""
    ).strip()
    if tier:
        parts.append(f'<span class="surface-tier">confidence: {_e(tier)}</span>')

    absent = result.get("absent_fields", [])
    if isinstance(absent, list) and absent:
        absent_s = ", ".join(str(x) for x in absent if x)
        if absent_s:
            parts.append(f'<span class="surface-absent">Missing: {_e(absent_s)}</span>')

    return "<br>".join(parts) if parts else _e("surface record found")


def _collect_http_urls(obj: Any, acc: list[str], local_seen: set[str]) -> None:
    if isinstance(obj, str):
        s = obj.strip()
        if (s.startswith("http://") or s.startswith("https://")) and s not in local_seen:
            local_seen.add(s)
            acc.append(s)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_http_urls(v, acc, local_seen)
    elif isinstance(obj, list):
        for v in obj:
            _collect_http_urls(v, acc, local_seen)


def _sources_section_html(receipt: dict[str, Any]) -> str:
    sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    def add(url: str, label: str, typ: str) -> None:
        u = (url or "").strip()
        if not u or u in seen_urls:
            return
        seen_urls.add(u)
        sources.append({"url": u, "label": label or u, "type": typ})

    article = receipt.get("article", {})
    if isinstance(article, dict) and article.get("url"):
        add(
            str(article["url"]),
            str(article.get("title") or article.get("url") or ""),
            "Original article",
        )

    for claim in _safe_list(receipt.get("claims_verified")):
        if not isinstance(claim, dict):
            continue
        subj = str(claim.get("subject", "") or "")
        for v in _safe_list(claim.get("verifications")):
            if not isinstance(v, dict):
                continue
            res = _verification_result_dict(v)
            url = res.get("source_url") if res else None
            if url:
                add(str(url), str(url), f"Cited in: {subj}" if subj else "Verification source")

    gp = receipt.get("global_perspectives")
    if isinstance(gp, dict):
        http_extra: list[str] = []
        _collect_http_urls(gp, http_extra, set())
        for u in http_extra:
            add(u, u, "Global perspectives")

    if not sources:
        return ""

    rows = []
    for s in sources:
        rows.append(
            f'<div class="source-row">'
            f'<span class="source-type">{_e(s["type"])}</span>'
            f'<a href="{_e(s["url"])}" target="_blank" rel="noopener" class="source-link">'
            f'{_e(s["label"])}</a>'
            f"</div>"
        )

    return (
        f'<section class="sources-section">'
        f'<h3 class="section-label">SOURCES</h3>'
        + "".join(rows)
        + f"</section>"
    )


def _absence_item_html(item: Any) -> str:
    """Single absent angle: legacy string or rich object (Phase 2)."""
    if isinstance(item, str) and item.strip():
        encoded = quote_plus(item.strip())
        return (
            f'<a href="{_GOOGLE_NEWS_SEARCH}{encoded}" '
            f'target="_blank" rel="noopener" class="absent-link absent-link-card">'
            f'<div class="absent-link-row" style="display:flex;align-items:center;gap:10px;'
            f'padding:12px 16px;border-radius:8px;margin-bottom:10px;'
            f'background:rgba(180,83,9,0.09);border:1px solid rgba(180,83,9,0.25)">'
            f'<span class="absent-icon" style="color:#b45315;flex-shrink:0">◆</span>'
            f'<span style="flex:1;min-width:0;font-size:18px;color:#5d4037;line-height:1.5">'
            f"{_e(item.strip())}</span>"
            f'<span class="absent-search-hint">Search →</span></div>'
            f"</a>"
        )
    if not isinstance(item, dict):
        return ""
    topic = str(item.get("topic") or "").strip()
    if not topic:
        return ""
    reason = str(item.get("absence_reason") or "unknown").strip()
    why = str(item.get("why_it_matters") or "").strip()
    suggested_query = str(item.get("suggested_query") or topic).strip()
    suggested_sources = item.get("suggested_sources")
    if not isinstance(suggested_sources, list):
        suggested_sources = []
    encoded = quote_plus(suggested_query)
    reason_labels: dict[str, tuple[str, str, str]] = {
        "too_new": ("TOO NEW", "#1565c0", "#e3f2fd"),
        "too_niche": ("NICHE TOPIC", "#4527a0", "#ede7f6"),
        "avoided": ("POSSIBLY AVOIDED", "#b71c1c", "#ffebee"),
        "poorly_indexed": ("HARD TO FIND", "#e65100", "#fff3e0"),
        "unknown": ("UNKNOWN", "#555", "#f5f5f5"),
    }
    label_text, label_color, label_bg = reason_labels.get(
        reason, ("UNKNOWN", "#555", "#f5f5f5")
    )
    source_urls: dict[str, str] = {
        "OpenSecrets": "https://www.opensecrets.org/search?q=",
        "FEC": "https://www.fec.gov/data/search/?search=",
        "CourtListener": "https://www.courtlistener.com/?q=",
        "Congressional Record": "https://www.congress.gov/search?q=",
        "ProPublica Nonprofit Explorer": "https://projects.propublica.org/nonprofits/",
        "PACER": "https://pacer.uscourts.gov/",
    }
    src_parts: list[str] = []
    q_enc = quote_plus(topic[:120])
    for src in suggested_sources:
        if not src:
            continue
        s = str(src).strip()
        base = source_urls.get(s)
        if base and "propublica.org/nonprofits" in base:
            src_parts.append(
                f'<a href="{base}" target="_blank" rel="noopener" '
                f'class="suggested-source-link">{_e(s)}</a>'
            )
        elif base:
            href = base + q_enc
            src_parts.append(
                f'<a href="{href}" target="_blank" rel="noopener" '
                f'class="suggested-source-link">{_e(s)}</a>'
            )
        else:
            src_parts.append(f'<span class="suggested-source">{_e(s)}</span>')
    sources_html = ""
    if src_parts:
        sources_html = (
            f'<div class="absence-sources"><span class="sources-label">Check:</span> '
            + " · ".join(src_parts)
            + "</div>"
        )
    why_html = f'<div class="absent-why">{_e(why)}</div>' if why else ""
    return f"""
<div class="absent-item-card">
  <div class="absent-item-header">
    <span class="absent-reason-badge" style="background:{label_bg};color:{label_color};">{_e(label_text)}</span>
    <a href="{_GOOGLE_NEWS_SEARCH}{encoded}" target="_blank" rel="noopener" class="absent-topic-link">
      <span class="absent-icon">◆</span> {_e(topic)}
      <span class="absent-search-hint">Search →</span>
    </a>
  </div>
  {why_html}
  {sources_html}
</div>
"""


def _san_html_id(rid: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", (rid or "")[:48]) or "receipt"


def _drift_tracker_html(receipt_id: str) -> str:
    rid = (receipt_id or "").strip()
    if not rid:
        return ""
    sid = _san_html_id(rid)
    return (
        f'<section class="drift-section inv-reader-soft" aria-label="Narrative drift">'
        f'<div class="drift-header">'
        f'<h3 class="section-label" style="margin:0">NARRATIVE DRIFT</h3>'
        f'<button type="button" class="track-btn" id="drift-track-btn" data-id="{_e(rid)}">'
        f"+ TRACK THIS STORY</button>"
        f"</div>"
        f'<div class="drift-timeline" id="drift-timeline-{sid}">'
        f'<div id="drift-loaded-{sid}"></div>'
        f'<p class="drift-empty" style="color:#888;font-size:0.9em;margin-top:8px">'
        f"Register tracking, then run a snapshot via API "
        f'<code style="font-size:0.85em">POST /v1/drift/run/{_e(rid)}</code> '
        f"to compare framing to the original analysis."
        f"</p></div></section>"
    )


def _actors_map_html(receipt_id: str) -> str:
    rid = (receipt_id or "").strip()
    if not rid:
        return ""
    sid = _san_html_id(rid)
    return (
        f'<section class="actors-section inv-reader-soft" aria-label="Actor map">'
        f'<div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;'
        f'color:#555;margin-bottom:10px">Actor relationships</div>'
        f'<div id="actors-mount-{sid}" class="actors-mount" data-id="{_e(rid)}">'
        f'<span style="color:#888;font-size:0.9em">Loading…</span></div></section>'
    )


def _investigative_leads_section_html(gp: dict[str, Any]) -> str:
    leads = _safe_list(gp.get("investigative_leads"))
    if not leads:
        return ""
    rows: list[str] = []
    for lead in leads[:8]:
        if not isinstance(lead, dict):
            continue
        action = str(lead.get("action") or "").strip()
        target = str(lead.get("target") or "").strip()
        reason = str(lead.get("reason") or "").strip()
        hint = str(lead.get("url_hint") or "").strip()
        link = ""
        if hint.startswith("http"):
            link = (
                f'<a href="{_e(hint)}" target="_blank" rel="noopener" class="inv-lead-link">Open →</a>'
            )
        rows.append(
            f'<div class="inv-lead-card">'
            f'<div class="inv-lead-action">{_e(action)} <strong>{_e(target)}</strong></div>'
            f'<div class="inv-lead-reason">{_e(reason)}</div>'
            f"{link}</div>"
        )
    if not rows:
        return ""
    return (
        f'<div class="inv-reader-soft" style="margin-bottom:32px">'
        f'<div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;'
        f'color:#1a1a1a;margin-bottom:12px;font-weight:700">Investigative leads</div>'
        f'{"".join(rows)}</div>'
    )


def _gp_confidence_all_zero(conf: dict[str, Any]) -> bool:
    try:
        pct_cited = int(conf.get("pct_directly_cited") or 0)
        pct_inf = int(conf.get("pct_inferred") or 0)
        pct_cons = int(conf.get("pct_consensus") or 0)
        pct_cont = int(conf.get("pct_contested") or 0)
    except (TypeError, ValueError):
        return True
    return (pct_cited + pct_inf + pct_cons + pct_cont) == 0


def _gp_limited_coverage_block(gp: dict[str, Any]) -> str | None:
    """Minimal card when there is no ecosystem map and confidence bars are all zero."""
    if not isinstance(gp, dict):
        return None
    ecosystems = _safe_list(gp.get("ecosystems"))
    div_pts = _safe_list(gp.get("divergence_points"))
    consensus = _safe_list(gp.get("consensus_elements"))
    if ecosystems or div_pts or consensus:
        return None
    conf = gp.get("confidence_breakdown") if isinstance(gp.get("confidence_breakdown"), dict) else {}
    if not _gp_confidence_all_zero(conf):
        return None
    reasoning_s = str(gp.get("reasoning_summary", "") or "").strip()
    claim_one = str(gp.get("claim", "") or "").strip()
    conf_note = str(gp.get("confidence_note", "") or "").strip()
    lead = reasoning_s or claim_one or conf_note
    if not lead:
        return None
    extra = ""
    if conf_note and conf_note != lead and conf_note not in lead:
        extra = (
            f'<p style="margin:12px 0 0;font-size:15px;color:#666">{_e(conf_note)}</p>'
        )
    return (
        '<div class="inv-reader-soft" style="margin-bottom:32px">'
        '<div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;'
        'color:#555;margin-bottom:12px">Global perspectives</div>'
        '<div class="inv-paper-card" style="padding:18px 22px;font-size:17px;line-height:1.65;color:#444">'
        '<p style="margin:0 0 10px;font-weight:600;color:#111827">Limited global coverage</p>'
        f'<p style="margin:0">{_e(lead)}</p>'
        f"{extra}"
        "</div></div>"
    )


def _global_perspectives_section_html(gp: dict[str, Any]) -> str:
    if not isinstance(gp, dict):
        return ""
    ecosystems = _safe_list(gp.get("ecosystems"))
    div_pts = _safe_list(gp.get("divergence_points"))
    absent = _safe_list(gp.get("absent_from_all"))
    consensus = _safe_list(gp.get("consensus_elements"))
    claim_one = str(gp.get("claim", "") or "").strip()
    conf_note = str(gp.get("confidence_note", "") or "").strip()
    reasoning_s = str(gp.get("reasoning_summary", "") or "").strip()
    conf = gp.get("confidence_breakdown") if isinstance(gp.get("confidence_breakdown"), dict) else {}

    # `absent_from_all` is rendered only in _absent_from_all_section_html; do not count it here
    # or we emit an empty "Global perspectives" shell when absent is the sole GP signal.
    has_main = (
        bool(ecosystems)
        or bool(div_pts)
        or bool(consensus)
        or bool(claim_one)
        or bool(conf_note)
        or bool(reasoning_s)
        or bool(conf)
    )
    if not has_main and not absent:
        return (
            '<div class="inv-reader-soft" style="margin-bottom:32px">'
            '<div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;'
            'color:#555;margin-bottom:12px">Global perspectives</div>'
            '<div class="inv-paper-card" style="padding:18px 22px;font-size:17px;color:#555">'
            "Global perspective mapping is running — check back shortly."
            "</div></div>"
        )
    if not has_main and absent:
        return ""

    lim = _gp_limited_coverage_block(gp)
    if lim is not None:
        return lim

    reasoning_block = ""
    if reasoning_s:
        reasoning_block = (
            f'<div class="reasoning-summary">'
            f'<span class="reasoning-label">Why the divergence score is what it is:</span> '
            f"{_e(reasoning_s)}"
            f"</div>"
        )

    conf_block = ""
    if conf:
        try:
            pct_cited = int(conf.get("pct_directly_cited") or 0)
            pct_inf = int(conf.get("pct_inferred") or 0)
            pct_cons = int(conf.get("pct_consensus") or 0)
            pct_cont = int(conf.get("pct_contested") or 0)
        except (TypeError, ValueError):
            pct_cited = pct_inf = pct_cons = pct_cont = 0
        evidence_type = str(conf.get("primary_evidence_type") or "").strip()
        ev_html = (
            f'<div class="conf-evidence-type">Primary evidence: {_e(evidence_type.replace("_", " "))}</div>'
            if evidence_type
            else ""
        )
        conf_block = (
            f'<div class="confidence-decomp">'
            f'<div class="conf-row">'
            f'<span class="conf-label">Evidence basis</span>'
            f'<div class="conf-bar-wrap">'
            f'<div class="conf-bar-cited" style="width:{max(0, min(100, pct_cited))}%"></div>'
            f'<div class="conf-bar-inferred" style="width:{max(0, min(100, pct_inf))}%"></div>'
            f"</div>"
            f'<span class="conf-detail">{pct_cited}% retrieved · {pct_inf}% inferred</span>'
            f"</div>"
            f'<div class="conf-row">'
            f'<span class="conf-label">Coverage split</span>'
            f'<div class="conf-bar-wrap">'
            f'<div class="conf-bar-consensus" style="width:{max(0, min(100, pct_cons))}%"></div>'
            f'<div class="conf-bar-contested" style="width:{max(0, min(100, pct_cont))}%"></div>'
            f"</div>"
            f'<span class="conf-detail">{pct_cons}% consensus · {pct_cont}% contested</span>'
            f"</div>"
            f"{ev_html}</div>"
        )

    parts: list[str] = []
    if claim_one:
        parts.append(
            f'<p style="font-size:16px;color:#444;line-height:1.6;margin-bottom:18px;font-style:italic">'
            f'{_e(claim_one)}</p>'
        )
    if reasoning_block:
        parts.append(reasoning_block)
    if conf_block:
        parts.append(conf_block)
    for eco in ecosystems:
        if not isinstance(eco, dict):
            continue
        elabel = str(eco.get("label", "") or "")
        tier = str(eco.get("confidence_tier", "") or "")
        outlets = _safe_list(eco.get("outlets"))
        framing = str(eco.get("framing", "") or "")
        emph = str(eco.get("emphasized", "") or "")
        mn = str(eco.get("minimized", "") or "")
        klang = _safe_list(eco.get("key_language"))
        triggers = _safe_list(eco.get("trigger_phrases"))
        tier_b = _pills([tier], "amber") if tier else ""
        outlet_links: list[str] = []
        for o in outlets:
            if not o:
                continue
            o_str = str(o).strip()
            if not o_str:
                continue
            outlet_links.append(_outlet_link_html(o_str))
        outlets_html = ", ".join(outlet_links) if outlet_links else "—"
        kl_txt = ", ".join(f'"{_e(x)}"' for x in klang if x)
        kl_block = ""
        if kl_txt:
            kl_block = (
                f'<div style="font-size:15px;color:#444;margin-top:10px">'
                f"<strong>Key language:</strong> {kl_txt}</div>"
            )
        trigger_block = ""
        if triggers:
            phrases_html = "".join(
                f'<span class="trigger-phrase">"{_e(p)}"</span>' for p in triggers if p
            )
            if phrases_html:
                trigger_block = (
                    f'<div class="trigger-phrases">'
                    f'<span class="trigger-label">Trigger phrases</span> '
                    f"{phrases_html}"
                    f"</div>"
                )
        headlines_block = ""
        ex_h = eco.get("example_headlines")
        if isinstance(ex_h, list) and ex_h:
            h_rows = ""
            for h in ex_h[:4]:
                if not isinstance(h, dict):
                    continue
                htext = str(h.get("text") or "").strip()
                if not htext:
                    continue
                src = str(h.get("source") or "").strip()
                htype = str(h.get("type") or "inferred").strip().lower()
                enc = quote_plus(htext[:200])
                type_badge = (
                    '<span class="headline-type retrieved">retrieved</span>'
                    if htype == "retrieved"
                    else '<span class="headline-type inferred">inferred</span>'
                )
                h_rows += (
                    f'<div class="example-headline">'
                    f'<a href="{_GOOGLE_NEWS_SEARCH}{enc}" target="_blank" rel="noopener" '
                    f'class="headline-text">{_e(htext)}</a>'
                    f'<span class="headline-source">{_e(src)}</span>'
                    f"{type_badge}"
                    f"</div>"
                )
            if h_rows:
                headlines_block = (
                    f'<div class="example-headlines">'
                    f'<div class="headlines-label">Example coverage</div>'
                    f"{h_rows}</div>"
                )
        parts.append(
            f'<div class="inv-paper-card" style="padding:18px 20px;margin-bottom:14px;'
            f'border:1px solid rgba(26,26,26,0.1)">'
            f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px">'
            f'<span style="font-size:18px;font-weight:700;color:#111827">{_e(elabel)}</span> {tier_b}'
            f"</div>"
            f'<div style="font-size:15px;color:#444;margin-bottom:8px"><strong>Outlets:</strong> '
            f"{outlets_html}</div>"
            f'<div style="font-size:17px;color:#333;line-height:1.55;margin-bottom:8px">'
            f"<strong>Framing:</strong> {_e(framing)}</div>"
            f"{trigger_block}"
            f"{headlines_block}"
            f'<div style="font-size:16px;color:#555;line-height:1.5"><strong>Emphasizes:</strong> '
            f"{_e(emph)}</div>"
            f'<div style="font-size:16px;color:#555;line-height:1.5;margin-top:6px">'
            f"<strong>Minimizes:</strong> {_e(mn)}</div>"
            f"{kl_block}</div>"
        )
    if consensus:
        li = "".join(
            f'<li style="margin:8px 0;font-size:17px;color:#333;line-height:1.5">{_e(x)}</li>'
            for x in consensus
            if x
        )
        parts.append(
            '<div style="margin:20px 0 16px">'
            '<div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;'
            'color:#555;margin-bottom:10px">What all sources agree happened</div>'
            f'<ul style="margin:0;padding-left:20px">{li}</ul></div>'
        )
    if div_pts:
        li = "".join(
            f'<li style="margin:8px 0;font-size:17px;color:#333;line-height:1.5">{_e(x)}</li>'
            for x in div_pts
            if x
        )
        parts.append(
            '<div style="margin:20px 0 16px">'
            '<div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;'
            'color:#b45309;margin-bottom:10px">Where coverage splits</div>'
            f'<ul style="margin:0;padding-left:20px">{li}</ul></div>'
        )
    if conf_note:
        parts.append(
            f'<p style="font-size:14px;color:#6b7280;line-height:1.55;margin-top:16px">'
            f'{_e(conf_note)}</p>'
        )
    return (
        f'<div class="inv-reader-soft" style="margin-bottom:32px">'
        f'<div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;'
        f'color:#555;margin-bottom:14px">Global perspectives</div>'
        f'{"".join(parts)}</div>'
    )


def _absent_from_all_section_html(gp: dict[str, Any]) -> str:
    """Absent angles from global_perspectives only (single 'what nobody' block on page)."""
    if not isinstance(gp, dict):
        return ""
    absent = _safe_list(gp.get("absent_from_all"))
    if not absent:
        return ""
    boxes = "".join(_absence_item_html(x) for x in absent if x)
    return (
        f'<div class="inv-reader-soft" style="margin-bottom:32px">'
        f'<div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;'
        f'color:#b45309;margin-bottom:12px;font-weight:700">What nobody is covering</div>'
        f"{boxes}</div>"
    )


def _build_verification_rows(claim: dict[str, Any]) -> str:
    """Build verification rows for one claim; filters actor_ledger noise and meaningless deferred."""
    subject = str(claim.get("subject", "") or "").strip()
    rows: list[str] = []
    for v in _safe_list(claim.get("verifications")):
        if not isinstance(v, dict):
            continue
        adapter = str(v.get("adapter") or v.get("adapter_name") or "").strip()
        status = str(v.get("status", "") or "").strip()
        st_l = status.lower()
        ad_k = _adapter_key(adapter)
        result = _verification_result_dict(v)

        if ad_k in _SKIP_VERIFICATION_ADAPTERS:
            continue
        if ad_k in _DEFERRED_NOISE_ADAPTER_KEYS and st_l == "deferred":
            continue

        if ad_k == "courtlistener" and st_l in ("found", "searched_none_found"):
            raw_r = v.get("result") if isinstance(v.get("result"), dict) else {}
            rows.append(_courtlistener_verification_html(status, raw_r or {}))
            continue

        if _should_omit_verification_row(adapter, status, result, subject):
            continue

        is_surf = _adapter_is_surface(adapter)
        brief_plain = ""
        surface_block = ""
        if is_surf and isinstance(result, dict) and st_l == "found":
            surface_block = _format_surface_result(result, subject)
        elif isinstance(result, dict):
            brief_plain = _flat_adapter_brief(result)
            tier = str(result.get("confidence_tier", "") or "").strip()
            if tier:
                brief_plain = f"{brief_plain} ({tier})" if brief_plain else tier
        if not isinstance(result, dict) or not result:
            det = v.get("detail")
            if det and not brief_plain and not surface_block:
                brief_plain = str(det).strip()
        if st_l == "deferred" and not brief_plain and not surface_block:
            brief_plain = "deferred (full lookup via dedicated endpoint)"

        if not _brief_has_reader_value(brief_plain, surface_block, st_l, v):
            continue

        st_col = _status_color(status)
        dash = ""
        if brief_plain and not surface_block:
            dash = f" — {_e(brief_plain)}"
        surf_html = (
            f'<div class="surface-verification-block">{surface_block}</div>'
            if surface_block
            else ""
        )
        rows.append(
            f'<div class="verification-row" style="font-size:15px;color:#333;padding:4px 0">'
            f'<span style="font-weight:600">{_e(adapter)}</span>: '
            f'<span style="color:{st_col};font-weight:600">{_e(status)}</span>'
            f"{dash}</div>"
            f"{surf_html}"
        )

    if not rows:
        return '<div class="verification-none">No independent verification found.</div>'
    return '<div class="verification-list">' + "".join(rows) + "</div>"


def _revision_trail_html(revisions: list[Any]) -> str:
    """Side-by-side BEFORE → AFTER for claim revision tracking (signed receipt)."""
    if not revisions:
        return ""

    items: list[str] = []
    for rev in revisions:
        if not isinstance(rev, dict):
            continue
        rev_raw = str(rev.get("revision_type") or "UNKNOWN").strip().upper()
        if "CONTRADICTED" in rev_raw:
            rev_type = "CONTRADICTED"
        else:
            rev_type = rev_raw
        label, color, bg = REVISION_TYPES.get(
            rev_type, ("CHANGED", "#555", "#f5f5f5")
        )

        orig_claim = rev.get("original_claim", "")
        orig_date = rev.get("original_date", "unknown")
        orig_url = str(rev.get("original_url") or "").strip()
        orig_source = rev.get("original_source", "")
        rev_claim = rev.get("revised_claim", "")
        rev_date = rev.get("revised_date", "")
        rev_url = str(rev.get("revised_url") or "").strip()
        rev_source = str(rev.get("revised_source") or "").strip()
        gap = rev.get("gap_description", "")
        significance = rev.get("significance", "")

        orig_link = (
            f'<a href="{_e(orig_url)}" target="_blank" rel="noopener" '
            f'class="revision-source-link">{_e(orig_source)}</a>'
            if orig_url else _e(orig_source or "unknown source")
        )

        rev_after_attr = ""
        if rev_url:
            rev_after_attr = (
                f'<div class="revision-attribution">— '
                f'<a href="{_e(rev_url)}" target="_blank" rel="noopener" '
                f'class="revision-source-link">{_e(rev_source or "source")}</a></div>'
            )
        elif rev_source:
            rev_after_attr = f'<div class="revision-attribution">— {_e(rev_source)}</div>'

        gap_html = f'<span class="revision-gap">{_e(gap)}</span>' if gap else ""
        sig_html = (
            f'<div class="revision-significance">{_e(significance)}</div>'
            if significance
            else ""
        )

        items.append(
            f'<div class="revision-item">'
            f'<div class="revision-header">'
            f'<span class="revision-badge" style="background:{bg};color:{color};">'
            f"{_e(label)}</span>{gap_html}</div>"
            f'<div class="revision-timeline">'
            f'<div class="revision-before">'
            f'<span class="revision-date-label">BEFORE</span>'
            f'<span class="revision-date">{_e(orig_date)}</span>'
            f'<div class="revision-claim-text">"{_e(orig_claim)}"</div>'
            f'<div class="revision-attribution">— {orig_link}</div>'
            f"</div>"
            f'<div class="revision-arrow">→</div>'
            f'<div class="revision-after">'
            f'<span class="revision-date-label">AFTER</span>'
            f'<span class="revision-date">{_e(rev_date)}</span>'
            f'<div class="revision-claim-text">"{_e(rev_claim)}"</div>'
            f"{rev_after_attr}"
            f"</div></div>"
            f"{sig_html}"
            f"</div>"
        )

    n = len(items)
    if not n:
        return ""
    label_plural = "change" if n == 1 else "changes"
    return (
        f'<div class="revision-trail">'
        f'<div class="revision-trail-label">'
        f"REVISION TRAIL — {n} {label_plural} detected"
        f"</div>"
        f'{"".join(items)}</div>'
    )


def _claims_section_html(receipt: dict[str, Any]) -> str:
    claims_in = _safe_list(receipt.get("claims_verified"))
    if not claims_in:
        return ""
    claims = _deduplicate_claims(claims_in)
    if not claims:
        return ""

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    order_key: dict[str, int] = {}
    for i, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        subj = str(claim.get("subject") or "").strip() or "General"
        groups[subj].append(claim)
        if subj not in order_key:
            order_key[subj] = i

    sorted_subjects = sorted(groups.keys(), key=lambda s: order_key.get(s, 9999))
    cards: list[str] = []

    for subject in sorted_subjects:
        subject_claims = groups[subject]
        encoded_subject = quote_plus(subject)
        subject_link = (
            f'<a href="{_GOOGLE_NEWS_SEARCH}{encoded_subject}" '
            f'target="_blank" rel="noopener" class="claim-subject-link">{_e(subject)}</a>'
        )

        types_in_group = [
            str(c.get("claim_type", "institutional") or "").lower() for c in subject_claims
        ]
        if "rumored" in types_in_group:
            badge_type = "rumored"
        elif "biographical" in types_in_group:
            badge_type = "biographical"
        elif "statistical" in types_in_group:
            badge_type = "statistical"
        else:
            badge_type = types_in_group[0] if types_in_group else "institutional"

        badge_label = badge_type.replace("_", " ").upper()
        badge_html = (
            f'<span class="claim-type-badge claim-type-{badge_type}">{badge_label}</span>'
        )

        claim_rows: list[str] = []
        for c in subject_claims:
            claim_text = str(c.get("claim", "") or "").strip()
            cited = c.get("cited_source")
            cited_s = str(cited).strip() if cited else ""
            rumor_src_raw = str(c.get("rumor_source", "") or "").strip()
            rumor_lang = str(c.get("rumor_language", "") or "").strip()
            claim_type = str(c.get("claim_type", "") or "").strip()
            ctype_l = claim_type.lower()

            rumor_display_src = rumor_src_raw or cited_s
            encoded_claim = quote_plus(claim_text[:150])
            claim_link = (
                f'<a href="{_GOOGLE_NEWS_SEARCH}{encoded_claim}" '
                f'target="_blank" rel="noopener" class="claim-text-link">{_e(claim_text)}</a>'
            )

            cited_html = ""
            if cited_s:
                if ctype_l == "rumored":
                    dup = _claim_text_dedupe_key(cited_s) == _claim_text_dedupe_key(
                        rumor_display_src or ""
                    )
                    if dup and not cited_s.startswith(("http://", "https://")):
                        cited_html = ""
                    elif cited_s.startswith(("http://", "https://")):
                        cited_html = (
                            f'<div class="cited-source">Article cited: '
                            f'<a href="{_e(cited_s)}" target="_blank" rel="noopener">'
                            f"<strong>{_e(cited_s)}</strong></a></div>"
                        )
                    else:
                        cited_html = (
                            f'<div class="cited-source">Article cited: '
                            f"<strong>{_e(cited_s)}</strong></div>"
                        )
                elif cited_s.startswith(("http://", "https://")):
                    cited_html = (
                        f'<div class="cited-source">Article cited: '
                        f'<a href="{_e(cited_s)}" target="_blank" rel="noopener">'
                        f"<strong>{_e(cited_s)}</strong></a></div>"
                    )
                else:
                    cited_html = (
                        f'<div class="cited-source">Article cited: <strong>{_e(cited_s)}</strong></div>'
                    )
            elif ctype_l != "rumored":
                cited_html = (
                    '<div style="font-size:15px;color:#6b7280;margin:8px 0 6px">'
                    "Cited source: none cited</div>"
                )

            rumor_html = ""
            if ctype_l == "rumored":
                source_label = rumor_src_raw or cited_s or "unnamed source"
                rumor_html = (
                    f'<div class="rumor-source-block">'
                    f'<span class="rumor-label">Source of rumor:</span> '
                    f"<strong>{_e(source_label)}</strong>"
                    f"</div>"
                )
                if rumor_lang:
                    rumor_html += (
                        f'<div class="rumor-language">Language from article: '
                        f'<em>“{_e(rumor_lang)}”</em></div>'
                    )
                rumor_html += (
                    f'<div class="rumor-disclaimer">'
                    f"PUBLIC EYE documents this allegation exists — not that it is true."
                    f"</div>"
                )

            verif_rows = _build_verification_rows(c)
            rev_raw = c.get("revisions")
            revisions_list = rev_raw if isinstance(rev_raw, list) else []
            revision_html = (
                _revision_trail_html(revisions_list) if revisions_list else ""
            )
            row_cls = "claim-row claim-row-rumored" if ctype_l == "rumored" else "claim-row"
            claim_rows.append(
                f'<div class="{row_cls}">'
                f'<div class="claim-row-text">{claim_link}</div>'
                f"{cited_html}"
                f"{rumor_html}"
                f'<div class="claim-verification-wrap">{verif_rows}</div>'
                f"{revision_html}"
                f"</div>"
            )

        claim_rows_html = "\n".join(claim_rows)
        n = len(subject_claims)
        count_label = f"{n} claim" + ("s" if n != 1 else "")
        card_class = "claim-card inv-paper-card"
        if badge_type == "rumored":
            card_class += " claim-card-rumored"

        cards.append(
            f'<div class="{card_class}">'
            f'<div class="claim-header">'
            f"{badge_html}"
            f'<span class="claim-subject">{subject_link}</span>'
            f'<span class="claim-count">{count_label}</span>'
            f"</div>"
            f'<div class="claim-rows">{claim_rows_html}</div>'
            f"</div>"
        )

    return (
        f'<section id="claims-section" class="claims-section inv-reader-soft" '
        f'style="margin-bottom:32px">'
        f'<h3 class="section-label">CLAIMS TRACED</h3>'
        f'{"".join(cards)}</section>'
    )


def _named_entities_section_html(receipt: dict) -> str:
    entities = receipt.get("named_entities", [])
    if not entities:
        return ""

    eye_items = []
    for entity in entities[:40]:
        ent = str(entity).strip()
        if not ent:
            continue
        encoded = quote_plus(ent)
        url = f"https://news.google.com/search?q={encoded}"
        # Escape entity name for HTML attribute and label
        safe_name = ent.replace('"', '&quot;').replace("<", "&lt;").replace(">", "&gt;")
        eye_items.append(
            f'<a href="{url}" target="_blank" rel="noopener" '
            f'class="eye-pill" title="{safe_name}">'
            f'<svg class="eye-svg" viewBox="0 0 44 26" xmlns="http://www.w3.org/2000/svg">'
            f'<path class="closed-line" d="M4 13 Q22 4 40 13"/>'
            f'<line class="eye-lash" x1="22" y1="4" x2="22" y2="1"/>'
            f'<line class="eye-lash" x1="14" y1="6.5" x2="12" y2="4"/>'
            f'<line class="eye-lash" x1="30" y1="6.5" x2="32" y2="4"/>'
            f'<path class="open-outline" d="M4 13 Q13 3 22 3 Q31 3 40 13 Q31 23 22 23 Q13 23 4 13 Z"/>'
            f'<circle class="eye-pupil" cx="22" cy="13" r="5.5"/>'
            f'<circle class="eye-shine" cx="25" cy="10" r="1.5"/>'
            f'<path class="eye-twinkle" d="M 31 4 l1.5 3 l3 1.5 l-3 1.5 l-1.5 3 l-1.5-3 l-3-1.5 l3-1.5 z"/>'
            f"</svg>"
            f'<span class="eye-label">{safe_name}</span>'
            f"</a>"
        )

    eyes_html = "\n".join(eye_items)

    return f"""
<section class="named-entities-section">
  <h3 class="section-label">NAMED ENTITIES</h3>
  <div class="eye-row">{eyes_html}</div>
</section>
"""


def _coverage_provenance_html(receipt: dict[str, Any]) -> str:
    cov = receipt.get("coverage_result") if isinstance(receipt.get("coverage_result"), dict) else {}
    adapter = str(cov.get("source_adapter", "") or "—")
    stage = cov.get("gdelt_stage")
    stage_s = str(stage) if stage else ""
    count = cov.get("comparative_article_count")
    if count is None:
        count = len(_safe_list(receipt.get("sources")))
    sc = receipt.get("sources_checked")
    adapters_line = ", ".join(str(x) for x in sc) if isinstance(sc, list) else "—"
    n_claims = receipt.get("claims_extracted", "—")
    grounded = receipt.get("perspectives_grounded")
    if grounded is None:
        sp = receipt.get("source_provenance")
        if isinstance(sp, dict):
            grounded = bool(sp.get("coverage_found"))
    gtxt = "yes" if grounded else "no"
    cov_line = _e(adapter)
    if stage_s and adapter == "gdelt":
        cov_line = f"{cov_line} ({_e(stage_s)})"

    comp_html = "0"
    if count is not None and str(count).strip() not in ("", "—"):
        ad_l = str(adapter).strip().lower()
        if ad_l == "gdelt":
            try:
                n_g = int(count)
                if n_g:
                    comp_html = (
                        f'<a href="https://www.gdeltproject.org" target="_blank" rel="noopener" '
                        f'class="entity-ref-link">{n_g} via GDELT</a>'
                    )
                else:
                    comp_html = "0"
            except (TypeError, ValueError):
                comp_html = _e(count)
        else:
            comp_html = _e(count)

    nc_html = _e(n_claims)
    if n_claims is not None and str(n_claims).strip() not in ("", "—"):
        nc_html = (
            f'<a href="#claims-section" class="internal-link">{_e(n_claims)}</a>'
        )

    cov_full = receipt.get("coverage_result") if isinstance(receipt.get("coverage_result"), dict) else {}
    sparse = bool(cov_full.get("coverage_sparse"))
    qexp = cov_full.get("query_expansions")
    if not isinstance(qexp, list):
        qexp = []
    sparse_html = ""
    if sparse and qexp:
        chips = "".join(
            f'<span class="query-expansion-chip">{_e(str(q))}</span>' for q in qexp[:6] if q
        )
        sparse_html = (
            f'<div class="coverage-sparse-note">Sparse comparative coverage — try: {chips}</div>'
        )
    elif sparse:
        sparse_html = (
            '<div class="coverage-sparse-note">Sparse comparative coverage — broader searches may help.</div>'
        )

    return f"""
<div class="inv-reader-soft" style="margin-bottom:28px;padding:16px 20px;
            background:#fafafa;border:1px solid rgba(26,26,26,0.12);border-radius:6px">
  <div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;
              color:#555;margin-bottom:12px">Sources &amp; provenance</div>
  <div style="font-size:16px;color:#333;line-height:1.7">
    <div><strong>Coverage retrieved via:</strong> {cov_line}</div>
    <div><strong>Comparative articles found:</strong> {comp_html}</div>
    <div><strong>Adapters checked:</strong> {_e(adapters_line)}</div>
    <div><strong>Claims extracted:</strong> {nc_html}</div>
    <div><strong>Generated:</strong> {_e(_fmt_generated_at(receipt.get("generated_at")))}</div>
    <div><strong>Perspectives grounded in retrieved sources:</strong> {_e(gtxt)}</div>
    {sparse_html}
  </div>
</div>"""


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


def _outlet_logo_html(outlet_name: str, story_url: str = "") -> str:
    """Small Clearbit logo; hidden on error."""
    key = outlet_name.lower().strip()
    domain = OUTLET_DOMAINS.get(key)
    if not domain and story_url:
        try:
            netloc = urlparse(story_url).netloc.lower()
            domain = netloc[4:] if netloc.startswith("www.") else netloc
        except Exception:  # noqa: BLE001
            domain = ""
    if not domain:
        slug = key.replace(" ", "").replace("the", "")
        if slug:
            domain = f"{slug}.com"
        else:
            return ""
    logo_url = f"https://logo.clearbit.com/{domain}"
    return (
        f'<img src="{_e(logo_url)}" '
        'style="width:20px;height:20px;border-radius:3px;object-fit:contain;'
        'flex-shrink:0;background:#f0f0f0;" '
        'onerror="this.style.display=\'none\'" '
        f'loading="lazy" alt="{_e(outlet_name)}">'
    )


def _one_outlet_row(item: dict) -> str:
    conf = item.get("alignment_confidence", "medium")
    dot = {"high": "#3ecf8e", "medium": "#e8a020", "low": "#5a5752"}.get(conf, "#5a5752")
    note = str(item.get("alignment_note", "") or "")
    story_url = str(item.get("story_url") or "").strip()
    oname = item.get("outlet", "") or ""
    not_found = "not found in sources" in note.lower()
    if not_found:
        note_color = "#555555"
        note_style = "font-style:italic"
        link_html = ""
    elif story_url:
        note_color = "#555555"
        note_style = ""
        link_html = (
            f'<a href="{_e(story_url)}" target="_blank" rel="noopener" '
            'style="font-size:13px;color:#0d47a1;margin-top:6px;display:inline-block;'
            'font-weight:600;text-decoration:underline;text-underline-offset:3px">'
            "Read coverage ↗</a>"
        )
    else:
        note_color = "#555555"
        note_style = ""
        link_html = ""
    if story_url:
        outlet_display = (
            f'<a href="{_e(story_url)}" target="_blank" rel="noopener" '
            'style="font-size:16px;font-weight:500;color:#111827;text-decoration:none;'
            'border-bottom:1px solid rgba(0,0,0,0.2)">'
            f"{_e(oname)}</a>"
        )
    else:
        outlet_display = (
            f'<span style="font-size:16px;font-weight:500;color:#111827">'
            f"{_e(oname)}</span>"
        )
    logo = _outlet_logo_html(str(oname), story_url)
    return (
        f'<div style="display:flex;gap:10px;align-items:flex-start;'
        f'padding:8px 0;border-bottom:0.5px solid rgba(0,0,0,0.08)">'
        f'<div style="flex:1;min-width:0">'
        f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:3px">'
        f"{logo}{outlet_display}"
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
        return '<div style="font-size:16px;color:#555;padding:12px 0">No outlets mapped yet.</div>'

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
                f'color:#555;margin-bottom:6px">{_e(label)}</div>'
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
                f'color:#555;margin-bottom:6px">{_e(otype)}</div>'
                f'<div style="padding-left:2px">{inner}</div>'
                f"</div>"
            )

        nid = f"side-{side_prefix}-country-{cidx}"
        n_out = len(items)
        blocks.append(
            f'<details class="country-acc" id="{nid}" style="border:0.5px solid rgba(0,0,0,0.08);'
            f'border-radius:10px;background:#FFFFFF;margin-bottom:10px;overflow:hidden">'
            f'<summary style="list-style:none;cursor:pointer;padding:12px 14px;display:flex;'
            f'align-items:center;gap:8px;flex-wrap:wrap;user-select:none">'
            f'<span style="font-size:16px;line-height:1">{flag}</span>'
            f'<span style="font-size:15px;font-weight:600;color:#111827">{_e(country)}</span>'
            f'<span class="country-chev" style="font-size:13px;color:#e8a020">▾</span>'
            f'<span style="font-size:13px;color:#555;margin-left:auto">'
            f'{n_out} outlet{"s" if n_out != 1 else ""} · {_e(str(len(by_type)))} type{"s" if len(by_type) != 1 else ""}'
            f"</span>"
            f"</summary>"
            f'<div style="padding:4px 14px 14px 14px;border-top:0.5px solid rgba(0,0,0,0.08)">'
            f'{"".join(type_sections)}'
            f"</div>"
            f"</details>"
        )

    hint = (
        '<p style="font-size:16px;color:#555;line-height:1.5;margin:0 0 10px 0">'
        "Tap a country to see how outlets there break down by kind of organization "
        "on this story.</p>"
    )
    return hint + "".join(blocks)


def _dig_deeper_button_html(receipt_id: str) -> str:
    rid = (receipt_id or "").strip()
    if not rid:
        return ""
    return f"""
<section class="dig-deeper-section" aria-label="Dig deeper">
    <button type="button" class="mouth-btn" id="dig-btn" data-receipt-id="{_e(rid)}"
            aria-label="Dig deeper into this investigation">
        <svg class="mouth-svg" id="mouth-svg" viewBox="0 0 120 60" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path class="mouth-closed"
                  d="M 20 30 Q 40 24 60 24 Q 80 24 100 30 Q 80 36 60 36 Q 40 36 20 30 Z"/>
            <path class="mouth-open-upper"
                  d="M 20 28 Q 40 20 60 20 Q 80 20 100 28"/>
            <path class="mouth-open-lower"
                  d="M 20 28 Q 40 44 60 46 Q 80 44 100 28"/>
            <rect class="mouth-teeth" x="28" y="21" width="10" height="8" rx="2"/>
            <rect class="mouth-teeth" x="41" y="20" width="10" height="9" rx="2"/>
            <rect class="mouth-teeth" x="54" y="20" width="10" height="9" rx="2"/>
            <rect class="mouth-teeth" x="67" y="20" width="10" height="9" rx="2"/>
            <rect class="mouth-teeth" x="80" y="21" width="10" height="8" rx="2"/>
            <ellipse class="mouth-tongue" cx="60" cy="39" rx="16" ry="7"/>
            <circle class="fact-dot dd1" cx="45" cy="52" r="3"/>
            <circle class="fact-dot dd2" cx="60" cy="56" r="3"/>
            <circle class="fact-dot dd3" cx="75" cy="52" r="3"/>
            <circle class="fact-dot dd4" cx="52" cy="62" r="2.5"/>
            <circle class="fact-dot dd5" cx="68" cy="62" r="2.5"/>
        </svg>
        <span class="mouth-label" id="mouth-label">DIG DEEPER</span>
    </button>
    <div class="deeper-results" id="deeper-results" style="display:none">
        <div class="deeper-loading" id="deeper-loading">
            <span class="deeper-loading-text">Pulling records…</span>
        </div>
        <div id="deeper-content"></div>
    </div>
</section>
"""


def _brief_hook_action_href(where: str, action: str) -> str | None:
    """Map investigative next_actions.where to a useful URL; optional search query."""
    q = quote_plus((action or where or "").strip()[:280])
    combined = f"{(where or '').lower()} {(action or '').lower()}"
    if "courtlistener" in combined or "court listener" in combined:
        return f"https://www.courtlistener.com/?q={q}"
    if "opensecrets" in combined:
        return f"https://www.opensecrets.org/search?q={q}"
    if re.search(r"\bfec\b", combined) or "fec.gov" in combined:
        return f"https://www.fec.gov/data/search/?q={q}"
    if "congress" in combined or "congressional" in combined:
        return f"https://www.congress.gov/search?q={q}"
    if "propublica" in combined:
        return f"https://www.propublica.org/search?q={q}"
    if "sec" in combined and ("edgar" in combined or "sec.gov" in combined):
        return f"https://www.sec.gov/edgar/search/#/q={q}"
    if "gdelt" in combined:
        return "https://www.gdeltproject.org/"
    if "ais" in combined or "marinetraffic" in combined or "marine traffic" in combined:
        return "https://www.marinetraffic.com/en/ais/home/centerx:45/centery:15/zoom:5"
    if "shipping" in combined:
        return "https://www.marinetraffic.com/en/ais/home/centerx:45/centery:15/zoom:5"
    return None


def _summary_section_html(receipt: dict) -> str:
    """Epistemics-disciplined contextual brief: FACT/INFERRED separation, hooks (signed with receipt)."""
    topic = str(receipt.get("article_topic") or receipt.get("narrative") or "").strip()
    if not topic and isinstance(receipt.get("article"), dict):
        topic = str((receipt.get("article") or {}).get("title") or "").strip()
    brief = receipt.get("contextual_brief")
    if not isinstance(brief, dict):
        brief = {}

    if not brief:
        if not topic:
            return ""
        return (
            f'<div class="inv-paper-card inv-reader-soft contextual-brief-fallback" '
            f'style="margin-bottom:32px;padding:18px 22px">'
            f'<div class="brief-label">SUMMARY</div>'
            f'<p class="summary-text">{_e(topic[:400])}{"…" if len(topic) > 400 else ""}</p></div>'
        )

    parts: list[str] = []

    claim_type = str(brief.get("claim_type") or "").strip()
    claim_type_colors = {
        "EVENT": ("#1b5e20", "#e8f5e9"),
        "STATEMENT": ("#0d47a1", "#e3f2fd"),
        "PREDICTION": ("#e65100", "#fff3e0"),
        "ALLEGATION": ("#b71c1c", "#ffebee"),
        "POLICY": ("#4a148c", "#f3e5f5"),
    }
    ctc, ctbg = claim_type_colors.get(claim_type, ("#555", "#f5f5f5"))
    ct_badge = (
        f'<span class="claim-type-tag" style="color:{ctc};background:{ctbg};">'
        f"{_e(claim_type)}</span>"
        if claim_type
        else ""
    )

    parts.append(
        f'<section class="summary-section inv-reader-soft">'
        f'<div class="brief-label">SUMMARY {ct_badge}</div>'
        f'<div class="summary-text">{_e(topic[:400])}{"…" if len(topic) > 400 else ""}</div>'
        f"</section>"
    )

    why = brief.get("why_it_matters") if isinstance(brief.get("why_it_matters"), dict) else {}
    if not why and isinstance(brief.get("why_it_matters_now"), dict):
        _old = brief["why_it_matters_now"]
        why = {
            "stakes": _old.get("text") or "",
            "urgency": _old.get("urgency") or "",
            "impact_signals": [],
        }
    stakes = str(why.get("stakes") or "").strip()
    impact_sigs = why.get("impact_signals") if isinstance(why.get("impact_signals"), list) else []
    if stakes or impact_sigs:
        urgency = str(why.get("urgency") or "").strip().lower()
        urgency_colors = {
            "immediate": ("#b71c1c", "#ffebee"),
            "days": ("#e65100", "#fff3e0"),
            "weeks": ("#f57f17", "#fffde7"),
            "long-term": ("#1b5e20", "#e8f5e9"),
        }
        uc, ubg = urgency_colors.get(urgency, ("#888", "#f5f5f5"))
        urgency_badge = ""
        if urgency:
            urg_disp = urgency.replace("-", " ").upper()
            urgency_badge = (
                f'<span class="urgency-badge" style="color:{uc};background:{ubg};">'
                f"{_e(urg_disp)}</span>"
            )

        signals_html = ""
        for sig in impact_sigs[:6]:
            if not isinstance(sig, dict):
                continue
            stype = str(sig.get("type") or "INFERRED").strip().upper()
            if stype not in ("FACT", "INFERRED"):
                stype = "INFERRED"
            sc = "#2e7d32" if stype == "FACT" else "#e65100"
            sbg = "#e8f5e9" if stype == "FACT" else "#fff3e0"
            sig_txt = str(sig.get("signal") or "").strip()
            if not sig_txt:
                continue
            src = str(sig.get("source") or "").strip()
            ts = str(sig.get("timestamp") or "").strip()
            attr = ""
            if src:
                attr = f" — {_e(src)}"
                if ts:
                    attr += f", {_e(ts)}"
            attr_html = f'<span class="signal-attr">{attr}</span>' if attr else ""
            signals_html += (
                f'<div class="impact-signal">'
                f'<span class="signal-type-tag" style="color:{sc};background:{sbg};">{stype}</span>'
                f'<span class="impact-signal-text">{_e(sig_txt)}</span>'
                f"{attr_html}</div>"
            )

        stakes_html = f'<div class="brief-text">{_e(stakes)}</div>' if stakes else ""
        sig_block = f'<div class="impact-signals">{signals_html}</div>' if signals_html else ""
        parts.append(
            f'<section class="brief-section">'
            f'<div class="brief-label">WHY IT MATTERS NOW {urgency_badge}</div>'
            f"{stakes_html}{sig_block}</section>"
        )

    prec = brief.get("historical_precedent") if isinstance(brief.get("historical_precedent"), dict) else {}
    case_name = str(prec.get("case") or prec.get("comparable_event") or "").strip()
    if case_name:
        conf = str(prec.get("confidence") or "medium").lower()
        conf_note = (
            ' <span class="conf-low-note">(low confidence analogy)</span>' if conf == "low" else ""
        )
        delta = prec.get("delta") if isinstance(prec.get("delta"), dict) else {}
        delta_html = ""
        for key, label in [
            ("military_posture", "Military posture"),
            ("actor_alignment", "Actor alignment"),
            ("information_environment", "Info environment"),
        ]:
            dv = str(delta.get(key) or "").strip()
            if dv:
                delta_html += (
                    f'<div class="delta-row">'
                    f'<span class="delta-label">{_e(label)}</span>'
                    f'<span class="delta-text">{_e(dv)}</span></div>'
                )

        bp = str(prec.get("breakpoint") or "").strip()
        breakpoint_html = (
            f'<div class="breakpoint-block">'
            f'<span class="breakpoint-label">WHERE ANALOGY BREAKS DOWN</span>'
            f'<span class="breakpoint-text">{_e(bp)}</span></div>'
            if bp
            else ""
        )

        dt = prec.get("date") or prec.get("comparable_date")
        dt_html = f'<span class="precedent-date">· {_e(dt)}</span>' if str(dt or "").strip() else ""
        trig = str(prec.get("trigger") or "").strip()
        esc = str(prec.get("escalation_pattern") or "").strip()
        res_m = str(prec.get("resolution_mechanism") or "").strip()
        res_t = str(prec.get("resolution_timeline") or "").strip()
        prec_rows = ""
        if trig:
            prec_rows += f'<div class="prec-row"><strong>Trigger:</strong> {_e(trig)}</div>'
        if esc:
            prec_rows += f'<div class="prec-row"><strong>Pattern:</strong> {_e(esc)}</div>'
        if res_m:
            rt_part = f" ({_e(res_t)})" if res_t else ""
            prec_rows += (
                f'<div class="prec-row"><strong>Resolution:</strong> {_e(res_m)}{rt_part}</div>'
            )

        delta_block = (
            f'<div class="delta-block"><div class="delta-title">THEN vs NOW</div>{delta_html}</div>'
            if delta_html
            else ""
        )

        parts.append(
            f'<section class="brief-section brief-precedent">'
            f'<div class="brief-label">HISTORICAL PRECEDENT{conf_note}</div>'
            f'<div class="precedent-case">{_e(case_name)}{dt_html}</div>'
            f'<div class="precedent-rows">{prec_rows}</div>'
            f"{delta_block}{breakpoint_html}</section>"
        )

    impl = (
        brief.get("downstream_implications")
        if isinstance(brief.get("downstream_implications"), dict)
        else {}
    )
    expected = impl.get("expected") if isinstance(impl.get("expected"), list) else []
    observed = impl.get("observed") if isinstance(impl.get("observed"), list) else []
    contradictions = impl.get("contradictions") if isinstance(impl.get("contradictions"), list) else []

    if expected or observed or contradictions:
        impl_html = ""
        direction_icons = {"positive": "↑", "negative": "↓", "uncertain": "?"}
        direction_colors = {"positive": "#2e7d32", "negative": "#c62828", "uncertain": "#888"}

        if expected:
            impl_html += '<div class="impl-group-label">EXPECTED (if claim holds)</div>'
            for e in expected[:6]:
                if not isinstance(e, dict):
                    continue
                if_claim = str(e.get("if_claim_holds") or e.get("implication") or "").strip()
                if not if_claim:
                    continue
                direction = str(e.get("direction") or "uncertain").lower()
                icon = direction_icons.get(direction, "?")
                color = direction_colors.get(direction, "#888")
                itype = str(e.get("type") or "INFERRED").strip().upper()
                if itype not in ("FACT", "INFERRED"):
                    itype = "INFERRED"
                itc = "#2e7d32" if itype == "FACT" else "#e65100"
                itbg = "#e8f5e9" if itype == "FACT" else "#fff3e0"
                dom = str(e.get("domain") or "").strip().upper()
                tf = str(e.get("timeframe") or "").strip()
                tf_html = f'<span class="impl-timeframe">{_e(tf)}</span>' if tf else ""
                impl_html += (
                    f'<div class="implication-row">'
                    f'<span class="impl-direction" style="color:{color};">{icon}</span>'
                    f'<span class="impl-domain">{_e(dom)}</span>'
                    f'<span class="impl-text">{_e(if_claim)}</span>'
                    f'<span class="signal-type-tag impl-type-tag" '
                    f'style="color:{itc};background:{itbg};">{itype}</span>{tf_html}</div>'
                )

        if observed:
            impl_html += (
                '<div class="impl-group-label" style="margin-top:8px;">OBSERVED (current reality)</div>'
            )
            for o in observed[:4]:
                if not isinstance(o, dict):
                    continue
                cr = str(o.get("current_reality") or "").strip()
                if not cr:
                    continue
                src = str(o.get("source") or "").strip()
                dom_o = str(o.get("domain") or "").strip().upper()
                src_html = f'<span class="impl-source"> — {_e(src)}</span>' if src else ""
                impl_html += (
                    f'<div class="implication-row observed-row">'
                    f'<span class="impl-direction" style="color:#888;">·</span>'
                    f'<span class="impl-domain">{_e(dom_o)}</span>'
                    f'<span class="impl-text">{_e(cr)}{src_html}</span></div>'
                )

        if contradictions:
            impl_html += (
                '<div class="impl-group-label contradiction-label" style="margin-top:8px;">'
                "⚠ CONTRADICTIONS</div>"
            )
            for c in contradictions[:4]:
                if not isinstance(c, dict):
                    continue
                claim = str(c.get("claim") or "").strip()
                reality = str(c.get("reality") or "").strip()
                if not claim and not reality:
                    continue
                sig = str(c.get("significance") or "").strip()
                sig_html = f'<div class="contradiction-sig">{_e(sig)}</div>' if sig else ""
                impl_html += (
                    f'<div class="contradiction-row">'
                    f'<div class="contradiction-claim">Claim: {_e(claim)}</div>'
                    f'<div class="contradiction-reality">Record: {_e(reality)}</div>'
                    f"{sig_html}</div>"
                )

        parts.append(
            f'<section class="brief-section">'
            f'<div class="brief-label">DOWNSTREAM IMPLICATIONS</div>'
            f'<div class="implications-list">{impl_html}</div></section>'
        )

    signals = brief.get("analyst_signals") if isinstance(brief.get("analyst_signals"), list) else []
    if signals:
        sig_html = ""
        for sig in signals[:5]:
            if not isinstance(sig, dict):
                continue
            source = str(sig.get("source") or "").strip()
            sig_txt = str(sig.get("signal") or "").strip()
            if not source or not sig_txt:
                continue
            conf = str(sig.get("confidence") or "SECONDARY").strip().upper()
            conf_colors = {
                "PRIMARY": ("#2e7d32", "#e8f5e9"),
                "SECONDARY": ("#555", "#f5f5f5"),
                "INFERRED": ("#e65100", "#fff3e0"),
            }
            sc, sbg = conf_colors.get(conf, ("#555", "#f5f5f5"))
            url = str(sig.get("url") or sig.get("url_hint") or "").strip()
            url_ok = url if url.startswith("http://") or url.startswith("https://") else ""
            if url_ok:
                source_html = (
                    f'<a href="{_e(url_ok)}" target="_blank" rel="noopener" '
                    f'class="signal-source-link">{_e(source)}</a>'
                )
            else:
                source_html = f'<span class="signal-source">{_e(source)}</span>'
            model = str(sig.get("model_type") or "").strip()
            model_html = f'<span class="signal-model">· {_e(model)}</span>' if model else ""
            date = str(sig.get("date") or "").strip()
            date_html = f'<span class="signal-date">· {_e(date)}</span>' if date else ""
            excerpt = str(sig.get("excerpt_note") or "").strip()
            ex_html = f'<div class="signal-excerpt">{_e(excerpt)}</div>' if excerpt else ""
            sig_html += (
                f'<div class="signal-row">'
                f'<div class="signal-meta">'
                f"{source_html}"
                f'<span class="signal-conf-tag" style="color:{sc};background:{sbg};">{_e(conf)}</span>'
                f"{model_html}{date_html}</div>"
                f'<div class="signal-text">{_e(sig_txt)}</div>{ex_html}</div>'
            )

        parts.append(
            f'<section class="brief-section">'
            f'<div class="brief-label">ANALYST SIGNALS</div>'
            f'<div class="signals-list">{sig_html}</div></section>'
        )

    comp = brief.get("comparable_moment") if isinstance(brief.get("comparable_moment"), dict) else {}
    if not comp and isinstance(brief.get("comparable_moment_brief"), dict):
        c0 = brief["comparable_moment_brief"]
        comp = {
            "headline": c0.get("headline"),
            "then": {"dynamics": c0.get("then")},
            "now": {"current_signals": c0.get("now")},
            "pattern": c0.get("lesson"),
            "breakpoint": "",
        }
    headline = str(comp.get("headline") or "").strip()
    if headline:
        then = comp.get("then") if isinstance(comp.get("then"), dict) else {}
        now = comp.get("now") if isinstance(comp.get("now"), dict) else {}
        pattern = str(comp.get("pattern") or "").strip()
        brk = str(comp.get("breakpoint") or "").strip()

        then_trig = str(then.get("trigger") or "").strip()
        then_dyn = str(then.get("dynamics") or "").strip()
        then_tl = str(then.get("timeline") or "").strip()
        now_sig = str(now.get("current_signals") or "").strip()
        now_act = str(now.get("actor_alignment") or "").strip()

        then_bits = ""
        if then_trig:
            then_bits += f'<div class="prec-row"><strong>Trigger:</strong> {_e(then_trig)}</div>'
        if then_dyn:
            then_bits += f'<div class="prec-row"><strong>Dynamics:</strong> {_e(then_dyn)}</div>'
        if then_tl:
            then_bits += f'<div class="prec-row"><strong>Timeline:</strong> {_e(then_tl)}</div>'

        now_bits = ""
        if now_sig:
            now_bits += f'<div class="prec-row">{_e(now_sig)}</div>'
        if now_act:
            now_bits += (
                f'<div class="prec-row"><strong>Actor alignment:</strong> {_e(now_act)}</div>'
            )

        pat_html = (
            f'<div class="comparable-pattern"><strong>Pattern:</strong> {_e(pattern)}</div>'
            if pattern
            else ""
        )
        brk_html = (
            f'<div class="breakpoint-block">'
            f'<span class="breakpoint-label">WHERE ANALOGY BREAKS DOWN</span>'
            f'<span class="breakpoint-text">{_e(brk)}</span></div>'
            if brk
            else ""
        )

        parts.append(
            f'<section class="brief-section brief-comparable">'
            f'<div class="brief-label">COMPARABLE MOMENT</div>'
            f'<div class="comparable-headline">{_e(headline)}</div>'
            f'<div class="comparable-columns">'
            f'<div class="comparable-col">'
            f'<div class="comparable-col-label">THEN</div>{then_bits}</div>'
            f'<div class="comparable-col">'
            f'<div class="comparable-col-label">NOW</div>{now_bits}</div>'
            f"</div>{pat_html}{brk_html}</section>"
        )

    hooks = brief.get("investigative_hooks") if isinstance(brief.get("investigative_hooks"), dict) else {}
    questions = hooks.get("next_questions") if isinstance(hooks.get("next_questions"), list) else []
    actions = hooks.get("next_actions") if isinstance(hooks.get("next_actions"), list) else []

    if questions or actions:
        q_html = ""
        for q in questions[:6]:
            qs = str(q).strip()
            if not qs:
                continue
            enc = quote_plus(qs[:200])
            q_html += (
                f'<div class="hook-question">'
                f'<span class="hook-q-icon">?</span>'
                f'<a href="https://news.google.com/search?q={enc}" '
                f'target="_blank" rel="noopener" class="hook-q-link">{_e(qs)}</a></div>'
            )

        a_html = ""
        for act in actions[:6]:
            if not isinstance(act, dict):
                continue
            action = str(act.get("action") or "").strip()
            where = str(act.get("where") or "").strip()
            why_s = str(act.get("why") or "").strip()
            if not action and not where:
                continue
            href = _brief_hook_action_href(where, action)
            if href:
                where_html = (
                    f'<a href="{_e(href)}" target="_blank" rel="noopener" '
                    f'class="action-where-link">{_e(where or action)}</a>'
                )
            else:
                where_html = f'<span class="action-where">{_e(where)}</span>'
            why_html = f'<div class="action-why">{_e(why_s)}</div>' if why_s else ""
            verb = _e(action) if action else ""
            a_html += (
                f'<div class="hook-action">'
                f'<span class="action-verb">{verb}</span> {where_html}{why_html}</div>'
            )

        qh = f'<div class="hooks-questions-label">NEXT QUESTIONS</div>{q_html}' if q_html else ""
        ah = f'<div class="hooks-actions-label">NEXT ACTIONS</div>{a_html}' if a_html else ""
        if qh or ah:
            parts.append(
                f'<section class="brief-section brief-hooks">'
                f'<div class="brief-label">INVESTIGATIVE HOOKS</div>{qh}{ah}</section>'
            )

    return f'<div class="ctx-brief-stack">{"".join(parts)}</div>'


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

    gp_raw = receipt.get("global_perspectives") if isinstance(receipt.get("global_perspectives"), dict) else {}
    claims_verified_list = _safe_list(receipt.get("claims_verified"))
    named_entities_list = _safe_list(receipt.get("named_entities"))
    eco_n = _safe_list(gp_raw.get("ecosystems"))
    div_n = _safe_list(gp_raw.get("divergence_points"))
    absent_n = _safe_list(gp_raw.get("absent_from_all"))
    consensus_n = _safe_list(gp_raw.get("consensus_elements"))
    has_gp_signal = (
        bool(eco_n)
        or bool(div_n)
        or bool(absent_n)
        or bool(consensus_n)
        or bool(str(gp_raw.get("claim", "") or "").strip())
        or bool(str(gp_raw.get("reasoning_summary", "") or "").strip())
        or bool(_safe_list(gp_raw.get("investigative_leads")))
    )

    echo_standalone_html = ""
    if not coalition:
        ech = receipt.get("echo_chamber")
        if isinstance(ech, dict) and ech.get("score") is not None:
            echo_standalone_html = _echo_chamber_standalone_html(ech, gp_raw)
        elif rtype == "article_analysis":
            base_sources = receipt.get("sources")
            if isinstance(base_sources, list) and base_sources:
                echo_standalone_html = _echo_chamber_standalone_html(
                    compute_echo_chamber_score(
                        merge_sources_for_echo(base_sources, None),
                        None,
                    ),
                    gp_raw,
                )

    claims_section_html = _claims_section_html(receipt)
    summary_block_html = _summary_section_html(receipt)
    dig_deeper_html = _dig_deeper_button_html(str(rid))
    perspectives_block_html = (
        _global_perspectives_section_html(gp_raw)
        if (rtype == "article_analysis" or gp_raw)
        else ""
    )
    absent_from_all_html = (
        _absent_from_all_section_html(gp_raw) if (rtype == "article_analysis" or gp_raw) else ""
    )
    investigative_leads_html = (
        _investigative_leads_section_html(gp_raw)
        if (rtype == "article_analysis" or gp_raw)
        else ""
    )
    named_entities_html = _named_entities_section_html(receipt)
    coverage_block_html = (
        _coverage_provenance_html(receipt) if rtype == "article_analysis" else ""
    )
    sources_section_html = _sources_section_html(receipt)
    drift_section_html = (
        _drift_tracker_html(str(rid)) if (rtype == "article_analysis" and rid) else ""
    )
    actors_section_html = (
        _actors_map_html(str(rid)) if (rtype == "article_analysis" and rid) else ""
    )

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
        base_sources = receipt.get("sources") or []
        echo = compute_echo_chamber_score(
            merge_sources_for_echo(base_sources if isinstance(base_sources, list) else [], coalition),
            coalition,
        )
        echo_score = int(round(float(echo.get("score", 0))))
        echo_label = str(echo.get("label", "") or "")
        echo_interp = str(echo.get("interpretation", "") or "")
        echo_components = echo.get("components") or {}
        echo_color = {"low": "#22C55E", "moderate": "#F59E0B", "high": "#EF4444"}.get(
            echo_label, "#9CA3AF"
        )
        if echo_label == "high":
            echo_pill_bg = "#FFF5F5"
        elif echo_label == "moderate":
            echo_pill_bg = "#FFFBF0"
        else:
            echo_pill_bg = "#F0FFF4"
        components_html = "".join(
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:6px 0;border-bottom:1px solid rgba(0,0,0,0.05);'
            f'font-size:12px">'
            f'<span style="color:#6B7280">{_e(k.replace("_", " ").title())}</span>'
            f'<span style="font-weight:600;color:#111827">{_e(v)}/20</span>'
            f"</div>"
            for k, v in echo_components.items()
        )
        echo_html = f"""
    <div style="flex:1;min-width:260px;padding:20px 24px;
                background:#FFFFFF;border:1px solid rgba(0,0,0,0.08);
                border-radius:12px">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap">
        <div style="display:inline-flex;align-items:center;gap:8px;
                    padding:8px 16px;border-radius:20px;
                    background:{echo_pill_bg};
                    border:1px solid {echo_color}22">
          <span style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;
                       color:{echo_color};font-weight:700">ECHO CHAMBER</span>
          <span style="font-family:'Playfair Display',serif;font-size:28px;
                       font-weight:900;color:#111827;line-height:1">{echo_score}</span>
          <span style="font-size:12px;color:{echo_color}">/100</span>
        </div>
        <a href="/methodology#echo-chamber"
           style="font-size:12px;color:#9CA3AF;border-bottom:1px solid rgba(0,0,0,0.15)">
          How this is calculated →
        </a>
      </div>
      <div style="font-size:13px;color:#6B7280;line-height:1.6;margin-bottom:16px">
        {_e(echo_interp)}
      </div>
      <div style="border-top:1px solid rgba(0,0,0,0.06);padding-top:12px">
        <div style="font-size:10px;letter-spacing:0.1em;text-transform:uppercase;
                    color:#9CA3AF;font-weight:600;margin-bottom:8px">
          SCORE COMPONENTS
        </div>
        {components_html}
      </div>
    </div>"""

        coalition_fight_html = f"""
<!-- VOLATILITY + ECHO CHAMBER -->
<div style="display:flex;flex-wrap:wrap;gap:24px;align-items:flex-start;margin-bottom:24px">
  <div style="flex:1;min-width:280px">
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
    <span style="font-size:16px;color:#555555">{_e(vol_copy)}</span>
    <button onclick="toggleWhyNumber()" style="font-size:13px;color:#555;
            background:none;border:none;cursor:pointer;padding:0;
            text-decoration:underline;text-underline-offset:3px">
      Why this number?
    </button>
    <span style="color:#ccc;margin:0 4px">·</span>
    <a href="/methodology#volatility" style="font-size:13px;color:#555;
       text-decoration:underline;text-underline-offset:3px">Methodology</a>
  </div>
  <div id="why-number" style="display:none;margin-top:10px;padding:12px 16px;
       border-radius:8px;background:#FFFFFF;border:1px solid rgba(0,0,0,0.1);
       font-size:16px;color:#333;line-height:1.6;max-width:520px">
    The volatility score measures how far apart the two most opposed outlet clusters
    are on this story — based on what each side emphasizes vs. minimizes, and how
    confidently they hold those positions. It's not a vibe: it's calculated from the
    actual emphasis and omission tags in the source analysis. 0 = everyone agrees.
    100 = parallel realities with no shared premise.
  </div>
  </div>
  {echo_html}
</div>

<!-- IRRECONCILABLE GAP — always visible -->
<div style="margin-bottom:32px;padding:18px 22px;
            border-left:3px solid {accent};
            background:{pill_bg};border-radius:0 10px 10px 0">
  <div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;
              color:{accent};margin-bottom:8px;font-weight:600">Where the story splits</div>
  <div style="font-size:16px;color:#1a1a1a;line-height:1.65">{_e(irreconcilable_gap)}</div>
</div>

<!-- TWO ANCHOR CARDS -->
<div style="display:flex;gap:1px;background:rgba(0,0,0,0.08);
            border-radius:14px;overflow:hidden;margin-bottom:24px">

  <!-- SIDE A -->
  <div style="flex:1;background:#FFFFFF;padding:24px 22px">
    <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                color:#7eb8ff;margin-bottom:8px">{_e(a_anchor)}</div>
    <div style="font-family:'Playfair Display',serif;font-size:22px;font-weight:700;
                color:#111827;margin-bottom:10px;line-height:1.2">{_e(a_label)}</div>
    <div style="font-size:18px;color:#555555;line-height:1.6;margin-bottom:16px">
      {_e(a_summary)}</div>
    <div style="margin-bottom:10px">
      <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                  color:#555555;margin-bottom:5px">Emphasizes</div>
      {_pills(a_em, "green")}
    </div>
    <div>
      <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                  color:#555555;margin-bottom:5px">Minimizes</div>
      {_pills(a_mn, "red")}
    </div>
  </div>

  <!-- VS -->
  <div style="display:flex;align-items:center;justify-content:center;
              background:#F5F2EC;padding:0 4px;min-width:36px">
    <span style="background:#F5F2EC;border:0.5px solid rgba(0,0,0,0.12);
                 border-radius:20px;padding:5px 8px;
                 font-size:12px;font-weight:700;color:#555">VS</span>
  </div>

  <!-- SIDE B -->
  <div style="flex:1;background:#FFFFFF;padding:24px 22px">
    <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                color:#ff8a80;margin-bottom:8px">{_e(b_anchor)}</div>
    <div style="font-family:'Playfair Display',serif;font-size:22px;font-weight:700;
                color:#111827;margin-bottom:10px;line-height:1.2">{_e(b_label)}</div>
    <div style="font-size:18px;color:#555555;line-height:1.6;margin-bottom:16px">
      {_e(b_summary)}</div>
    <div style="margin-bottom:10px">
      <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                  color:#555555;margin-bottom:5px">Emphasizes</div>
      {_pills(b_em, "green")}
    </div>
    <div>
      <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                  color:#555555;margin-bottom:5px">Minimizes</div>
      {_pills(b_mn, "red")}
    </div>
  </div>
</div>

<!-- WHO'S ON EACH SIDE — collapsed by default -->
<div style="margin-bottom:40px">
  <div style="display:flex;gap:12px;flex-wrap:wrap">

    <!-- Side A toggle -->
    <div style="flex:1;min-width:240px;border:0.5px solid rgba(0,0,0,0.08);
                border-radius:12px;background:#FFFFFF;overflow:hidden">
      <button onclick="toggleChain('chain-a')"
              style="width:100%;padding:14px 18px;background:rgba(56,132,255,0.06);border:none;
                     cursor:pointer;text-align:left;
                     border-bottom:0.5px solid rgba(0,0,0,0.08)">
        <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                    color:#5b9fff;margin-bottom:3px">Who's on this side</div>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div style="font-size:15px;font-weight:600;color:#111827">{_e(a_label)}</div>
          <div style="font-size:15px;color:#555;display:flex;align-items:center;gap:6px">
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
    <div style="flex:1;min-width:240px;border:0.5px solid rgba(0,0,0,0.08);
                border-radius:12px;background:#FFFFFF;overflow:hidden">
      <button onclick="toggleChain('chain-b')"
              style="width:100%;padding:14px 18px;background:rgba(224,80,80,0.06);border:none;
                     cursor:pointer;text-align:left;
                     border-bottom:0.5px solid rgba(0,0,0,0.08)">
        <div style="font-size:13px;letter-spacing:0.1em;text-transform:uppercase;
                    color:#e05050;margin-bottom:3px">Who's on this side</div>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div style="font-size:15px;font-weight:600;color:#111827">{_e(b_label)}</div>
          <div style="font-size:15px;color:#555;display:flex;align-items:center;gap:6px">
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
        show_coalition_placeholder = (
            not has_gp_signal and not claims_verified_list and not echo_standalone_html
        )
        coalition_section = no_coalition_html if show_coalition_placeholder else ""

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
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#111827">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="PUBLIC EYE">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">
<script>
  if ('serviceWorker' in navigator) {{
    navigator.serviceWorker.register('/sw.js');
  }}
</script>
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
    background:#F7F4EF;color:#1a1a1a;padding:28px 24px 32px;border-radius:8px;margin-bottom:8px;
    border:1px solid rgba(26,26,26,0.12);
  }}
  .inv-paper-card{{background:#fff;border:1px solid rgba(26,26,26,0.15);border-radius:4px;}}
  .ctx-brief-stack{{margin-bottom:32px;}}
  .summary-section,.brief-section{{
    background:#fff;border:1px solid rgba(26,26,26,0.12);border-radius:4px;padding:14px 18px;margin-bottom:10px;
  }}
  .brief-label{{
    font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#555;margin-bottom:8px;
    font-weight:700;display:flex;align-items:center;gap:8px;flex-wrap:wrap;
  }}
  .summary-text,.brief-text{{font-size:18px;color:#333;line-height:1.7;}}
  .brief-text{{font-size:16px;}}
  .claim-type-tag{{
    font-size:11px;font-weight:800;letter-spacing:0.1em;padding:2px 8px;border-radius:10px;text-transform:uppercase;vertical-align:middle;
  }}
  .signal-type-tag{{
    font-size:11px;font-weight:700;padding:1px 6px;border-radius:8px;letter-spacing:0.06em;text-transform:uppercase;white-space:nowrap;
  }}
  .impl-type-tag{{font-size:10px !important;padding:2px 5px !important;}}
  .urgency-badge{{font-size:11px;padding:2px 8px;border-radius:10px;font-weight:700;letter-spacing:0.06em;}}
  .impact-signals{{margin-top:8px;display:flex;flex-direction:column;gap:5px;}}
  .impact-signal{{
    display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;padding:4px 0;border-bottom:1px solid rgba(26,26,26,0.06);
  }}
  .impact-signal:last-child{{border-bottom:none;}}
  .impact-signal-text{{font-size:16px;color:#333;flex:1;line-height:1.55;}}
  .signal-attr{{font-size:13px;color:#888;}}
  .brief-precedent{{border-left:3px solid #1a1a1a;}}
  .precedent-case{{
    font-size:17px;font-weight:700;color:#1a1a1a;margin-bottom:8px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;
  }}
  .precedent-date{{font-size:14px;font-weight:400;color:#888;}}
  .precedent-rows{{display:flex;flex-direction:column;gap:4px;margin-bottom:8px;}}
  .prec-row{{font-size:15px;color:#444;line-height:1.5;}}
  .conf-low-note{{font-size:12px;color:#e65100;font-style:italic;}}
  .delta-block{{margin:8px 0;padding:8px 0;border-top:1px dashed rgba(26,26,26,0.12);}}
  .delta-title{{
    font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#aaa;margin-bottom:6px;font-weight:700;
  }}
  .delta-row{{display:flex;gap:10px;padding:3px 0;font-size:15px;}}
  .delta-label{{min-width:130px;color:#888;font-size:14px;}}
  .delta-text{{color:#333;flex:1;}}
  .breakpoint-block{{
    background:#fff8e1;border-left:3px solid #f9a825;padding:8px 10px;margin-top:8px;
    display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;
  }}
  .breakpoint-label{{
    font-size:11px;font-weight:800;color:#f57f17;letter-spacing:0.08em;white-space:nowrap;
  }}
  .breakpoint-text{{font-size:15px;color:#5d4037;flex:1;line-height:1.5;}}
  .impl-group-label{{
    font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#aaa;margin-bottom:4px;font-weight:700;
  }}
  .contradiction-label{{color:#c62828 !important;}}
  .implications-list{{display:flex;flex-direction:column;gap:4px;}}
  .implication-row{{
    display:flex;align-items:baseline;gap:8px;padding:5px 0;border-bottom:1px solid rgba(26,26,26,0.06);flex-wrap:wrap;
  }}
  .implication-row:last-child{{border-bottom:none;}}
  .observed-row{{opacity:0.9;}}
  .impl-direction{{font-size:1.1em;font-weight:700;min-width:14px;}}
  .impl-domain{{font-size:11px;font-weight:700;letter-spacing:0.08em;color:#888;min-width:75px;}}
  .impl-text{{font-size:15px;color:#333;flex:1;line-height:1.5;min-width:120px;}}
  .impl-source{{font-size:14px;color:#888;}}
  .impl-timeframe{{font-size:12px;color:#aaa;white-space:nowrap;}}
  .contradiction-row{{
    background:#fff8f8;border-left:2px solid #e53935;padding:8px 10px;margin-bottom:6px;border-radius:0 3px 3px 0;
  }}
  .contradiction-claim{{font-size:15px;color:#444;font-style:italic;}}
  .contradiction-reality{{font-size:15px;color:#c62828;margin-top:4px;}}
  .contradiction-sig{{font-size:13px;color:#888;margin-top:4px;}}
  .signals-list{{display:flex;flex-direction:column;gap:10px;}}
  .signal-row{{padding:8px 0;border-bottom:1px solid rgba(26,26,26,0.06);}}
  .signal-row:last-child{{border-bottom:none;}}
  .signal-meta{{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:4px;}}
  .signal-source{{font-size:15px;font-weight:600;color:#1a1a1a;}}
  .signal-source-link{{
    font-size:15px;font-weight:600;color:#1a1a1a;text-decoration:underline;text-decoration-color:#ccc;
  }}
  .signal-source-link:hover{{text-decoration-color:#1a1a1a;}}
  .signal-conf-tag{{font-size:10px;padding:1px 6px;border-radius:8px;font-weight:700;letter-spacing:0.06em;}}
  .signal-model{{font-size:13px;color:#aaa;}}
  .signal-date{{font-size:13px;color:#aaa;}}
  .signal-text{{font-size:15px;color:#444;font-style:italic;line-height:1.5;}}
  .signal-excerpt{{font-size:13px;color:#aaa;margin-top:4px;}}
  .brief-comparable{{background:#f8f7f2;}}
  .comparable-headline{{
    font-size:18px;font-weight:700;color:#1a1a1a;font-style:italic;margin-bottom:12px;line-height:1.4;
  }}
  .comparable-columns{{display:flex;gap:16px;margin-bottom:10px;}}
  .comparable-col{{flex:1;}}
  .comparable-col-label{{
    font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:#aaa;font-weight:700;margin-bottom:4px;
  }}
  .comparable-pattern{{
    font-size:15px;color:#333;padding-top:8px;border-top:1px solid rgba(26,26,26,0.1);line-height:1.5;
  }}
  .brief-hooks{{border-left:3px solid #1a1a1a;}}
  .hooks-questions-label,.hooks-actions-label{{
    font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#aaa;font-weight:700;margin:8px 0 4px;
  }}
  .hooks-actions-label{{margin-top:14px;}}
  .hook-question{{
    display:flex;align-items:baseline;gap:8px;padding:5px 0;border-bottom:1px solid rgba(26,26,26,0.06);
  }}
  .hook-q-icon{{font-size:16px;font-weight:700;color:#888;min-width:14px;}}
  .hook-q-link{{
    font-size:15px;color:#1a1a1a;text-decoration:underline;text-decoration-color:#ccc;flex:1;line-height:1.5;
  }}
  .hook-q-link:hover{{text-decoration-color:#1a1a1a;}}
  .hook-action{{
    padding:6px 0;border-bottom:1px solid rgba(26,26,26,0.06);display:flex;flex-wrap:wrap;align-items:baseline;gap:6px;
  }}
  .action-verb{{
    font-size:12px;text-transform:uppercase;letter-spacing:0.07em;color:#888;white-space:nowrap;
  }}
  .action-where,.action-where-link{{font-size:15px;font-weight:600;color:#1a1a1a;}}
  .action-where-link{{text-decoration:underline;text-decoration-color:#ccc;}}
  .action-where-link:hover{{text-decoration-color:#1a1a1a;}}
  .action-why{{width:100%;font-size:13px;color:#888;margin-top:4px;}}
  @media (max-width: 600px) {{
    .comparable-columns{{flex-direction:column;}}
    .delta-row{{flex-direction:column;gap:2px;}}
    .implication-row{{flex-direction:column;align-items:flex-start;gap:4px;}}
  }}
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
  .cited-source {{
    background: #fff8f0;
    border-left: 3px solid #e67e22;
    padding: 6px 10px;
    margin: 8px 0;
    font-size: 0.9em;
    color: #333;
  }}
  .cited-source a {{
    color: #0d47a1;
    text-decoration: underline;
    text-underline-offset: 3px;
    word-break: break-all;
  }}
  .verification-none {{
    color: #999;
    font-style: italic;
    font-size: 0.85em;
  }}
  .claim-type-badge {{
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.75em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    background: #eee;
    color: #444;
    border: 1px solid #ddd;
  }}
  .claim-type-badge.claim-type-rumored {{
    background: #fff3cd;
    color: #856404;
    border: 1px solid #ffc107;
  }}
  .claim-type-badge.claim-type-biographical {{
    background: #e3f2fd;
    color: #1565c0;
    border: 1px solid #90caf9;
  }}
  .claim-type-badge.claim-type-statistical {{
    background: #f3e5f5;
    color: #6a1b9a;
    border: 1px solid #ce93d8;
  }}
  .claim-card {{
    border: 1px solid #e8e4dc;
    border-radius: 4px;
    margin-bottom: 1.5rem;
    overflow: hidden;
  }}
  .claim-card-rumored {{
    border-left: 3px solid #ffc107;
    background: #fffdf7;
  }}
  .claim-header {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    background: #f8f7f2;
    border-bottom: 1px solid #e8e4dc;
  }}
  .claim-count {{
    margin-left: auto;
    font-size: 11px;
    color: #999;
    letter-spacing: 0.04em;
  }}
  .claim-subject {{
    font-size: 16px;
    font-weight: 600;
    color: #111827;
  }}
  .claim-rows {{
    padding: 0;
  }}
  .claim-row {{
    padding: 12px 16px;
    border-bottom: 1px solid #f0ede6;
  }}
  .claim-row:last-child {{
    border-bottom: none;
  }}
  .claim-row-rumored {{
    background: #fffef7;
  }}
  .claim-row-text {{
    font-size: 0.95em;
    line-height: 1.5;
    margin-bottom: 4px;
  }}
  .claim-verification-wrap {{
    margin-top: 8px;
  }}
  .revision-trail {{
    margin-top: 10px;
    border-top: 1px solid #e8e4dc;
    padding-top: 10px;
  }}
  .revision-trail-label {{
    font-size: 0.68em;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #888;
    font-weight: 700;
    margin-bottom: 8px;
  }}
  .revision-item {{
    border-radius: 4px;
    overflow: hidden;
    margin-bottom: 8px;
    border: 1px solid #e8e4dc;
  }}
  .revision-header {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 10px;
    background: #f8f7f2;
    border-bottom: 1px solid #e8e4dc;
  }}
  .revision-badge {{
    font-size: 0.65em;
    font-weight: 800;
    letter-spacing: 0.1em;
    padding: 2px 8px;
    border-radius: 10px;
    text-transform: uppercase;
  }}
  .revision-gap {{
    font-size: 0.75em;
    color: #888;
    font-style: italic;
  }}
  .revision-timeline {{
    display: flex;
    align-items: stretch;
    gap: 0;
  }}
  .revision-before,
  .revision-after {{
    flex: 1;
    padding: 10px 12px;
  }}
  .revision-before {{
    border-right: 1px solid #e8e4dc;
    background: #fffefe;
  }}
  .revision-after {{
    background: #f8fff8;
  }}
  .revision-arrow {{
    display: flex;
    align-items: center;
    padding: 0 8px;
    color: #ccc;
    font-size: 1.2em;
    background: #f8f7f2;
  }}
  .revision-date-label {{
    display: block;
    font-size: 0.62em;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #aaa;
    margin-bottom: 2px;
  }}
  .revision-date {{
    display: block;
    font-size: 0.78em;
    font-weight: 600;
    color: #555;
    margin-bottom: 4px;
  }}
  .revision-claim-text {{
    font-size: 0.85em;
    color: #1a1a1a;
    line-height: 1.5;
    font-style: italic;
  }}
  .revision-attribution {{
    font-size: 0.75em;
    color: #888;
    margin-top: 4px;
  }}
  .revision-source-link {{
    color: #1a1a1a;
    text-decoration: underline;
    text-decoration-color: #ccc;
  }}
  .revision-source-link:hover {{ text-decoration-color: #1a1a1a; }}
  .revision-significance {{
    padding: 6px 12px 8px;
    font-size: 0.78em;
    color: #666;
    background: #fafafa;
    border-top: 1px solid #f0ede6;
    line-height: 1.5;
  }}
  @media (max-width: 600px) {{
    .revision-timeline {{ flex-direction: column; }}
    .revision-before {{ border-right: none; border-bottom: 1px solid #e8e4dc; }}
    .revision-arrow {{ display: none; }}
  }}
  .verification-list {{
    margin-top: 6px;
  }}
  .claims-section .section-label {{
    font-size: 13px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #555;
    margin-bottom: 14px;
  }}
  .rumor-source-block {{
    margin: 10px 0;
    padding: 8px 12px;
    background: #fff8e1;
    border-radius: 4px;
    font-size: 0.92em;
  }}
  .rumor-label {{ color: #856404; margin-right: 6px; font-weight: 500; }}
  .rumor-language {{ font-size: 0.88em; color: #555; margin: 6px 0; line-height: 1.45; }}
  .rumor-disclaimer {{
    font-size: 0.82em;
    color: #777;
    font-style: italic;
    border-top: 1px solid #f0e68c;
    padding-top: 8px;
    margin-top: 10px;
    line-height: 1.5;
  }}
  .verification-courtlistener {{
    border-left: 2px solid #2c3e50;
    padding-left: 10px;
    margin: 6px 0;
  }}
  .court-result {{ margin-top: 6px; font-size: 0.92em; }}
  .court-meta {{ color: #888; font-size: 0.82em; margin-top: 4px; }}
  .court-snippet {{ color: #555; font-style: italic; margin-top: 6px; font-size: 0.86em; line-height: 1.45; }}
  .verification-courtlistener .court-result a {{
    color: #2c3e50;
    text-decoration: underline;
    text-underline-offset: 2px;
  }}
  .outlet-link {{
    color: #1a1a1a;
    text-decoration: underline;
    text-decoration-color: #ccc;
  }}
  .outlet-link:hover {{
    text-decoration-color: #1a1a1a;
  }}
  .eye-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 18px 14px;
    padding: 0.5rem 0 2rem;
  }}

  .eye-pill {{
    position: relative;
    width: 44px;
    height: 26px;
    cursor: pointer;
    text-decoration: none;
    display: inline-block;
    flex-shrink: 0;
  }}

  .eye-svg {{
    width: 44px;
    height: 26px;
    overflow: visible;
    display: block;
  }}

  .closed-line {{
    stroke: #111111;
    stroke-width: 3;
    stroke-linecap: round;
    fill: none;
    opacity: 1;
    transition: opacity 0.2s ease;
  }}

  .eye-lash {{
    stroke: #111111;
    stroke-width: 2;
    stroke-linecap: round;
    opacity: 1;
    transition: opacity 0.15s ease;
  }}

  .open-outline {{
    fill: #f0ede6;
    stroke: #111111;
    stroke-width: 3;
    opacity: 0;
    transition: opacity 0.25s ease 0.05s;
  }}

  .eye-pupil {{
    fill: #111111;
    opacity: 0;
    transition: opacity 0.2s ease 0.12s;
  }}

  .eye-shine {{
    fill: #ffffff;
    opacity: 0;
    transition: opacity 0.15s ease 0.2s;
  }}

  .eye-twinkle {{
    fill: #111111;
    opacity: 0;
    transform-origin: 31px 4px;
    transition: opacity 0.15s ease 0.28s;
  }}

  .eye-pill:hover .eye-twinkle {{
    opacity: 1;
    animation: twinkle-pop 0.4s ease 0.28s forwards;
  }}

  @keyframes twinkle-pop {{
    0%   {{ opacity: 0; transform: scale(0) rotate(0deg); }}
    60%  {{ opacity: 1; transform: scale(1.3) rotate(15deg); }}
    100% {{ opacity: 1; transform: scale(1) rotate(0deg); }}
  }}

  .eye-label {{
    position: absolute;
    bottom: -20px;
    left: 50%;
    transform: translateX(-50%);
    white-space: nowrap;
    color: #222222;
    font-size: 11px;
    font-weight: 500;
    opacity: 0;
    transition: opacity 0.18s ease;
    pointer-events: none;
    font-family: inherit;
  }}

  .eye-pill:hover .closed-line,
  .eye-pill:hover .eye-lash {{
    opacity: 0;
  }}

  .eye-pill:hover .open-outline,
  .eye-pill:hover .eye-pupil,
  .eye-pill:hover .eye-shine {{
    opacity: 1;
  }}

  .eye-pill:hover .eye-label {{
    opacity: 1;
  }}

  .dig-deeper-section {{
    margin: 2.5rem 0;
    text-align: center;
  }}
  .mouth-btn {{
    background: none;
    border: 2px solid #111111;
    border-radius: 4px;
    padding: 1rem 2rem;
    cursor: pointer;
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    transition: background 0.15s ease;
    font-family: inherit;
  }}
  .mouth-btn:hover {{ background: #f5f2eb; }}
  .mouth-btn.loading {{ opacity: 0.6; pointer-events: none; }}
  .mouth-svg {{
    width: 96px;
    height: 48px;
    overflow: visible;
  }}
  .mouth-closed {{
    fill: #111111;
    opacity: 1;
    transition: opacity 0.2s ease;
  }}
  .mouth-open-upper,
  .mouth-open-lower {{
    fill: none;
    stroke: #111111;
    stroke-width: 2.5;
    stroke-linecap: round;
    opacity: 0;
    transition: opacity 0.2s ease 0.1s;
  }}
  .mouth-teeth {{
    fill: #ffffff;
    stroke: #111111;
    stroke-width: 1;
    opacity: 0;
    transition: opacity 0.15s ease 0.15s;
  }}
  .mouth-tongue {{
    fill: #cc4444;
    opacity: 0;
    transition: opacity 0.15s ease 0.2s;
  }}
  .fact-dot {{
    fill: #111111;
    opacity: 0;
  }}
  .mouth-btn.open .mouth-closed {{ opacity: 0; }}
  .mouth-btn.open .mouth-open-upper,
  .mouth-btn.open .mouth-open-lower,
  .mouth-btn.open .mouth-teeth,
  .mouth-btn.open .mouth-tongue {{ opacity: 1; }}
  .mouth-btn.open .fact-dot {{
    opacity: 1;
    animation: dig-spill 0.65s ease forwards;
  }}
  .mouth-btn.open .fact-dot.dd1 {{ animation-delay: 0.05s; }}
  .mouth-btn.open .fact-dot.dd2 {{ animation-delay: 0.12s; }}
  .mouth-btn.open .fact-dot.dd3 {{ animation-delay: 0.18s; }}
  .mouth-btn.open .fact-dot.dd4 {{ animation-delay: 0.08s; }}
  .mouth-btn.open .fact-dot.dd5 {{ animation-delay: 0.15s; }}
  @keyframes dig-spill {{
    0%   {{ transform: translateY(0); opacity: 0; }}
    35%  {{ opacity: 1; }}
    100% {{ transform: translateY(14px); opacity: 1; }}
  }}
  .mouth-label {{
    font-size: 10px;
    letter-spacing: 0.12em;
    font-weight: 600;
    color: #111111;
  }}
  .deeper-results {{
    margin-top: 1.5rem;
    text-align: left;
  }}
  .deeper-loading {{
    text-align: center;
    padding: 2rem;
    color: #999;
    font-size: 0.85em;
    letter-spacing: 0.05em;
  }}
  .dig-deeper-h3 {{
    font-size: 0.75em;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #999;
    margin-bottom: 0.75rem;
    margin-top: 0.5rem;
    font-weight: 600;
  }}
  .counter-claim-card {{
    border-left: 3px solid #e74c3c;
    background: #fff8f8;
    padding: 10px 14px;
    margin-bottom: 12px;
    border-radius: 0 4px 4px 0;
  }}
  .counter-claim-label {{
    font-size: 10px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #e74c3c;
    font-weight: 700;
    margin-bottom: 4px;
  }}
  .counter-source {{
    font-size: 0.8em;
    color: #888;
    margin-top: 4px;
  }}
  .no-primary-source {{
    font-size: 0.75em;
    background: #fff3cd;
    color: #856404;
    padding: 3px 8px;
    border-radius: 3px;
    display: inline-block;
    margin-top: 4px;
  }}
  .unsourced-block {{
    background: #f8f7f2;
    border: 1px solid #e8e4dc;
    border-radius: 4px;
    padding: 12px 16px;
    margin-bottom: 12px;
  }}
  .unsourced-count {{
    font-size: 1.1em;
    font-weight: 700;
    color: #1a1a1a;
  }}
  .unsourced-label {{
    font-size: 0.8em;
    color: #888;
    margin-top: 2px;
  }}
  .crime-taxonomy-section {{ margin-bottom: 1.5rem; }}
  .crime-row {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
    border-bottom: 1px solid #f0ede6;
    font-size: 0.85em;
  }}
  .crime-type {{ flex: 1; color: #333; }}
  .crime-bar-wrap {{ flex: 2; background: #eee; border-radius: 2px; height: 6px; }}
  .crime-bar {{ height: 6px; border-radius: 2px; background: #111111; }}
  .crime-count {{ min-width: 40px; text-align: right; color: #888; font-size: 0.9em; }}
  .court-case-link {{
    color: #2c3e50;
    font-weight: 600;
    text-decoration: underline;
    text-underline-offset: 2px;
  }}

  .reasoning-summary {{
    font-size: 0.95em;
    color: #444;
    line-height: 1.6;
    margin: 0 0 16px;
    padding: 12px 14px;
    background: #faf8f4;
    border-left: 3px solid #111;
    border-radius: 0 4px 4px 0;
  }}
  .reasoning-label {{
    display: block;
    font-size: 0.72em;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #666;
    margin-bottom: 6px;
    font-weight: 700;
  }}
  .confidence-decomp {{
    margin-bottom: 20px;
    padding: 12px 14px;
    background: #fff;
    border: 1px solid #e8e4dc;
    border-radius: 4px;
  }}
  .conf-row {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 10px;
    flex-wrap: wrap;
  }}
  .conf-row:last-child {{ margin-bottom: 0; }}
  .conf-label {{
    min-width: 110px;
    color: #888;
    font-size: 0.85em;
  }}
  .conf-bar-wrap {{
    flex: 1;
    height: 6px;
    background: #e8e4dc;
    border-radius: 3px;
    overflow: hidden;
    display: flex;
    min-width: 120px;
  }}
  .conf-bar-cited {{ background: #2e7d32; height: 100%; }}
  .conf-bar-inferred {{ background: #f9a825; height: 100%; }}
  .conf-bar-consensus {{ background: #1565c0; height: 100%; }}
  .conf-bar-contested {{ background: #c62828; height: 100%; }}
  .conf-detail {{
    font-size: 0.78em;
    color: #888;
    min-width: 160px;
    text-align: right;
  }}
  .conf-evidence-type {{
    font-size: 0.75em;
    color: #aaa;
    margin-top: 4px;
    text-align: right;
  }}
  .trigger-phrases {{
    margin: 6px 0 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
  }}
  .trigger-label {{
    font-size: 0.75em;
    color: #888;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-right: 4px;
  }}
  .trigger-phrase {{
    font-size: 0.82em;
    background: #f0ede6;
    border: 1px solid #e0ddd6;
    border-radius: 3px;
    padding: 2px 8px;
    color: #444;
    font-style: italic;
  }}
  .example-headlines {{
    margin: 8px 0 10px;
    padding: 8px 0 0;
    border-top: 1px dashed #e8e4dc;
  }}
  .headlines-label {{
    font-size: 0.72em;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: #aaa;
    margin-bottom: 6px;
  }}
  .example-headline {{
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 6px;
    font-size: 0.9em;
  }}
  .headline-text {{ color: #0d47a1; flex: 1; min-width: 0; }}
  .headline-source {{ font-size: 0.85em; color: #888; }}
  .headline-type {{
    font-size: 0.65em;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 2px 6px;
    border-radius: 2px;
  }}
  .headline-type.retrieved {{ background: #e8f5e9; color: #2e7d32; }}
  .headline-type.inferred {{ background: #fff8e1; color: #f57f17; }}
  .echo-conf-note {{
    font-size: 0.75em;
    color: #aaa;
    margin-top: 6px;
    font-style: italic;
  }}
  .absent-item-card {{
    margin-bottom: 14px;
    padding: 12px 14px;
    background: rgba(180, 83, 9, 0.06);
    border: 1px solid rgba(180, 83, 9, 0.2);
    border-radius: 8px;
    text-align: left;
  }}
  .absent-item-header {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
  }}
  .absent-reason-badge {{
    font-size: 0.65em;
    font-weight: 700;
    letter-spacing: 0.06em;
    padding: 4px 8px;
    border-radius: 3px;
  }}
  .absent-topic-link {{
    color: #5d4037;
    font-weight: 600;
    text-decoration: none;
    flex: 1;
    min-width: 0;
  }}
  .absent-why {{ font-size: 0.92em; color: #555; line-height: 1.5; margin-top: 6px; }}
  .absence-sources {{ font-size: 0.85em; color: #666; margin-top: 8px; }}
  .sources-label {{ font-weight: 600; margin-right: 6px; }}
  .suggested-source-link {{ color: #0d47a1; margin-right: 6px; }}
  .inv-lead-card {{
    padding: 12px 14px;
    margin-bottom: 10px;
    border: 1px solid #e0ddd6;
    border-radius: 4px;
    background: #fff;
    text-align: left;
  }}
  .inv-lead-action {{ font-size: 0.95em; color: #333; }}
  .inv-lead-reason {{ font-size: 0.88em; color: #666; margin-top: 6px; line-height: 1.45; }}
  .inv-lead-link {{ font-size: 0.85em; margin-top: 6px; display: inline-block; }}
  .coverage-sparse-note {{
    margin-top: 12px;
    font-size: 0.88em;
    color: #856404;
    line-height: 1.5;
  }}
  .query-expansion-chip {{
    display: inline-block;
    margin: 2px 6px 2px 0;
    padding: 2px 8px;
    background: #fff8e1;
    border-radius: 3px;
    font-size: 0.85em;
  }}
  .drift-section {{
    margin: 28px 0;
    padding: 16px 18px;
    border: 1px solid rgba(26, 26, 26, 0.12);
    border-radius: 6px;
    background: #fafafa;
    text-align: left;
  }}
  .drift-header {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
  }}
  .track-btn {{
    font-family: inherit;
    font-size: 11px;
    letter-spacing: 0.1em;
    font-weight: 700;
    padding: 8px 14px;
    border: 2px solid #111;
    background: #fff;
    cursor: pointer;
    border-radius: 4px;
  }}
  .track-btn:hover {{ background: #f5f2eb; }}
  .drift-timeline {{ font-size: 0.92em; color: #555; line-height: 1.5; }}
  .drift-point {{
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid #e8e4dc;
  }}
  .drift-score {{ font-weight: 700; }}
  .actors-section {{
    margin: 24px 0;
    padding: 16px 18px;
    border: 1px solid rgba(26, 26, 26, 0.1);
    border-radius: 6px;
    background: #fff;
    text-align: left;
  }}
  .actor-node {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin: 4px 8px 4px 0;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 0.88em;
    border: 1px solid #e0ddd6;
  }}
  .actor-type-person {{ background: #e3f2fd; }}
  .actor-type-org {{ background: #f3e5f5; }}
  .actor-type-gov {{ background: #ffebee; }}
  .actor-type-outlet {{ background: #e8f5e9; }}
  .actor-edge {{ font-size: 0.8em; color: #666; margin: 4px 0; }}
  .actor-badge {{
    font-size: 0.65em;
    margin-left: 4px;
    color: #0d47a1;
    text-decoration: underline;
    text-underline-offset: 2px;
  }}

  .named-entities-section {{
    margin: 2em 0 3em;
  }}

  .named-entities-section .section-label {{
    font-size: 13px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #555;
    margin-bottom: 10px;
  }}

  .absent-link {{
    display: block;
    text-decoration: none;
    color: inherit;
    width: 100%;
    border-radius: 8px;
    transition: box-shadow 0.15s ease, transform 0.12s ease;
  }}
  .absent-link:focus-visible {{
    outline: 2px solid #c67e22;
    outline-offset: 2px;
  }}
  .absent-link:hover {{
    box-shadow: 0 2px 8px rgba(26, 26, 26, 0.08);
  }}
  .absent-link:hover .absent-link-row {{
    border-color: rgba(180, 83, 9, 0.45);
  }}
  .absent-search-hint {{
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: #8d6e63;
    flex-shrink: 0;
  }}
  .surface-field {{ display: block; margin: 2px 0; font-size: 0.9em; }}
  .surface-substrate {{ color: #555; font-style: italic; }}
  .surface-tier {{ display: block; font-size: 0.8em; color: #888; margin-top: 4px; }}
  .surface-absent {{ display: block; font-size: 0.8em; color: #c0392b; }}
  .surface-verification-block {{
    margin: 6px 0 10px 12px;
    padding: 10px 12px;
    border-left: 2px solid rgba(26, 26, 26, 0.12);
    font-size: 15px;
    color: #333;
    line-height: 1.55;
  }}
  .sources-section {{ margin: 2em 0; }}
  .sources-section .section-label {{
    font-size: 13px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #555;
    margin-bottom: 10px;
  }}
  .source-row {{
    display: flex;
    gap: 1em;
    padding: 0.5em 0;
    border-bottom: 1px solid #eee;
    align-items: baseline;
  }}
  .source-type {{ font-size: 0.8em; color: #888; min-width: 140px; flex-shrink: 0; }}
  .source-link {{ color: #1a1a1a; font-size: 0.9em; word-break: break-all; text-decoration: none; }}
  .source-link:hover {{ text-decoration: underline; }}
  .claim-subject-link {{
    color: inherit;
    text-decoration: none;
    border-bottom: 1px dotted #999;
  }}
  .claim-subject-link:hover {{ border-bottom-color: #1a1a1a; }}
  .claim-text-link {{
    color: inherit;
    text-decoration: none;
  }}
  .claim-text-link:hover {{
    text-decoration: underline;
    text-decoration-color: #999;
  }}
  .entity-ref-link {{
    color: #2c3e50;
    text-decoration: underline;
    text-decoration-color: #bbb;
  }}
  .entity-ref-link:hover {{ text-decoration-color: #2c3e50; }}
  .internal-link {{
    color: #1a1a1a;
    font-weight: 600;
    text-decoration: underline;
  }}
  .internal-link:hover {{ color: #555; }}
  .court-case-link {{
    color: #2c3e50;
    font-weight: 600;
    text-decoration: underline;
  }}

  @media (prefers-color-scheme: dark) {{
    .closed-line, .eye-lash, .open-outline {{ stroke: #e0e0e0; }}
    .open-outline {{ fill: #2a2a2a; }}
    .eye-pupil {{ fill: #e0e0e0; }}
    .eye-shine {{ fill: #1a1a1a; }}
    .eye-label {{ color: #aaa; }}
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
    <form id="inv-investigate-form" action="#" method="get" style="display:inline-flex;gap:6px;align-items:center;margin-right:4px">
      <input type="text" id="inv-investigate-q" name="q" placeholder="URL, name, or topic…" autocomplete="off" aria-label="Article URL, name, or topic"
        style="width:min(220px,42vw);padding:5px 8px;font-size:12px;border:1px solid rgba(26,26,26,0.2);font-family:inherit" />
      <button type="submit" style="padding:5px 10px;font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;border:1px solid #1a1a1a;background:#1a1a1a;color:#F7F4EF;cursor:pointer">INVESTIGATE</button>
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

<!-- SUMMARY + CONTEXTUAL BRIEF -->
{summary_block_html}

{echo_standalone_html}

{coalition_section}

{perspectives_block_html}

{absent_from_all_html}

{investigative_leads_html}

{claims_section_html}

{dig_deeper_html}

{named_entities_html}

<!-- CROSS-CORROBORATED -->
{f'<div class="reporter-only" style="margin-bottom:32px"><div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#555;margin-bottom:12px">Cross-corroborated</div><div class="inv-paper-card" style="padding:4px 18px">{confirmed_html}</div></div>' if confirmed_html else ""}

<div style="height:1px;background:rgba(26,26,26,0.2);margin-bottom:32px"></div>

{reporter_strip}

{coverage_block_html}

{sources_section_html}

{drift_section_html}

{actors_section_html}

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
<script>
(function() {{
  function publicEyeInvestigate(q) {{
    q = (q || '').trim();
    if (!q) return;
    if (q.startsWith('http://') || q.startsWith('https://')) {{
      window.location.href = '/analyze?' + new URLSearchParams({{ url: q }});
      return;
    }}
    window.open('https://news.google.com/search?q=' + encodeURIComponent(q), '_blank');
  }}
  var form = document.getElementById('inv-investigate-form');
  var input = document.getElementById('inv-investigate-q');
  if (form && input) {{
    form.addEventListener('submit', function(e) {{
      e.preventDefault();
      publicEyeInvestigate(input.value);
    }});
  }}
}})();
</script>
<script>
(function() {{
  var cache = {{}};
  function escapeHtml(s) {{
    if (s == null) return '';
    var d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
  }}
  function escapeAttr(s) {{
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }}
  function renderDeeperResults(data) {{
    var html = '';
    var i, j;
    if (data.counter_claims && data.counter_claims.length) {{
      html += '<h3 class="dig-deeper-h3">Counter-claims from opposing outlets</h3>';
      for (i = 0; i < data.counter_claims.length; i++) {{
        var cc = data.counter_claims[i];
        var sourceHtml = cc.source ? '<span class="counter-source">Source: ' + escapeHtml(cc.source) + '</span>' : '';
        var noSrc = !cc.has_primary_source ? '<span class="no-primary-source">⚠ No primary source cited</span>' : '';
        html += '<div class="counter-claim-card"><div class="counter-claim-label">Counter-claim</div><div>' + escapeHtml(cc.claim) + '</div>' + sourceHtml + noSrc + '</div>';
      }}
    }}
    if (data.unsourced_patterns && data.unsourced_patterns.length) {{
      html += '<h3 class="dig-deeper-h3">Unsourced claim patterns</h3>';
      for (i = 0; i < data.unsourced_patterns.length; i++) {{
        var p = data.unsourced_patterns[i];
        var oc = p.outlet_count != null ? p.outlet_count : 0;
        var sc = p.sources_citing != null ? p.sources_citing : 0;
        var scLabel = sc === 0 ? '0 cited a primary source' : (sc + ' cited a source');
        html += '<div class="unsourced-block"><div class="unsourced-count">' + oc + ' outlets</div><div style="font-size:0.9em;margin:4px 0;">&ldquo;' + escapeHtml(p.claim) + '&rdquo;</div><div class="unsourced-label">repeated this claim — ' + scLabel + '</div></div>';
      }}
    }}
    if (data.crime_taxonomy && data.crime_taxonomy.length) {{
      var maxCr = 0;
      for (i = 0; i < data.crime_taxonomy.length; i++) {{
        if (data.crime_taxonomy[i].count > maxCr) maxCr = data.crime_taxonomy[i].count;
      }}
      if (maxCr < 1) maxCr = 1;
      html += '<h3 class="dig-deeper-h3">Case type breakdown</h3><div class="crime-taxonomy-section">';
      for (i = 0; i < data.crime_taxonomy.length; i++) {{
        var row = data.crime_taxonomy[i];
        var pct = Math.round((row.count / maxCr) * 100);
        html += '<div class="crime-row"><span class="crime-type">' + escapeHtml(row.type) + '</span><div class="crime-bar-wrap"><div class="crime-bar" style="width:' + pct + '%"></div></div><span class="crime-count">' + escapeHtml(String(row.count)) + '</span></div>';
      }}
      html += '</div>';
    }}
    if (data.court_records && data.court_records.length) {{
      html += '<h3 class="dig-deeper-h3">Court records — named persons</h3>';
      for (i = 0; i < data.court_records.length; i++) {{
        var rec = data.court_records[i];
        html += '<div class="claim-card" style="margin-bottom:10px;"><div class="claim-header"><span style="font-weight:600;">' + escapeHtml(rec.person) + '</span></div><div class="claim-rows">';
        for (j = 0; j < rec.cases.length; j++) {{
          var c = rec.cases[j];
          var rawU = (c.url || '').trim();
          if (rawU.indexOf('http') !== 0) rawU = 'https://www.courtlistener.com' + (rawU.charAt(0) === '/' ? rawU : '/' + rawU);
          var link = rawU ? '<a href="' + escapeAttr(rawU) + '" target="_blank" rel="noopener" class="court-case-link">' + escapeHtml(c.case_name) + '</a>' : escapeHtml(c.case_name);
          var meta = (c.court || '') + (c.date_filed ? (' · ' + c.date_filed) : '');
          var snip = c.snippet ? '<div class="court-snippet">&ldquo;' + escapeHtml(c.snippet) + '&rdquo;</div>' : '';
          html += '<div class="claim-row"><div class="claim-row-text">' + link + '</div><div class="counter-source">' + escapeHtml(meta) + '</div>' + snip + '</div>';
        }}
        html += '</div></div>';
      }}
    }}
    if (!html) {{
      html = '<p style="color:#999;font-size:.85em;padding:1rem 0;">No additional records found for this investigation.</p>';
    }}
    return html;
  }}
  var btn = document.getElementById('dig-btn');
  var resultsDiv = document.getElementById('deeper-results');
  var loadingDiv = document.getElementById('deeper-loading');
  var contentDiv = document.getElementById('deeper-content');
  var label = document.getElementById('mouth-label');
  if (!btn || !resultsDiv || !loadingDiv || !contentDiv || !label) return;
  btn.addEventListener('click', function() {{
    var receiptId = btn.getAttribute('data-receipt-id') || '';
    if (!receiptId) return;
    if (btn.classList.contains('open')) {{
      btn.classList.remove('open');
      resultsDiv.style.display = 'none';
      label.textContent = 'DIG DEEPER';
      return;
    }}
    btn.classList.add('open', 'loading');
    label.textContent = 'PULLING RECORDS…';
    resultsDiv.style.display = 'block';
    loadingDiv.style.display = 'block';
    contentDiv.innerHTML = '';
    if (cache[receiptId]) {{
      loadingDiv.style.display = 'none';
      contentDiv.innerHTML = renderDeeperResults(cache[receiptId]);
      label.textContent = 'CLOSE';
      btn.classList.remove('loading');
      return;
    }}
    fetch('/v1/dig-deeper/' + encodeURIComponent(receiptId))
      .then(function(r) {{ if (!r.ok) throw new Error('fail'); return r.json(); }})
      .then(function(data) {{
        cache[receiptId] = data;
        loadingDiv.style.display = 'none';
        contentDiv.innerHTML = renderDeeperResults(data);
        label.textContent = 'CLOSE';
        btn.classList.remove('loading');
      }})
      .catch(function() {{
        loadingDiv.style.display = 'none';
        contentDiv.innerHTML = '<p style="color:#999;font-size:.85em;padding:1rem;">Could not load deeper analysis. Try again.</p>';
        btn.classList.remove('open', 'loading');
        label.textContent = 'DIG DEEPER';
      }});
  }});
}})();
</script>
<script>
(function() {{
  function esc(s) {{
    if (s == null) return '';
    var d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
  }}
  function escapeAttr(s) {{
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }}
  function sanId(rid) {{
    return (rid || '').replace(/[^a-zA-Z0-9_-]/g, '_').substring(0, 48) || 'receipt';
  }}
  var dbtn = document.getElementById('drift-track-btn');
  if (dbtn) {{
    var drid = dbtn.getAttribute('data-id') || '';
    var dsid = sanId(drid);
    function loadDrift() {{
      if (!drid) return;
      fetch('/v1/drift/' + encodeURIComponent(drid))
        .then(function(r) {{ return r.ok ? r.json() : []; }})
        .then(function(data) {{
          var el = document.getElementById('drift-loaded-' + dsid);
          if (!el || !data || !data.length) return;
          var html = '';
          for (var i = 0; i < data.length; i++) {{
            var s = data[i];
            var sc = Number(s.drift_score || 0);
            var col = sc > 50 ? '#c62828' : (sc > 20 ? '#f9a825' : '#2e7d32');
            html += '<div class="drift-point"><div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap">'
              + '<span>T+' + (s.hours_since_original || 0) + 'h</span>'
              + '<span class="drift-score" style="color:' + col + '">' + Math.round(sc) + '/100 drift</span></div>'
              + '<div style="margin-top:6px">' + esc(s.drift_summary) + '</div></div>';
          }}
          el.innerHTML = html;
        }});
    }}
    loadDrift();
    dbtn.addEventListener('click', function() {{
      fetch('/v1/schedule-drift/' + encodeURIComponent(drid), {{ method: 'POST' }})
        .then(function(r) {{ return r.json(); }})
        .then(function() {{ dbtn.textContent = 'TRACKING ENABLED'; dbtn.disabled = true; }});
    }});
  }}
  var mount = document.querySelector('.actors-mount');
  if (mount) {{
    var aid = mount.getAttribute('data-id');
    if (aid) {{
      fetch('/v1/actors/' + encodeURIComponent(aid))
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
          var h = '';
          if (data.nodes && data.nodes.length) {{
            for (var j = 0; j < data.nodes.length; j++) {{
              var n = data.nodes[j];
              var t = String(n.type || 'org').replace(/[^a-z]/gi, '');
              h += '<span class="actor-node actor-type-' + t + '">' + esc(n.label)
                + ' <small>(' + esc(n.type) + ')</small> '
                + '<a href="' + escapeAttr(n.fec_search) + '" target="_blank" rel="noopener" class="actor-badge">FEC</a> '
                + '<a href="' + escapeAttr(n.open_secrets) + '" target="_blank" rel="noopener" class="actor-badge">OS</a> '
                + '<a href="' + escapeAttr(n.courtlistener) + '" target="_blank" rel="noopener" class="actor-badge">CL</a>'
                + '</span>';
            }}
          }}
          if (data.edges && data.edges.length) {{
            for (var k = 0; k < data.edges.length; k++) {{
              var e = data.edges[k];
              h += '<div class="actor-edge">' + esc(e.from) + ' — ' + esc(e.kind) + ' — ' + esc(e.to) + '</div>';
            }}
          }}
          mount.innerHTML = h || '<span style="color:#888">No named entities.</span>';
        }})
        .catch(function() {{ mount.innerHTML = '<span style="color:#888">Could not load actors.</span>'; }});
    }}
  }}
}})();
</script>

</body>
</html>"""
