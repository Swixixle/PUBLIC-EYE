"""
Public Narrative layer — framing analysis for how outlets may cover a claim (model-informed).

Does not fetch live outlet pages; outputs structured JSON with explicit confidence note.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import anthropic

FRAMING_PROMPT = """You are a media framing analyst for a public record verification system.

Given a narrative or claim, analyze how different news outlets frame this story.
Focus on:
1. Word choice differences (e.g. "warns" vs "threatens" vs "promises retaliation")
2. What each outlet emphasizes or de-emphasizes
3. Which sources each outlet cites
4. What is present in some framings but absent in others
5. Whether any outlet presents contested facts as settled

Return ONLY valid JSON. No preamble. No markdown fences.

Format:
{
  "claim": "the core claim being analyzed",
  "framings": [
    {
      "outlet": "outlet name",
      "framing_summary": "one sentence describing how this outlet frames it",
      "key_word_choices": ["word1", "word2"],
      "emphasized": "what this outlet emphasizes",
      "absent": "what this outlet omits or downplays",
      "confidence_tier": "official_primary|official_secondary|single_source"
    }
  ],
  "divergence_points": ["point where framings conflict 1", "point 2"],
  "consensus_elements": ["what all outlets agree on"],
  "absent_from_all": ["what no outlet addresses"]
}"""


def run_public_narrative(narrative: str) -> dict[str, Any]:
    """
    Use Claude to analyze how this narrative might be framed across major outlets.
    """
    text = (narrative or "").strip()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return {
            "claim": text[:200],
            "framings": [],
            "divergence_points": [],
            "consensus_elements": [],
            "absent_from_all": [],
            "error": "ANTHROPIC_API_KEY not set",
            "confidence_tier": "structural_heuristic",
        }

    client = anthropic.Anthropic(api_key=key)

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": f"{FRAMING_PROMPT}\n\nNarrative to analyze:\n{text[:3000]}",
                }
            ],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        result: dict[str, Any] = json.loads(raw)
        result["confidence_note"] = (
            "Framing analysis based on model knowledge of coverage patterns. "
            "Verify against live sources before citing."
        )
        result.setdefault("confidence_tier", "structural_heuristic")
        return result
    except json.JSONDecodeError as e:
        return {
            "claim": text[:200],
            "framings": [],
            "divergence_points": [],
            "consensus_elements": [],
            "absent_from_all": [],
            "error": f"Parse error: {e}",
            "confidence_tier": "structural_heuristic",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "claim": text[:200],
            "framings": [],
            "divergence_points": [],
            "consensus_elements": [],
            "absent_from_all": [],
            "error": str(e),
            "confidence_tier": "structural_heuristic",
        }
