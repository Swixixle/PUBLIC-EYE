"""
Synthesis layer: given multiple articles on the same topic,
produce a unified signed receipt with global framing analysis.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import anthropic

SYNTHESIS_PROMPT = """You are a global news synthesis engine for a public record verification system.

You have been given multiple news articles about the same topic from different media ecosystems around the world.

Your job is to synthesize what is actually happening based on cross-source analysis.

Return ONLY valid JSON. No preamble. No markdown fences.

Format:
{
  "what_is_happening": "2-3 sentence factual summary of the core event based on cross-source analysis",
  "confidence_tier": "official_primary|official_secondary|cross_corroborated|single_source",
  "key_facts": [
    {"fact": "specific verifiable fact", "supported_by": ["outlet1", "outlet2"], "confidence": "high|medium|low"}
  ],
  "contested_facts": [
    {"fact": "fact that outlets disagree on", "version_a": "what some say", "version_b": "what others say", "outlets_a": ["outlet1"], "outlets_b": ["outlet2"]}
  ],
  "ecosystem_framings": [
    {"ecosystem": "ecosystem label", "outlet": "outlet name", "framing": "one sentence on how this outlet frames it", "key_language": ["word1", "word2"]}
  ],
  "what_nobody_is_saying": ["important angle absent from all coverage"],
  "timeline": [
    {"when": "time reference", "event": "what happened", "source": "outlet name"}
  ],
  "named_entities": ["alphabetically sorted list of named people and organizations"]
}"""


def synthesize_articles(query: str, articles: list[dict[str, Any]]) -> dict[str, Any]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return {
            "what_is_happening": "Synthesis unavailable (ANTHROPIC_API_KEY not set).",
            "confidence_tier": "structural_heuristic",
            "key_facts": [],
            "contested_facts": [],
            "ecosystem_framings": [],
            "what_nobody_is_saying": [],
            "timeline": [],
            "named_entities": [],
            "error": "ANTHROPIC_API_KEY not set",
        }

    client = anthropic.Anthropic(api_key=key)

    article_summaries: list[str] = []
    for i, article in enumerate(articles[:8]):
        text = article.get("text") or article.get("summary") or ""
        if not text:
            continue
        article_summaries.append(
            f"--- Article {i + 1}: {article.get('outlet')} ({article.get('ecosystem')}) ---\n"
            f"Title: {article.get('title', 'Unknown')}\n"
            f"URL: {article.get('url', '')}\n"
            f"Text: {text[:1500]}\n"
        )

    if not article_summaries:
        return {
            "what_is_happening": "No article content available for synthesis.",
            "confidence_tier": "structural_heuristic",
            "key_facts": [],
            "contested_facts": [],
            "ecosystem_framings": [],
            "what_nobody_is_saying": [],
            "timeline": [],
            "named_entities": [],
            "error": "No fetchable article content",
        }

    combined = "\n\n".join(article_summaries)
    user_content = f"Query: {query}\n\nArticles to synthesize:\n\n{combined}"

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=3000,
            messages=[{"role": "user", "content": SYNTHESIS_PROMPT + "\n\n" + user_content}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        result: dict[str, Any] = json.loads(raw)
        if isinstance(result.get("named_entities"), list):
            result["named_entities"] = sorted(
                [str(x) for x in result["named_entities"] if x is not None],
                key=str.lower,
            )
        return result
    except json.JSONDecodeError as e:
        return {
            "what_is_happening": "Synthesis parse error.",
            "confidence_tier": "structural_heuristic",
            "key_facts": [],
            "contested_facts": [],
            "ecosystem_framings": [],
            "what_nobody_is_saying": [],
            "timeline": [],
            "named_entities": [],
            "error": f"Parse error: {e}",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "what_is_happening": "Synthesis failed.",
            "confidence_tier": "structural_heuristic",
            "key_facts": [],
            "contested_facts": [],
            "ecosystem_framings": [],
            "what_nobody_is_saying": [],
            "timeline": [],
            "named_entities": [],
            "error": str(e),
        }
