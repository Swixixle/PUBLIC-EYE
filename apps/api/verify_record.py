"""Generic JCS + Ed25519 (hex) record verification — `packages/signing` record-signing."""

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


def verify_generic_record(body: dict[str, Any]) -> dict[str, Any]:
    root = _repo_root()
    script = root / "scripts" / "verify-record-cli.mjs"
    if not script.is_file():
        raise RuntimeError(f"Missing {script}")
    payload = {
        "record": body["record"],
        "signature": body["signature"],
        "public_key": body["public_key"],
    }
    proc = subprocess.run(
        ["node", str(script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(root),
        env={**os.environ},
        timeout=30,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err[:2000] if err else "verify-record CLI failed")
    out = proc.stdout.strip()
    if not out:
        raise RuntimeError("verify-record CLI returned empty stdout")
    parsed = json.loads(out)
    valid = bool(parsed.get("valid"))
    return {
        "valid": valid,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
