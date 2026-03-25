"""
Podcast / video adapter: download audio, Whisper transcription, Claude claim extraction.

Caps: first 30 minutes of audio only (v1 — Render timeouts).
Requires: yt-dlp, ffmpeg (for trim), faster-whisper, ANTHROPIC_API_KEY for claims.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

# Max audio processed (seconds) — v1 cap for serverless timeouts
PODCAST_MAX_SECONDS = int(os.environ.get("FRAME_PODCAST_MAX_SECONDS", str(30 * 60)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def acoustic_fingerprint(audio_path: str) -> str:
    """
    SHA-256 of decoded PCM from the first ~30s of audio (ffmpeg).
    Falls back to first 512KiB of file bytes if ffmpeg is unavailable.
    """
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                audio_path,
                "-t",
                "30",
                "-f",
                "wav",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                "pipe:1",
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            return hashlib.sha256(proc.stdout).hexdigest()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    with open(audio_path, "rb") as f:
        chunk = f.read(512_000)
    return hashlib.sha256(chunk).hexdigest()


def download_audio(url: str) -> dict[str, Any]:
    """
    Download best audio-only stream with yt-dlp to /tmp/frame_podcast/{hash}.<ext>.
    Returns path, title, duration (if known), source_url, downloaded_at.
    """
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL must be http(s)")

    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    out_dir = Path(os.environ.get("FRAME_PODCAST_TMP", "/tmp/frame_podcast"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tpl = str(out_dir / f"{h}.%(ext)s")

    title = "podcast"
    duration: float | None = None
    meta = subprocess.run(
        ["yt-dlp", "--no-playlist", "--dump-json", "--no-download", url],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if meta.returncode == 0 and meta.stdout:
        try:
            line = meta.stdout.strip().splitlines()[0]
            j = json.loads(line)
            title = str(j.get("title") or title)[:500]
            d = j.get("duration")
            if d is not None:
                duration = float(d)
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

    proc = subprocess.run(
        [
            "yt-dlp",
            "--no-playlist",
            "--max-downloads",
            "1",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "5",
            "-o",
            out_tpl,
            url,
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    # yt-dlp exits with code 101 when --max-downloads is reached,
    # even on success. Only raise if no output file was produced.
    if proc.returncode not in (0, 101):
        err = (proc.stderr or proc.stdout or "")[-2000:]
        raise RuntimeError(f"yt-dlp failed: {err}")

    matches = sorted(out_dir.glob(f"{h}.*"))
    filepath = ""
    for p in matches:
        if p.is_file() and p.suffix.lower() in (
            ".mp3",
            ".m4a",
            ".opus",
            ".webm",
            ".ogg",
            ".wav",
        ):
            filepath = str(p)
            break
    if not filepath and matches:
        filepath = str(matches[0])
    if not filepath or not Path(filepath).is_file():
        raise RuntimeError("yt-dlp did not produce an audio file")

    return {
        "path": filepath,
        "title": title,
        "duration": duration,
        "source_url": url,
        "downloaded_at": _now_iso(),
    }


def trim_audio_max(input_path: str, max_seconds: int = PODCAST_MAX_SECONDS) -> tuple[str, bool]:
    """
    If longer than max_seconds, write trimmed copy next to input. Returns (path_to_use, was_trimmed).
    """
    out = str(Path(input_path).with_suffix("")) + ".frame30m.mp3"
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            input_path,
            "-t",
            str(max_seconds),
            "-c",
            "copy",
            out,
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if proc.returncode == 0 and Path(out).is_file():
        return out, True
    # Fallback: use original (Whisper still processes but may timeout on huge files)
    return input_path, False


def probe_audio_duration_seconds(path: str) -> float | None:
    """Best-effort duration via ffprobe (returns None if unavailable)."""
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return float(proc.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


_whisper_model: Any = None


def _get_whisper_model() -> Any:
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        model_size = os.environ.get("FRAME_WHISPER_MODEL", "base")
        _whisper_model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            download_root=os.environ.get(
                "FRAME_WHISPER_CACHE",
                "/tmp/faster_whisper_models",
            ),
        )
    return _whisper_model


def transcribe_audio(path: str) -> dict[str, Any]:
    """Run faster-whisper. Returns segments, full_text, duration, language."""
    model = _get_whisper_model()
    segments_iter, info = model.transcribe(
        path,
        beam_size=5,
        vad_filter=True,
    )
    segments = []
    full_text_parts = []
    for s in segments_iter:
        segments.append(
            {
                "start": float(s.start),
                "end": float(s.end),
                "text": s.text.strip(),
            }
        )
        full_text_parts.append(s.text.strip())
    full_text = " ".join(full_text_parts)
    duration = float(info.duration) if hasattr(info, "duration") else 0.0
    return {
        "segments": segments,
        "full_text": full_text,
        "duration": duration,
        "language": info.language if hasattr(info, "language") else "unknown",
    }


def extract_speaker_claims(
    transcript: dict[str, Any],
    title: str,
    *,
    chunk_index: int | None = None,
    article_mode: bool = False,
    precontext: str = "",
) -> list[dict[str, Any]]:
    """
    Call Claude to extract verifiable factual claims with timestamps and entities.
    Returns list of dicts: text, type, entities, timestamp_start, timestamp_end, speaker, primary_sources.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY required for claim extraction")

    import anthropic as ant

    full_text = transcript.get("full_text") or ""
    segments = transcript.get("segments") or []
    # Bound prompt size (~24k chars)
    if len(full_text) > 24000:
        full_text = full_text[:24000] + "\n\n[… transcript truncated for claim extraction …]"
    seg_preview = json.dumps(segments[:400], ensure_ascii=False)[:12000]
    if article_mode:
        seg_preview = "[]"

    client = ant.Anthropic(api_key=key)
    article_intro = ""
    if article_mode:
        article_intro = (
            "This is a written article, not audio. "
            "Speaker attribution should use the author name if known, "
            "or 'article states' for unattributed claims.\n\n"
        )
    if precontext.strip():
        article_intro = article_intro + precontext.strip() + "\n\n"

    source_label = (
        "You are analyzing a written news article, blog post, or op-ed. "
        "Return JSON only — no markdown."
        if article_mode
        else "You are analyzing a podcast/video transcript. Return JSON only — no markdown."
    )
    title_line = f"Title: {title}" if article_mode else f"Episode / clip title: {title}"
    segment_label = (
        "Segment timestamps (not applicable for static text; use 0.0 if required):"
        if article_mode
        else "Segment timestamps (reference for alignment):"
    )
    speaker_task = (
        '- Attribute claims to the author or "article states" when the piece is unsigned.\n'
        if article_mode
        else '- Identify distinct speakers when possible (host, guest, or "unknown").\n'
    )

    prompt = f"""{article_intro}{title_line}

{source_label}

Full text:
{full_text}

{segment_label}
{seg_preview}

Task:
{f"- This is chunk {chunk_index} of a multi-part transcription. Extract all claims. Do not summarize — capture everything.\n" if chunk_index is not None and not article_mode else ""}{speaker_task}
- Extract all **verifiable factual claims** — statements that assert something checkable about the world.
- This includes: political and financial claims, scientific claims, historical claims, statistical claims, biographical claims, and claims about animal or natural world behavior documented in published research.
- Do NOT extract: opinions, predictions, hedged speculation, or rhetorical questions.
- For each claim assign: type (one of: financial, government_action, biographical, lobbying, health, statistical, legal, corporate, election, scientific, ecological, historical, behavioral, general).
- Named entities per claim (people, orgs, agencies).
- timestamp_start and timestamp_end in **seconds** (float) covering when the claim is stated ({'infer from transcript' if not article_mode else 'for articles use 0.0 for both if not applicable'}).
- Up to 2 primary source URLs per claim (real government/database URLs when possible).
- implication_risk must be exactly one of: low, medium, high
  low = bare fact with no inferential risk
  medium = could imply wrongdoing without stating it
  high = strongly implies causation or intent
- implication_note is REQUIRED when implication_risk is "high"
  One sentence stating what this fact does NOT establish.
  Example: "This does not establish that the donation influenced the vote."
- implication_note must be null when implication_risk is low or medium

Return exactly this JSON shape:
{{
  "claims": [
    {{
      "text": "the specific factual assertion as a neutral declarative sentence",
      "type": "government_action",
      "entities": ["Name One", "Agency"],
      "timestamp_start": 74.2,
      "timestamp_end": 82.0,
      "speaker": "guest",
      "implication_risk": "low",
      "implication_note": null,
      "primary_sources": [
        {{ "label": "short name", "url": "https://...", "type": "government" }}
      ]
    }}
  ]
}}

If no factual claims: {{"claims": []}}.
"""

    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    block = msg.content[0]
    raw = getattr(block, "text", str(block)).strip()
    print(f"[claim-extract] raw Claude response (first 500 chars): {raw[:500]}")
    print(f"[claim-extract] stop_reason: {msg.stop_reason}")
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
    try:
        data = json.loads(raw)
        print(f"[claim-extract] parsed claims count: {len(data.get('claims', []))}")
    except json.JSONDecodeError as e:
        print(f"[claim-extract] JSON parse error: {e}")
        print(f"[claim-extract] raw was: {raw[:300]}")
        data = {"claims": []}
    claims = data.get("claims") or []
    out: list[dict[str, Any]] = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        text = str(c.get("text") or "").strip()
        if not text:
            continue
        ctype = str(c.get("type") or "general").strip() or "general"
        entities = c.get("entities") if isinstance(c.get("entities"), list) else []
        entities = [str(e).strip() for e in entities if str(e).strip()]
        try:
            ts = float(c.get("timestamp_start", 0))
        except (TypeError, ValueError):
            ts = 0.0
        try:
            te = float(c.get("timestamp_end", ts))
        except (TypeError, ValueError):
            te = ts
        speaker = str(c.get("speaker") or "unknown").strip() or "unknown"
        ps = c.get("primary_sources") if isinstance(c.get("primary_sources"), list) else []
        clean_ps: list[dict[str, Any]] = []
        for p in ps[:3]:
            if not isinstance(p, dict):
                continue
            u = str(p.get("url") or "").strip()
            if not u.startswith("http"):
                continue
            clean_ps.append(
                {
                    "label": str(p.get("label") or "source")[:200],
                    "url": u,
                    "type": str(p.get("type") or "database")[:80],
                }
            )
        risk_raw = str(c.get("implication_risk") or "low").strip().lower()
        risk = risk_raw if risk_raw in ("low", "medium", "high") else "low"
        note = c.get("implication_note")
        implication_note = str(note).strip() if note and isinstance(note, str) else None
        out.append(
            {
                "text": text[:2000],
                "type": ctype,
                "entities": entities[:20],
                "timestamp_start": ts,
                "timestamp_end": te,
                "speaker": speaker[:80],
                "implication_risk": risk,
                "implication_note": implication_note,
                "primary_sources": clean_ps,
            }
        )
    return out[:15]


def save_uploaded_audio(data: bytes, filename: str) -> dict[str, Any]:
    """Write upload to temp path; return same shape as download_audio (no duration from yt-dlp)."""
    ext = Path(filename or "audio").suffix.lower() or ".mp3"
    if ext not in (".mp3", ".m4a", ".wav", ".ogg", ".webm", ".opus", ".flac"):
        ext = ".mp3"
    h = hashlib.sha256(data).hexdigest()[:16]
    out_dir = Path(os.environ.get("FRAME_PODCAST_TMP", "/tmp/frame_podcast"))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = str(out_dir / f"upload-{h}{ext}")
    with open(path, "wb") as f:
        f.write(data)
    return {
        "path": path,
        "title": Path(filename).stem or "upload",
        "duration": None,
        "source_url": "upload://local",
        "downloaded_at": _now_iso(),
    }


import uuid as _uuid_mod


def _salience_score(claim: dict) -> float:
    """
    Rank claims for Layer Zero selection.
    Returns 0.0 to 1.0. Higher = more salient.
    Priority: implication_risk weight + domain bonus + observed type bonus.
    """
    risk_weight = {"high": 1.0, "medium": 0.6, "low": 0.3}.get(
        claim.get("implication_risk", "low"), 0.3
    )
    type_bonus = 0.1 if claim.get("type") == "observed" else 0.0
    domain_bonus = 0.1 if claim.get("type", "general") in (
        "financial", "government_action", "election", "lobbying"
    ) else 0.0
    return min(1.0, risk_weight + type_bonus + domain_bonus)


def generate_layer_zero(
    claims: list,
    subject_context: str,
    *,
    cohort_definition: str | None = None,
) -> dict:
    """
    Select the most salient claim and generate the 12-word stop signal.
    Synchronous — call via asyncio.to_thread from async routes.

    Returns a LayerZero-shaped dict.
    Returns operational_unknown if generation fails or key is missing.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or not claims:
        return {
            "text": None,
            "operational_unknown": (
                "Layer Zero requires ANTHROPIC_API_KEY and at least one "
                "extracted claim."
            ),
        }

    import anthropic as _ant
    import hashlib as _hl

    sorted_claims = sorted(claims, key=_salience_score, reverse=True)
    selected = sorted_claims[0]

    model_name = "claude-sonnet-4-20250514"
    client = _ant.Anthropic(api_key=key)

    prompt = (
        "State this public-record finding in 12 words or fewer.\n"
        "Do not imply causation, intent, or judgment.\n"
        "Do not use evaluative adjectives: large, massive, unusual, "
        "concerning, alarming.\n"
        "Prefer precision over emphasis.\n"
        "If the finding is an absence, state what was not found.\n"
        "Return only the sentence. Nothing else. No period at the end.\n\n"
        f"FINDING: {selected['text']}\n"
        f"SUBJECT CONTEXT: {subject_context}\n"
        f"EVIDENCE SOURCE: {selected.get('type', 'general')}\n"
        f"INTERPRETATION GUARDRAIL: Does not establish intent or improper conduct."
    )

    try:
        response = client.messages.create(
            model=model_name,
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip().rstrip(".")
        cohort = cohort_definition or "Claims extracted from audio via Whisper + Claude"
        return {
            "text": text,
            "selected_finding_type": selected.get("type", "general"),
            "salience_score": round(_salience_score(selected), 3),
            "cohort_definition": cohort,
            "generated_by": model_name,
            "generation_timestamp": _now_iso(),
            "source_claim_id": selected.get("id"),
        }
    except Exception as exc:
        return {
            "text": None,
            "operational_unknown": f"Layer Zero generation error: {str(exc)[:200]}",
        }


def assemble_podcast_payload(
    audio_info: dict,
    transcription: dict,
    claims: list,
    layer_zero: dict,
    source_input: str,
    *,
    tier: str = "pro",
    chunks_processed: int | None = None,
    chunk_strategy: str | None = None,
    canonical_entities_chunked: list[dict] | None = None,
    content_source: str = "audio",
    article_source_record: dict[str, Any] | None = None,
) -> dict:
    """
    Assemble the full FrameReceiptPayload dict from all pipeline stages.
    This is the object passed to _sign_frame_payload in main.py.

    source_input: "url" or "upload"
    content_source: "audio" or "article" — article skips Whisper-specific copy.
    article_source_record: when set with content_source article, used as sources[0].
    """
    receipt_id = f"pod_{_uuid_mod.uuid4().hex[:12]}"
    now = _now_iso()
    full_text = transcription.get("full_text", "")

    # ── Unknowns — operational vs epistemic ──────────────────
    operational: list[dict] = []
    epistemic: list[dict] = []

    if lz_op := layer_zero.get("operational_unknown"):
        operational.append({"text": lz_op, "resolution_possible": True})

    if not full_text:
        default_op = (
            "Article extraction produced no usable text."
            if content_source == "article"
            else "Whisper transcription produced no output."
        )
        op_msg = transcription.get("operational_unknown", default_op)
        operational.append({"text": op_msg, "resolution_possible": True})

    medium = "article" if content_source == "article" else "recording"
    epistemic.append({
        "text": (
            "Public records cannot establish the intent behind statements "
            f"made in this {medium}, regardless of text completeness."
        ),
        "resolution_possible": False,
    })
    if source_input == "url":
        epistemic.append({
            "text": (
                "Context preceding and following the retrieved segment "
                "is not captured in this receipt."
            ),
            "resolution_possible": False,
        })

    # ── Claims ───────────────────────────────────────────────
    built_claims = []
    for c in claims:
        text = str(c.get("text") or "").strip()
        if not text:
            continue
        claim: dict = {
            "id": c.get("id") or f"c{_uuid_mod.uuid4().hex[:6]}",
            "statement": text,
            "type": "observed",
            "implication_risk": c.get("implication_risk", "low"),
            "entities": c.get("entities") or [],
        }
        if c.get("implication_note"):
            claim["implication_note"] = c["implication_note"]
        if c.get("citation_chain") is not None:
            claim["citation_chain"] = c["citation_chain"]
        if c.get("origin_stamp"):
            claim["origin_stamp"] = c["origin_stamp"]
        built_claims.append(claim)

    # ── Sources ──────────────────────────────────────────────
    if content_source == "article" and article_source_record:
        sources = [article_source_record]
    else:
        sources = [
            {
                "id": "s001",
                "adapter": "audio_file",
                "url": audio_info.get("source_url", "upload://local"),
                "title": audio_info.get("title", "Audio source"),
                "retrievedAt": audio_info.get("downloaded_at", now),
                "metadata": {
                    "whisper_model": os.environ.get("FRAME_WHISPER_MODEL", "base"),
                    "language": transcription.get("language", "unknown"),
                    "duration_seconds": str(transcription.get("duration", "")),
                },
            }
        ]

    # ── Narrative ────────────────────────────────────────────
    narrative = []
    if full_text:
        if content_source == "article":
            fm = (
                (article_source_record or {}).get("metadata") or {}
            ).get("fetch_method", "unknown")
            narrative.append({
                "text": (
                    f"Article text extracted ({fm}). "
                    f"{len(built_claims)} factual claim(s) extracted."
                ),
                "sourceId": "s001",
            })
        else:
            narrative.append({
                "text": (
                    f"Audio transcribed via Whisper "
                    f"({os.environ.get('FRAME_WHISPER_MODEL', 'base')} model). "
                    f"{len(built_claims)} factual claim(s) extracted."
                ),
                "sourceId": "s001",
            })

    # ── Payload ──────────────────────────────────────────────
    payload: dict = {
        "schemaVersion": "1.0.0",
        "receiptId": receipt_id,
        "createdAt": now,
        "mode": "exploratory",
        "claims": built_claims,
        "sources": sources,
        "narrative": narrative,
        "unknowns": {
            "operational": operational,
            "epistemic": epistemic,
        },
        "meta": {
            "pipeline": "podcast_v2",
            "tier": tier,
            "transcript_chars": len(full_text),
            "entities_detected": list({
                e
                for c in claims
                for e in (c.get("entities") or [])
                if e and len(e.strip()) > 2
            }),
        },
    }
    if content_source == "article":
        payload["meta"]["input_type"] = "article"
        payload["meta"]["source_type"] = "text"
    if chunks_processed is not None:
        payload["meta"]["chunks_processed"] = chunks_processed
    if chunk_strategy:
        payload["meta"]["chunk_strategy"] = chunk_strategy
    if canonical_entities_chunked:
        payload["meta"]["canonical_entities"] = canonical_entities_chunked

    if layer_zero.get("text"):
        payload["layer_zero"] = {
            "text": layer_zero["text"],
            "selected_finding_type": layer_zero.get("selected_finding_type", ""),
            "salience_score": layer_zero.get("salience_score", 0.0),
            "cohort_definition": layer_zero.get("cohort_definition", ""),
            "generated_by": layer_zero.get("generated_by", ""),
            "generation_timestamp": layer_zero.get("generation_timestamp", now),
            "source_claim_id": layer_zero.get("source_claim_id"),
        }

    return payload


async def run_stage2_enrichment(
    payload: dict,
    entities: list[str],
    claims: list[dict],
) -> tuple[dict, list[dict]]:
    """
    Run Stage 2 adapter dispatch on an assembled payload.
    Merges enrichment results back into the payload.
    Returns (updated payload, adapter_results for Stage 3).
    """
    adapter_results: list[dict] = []
    try:
        from enrichment.dispatch import dispatch_entity_enrichment

        enrichment = await dispatch_entity_enrichment(
            entities=entities,
            claims=claims,
        )
        adapter_results = enrichment.get("adapter_results", [])

        # Merge additional sources
        existing_ids = {s["id"] for s in payload.get("sources", [])}
        for src in enrichment.get("additional_sources", []):
            if src.get("id") not in existing_ids:
                payload["sources"].append(src)
                existing_ids.add(src.get("id"))

        # Merge operational unknowns
        for u in enrichment.get("operational_unknowns", []):
            payload["unknowns"]["operational"].append(u)

        # Merge epistemic unknowns
        for u in enrichment.get("epistemic_unknowns", []):
            payload["unknowns"]["epistemic"].append(u)

        # Add verification notes to meta
        if enrichment.get("verification_notes"):
            payload.setdefault("meta", {})
            payload["meta"]["verification_notes"] = (
                enrichment["verification_notes"]
            )

        # Build manifest — replaces flat adapters_dispatched
        _manifest: list[dict[str, Any]] = []
        for r in enrichment.get("adapter_results", []):
            entity_label = r.get("entity_name") or r.get("entity") or "unknown"
            alog = r.get("adapter_log")
            if alog:
                for entry in alog:
                    _manifest.append({
                        "source": entry.get("source", "unknown"),
                        "entity": entity_label,
                        "status": entry.get("status", "unknown"),
                        "result_count": entry.get("result_count", 0),
                        "queried_at": entry.get("queried_at", ""),
                        "note": entry.get("note", ""),
                    })
            elif alog is None:
                for src in r.get("adapters_run", []):
                    _manifest.append({
                        "source": src,
                        "entity": entity_label,
                        "status": "found" if r.get("found") else "not_found",
                        "result_count": len(r.get("sources", []))
                        if r.get("found")
                        else 0,
                        "queried_at": "",
                        "note": "legacy — no per-adapter timing",
                    })

        payload["adapters_queried"] = _manifest
        payload.setdefault("meta", {})
        payload["meta"]["adapters_dispatched"] = list(
            {e["source"] for e in _manifest}
        )

    except Exception as e:
        # Non-fatal — payload still valid without enrichment
        payload["unknowns"]["operational"].append({
            "text": (
                f"Stage 2 enrichment failed: {str(e)[:150]}. "
                f"Receipt is valid without enrichment data."
            ),
            "resolution_possible": True,
        })

    return payload, adapter_results
