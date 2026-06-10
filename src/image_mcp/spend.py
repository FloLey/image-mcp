"""Cumulative spend ledger, keyed by email.

The dashboard's cost figures are *money already spent* on the image API, so
they must not drop when a user deletes an image: a deletion is not a refund.
A per-image sidecar cost disappears with the image, so it cannot be the source
of the running total; this ledger keeps that total independently. A single
``spend.json`` under IMG_ROOT, with the same atomic-enough write as
``prefs.json`` and living in the same persistent volume. Pure stdlib so the
tests need no extras.
"""

from __future__ import annotations

import json
from pathlib import Path

SPEND_FILE = "spend.json"


def _load(root: Path) -> dict:
    path = root / SPEND_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(root: Path, data: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / SPEND_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _coerce(value) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def totals(root: Path) -> dict[str, float]:
    """Cumulative spend per email (lower-cased keys); junk values count as 0."""
    out: dict[str, float] = {}
    for email, amount in _load(root).items():
        key = str(email).strip().lower()
        if key:
            out[key] = _coerce(amount)
    return out


def record(root: Path, email: str, cost: float) -> None:
    """Add ``cost`` to the running total for ``email``."""
    key = email.strip().lower()
    if not key:
        return
    data = _load(root)
    data[key] = _coerce(data.get(key)) + _coerce(cost)
    _save(root, data)


def seed_missing(root: Path, costs_by_email: dict[str, float]) -> None:
    """Initialise the ledger from historical per-user costs, but only for
    emails not already tracked. Idempotent: existing totals are never touched,
    so calling it on every startup never double-counts. This is what carries
    spend that predates the ledger (sidecars already on disk) into the total."""
    data = _load(root)
    changed = False
    for email, cost in costs_by_email.items():
        key = str(email).strip().lower()
        if key and key not in data:
            data[key] = _coerce(cost)
            changed = True
    if changed:
        _save(root, data)
