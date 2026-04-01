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
- identify the claim type (see types below)
- note any source the article cites for this claim (or null if none cited)

Claim types:
- "institutional": A factual assertion the article states as established fact (not qualified as reporting or rumor).
- "biographical": A factual assertion about a named person's background, role, or record asserted as fact by the article.
- "financial", "legislative", "judicial", "statistical": as usual.
- "rumored": Use when the article attributes the claim to anonymous/unnamed sources, hedges, or secondary reporting:
    * "according to sources", "officials say", "people familiar with the matter", "sources close to",
      "reportedly", "allegedly", "is said to", "is believed to", "unconfirmed reports suggest"
    * Secondary report of what another outlet reported ("X reported that...")
    * Hedging like "may have", "could have", "appears to have", "is thought to", "is suspected of"
    * The article qualifies the claim as unverified or uncertain

For claim_type "rumored" you MUST include:
- "cited_source": Who is the attributed source — be specific. If anonymous, say exactly who
  (e.g. "two anonymous senior Pentagon officials") not just "sources".
- "rumor_source": Same as cited_source when the story is a rumor — who made or reported the allegation
  (outlet, unnamed role, or named person). Duplicate is OK if identical.
- "rumor_language": The exact short phrase from the article signaling rumor/attribution
  (e.g. "according to two people familiar with the matter", "allegedly", "reportedly").
  Copy verbatim from the article text when possible.

Examples (rumored):
{"claim": "The memo was intentionally backdated", "subject": "...", "claim_type": "rumored",
 "cited_source": "Politico, citing two anonymous senior officials",
 "rumor_source": "Politico, citing two anonymous senior officials",
 "rumor_language": "according to people familiar with the discussions", "verifiable": true}

Return ONLY valid JSON. No preamble. No explanation. No markdown fences.

Format:
{
  "claims": [
    {
      "claim": "string — the factual assertion",
      "subject": "string — who or what this is about",
      "claim_type": "financial|legislative|judicial|biographical|statistical|institutional|rumored",
      "cited_source": "string or null",
      "rumor_source": "string or null — only for rumored; who reported or alleged it",
      "rumor_language": "string or null — only for rumored; exact hedging phrase from the article",
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
        result: dict[str, Any] = json.loads(raw)
        if isinstance(result.get("named_entities"), list):
            result["named_entities"] = sorted(
                [str(x) for x in result["named_entities"] if x is not None],
                key=lambda x: x.lower(),
            )
        return result
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
