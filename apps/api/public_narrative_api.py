"""
Public Narrative + Global Perspectives layer.
Given a claim or narrative, returns how different regional media ecosystems
are framing the same story — with reasoning layer, absence detail, and leads.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

MEDIA_ECOSYSTEMS = [
    {
        "id": "western_anglophone",
        "label": "Western / Anglophone",
        "outlets": ["AP News", "Reuters", "BBC", "New York Times", "Washington Post"],
    },
    {
        "id": "russian_state",
        "label": "Russian / state media",
        "outlets": ["RT", "TASS", "Pravda", "Sputnik"],
    },
    {
        "id": "iranian_regional",
        "label": "Iranian / regional",
        "outlets": ["PressTV", "Islamic Republic News Agency", "Tasnim News"],
    },
    {
        "id": "chinese_state",
        "label": "Chinese / state media",
        "outlets": ["Xinhua", "CGTN", "Global Times", "People's Daily"],
    },
    {
        "id": "arab_gulf",
        "label": "Arab / Gulf",
        "outlets": ["Al Jazeera", "Al Arabiya", "Gulf News", "Middle East Eye"],
    },
    {
        "id": "israeli",
        "label": "Israeli",
        "outlets": ["Haaretz", "Times of Israel", "Jerusalem Post", "Ynet"],
    },
    {
        "id": "south_asian",
        "label": "South Asian",
        "outlets": ["Dawn (Pakistan)", "The Hindu", "Hindustan Times", "Daily Star (Bangladesh)"],
    },
    {
        "id": "european",
        "label": "European",
        "outlets": ["Der Spiegel", "Le Monde", "El País", "Euronews"],
    },
]

GLOBAL_PERSPECTIVES_PROMPT = """You are a global media framing analyst for a public record verification system.

__COVERAGE_BLOCK__

Given a narrative or claim, analyze how different regional media ecosystems are framing this story.

For each ecosystem, analyze how the listed outlets typically cover this type of story based on their documented editorial positions, state affiliations, and historical coverage patterns.

Be precise and specific. Do not be neutral to the point of uselessness. Name the actual framing differences.

Return ONLY valid JSON. No preamble. No markdown fences.

Schema (all keys required; use empty arrays/objects where unknown):

{
  "claim": "the core claim being analyzed in one sentence",
  "ecosystems": [
    {
      "id": "ecosystem_id",
      "label": "ecosystem label",
      "outlets": ["outlet1", "outlet2"],
      "framing": "2-3 sentence description of how this ecosystem frames this story",
      "key_language": ["specific word or phrase choices", "that distinguish this framing"],
      "emphasized": "what this ecosystem emphasizes",
      "minimized": "what this ecosystem downplays or omits",
      "confidence_tier": "official_primary|official_secondary|single_source|structural_heuristic",
      "confidence_note": "brief note on how reliable this characterization is",
      "trigger_phrases": ["3-5 exact phrases readers would see in this ecosystem on this story"],
      "example_headlines": [
        {"text": "headline text", "source": "Reuters or inferred", "type": "retrieved|inferred"}
      ]
    }
  ],
  "divergence_points": ["specific point where ecosystem framings directly conflict"],
  "consensus_elements": ["factual element that all ecosystems agree on"],
  "absent_from_all": [
    {
      "topic": "absent topic in plain English",
      "absence_reason": "too_new|too_niche|avoided|poorly_indexed|unknown",
      "why_it_matters": "one sentence on why this absence is significant",
      "suggested_query": "3-5 word search string to find this angle",
      "suggested_sources": ["OpenSecrets", "FEC", "CourtListener", "Congressional Record"]
    }
  ],
  "most_divergent_pair": {
    "ecosystem_a": "id",
    "ecosystem_b": "id",
    "reason": "why these two framings are most irreconcilable"
  },
  "reasoning_summary": "2-3 sentences: what linguistic or framing evidence most influenced divergence; strongest signal that ecosystems tell different stories",
  "confidence_breakdown": {
    "pct_directly_cited": 0,
    "pct_inferred": 0,
    "pct_consensus": 0,
    "pct_contested": 0,
    "primary_evidence_type": "retrieved_articles|outlet_patterns|mixed"
  },
  "investigative_leads": [
    {
      "action": "Search CourtListener for",
      "target": "specific query or entity",
      "reason": "why this matters",
      "url_hint": "optional URL pattern"
    }
  ],
  "confidence_note": "Overall note on reliability of this analysis"
}

Rules for absent_from_all: each item MUST be an object with topic, absence_reason, why_it_matters, suggested_query, suggested_sources (array of strings). absence_reason must be one of: too_new, too_niche, avoided, poorly_indexed, unknown.

Rules for example_headlines: type is "retrieved" only if the headline clearly came from the coverage block above; otherwise "inferred".

Rules for confidence_breakdown: integers 0-100; pct_directly_cited + pct_inferred should sum to 100; pct_consensus + pct_contested should sum to 100.

Rules for investigative_leads: 3-5 objects with concrete actions (OpenSecrets, FEC, CourtListener, Congressional Record, GDELT, FOIA) where relevant.

Ecosystems to analyze:
__ECOSYSTEMS_JSON__

Narrative to analyze:
__NARRATIVE__"""


def _normalize_global_perspectives(result: dict[str, Any]) -> dict[str, Any]:
    """Ensure new fields exist; keep legacy string-only absent_from_all entries."""
    eco_list = result.get("ecosystems")
    if isinstance(eco_list, list):
        for eco in eco_list:
            if not isinstance(eco, dict):
                continue
            if "trigger_phrases" not in eco:
                eco["trigger_phrases"] = []
            if "example_headlines" not in eco:
                eco["example_headlines"] = []
    absent = result.get("absent_from_all")
    if isinstance(absent, list):
        norm_abs: list[Any] = []
        for item in absent:
            if isinstance(item, str) and item.strip():
                norm_abs.append(item.strip())
            elif isinstance(item, dict):
                norm_abs.append(item)
        result["absent_from_all"] = norm_abs
    if "reasoning_summary" not in result:
        result["reasoning_summary"] = ""
    if "confidence_breakdown" not in result or not isinstance(result.get("confidence_breakdown"), dict):
        result["confidence_breakdown"] = {}
    if "investigative_leads" not in result or not isinstance(result.get("investigative_leads"), list):
        result["investigative_leads"] = []
    return result


def run_global_perspectives(narrative: str, coverage_context: str = "") -> dict[str, Any]:
    """
    Use Claude to analyze how this narrative is being framed
    across regional media ecosystems worldwide.
    """
    text = (narrative or "").strip()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return {
            "claim": text[:200],
            "ecosystems": [],
            "divergence_points": [],
            "consensus_elements": [],
            "absent_from_all": [],
            "most_divergent_pair": None,
            "reasoning_summary": "",
            "confidence_breakdown": {},
            "investigative_leads": [],
            "error": "ANTHROPIC_API_KEY not set",
        }

    client = anthropic.Anthropic(api_key=key)

    ecosystems_json = json.dumps(
        [{"id": e["id"], "label": e["label"], "outlets": e["outlets"]} for e in MEDIA_ECOSYSTEMS],
        indent=2,
    )
    cc = (coverage_context or "").strip()
    grounded = bool(cc)
    logger.info("[PERSPECTIVES] grounded=%s", grounded)
    if cc:
        coverage_block = (
            "The following sources were retrieved and verified to cover this story. "
            "Use these as the factual basis for identifying which outlets are on each side. "
            "Do not invent outlets or attribute positions to sources not listed here.\n\n"
            + cc
        )
    else:
        coverage_block = (
            "No comparative coverage was retrieved for this story. "
            "Base the analysis only on the original article. "
            "Do not fabricate outlet names or positions."
        )
    prompt = (
        GLOBAL_PERSPECTIVES_PROMPT.replace("__COVERAGE_BLOCK__", coverage_block)
        .replace("__ECOSYSTEMS_JSON__", ecosystems_json)
        .replace("__NARRATIVE__", text[:4000])
    )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        result: dict[str, Any] = json.loads(raw)
        result = _normalize_global_perspectives(result)
        result["source"] = "model_knowledge"
        if not (result.get("confidence_note") or "").strip():
            result["confidence_note"] = (
                "Framing analysis based on documented editorial positions and historical "
                "coverage patterns of named outlets. Characterizations reflect general "
                "tendencies, not any specific article. Verify against live sources."
            )
        return result
    except json.JSONDecodeError as e:
        return {
            "claim": text[:200],
            "ecosystems": [],
            "divergence_points": [],
            "consensus_elements": [],
            "absent_from_all": [],
            "most_divergent_pair": None,
            "reasoning_summary": "",
            "confidence_breakdown": {},
            "investigative_leads": [],
            "error": f"Parse error: {e}",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "claim": text[:200],
            "ecosystems": [],
            "divergence_points": [],
            "consensus_elements": [],
            "absent_from_all": [],
            "most_divergent_pair": None,
            "reasoning_summary": "",
            "confidence_breakdown": {},
            "investigative_leads": [],
            "error": str(e),
        }


# Keep backward compat — old endpoint used run_public_narrative
run_public_narrative = run_global_perspectives
