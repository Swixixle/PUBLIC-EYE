"""
Asymmetric scrutiny: compares how attributed speakers treat claims about different actors.
Runs only when AssemblyAI speaker diarization is active; otherwise returns operational_unknown.
No verdict language. Output is documented pattern + timestamped examples.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

PATTERN_TYPES = frozenset({
    "selective_skepticism",
    "asymmetric_challenge",
    "hedge_asymmetry",
})

SCRUTINY_NOTE = (
    "This analysis documents patterns in the public record of this episode. "
    "It does not establish intent, political motivation, or deliberate bias. "
    "It does not show that any speaker acted in bad faith. "
    "It does not rank which side is correct or apply an external standard of fairness. "
    "Patterns may reflect editorial judgment, guest selection, time limits, or topic focus."
)


def transcription_has_assemblyai_diarization(transcription: dict[str, Any] | None) -> bool:
    if not transcription:
        return False
    if (transcription.get("transcription_provider") or "").lower() != "assemblyai":
        return False
    segments = transcription.get("segments") or []
    if not segments:
        return False
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        sp = str(seg.get("speaker") or "").strip().lower()
        if sp and sp != "unknown":
            return True
    return False


def _claim_speakers_present(claims: list[dict[str, Any]]) -> bool:
    for c in claims:
        if not isinstance(c, dict):
            continue
        sp = str(c.get("speaker") or "").strip().lower()
        if sp and sp != "unknown":
            return True
    return False


def _normalize_pattern_type(raw: str) -> str:
    t = (raw or "").strip().lower()
    t = re.sub(r"[\s-]+", "_", t)
    if t in PATTERN_TYPES:
        return t
    return ""


def analyze_asymmetric_scrutiny(
    claims: list[dict[str, Any]],
    transcription: dict[str, Any],
    episode_title: str = "",
) -> dict[str, Any]:
    """
    Analyze speaker-attributed claims for asymmetric scrutiny. Requires AssemblyAI diarization.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return {
            "scrutiny_patterns": [],
            "speakers_analyzed": [],
            "note": "",
            "operational_unknown": "ANTHROPIC_API_KEY required for asymmetric scrutiny analysis.",
        }

    if not transcription_has_assemblyai_diarization(transcription):
        return {
            "scrutiny_patterns": [],
            "speakers_analyzed": [],
            "note": "",
            "operational_unknown": (
                "Asymmetric scrutiny analysis requires AssemblyAI transcription "
                "with speaker diarization. This receipt used a different transcription path."
            ),
        }

    if not _claim_speakers_present(claims):
        return {
            "scrutiny_patterns": [],
            "speakers_analyzed": [],
            "note": "",
            "operational_unknown": (
                "No speaker-attributed claims available. "
                "Asymmetric scrutiny requires diarized speaker labels on extracted claims."
            ),
        }

    speaker_claims: dict[str, list[dict[str, Any]]] = {}
    for c in claims:
        if not isinstance(c, dict):
            continue
        sp = str(c.get("speaker") or "unknown").strip() or "unknown"
        if sp.lower() == "unknown":
            continue
        if sp not in speaker_claims:
            speaker_claims[sp] = []
        text = str(c.get("text") or c.get("statement") or "")
        speaker_claims[sp].append({
            "text": text[:300],
            "entities": (c.get("entities") or [])[:5],
            "timestamp": c.get("timestamp_start", 0),
            "type": c.get("type", "general"),
            "risk": c.get("implication_risk", "low"),
        })

    if len(speaker_claims) < 1:
        return {
            "scrutiny_patterns": [],
            "speakers_analyzed": [],
            "note": "",
            "operational_unknown": (
                "Speaker labels were present in the transcript but not on extracted claims."
            ),
        }

    import anthropic as _ant

    model = os.environ.get("CLAUDE_SONNET_MODEL", "claude-sonnet-4-20250514")
    client = _ant.Anthropic(api_key=key)

    prompt = f"""You are analyzing a podcast transcript for asymmetric scrutiny patterns.

Episode: {episode_title}
Speakers with attributed claims: {json.dumps(list(speaker_claims.keys()))}

Speaker claims:
{json.dumps(speaker_claims, ensure_ascii=False)[:8000]}

Task: Identify cases where a speaker applies different standards of
skepticism, challenge, or framing to comparable claims depending on
which political actor, party, or institution is being discussed.

Three pattern types (use these exact snake_case values for pattern_type):

1. selective_skepticism — Speaker expresses doubt or demands evidence for
   claims about Actor A but accepts equivalent claims about Actor B without
   the same standard.

2. asymmetric_challenge — Speaker pushes back on, or revises, claims about
   Actor A but does not do the same for equivalent claims about Actor B.

3. hedge_asymmetry — Speaker uses hedging language ("allegedly", "some say",
   "it's claimed") when discussing Actor A but states equivalent information
   about Actor B as established fact.

STRICT RULES:
- Only flag patterns with two specific, comparable examples grounded in the claim list.
- Never infer intent or motive.
- Never use these words: bias, agenda, unfair, dishonest, partisan, hypocrisy, double standard.
- Each pattern must cite specific claims; timestamps as HH:MM:SS strings.
- "treatment" must be exactly one of: challenged, accepted, hedged, stated_as_fact
- Only flag patterns with clear textual evidence; otherwise return an empty scrutiny_patterns array.

Return ONLY valid JSON (no markdown):
{{
  "scrutiny_patterns": [
    {{
      "speaker": "Speaker A",
      "pattern_type": "hedge_asymmetry",
      "description": "neutral one sentence, no verdict language",
      "example_a": {{
        "actor": "name of political actor or institution",
        "claim": "the specific claim text",
        "treatment": "hedged",
        "timestamp": "00:12:34"
      }},
      "example_b": {{
        "actor": "name of political actor or institution",
        "claim": "the specific claim text",
        "treatment": "stated_as_fact",
        "timestamp": "00:31:07"
      }},
      "confidence": "high"
    }}
  ],
  "speakers_analyzed": ["Speaker A", "Speaker B"]
}}"""

    speakers = list(speaker_claims.keys())

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            if len(parts) >= 2:
                raw = parts[1]
                if raw.startswith("json"):
                    raw = raw[4:]
        data = json.loads(raw.strip())

        raw_patterns = data.get("scrutiny_patterns", [])
        patterns_out: list[dict[str, Any]] = []
        if isinstance(raw_patterns, list):
            for p in raw_patterns:
                if not isinstance(p, dict):
                    continue
                pt = _normalize_pattern_type(str(p.get("pattern_type") or ""))
                if not pt:
                    continue
                p_clean = {**p, "pattern_type": pt}
                patterns_out.append(p_clean)

        speakers_analyzed = data.get("speakers_analyzed")
        if not isinstance(speakers_analyzed, list):
            speakers_analyzed = speakers

        return {
            "scrutiny_patterns": patterns_out,
            "speakers_analyzed": speakers_analyzed,
            "note": SCRUTINY_NOTE,
            "operational_unknown": None,
        }

    except Exception as exc:
        logger.warning("analyze_asymmetric_scrutiny failed: %s", exc)
        return {
            "scrutiny_patterns": [],
            "speakers_analyzed": speakers,
            "note": "",
            "operational_unknown": f"Scrutiny analysis error: {str(exc)[:200]}",
        }
