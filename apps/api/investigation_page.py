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


def _echo_chamber_standalone_html(echo: dict[str, Any]) -> str:
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


def _claims_section_html(claims: list[Any]) -> str:
    if not claims:
        return ""
    claims = _deduplicate_claims(claims)
    blocks: list[str] = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        ctype = str(c.get("claim_type", "") or "").strip()
        ctype_l = ctype.lower()
        subject = str(c.get("subject", "") or "").strip()
        ctext = str(c.get("claim", "") or "").strip()
        cited = c.get("cited_source")
        cited_s = str(cited).strip() if cited else ""
        rumor_src_raw = str(c.get("rumor_source", "") or "").strip()
        rumor_lang = str(c.get("rumor_language", "") or "").strip()
        rumor_display_src = rumor_src_raw or cited_s
        badge = _pills([ctype] if ctype else ["claim"], "blue")
        cited_block = ""
        if cited_s:
            if ctype_l == "rumored":
                dup = _claim_text_dedupe_key(cited_s) == _claim_text_dedupe_key(
                    rumor_display_src or ""
                )
                if dup and not cited_s.startswith(("http://", "https://")):
                    cited_block = ""
                elif cited_s.startswith(("http://", "https://")):
                    cited_block = (
                        f'<div class="cited-source">Article cited: '
                        f'<a href="{_e(cited_s)}" target="_blank" rel="noopener">'
                        f"<strong>{_e(cited_s)}</strong></a></div>"
                    )
                else:
                    cited_block = (
                        f'<div class="cited-source">Article cited: '
                        f"<strong>{_e(cited_s)}</strong></div>"
                    )
            elif cited_s.startswith(("http://", "https://")):
                cited_block = (
                    f'<div class="cited-source">Article cited: '
                    f'<a href="{_e(cited_s)}" target="_blank" rel="noopener">'
                    f"<strong>{_e(cited_s)}</strong></a></div>"
                )
            else:
                cited_block = (
                    f'<div class="cited-source">Article cited: <strong>{_e(cited_s)}</strong></div>'
                )
        elif ctype_l != "rumored":
            cited_block = (
                '<div style="font-size:15px;color:#6b7280;margin:8px 0 6px">'
                "Cited source: none cited</div>"
            )
        vrows: list[str] = []
        subj_link_html = _claim_subject_link_html(subject)
        claim_link_html = _claim_body_link_html(ctext)
        for v in _safe_list(c.get("verifications")):
            if not isinstance(v, dict):
                continue
            adapter = str(v.get("adapter") or v.get("adapter_name") or "").strip()
            status = str(v.get("status", "") or "").strip()
            st_col = _status_color(status)
            result = _verification_result_dict(v)
            st_l = status.lower()
            ad_k = _adapter_key(adapter)
            is_surf = _adapter_is_surface(adapter)

            if ad_k in _SKIP_VERIFICATION_ADAPTERS:
                continue

            if ad_k == "courtlistener" and st_l in ("found", "searched_none_found"):
                raw_r = v.get("result") if isinstance(v.get("result"), dict) else {}
                vrows.append(_courtlistener_verification_html(status, raw_r or {}))
                continue

            if _should_omit_verification_row(adapter, status, result, subject):
                continue

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

            dash = ""
            if brief_plain and not surface_block:
                dash = f" — {_e(brief_plain)}"
            surf_html = (
                f'<div class="surface-verification-block">{surface_block}</div>'
                if surface_block
                else ""
            )
            vrows.append(
                f'<div class="verification-row" style="font-size:15px;color:#333;padding:4px 0">'
                f'<span style="font-weight:600">{_e(adapter)}</span>: '
                f'<span style="color:{st_col};font-weight:600">{_e(status)}</span>'
                f"{dash}</div>"
                f"{surf_html}"
            )
        ver_html = "".join(vrows) or (
            '<div class="verification-row verification-none">'
            "No independent verification found for this claim."
            "</div>"
        )
        if ctype_l == "rumored":
            src_line = rumor_display_src or "Source not specified in extraction"
            rum_lang_html = ""
            if rumor_lang:
                rum_lang_html = (
                    f'<div class="rumor-language">Language from article: '
                    f'<em>“{_e(rumor_lang)}”</em></div>'
                )
            blocks.append(
                f'<div class="claim-card claim-card-rumored inv-paper-card" '
                f'style="padding:18px 20px;margin-bottom:16px;border:1px solid rgba(255,193,7,0.45)">'
                f'<div class="claim-header" style="display:flex;align-items:center;gap:10px;'
                f'flex-wrap:wrap;margin-bottom:8px">'
                f'<span class="claim-type-badge claim-type-rumored">RUMORED</span>'
                f'<span class="claim-subject" style="font-size:16px;font-weight:600;color:#111827">'
                f"{subj_link_html or _e(subject)}</span></div>"
                f'<div class="claim-text" style="font-size:18px;color:#1a1a1a;line-height:1.55;'
                f'margin:6px 0">“{claim_link_html or _e(ctext)}”</div>'
                f'<div class="rumor-source-block"><span class="rumor-label">Source of rumor:</span> '
                f"<strong>{_e(src_line)}</strong></div>"
                f"{rum_lang_html}"
                f"{cited_block}"
                f'<div class="rumor-disclaimer">'
                "This claim has not been independently verified. PUBLIC EYE documents that this "
                "allegation exists and was reported — not that it is true. A dated, signed receipt "
                "records what was published and when; it does not assert the underlying allegation."
                "</div>"
                f'<div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(0,0,0,0.06)">'
                f'<div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;'
                f'color:#6b7280;margin-bottom:6px">Verification</div>{ver_html}</div>'
                f"</div>"
            )
        else:
            blocks.append(
                f'<div class="inv-paper-card" style="padding:18px 20px;margin-bottom:16px;'
                f'border:1px solid rgba(26,26,26,0.1)">'
                f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">'
                f"{badge}"
                f'<span style="font-size:16px;font-weight:600;color:#111827">'
                f"{subj_link_html or _e(subject)}</span>"
                f"</div>"
                f'<p style="font-size:18px;color:#1a1a1a;line-height:1.55;margin:6px 0">'
                f"{claim_link_html or _e(ctext)}</p>"
                f"{cited_block}"
                f'<div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(0,0,0,0.06)">'
                f'<div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;'
                f'color:#6b7280;margin-bottom:6px">Verification</div>{ver_html}</div>'
                f"</div>"
            )
    if not blocks:
        return ""
    return (
        f'<section id="claims-section" class="claims-section inv-reader-soft" '
        f'style="margin-bottom:32px">'
        f'<div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;'
        f'color:#555;margin-bottom:14px">Claims traced</div>'
        f'{"".join(blocks)}</section>'
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

    has_any = bool(ecosystems) or bool(div_pts) or bool(absent) or bool(consensus) or bool(claim_one)
    if not has_any:
        return (
            '<div class="inv-reader-soft" style="margin-bottom:32px">'
            '<div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;'
            'color:#555;margin-bottom:12px">Global perspectives</div>'
            '<div class="inv-paper-card" style="padding:18px 22px;font-size:17px;color:#555">'
            "Global perspective mapping is running — check back shortly."
            "</div></div>"
        )

    parts: list[str] = []
    if claim_one:
        parts.append(
            f'<p style="font-size:16px;color:#444;line-height:1.6;margin-bottom:18px;font-style:italic">'
            f'{_e(claim_one)}</p>'
        )
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
    if absent:
        boxes = "".join(
            f'<a href="{_GOOGLE_NEWS_SEARCH}{quote_plus(str(x))}" '
            f'target="_blank" rel="noopener" class="absent-link absent-link-card">'
            f'<div class="absent-link-row" style="display:flex;align-items:center;gap:10px;'
            f'padding:12px 16px;border-radius:8px;margin-bottom:10px;'
            f'background:rgba(180,83,9,0.09);border:1px solid rgba(180,83,9,0.25)">'
            f'<span class="absent-icon" style="color:#b45315;flex-shrink:0">◆</span>'
            f'<span style="flex:1;min-width:0;font-size:18px;color:#5d4037;line-height:1.5">'
            f"{_e(x)}</span>"
            f'<span class="absent-search-hint">Search →</span></div>'
            f"</a>"
            for x in absent
            if x
        )
        parts.append(
            '<div style="margin:24px 0 16px">'
            '<div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;'
            'color:#b45309;margin-bottom:12px;font-weight:700">What nobody is covering</div>'
            f"{boxes}</div>"
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
        f'<a href="{_GOOGLE_NEWS_SEARCH}{quote_plus(str(w))}" '
        f'target="_blank" rel="noopener" class="absent-link absent-link-card">'
        f'<div class="absent-link-row" style="display:flex;align-items:center;gap:10px;'
        f'padding:10px 14px;border-radius:6px;margin-bottom:8px;'
        f'background:rgba(230,81,0,0.07);border:1px solid rgba(230,81,0,0.18)">'
        f'<span style="color:#E65100;flex-shrink:0">◈</span>'
        f'<span style="flex:1;min-width:0;font-size:18px;color:#5d4037;line-height:1.5">'
        f"{_e(w)}</span>"
        f'<span class="absent-search-hint">Search →</span></div>'
        f"</a>"
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

    gp_raw = receipt.get("global_perspectives") if isinstance(receipt.get("global_perspectives"), dict) else {}
    claims_verified_list = _safe_list(receipt.get("claims_verified"))
    named_entities_list = _safe_list(receipt.get("named_entities"))
    eco_n = _safe_list(gp_raw.get("ecosystems"))
    div_n = _safe_list(gp_raw.get("divergence_points"))
    absent_n = _safe_list(gp_raw.get("absent_from_all"))
    consensus_n = _safe_list(gp_raw.get("consensus_elements"))
    has_gp_signal = bool(eco_n) or bool(div_n) or bool(absent_n) or bool(consensus_n) or bool(
        str(gp_raw.get("claim", "") or "").strip()
    )

    echo_standalone_html = ""
    if not coalition:
        ech = receipt.get("echo_chamber")
        if isinstance(ech, dict) and ech.get("score") is not None:
            echo_standalone_html = _echo_chamber_standalone_html(ech)
        elif rtype == "article_analysis":
            base_sources = receipt.get("sources")
            if isinstance(base_sources, list) and base_sources:
                echo_standalone_html = _echo_chamber_standalone_html(
                    compute_echo_chamber_score(
                        merge_sources_for_echo(base_sources, None),
                        None,
                    )
                )

    claims_section_html = _claims_section_html(claims_verified_list)
    perspectives_block_html = (
        _global_perspectives_section_html(gp_raw)
        if (rtype == "article_analysis" or gp_raw)
        else ""
    )
    named_entities_html = _named_entities_section_html(receipt)
    coverage_block_html = (
        _coverage_provenance_html(receipt) if rtype == "article_analysis" else ""
    )
    sources_section_html = _sources_section_html(receipt)

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
  .claim-type-badge.claim-type-rumored {{
    background: #fff3cd;
    color: #856404;
    border: 1px solid #ffc107;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.75em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .claim-card-rumored {{
    border-left: 3px solid #ffc107 !important;
    background: #fffdf7;
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
    stroke: #1a1a1a;
    stroke-width: 1.5;
    stroke-linecap: round;
    fill: none;
    opacity: 1;
    transition: opacity 0.15s ease;
  }}

  .eye-lash {{
    stroke: #1a1a1a;
    stroke-width: 1;
    stroke-linecap: round;
    opacity: 1;
    transition: opacity 0.15s ease;
  }}

  .open-outline {{
    fill: #f5f5f0;
    stroke: #1a1a1a;
    stroke-width: 1.5;
    opacity: 0;
    transition: opacity 0.2s ease;
  }}

  .eye-pupil {{
    fill: #1a1a1a;
    opacity: 0;
    transition: opacity 0.2s ease 0.08s;
  }}

  .eye-shine {{
    fill: #ffffff;
    opacity: 0;
    transition: opacity 0.2s ease 0.12s;
  }}

  .eye-label {{
    position: absolute;
    bottom: -20px;
    left: 50%;
    transform: translateX(-50%);
    white-space: nowrap;
    font-size: 10px;
    letter-spacing: 0.03em;
    color: #888;
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

{echo_standalone_html}

{coalition_section}

<!-- SUMMARY (after the fight) -->
{f'<div class="inv-paper-card inv-reader-soft" style="margin-bottom:32px;padding:18px 22px"><div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#555;margin-bottom:8px">Summary</div><p style="font-size:18px;color:#333;line-height:1.7">{_e(str(narrative)[:400])}{"…" if len(str(narrative))>400 else ""}</p></div>' if narrative else ""}

{claims_section_html}

{perspectives_block_html}

{named_entities_html}

<!-- WHAT NO ONE IS REALLY TALKING ABOUT -->
{f'<div class="inv-reader-soft" style="margin-bottom:32px"><div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#555;margin-bottom:12px">What no one is really talking about</div>{nobody_html}</div>' if nobody_html else ""}

<!-- CROSS-CORROBORATED -->
{f'<div class="reporter-only" style="margin-bottom:32px"><div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#555;margin-bottom:12px">Cross-corroborated</div><div class="inv-paper-card" style="padding:4px 18px">{confirmed_html}</div></div>' if confirmed_html else ""}

<div style="height:1px;background:rgba(26,26,26,0.2);margin-bottom:32px"></div>

{reporter_strip}

{coverage_block_html}

{sources_section_html}

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

</body>
</html>"""
