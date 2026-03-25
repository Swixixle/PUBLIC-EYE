"""
Layer 1 (Surface) — invokes `scripts/run-surface-layer.mjs` (Node + @frame/adapters).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# Inoculation baseline: fully traced Layer 1 for Slender Man / Victor Surge / Something Awful.
# Do not call the adapter for this route — benchmark for real traces.
SLENDERMAN_SURFACE_BASELINE: dict[str, Any] = {
    "what": (
        "Slender Man is a fictional Internet horror character created in June 2009 when "
        'Eric Knudsen (posting as Victor Surge) submitted two altered photographs to the '
        '"Create Paranormal Images" thread on the Something Awful forums. The '
        "character is not a verified real-world entity; it is documented as originating "
        "in that forum contest."
    ),
    "what_confidence_tier": "cross_corroborated",
    "who": [
        {"name": "Eric Knudsen (Victor Surge)", "confidence_tier": "official_primary"},
        {"name": "Something Awful", "confidence_tier": "official_secondary"},
    ],
    "when": {
        "earliest_appearance": (
            "June 2009 — first published appearance in the Something Awful forums thread "
            "\"Create Paranormal Images\" (Photoshop contest)."
        ),
        "source": (
            "Something Awful forums; documented attribution to Eric Knudsen (Victor Surge) "
            "as creator of the first Slender Man images."
        ),
        "confidence_tier": "cross_corroborated",
    },
    "source_url": None,
    "source_url_confidence_tier": None,
    "absent_fields": [],
}


def _repo_root() -> Path:
    override = os.environ.get("FRAME_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def run_surface_layer(body: dict[str, Any]) -> dict[str, Any]:
    """Run the TypeScript surface adapter via Node (requires `npm run build` and ANTHROPIC_API_KEY)."""
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        raise RuntimeError("ANTHROPIC_API_KEY is required for surface extraction")

    root = _repo_root()
    script = root / "scripts" / "run-surface-layer.mjs"
    if not script.is_file():
        raise RuntimeError(f"Surface script missing: {script}")

    proc = subprocess.run(
        ["node", str(script)],
        input=json.dumps(body),
        text=True,
        capture_output=True,
        cwd=str(root),
        env={**os.environ},
        timeout=120,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        for line in err.splitlines():
            t = line.strip()
            if t.startswith("Error:") and "Anthropic surface:" in t:
                t = t.removeprefix("Error:").strip()
                raise RuntimeError(t[:2000])
        raise RuntimeError((err[:1500] if err else "surface adapter failed"))
    out = proc.stdout.strip()
    if not out:
        raise RuntimeError("surface adapter returned empty stdout")
    return json.loads(out)
