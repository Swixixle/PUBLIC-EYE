"""Pattern library + Layer 5 heuristic match (Node subprocess; no external APIs)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    override = os.environ.get("FRAME_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def get_pattern_lib_payload() -> dict[str, Any]:
    path = _repo_root() / "packages" / "pattern-lib" / "patterns.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("patterns.json must be a top-level array")
    unsigned = sum(
        1 for p in data if isinstance(p, dict) and p.get("signature") == "UNSIGNED"
    )
    return {
        "patterns": data,
        "pattern_count": len(data),
        "unsigned_count": unsigned,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def run_pattern_match(narrative: str) -> dict[str, Any]:
    """Invoke packages/adapters `getPatternLayer` via Node (requires `npm run build`)."""
    root = _repo_root()
    script = root / "scripts" / "run-pattern-match.mjs"
    if not script.is_file():
        raise RuntimeError(f"Missing {script}")

    proc = subprocess.run(
        ["node", str(script)],
        input=json.dumps({"narrative": narrative}),
        text=True,
        capture_output=True,
        cwd=str(root),
        env={**os.environ},
        timeout=120,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err[:2000] if err else "pattern matcher failed")
    out = proc.stdout.strip()
    if not out:
        raise RuntimeError("pattern matcher returned empty stdout")
    return json.loads(out)
