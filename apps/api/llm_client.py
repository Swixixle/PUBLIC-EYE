"""
llm_client.py
Model-agnostic LLM client for PUBLIC EYE.

Wraps Anthropic (primary) with automatic fallback to other providers
when rate-limited, unavailable, or explicitly overridden via env var.

Usage:
    from llm_client import llm_complete, LLMMessage

    response = llm_complete(
        system="You are a coalition analyst.",
        messages=[LLMMessage(role="user", content="Analyze this...")],
        max_tokens=4096,
    )
    text = response.text

Drop-in replacement anywhere the codebase calls anthropic.Anthropic() directly.
Set LLM_PROVIDER env var to override: anthropic | openai | google | groq | auto
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class LLMMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Provider registry
# The order here is the fallback order when provider="auto"
# ---------------------------------------------------------------------------

PROVIDER_ORDER = ["anthropic", "groq", "google", "openai"]

MODEL_MAP = {
    "anthropic": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
    "openai":    os.environ.get("OPENAI_MODEL",    "gpt-4o"),
    "google":    os.environ.get("GOOGLE_MODEL",    "gemini-2.0-flash"),
    "groq":      os.environ.get("GROQ_MODEL",      "llama-3.3-70b-versatile"),
}


# ---------------------------------------------------------------------------
# Anthropic backend
# ---------------------------------------------------------------------------

def _anthropic_complete(
    system: str,
    messages: list[LLMMessage],
    max_tokens: int,
    temperature: float,
) -> LLMResponse:
    import anthropic  # type: ignore

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    model = MODEL_MAP["anthropic"]

    t0 = time.monotonic()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": m.role, "content": m.content} for m in messages],
    )
    latency = (time.monotonic() - t0) * 1000

    return LLMResponse(
        text=resp.content[0].text,
        model=model,
        provider="anthropic",
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
        latency_ms=latency,
    )


# ---------------------------------------------------------------------------
# OpenAI backend
# ---------------------------------------------------------------------------

def _openai_complete(
    system: str,
    messages: list[LLMMessage],
    max_tokens: int,
    temperature: float,
) -> LLMResponse:
    import openai  # type: ignore

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    client = openai.OpenAI(api_key=api_key)
    model = MODEL_MAP["openai"]

    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            *[{"role": m.role, "content": m.content} for m in messages],
        ],
    )
    latency = (time.monotonic() - t0) * 1000

    return LLMResponse(
        text=resp.choices[0].message.content or "",
        model=model,
        provider="openai",
        input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
        output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        latency_ms=latency,
    )


# ---------------------------------------------------------------------------
# Google Gemini backend
# ---------------------------------------------------------------------------

def _google_complete(
    system: str,
    messages: list[LLMMessage],
    max_tokens: int,
    temperature: float,
) -> LLMResponse:
    import google.generativeai as genai  # type: ignore

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")

    genai.configure(api_key=api_key)
    model_name = MODEL_MAP["google"]
    model = genai.GenerativeModel(
        model_name,
        system_instruction=system,
    )

    t0 = time.monotonic()
    history = []
    for m in messages[:-1]:
        history.append({"role": m.role, "parts": [m.content]})

    chat = model.start_chat(history=history)
    resp = chat.send_message(
        messages[-1].content,
        generation_config=genai.GenerationConfig(max_output_tokens=max_tokens, temperature=temperature),
    )
    latency = (time.monotonic() - t0) * 1000

    return LLMResponse(
        text=resp.text,
        model=model_name,
        provider="google",
        latency_ms=latency,
    )


# ---------------------------------------------------------------------------
# Groq backend
# ---------------------------------------------------------------------------

def _groq_complete(
    system: str,
    messages: list[LLMMessage],
    max_tokens: int,
    temperature: float,
) -> LLMResponse:
    import groq  # type: ignore

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    client = groq.Groq(api_key=api_key)
    model = MODEL_MAP["groq"]

    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            *[{"role": m.role, "content": m.content} for m in messages],
        ],
    )
    latency = (time.monotonic() - t0) * 1000

    return LLMResponse(
        text=resp.choices[0].message.content or "",
        model=model,
        provider="groq",
        input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
        output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        latency_ms=latency,
    )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_BACKENDS = {
    "anthropic": _anthropic_complete,
    "openai":    _openai_complete,
    "google":    _google_complete,
    "groq":      _groq_complete,
}

_RETRYABLE_ERRORS = (
    "rate_limit", "overloaded", "529", "503", "502",
    "RateLimitError", "APIStatusError", "InternalServerError",
)


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc) + type(exc).__name__
    return any(token in msg for token in _RETRYABLE_ERRORS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def llm_complete(
    system: str,
    messages: list[LLMMessage],
    max_tokens: int = 4096,
    temperature: float = 0.3,
    provider: str | None = None,
) -> LLMResponse:
    """
    Call an LLM with automatic fallback.

    provider: "anthropic" | "openai" | "google" | "groq" | "auto" | None
              None → reads LLM_PROVIDER env var, defaults to "auto"
    """
    chosen = provider or os.environ.get("LLM_PROVIDER", "auto")

    if chosen == "auto":
        order = PROVIDER_ORDER
    else:
        order = [chosen]

    last_exc: Exception | None = None

    for p in order:
        backend = _BACKENDS.get(p)
        if backend is None:
            logger.warning("Unknown LLM provider: %s", p)
            continue

        try:
            result = backend(system, messages, max_tokens, temperature)
            if p != "anthropic":
                logger.info("LLM fallback used: %s (%.0f ms)", p, result.latency_ms)
            return result

        except Exception as exc:
            last_exc = exc
            if _is_retryable(exc):
                logger.warning("Provider %s unavailable (%s), trying next", p, exc)
                continue
            # Non-retryable (bad API key, malformed request) — don't try next provider
            raise

    raise RuntimeError(
        f"All LLM providers exhausted. Last error: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Convenience: async wrapper for FastAPI routes
# ---------------------------------------------------------------------------

async def llm_complete_async(
    system: str,
    messages: list[LLMMessage],
    max_tokens: int = 4096,
    temperature: float = 0.3,
    provider: str | None = None,
) -> LLMResponse:
    """Async wrapper — runs the sync call in a thread pool."""
    import asyncio
    return await asyncio.to_thread(
        llm_complete, system, messages, max_tokens, temperature, provider
    )
