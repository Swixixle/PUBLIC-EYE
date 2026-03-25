"""Layer 4 actor ledger — Node subprocess to @frame/actor-ledger (append-only JSON)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

_ACTOR_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def validate_actor_slug(slug: str) -> str:
    s = slug.strip().lower()
    if not _ACTOR_SLUG_RE.fullmatch(s):
        raise ValueError("Invalid slug: use lowercase letters, digits, and hyphens only")
    return s


def _repo_root() -> Path:
    override = os.environ.get("FRAME_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def _run_cli(payload: dict[str, Any]) -> Any:
    root = _repo_root()
    script = root / "scripts" / "actor-ledger-cli.mjs"
    if not script.is_file():
        raise RuntimeError(f"Missing {script}")
    proc = subprocess.run(
        ["node", str(script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(root),
        env={**os.environ},
        timeout=120,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err[:2000] if err else "actor ledger CLI failed")
    out = proc.stdout.strip()
    if not out and payload.get("op") != "getActor":
        raise RuntimeError("actor ledger CLI returned empty stdout")
    return json.loads(out)


def actor_ledger_get_actor(slug: str) -> dict[str, Any] | None:
    data = _run_cli({"op": "getActor", "slug": slug})
    return data if isinstance(data, dict) else None


def actor_ledger_get_events(slug: str) -> list[dict[str, Any]]:
    data = _run_cli({"op": "getActorEvents", "slug": slug})
    if not isinstance(data, list):
        return []
    return data


def actor_ledger_append_event(slug: str, event: dict[str, Any]) -> dict[str, Any]:
    data = _run_cli({"op": "appendEvent", "slug": slug, "event": event})
    if not isinstance(data, dict):
        raise RuntimeError("appendEvent did not return a record")
    return data
