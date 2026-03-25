"""Pattern dispute log — append-only JSON via Node (`@frame/dispute-log`)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    override = os.environ.get("FRAME_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def pattern_ids_in_library() -> set[str]:
    path = _repo_root() / "packages" / "pattern-lib" / "patterns.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return set()
    out: set[str] = set()
    for row in data:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            out.add(row["id"])
    return out


def run_dispute_append(entry: dict[str, Any]) -> dict[str, Any]:
    root = _repo_root()
    script = root / "scripts" / "dispute-log-cli.mjs"
    if not script.is_file():
        raise RuntimeError(f"Missing {script}")
    proc = subprocess.run(
        ["node", str(script)],
        input=json.dumps({"op": "append", "entry": entry}),
        text=True,
        capture_output=True,
        cwd=str(root),
        env={**os.environ},
        timeout=120,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err[:2000] if err else "dispute append failed")
    out = proc.stdout.strip()
    if not out:
        raise RuntimeError("dispute append returned empty stdout")
    return json.loads(out)


def run_dispute_get(pattern_id: str) -> list[dict[str, Any]]:
    root = _repo_root()
    script = root / "scripts" / "dispute-log-cli.mjs"
    if not script.is_file():
        raise RuntimeError(f"Missing {script}")
    proc = subprocess.run(
        ["node", str(script)],
        input=json.dumps({"op": "get", "pattern_id": pattern_id}),
        text=True,
        capture_output=True,
        cwd=str(root),
        env={**os.environ},
        timeout=120,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err[:2000] if err else "dispute get failed")
    out = proc.stdout.strip()
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else []
