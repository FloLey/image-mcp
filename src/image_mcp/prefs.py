"""Per-user preferences (currently just the default model).

A single ``prefs.json`` under IMG_ROOT, keyed by email: tiny, atomic enough
for a handful of friends, and it lives in the same persistent volume as the
images. Pure stdlib so the tests need no extras.
"""

from __future__ import annotations

import json
from pathlib import Path

from image_mcp.models import MODELS

PREFS_FILE = "prefs.json"


def _load(root: Path) -> dict:
    path = root / PREFS_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def get_default_model(root: Path, email: str) -> str | None:
    """The user's chosen default model alias, or ``None`` when unset/invalid."""
    entry = _load(root).get(email.strip().lower())
    alias = entry.get("model") if isinstance(entry, dict) else None
    return alias if alias in MODELS else None


def set_default_model(root: Path, email: str, alias: str) -> None:
    if alias not in MODELS:
        raise ValueError(f"Unknown model alias {alias!r}.")
    prefs = _load(root)
    entry = prefs.setdefault(email.strip().lower(), {})
    if not isinstance(entry, dict):
        entry = prefs[email.strip().lower()] = {}
    entry["model"] = alias
    root.mkdir(parents=True, exist_ok=True)
    (root / PREFS_FILE).write_text(
        json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
