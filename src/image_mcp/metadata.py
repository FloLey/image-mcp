"""Per-generation metadata, the source for the /ui dashboard.

Each generated image gets a sidecar JSON (``{uuid}.json`` next to
``{uuid}.png``) recording who generated it, the prompt, when, and the
estimated cost. Sidecars are never served publicly: the ``/i/{name}`` route
only matches ``.png`` names. Pure stdlib so the tests need no extras.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

_SAFE_STEM = re.compile(r"^[0-9a-f]{32}$")


def save_meta(
    root: Path,
    name: str,
    *,
    email: str,
    prompt: str,
    aspect_ratio: str,
    cost: float,
    model: str,
    model_alias: str = "",
    image_size: str = "",
) -> dict:
    """Write the sidecar JSON for image ``name`` (``{uuid}.png``)."""
    meta = {
        "name": name,
        "email": email,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "cost": cost,
        "model": model,
        "model_alias": model_alias,
        "image_size": image_size,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    stem = name.rsplit(".", 1)[0]
    (root / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return meta


def load_all_meta(root: Path) -> list[dict]:
    """All sidecar records, newest first. Unparseable or foreign files are
    skipped rather than breaking the dashboard."""
    metas = []
    if not root.is_dir():
        return metas
    for path in root.glob("*.json"):
        if not _SAFE_STEM.match(path.stem):
            continue
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(meta, dict) and meta.get("name"):
            metas.append(meta)
    # ISO-8601 UTC timestamps sort lexicographically.
    metas.sort(key=lambda m: str(m.get("created", "")), reverse=True)
    return metas


def load_meta(root: Path, name: str) -> dict | None:
    """The sidecar record for a single image ``name`` (``{uuid}.png``), or
    ``None`` when there is no readable sidecar for it."""
    stem = name.rsplit(".", 1)[0]
    if not _SAFE_STEM.match(stem):
        return None
    path = root / f"{stem}.json"
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return meta if isinstance(meta, dict) and meta.get("name") else None


def summarize_by_user(metas: list[dict]) -> list[tuple[str, dict]]:
    """Group records per email: ``[(email, {count, cost, images})]``, biggest
    spender first; each user's images stay newest first."""
    per_user: dict[str, dict] = {}
    for meta in metas:
        email = str(meta.get("email") or "unknown")
        entry = per_user.setdefault(email, {"count": 0, "cost": 0.0, "images": []})
        entry["count"] += 1
        try:
            entry["cost"] += float(meta.get("cost", 0))
        except (TypeError, ValueError):
            pass
        entry["images"].append(meta)
    return sorted(per_user.items(), key=lambda kv: kv[1]["cost"], reverse=True)
