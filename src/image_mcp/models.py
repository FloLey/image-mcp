"""The two supported image models and their per-image price grid.

Prices are Google's list prices per generated image, which depend on the
model and the output size (1K/2K/4K). IDs and prices are env-overridable
(``IMG_MODEL_FLASH``, ``IMG_COST_PRO_4K``, ...) so a rename (e.g. a preview
suffix dropping) or a price change never needs a code change. Pure stdlib so
the tests need no extras.
"""

from __future__ import annotations

import os

DEFAULT_ALIAS = "flash"
DEFAULT_SIZE = "1K"
ALLOWED_SIZES = ("1K", "2K", "4K")

# alias -> {id, label, costs per size (USD)}; env overrides below.
MODELS = {
    "flash": {
        "id": "gemini-3.1-flash-image-preview",
        "label": "Nano Banana 2 (flash): fast, low cost",
        "costs": {"1K": 0.067, "2K": 0.101, "4K": 0.151},
    },
    "pro": {
        "id": "gemini-3-pro-image-preview",
        # Deliberately neutral: this label is also shown to Claude in the help
        # text, so it must not advertise pro as "best" — that nudges the model
        # into picking it for "high quality" prompts the user never asked to
        # upgrade. Price is the only differentiator Claude sees; the human gets
        # the quality note in the dashboard's model picker instead.
        "label": "Nano Banana Pro: higher cost",
        "costs": {"1K": 0.134, "2K": 0.134, "4K": 0.24},
    },
}


def model_id(alias: str) -> str:
    override = os.environ.get(f"IMG_MODEL_{alias.upper()}")
    return override or MODELS[alias]["id"]


def cost_for(alias: str, size: str = DEFAULT_SIZE) -> float:
    raw = os.environ.get(f"IMG_COST_{alias.upper()}_{size.upper()}", "")
    try:
        return float(raw)
    except ValueError:
        return MODELS[alias]["costs"][size]


def resolve_size(value: str | None) -> str:
    """Normalize an image size to 1K/2K/4K (case-insensitive); ``None``/empty
    means the default. Raises ``ValueError`` on anything else."""
    if value is None or not value.strip():
        return DEFAULT_SIZE
    size = value.strip().upper()
    if size not in ALLOWED_SIZES:
        raise ValueError(
            f"Unknown image_size {value!r}. Use one of: {', '.join(ALLOWED_SIZES)}."
        )
    return size


def choose_alias(requested: str | None, pref: str | None) -> str:
    """Which model to use: an explicit request wins (the tool contract says
    the caller only passes one when the human explicitly asked for it), then
    the dashboard preference, then the default."""
    return requested or pref or DEFAULT_ALIAS


def resolve_alias(value: str | None) -> str | None:
    """Map a caller-supplied model name to an alias, or ``None`` for "no
    preference". Accepts the alias, the full model id (including an env
    override), or any name containing the alias (so the doc-page names
    ``gemini-3-pro-image`` / ``gemini-3.1-flash-image`` work). Raises
    ``ValueError`` on anything else."""
    if value is None:
        return None
    needle = value.strip().lower()
    if not needle:
        return None
    for alias in MODELS:
        if needle == alias or needle == model_id(alias).lower() or alias in needle:
            return alias
    raise ValueError(
        f"Unknown model {value!r}. Use one of: "
        + ", ".join(f"{a} ({model_id(a)})" for a in MODELS)
        + "."
    )
