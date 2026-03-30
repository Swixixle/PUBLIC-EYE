"""Extract verifiable claims from article text via Claude."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import anthropic

CLAIM_EXTRACTION_PROMPT = """You are a claim extraction engine for a public-record verification system.

Given article text, extract every verifiable factual claim. For each claim:
- state it as a single declarative sentence
- identify the subject (a person, organization, law, event, or policy)
- identify the claim type: financial, legislative, judicial, biographical, statistical, or institutional
- note any source the article cites for this claim (or null if none cited)

Return ONLY valid JSON. No preamble. No explanation. No markdown fences.

Format:
{
  "claims": [
    {
      "claim": "string — the factual assertion",
      "subject": "string — who or what this is about",
      "claim_type": "financial|legislative|judicial|biographical|statistical|institutional",
      "cited_source": "string or null",
      "verifiable": true
    }
  ],
  "article_topic": "string — one sentence summary of what this article is about",
  "named_entities": ["list of named people and organizations mentioned"]
}

Extract up to 20 claims. Prioritize claims that reference public records, named people, institutions, legislation, court cases, or financial figures. Skip pure opinion sentences."""


def extract_claims(article_text: str, title: Optional[str] = None) -> dict[str, Any]:
    """
    Extract verifiable claims from article text using Claude.
    Returns parsed claims dict or error dict.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return {
            "claims": [],
            "article_topic": None,
            "named_entities": [],
            "extraction_error": "ANTHROPIC_API_KEY not set",
        }

    client = anthropic.Anthropic(api_key=key)

    context = f"Article title: {title}\n\n" if title else ""
    raw_text = (article_text or "").strip()
    user_content = f"{context}Article text:\n{raw_text[:6000]}"

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": CLAIM_EXTRACTION_PROMPT + "\n\n" + user_content}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        return {
            "claims": [],
            "article_topic": None,
            "named_entities": [],
            "extraction_error": f"JSON parse error: {e}",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "claims": [],
            "article_topic": None,
            "named_entities": [],
            "extraction_error": str(e),
        }
