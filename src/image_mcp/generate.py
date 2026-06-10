"""Image generation via the Gemini API ("nano banana").

Mirrors the repo's ``.claude/scripts/generate_image.py`` (same model, same
config), with two additions for the MCP tool: a validated aspect ratio, and
optional reference images so a friend can iterate on a previous generation.
"""

from __future__ import annotations

import os

# Aspect ratios the Gemini image models accept.
ALLOWED_ASPECT_RATIOS = frozenset(
    {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
)


class GenerationError(Exception):
    """A user-reportable generation failure (bad input, empty response)."""


def _client():
    # Imported lazily so the unit tests never need the google-genai package.
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise GenerationError("GEMINI_API_KEY is not configured on the server.")
    return genai.Client(api_key=api_key)


def generate_image(
    prompt: str,
    model_id: str,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    reference_images: list[bytes] | None = None,
) -> bytes:
    """Generate one PNG from ``prompt`` (plus optional reference images) with
    ``model_id`` at ``image_size`` and return its raw bytes. Raises
    ``GenerationError`` on bad input or when the model returns no image."""
    from google.genai import types

    if not prompt.strip():
        raise GenerationError("Empty prompt.")
    if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        raise GenerationError(
            f"Invalid aspect_ratio {aspect_ratio!r}. "
            f"Use one of: {', '.join(sorted(ALLOWED_ASPECT_RATIOS))}."
        )

    parts = [
        types.Part.from_bytes(data=data, mime_type="image/png")
        for data in (reference_images or [])
    ]
    parts.append(types.Part.from_text(text=prompt))

    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
        image_config=types.ImageConfig(image_size=image_size, aspect_ratio=aspect_ratio),
        response_modalities=["IMAGE"],
    )

    client = _client()
    # Non-streaming: the tool blocks for the full image anyway, and a single
    # response avoids any chance of the image being split across chunks.
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=[types.Content(role="user", parts=parts)],
            config=config,
        )
    except Exception as exc:  # noqa: BLE001 - surface the real API error to the user
        # Anything other than GenerationError otherwise reaches the client as a
        # masked "Error occurred during tool execution" with no cause. Re-raise
        # with the actual message (API error, quota, invalid argument, ...).
        raise GenerationError(f"Image API error: {exc}") from exc

    for part in response.parts or []:
        if part.inline_data and part.inline_data.data:
            return part.inline_data.data

    # No image came back: surface why, when the API tells us (a safety/policy
    # block on the prompt or the generated image is the common case).
    raise GenerationError(_no_image_reason(response))


def _no_image_reason(response) -> str:
    """Best-effort human-readable reason for an image-less response: a prompt
    block reason or a candidate finish reason when present, else a generic
    rephrase hint."""
    feedback = getattr(response, "prompt_feedback", None)
    block = getattr(feedback, "block_reason", None)
    if block:
        msg = getattr(feedback, "block_reason_message", None)
        return (
            f"The prompt was blocked by the model's safety filter ({block})."
            + (f" {msg}" if msg else "")
            + " Try rephrasing or removing sensitive content."
        )
    for cand in getattr(response, "candidates", None) or []:
        reason = getattr(cand, "finish_reason", None)
        # STOP is the normal completion; anything else with no image is a block.
        if reason and str(getattr(reason, "name", reason)).upper() not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
            return (
                f"The model stopped without producing an image ({getattr(reason, 'name', reason)}), "
                "usually a safety/policy block. Try rephrasing or removing sensitive content."
            )
    return "The model returned no image. Try rephrasing the prompt."


def make_preview(data: bytes, max_side: int = 512) -> bytes:
    """Downscale a PNG to a small JPEG for inline display in the conversation,
    so the full-size file only travels via its URL."""
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(data)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()
