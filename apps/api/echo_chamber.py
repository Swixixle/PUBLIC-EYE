"""
Echo chamber score: 0–100 measuring source independence (higher = more echo-like concentration).
Five components, each 0–20, summed to 0–100. Rubric lives on GET /methodology#echo-chamber.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


def _normalize(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def merge_sources_for_echo(
    sources: list[dict[str, Any]],
    coalition: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Merge coalition chain links into a source list for scoring."""
    out: list[dict[str, Any]] = [dict(s) for s in (sources or []) if isinstance(s, dict)]
    if not coalition:
        return out
    for pos_key in ("position_a", "position_b"):
        pos = coalition.get(pos_key)
        if not isinstance(pos, dict):
            continue
        for link in pos.get("chain") or []:
            if not isinstance(link, dict):
                continue
            url = str(link.get("story_url") or "").strip()
            outlet = str(link.get("outlet") or "").strip()
            note = str(link.get("alignment_note") or "").strip()
            country = str(link.get("country") or "").strip()
            otype = str(link.get("outlet_type") or "").strip()
            summary = f"{outlet}: {note}" if outlet and note else (outlet or note)
            out.append({
                "url": url or f"urn:coalition:{pos_key}:{outlet}",
                "title": outlet or pos_key,
                "summary": summary,
                "note": summary,
                "country": country,
                "outlet_country": country,
                "tone": otype,
                "framing": otype,
            })
    return out


def _claim_overlap_score(sources: list[dict]) -> float:
    texts = []
    for s in sources:
        note = str(s.get("note") or s.get("summary") or s.get("title") or "")
        if note.strip():
            texts.append(_normalize(note))

    if len(texts) < 2:
        return 5.0

    word_sets = [set(t.split()) for t in texts]
    overlaps = []
    for i in range(len(word_sets)):
        for j in range(i + 1, len(word_sets)):
            if not word_sets[i] or not word_sets[j]:
                continue
            intersection = len(word_sets[i] & word_sets[j])
            union = len(word_sets[i] | word_sets[j])
            overlaps.append(intersection / union if union else 0)

    if not overlaps:
        return 5.0
    avg_overlap = sum(overlaps) / len(overlaps)
    return round(min(20.0, avg_overlap * 20), 2)


def _source_diversity_score(sources: list[dict]) -> float:
    n = len(sources)
    if n == 0:
        return 20.0

    countries = set()
    for s in sources:
        c = str(s.get("country") or s.get("outlet_country") or "")
        if c.strip():
            countries.add(c.strip().lower())

    source_penalty = max(0, 20 - (n * 2))
    country_penalty = max(0, 10 - (len(countries) * 3))

    return round(min(20.0, source_penalty * 0.5 + country_penalty), 2)


def _coalition_balance_score(coalition: dict | None) -> float:
    if not coalition:
        return 10.0

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

    total = a_count + b_count
    if total == 0:
        return 10.0

    majority = max(a_count, b_count)
    skew = majority / total
    return round(min(20.0, (skew - 0.5) * 40), 2)


def _primary_source_distance_score(sources: list[dict]) -> float:
    if len(sources) < 2:
        return 5.0

    domains = []
    for s in sources:
        url = str(s.get("url") or s.get("source_url") or "")
        if url.startswith("urn:"):
            continue
        if url:
            try:
                domain = url.split("/")[2].replace("www.", "")
                domains.append(domain)
            except IndexError:
                pass

    if not domains:
        return 5.0

    counts = Counter(domains)
    most_common_count = counts.most_common(1)[0][1]
    concentration = most_common_count / len(domains)
    return round(min(20.0, concentration * 20), 2)


def _framing_variation_score(sources: list[dict]) -> float:
    tones = []
    for s in sources:
        tone = str(
            s.get("tone") or s.get("framing") or s.get("emphasis") or "",
        ).strip().lower()
        if tone:
            tones.append(tone)

    if len(tones) < 2:
        return 10.0

    unique_tones = len(set(tones))
    total_tones = len(tones)
    variation = unique_tones / total_tones
    return round(min(20.0, (1 - variation) * 20), 2)


def compute_echo_chamber_score(
    sources: list[dict],
    coalition: dict | None = None,
    claims: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Compute echo chamber score from sources and optional coalition map.

    claims is reserved for future overlap with extracted claims; currently unused.
    """
    _ = claims
    c1 = _claim_overlap_score(sources)
    c2 = _source_diversity_score(sources)
    c3 = _coalition_balance_score(coalition)
    c4 = _primary_source_distance_score(sources)
    c5 = _framing_variation_score(sources)

    total = round(c1 + c2 + c3 + c4 + c5, 1)

    if total <= 33:
        label = "low"
        interpretation = (
            "Sources covering this story appear largely independent. "
            "Agreement or disagreement reflects diverse sourcing."
        )
    elif total <= 66:
        label = "moderate"
        interpretation = (
            "Some concentration in how this story is being sourced. "
            "A portion of coverage may share common origin points."
        )
    else:
        label = "high"
        interpretation = (
            "Coverage of this story shows signs of source concentration. "
            "Multiple outlets appear to be drawing from the same origin points "
            "rather than independent reporting."
        )

    return {
        "score": total,
        "label": label,
        "components": {
            "claim_overlap": c1,
            "source_diversity": c2,
            "coalition_balance": c3,
            "primary_source_distance": c4,
            "framing_variation": c5,
        },
        "interpretation": interpretation,
    }
