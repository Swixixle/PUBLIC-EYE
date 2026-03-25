"""Layer 4 actor ledger resolution (Node subprocess; reads packages/actor-ledger/ledger.json)."""

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


def run_actor_layer(narrative: str) -> dict[str, Any]:
    """Invoke packages/adapters `getActorLayer` via Node (requires `npm run build`)."""
    root = _repo_root()
    script = root / "scripts" / "run-actor-layer.mjs"
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
        raise RuntimeError(err[:2000] if err else "actor layer failed")
    out = proc.stdout.strip()
    if not out:
        raise RuntimeError("actor layer returned empty stdout")
    return json.loads(out)
