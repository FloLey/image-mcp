"""The full usage guide returned by the ``help`` tool.

Built dynamically from the model registry and the validation tables, so the
prices and allowed values shown are always the ones actually enforced
(including env overrides). Kept apart from server.py so it stays importable
and unit-testable without fastmcp.
"""

from __future__ import annotations

from image_mcp.generate import ALLOWED_ASPECT_RATIOS
from image_mcp.models import ALLOWED_SIZES, DEFAULT_ALIAS, DEFAULT_SIZE, MODELS, cost_for, model_id


def build_help(public_url: str) -> str:
    base = public_url.rstrip("/")
    model_lines = "\n".join(
        f"  - \"{alias}\" ({model_id(alias)}): {spec['label']}. Price per image: "
        + ", ".join(f"{size} ${cost_for(alias, size):.3f}" for size in ALLOWED_SIZES)
        for alias, spec in MODELS.items()
    )
    ratios = ", ".join(sorted(ALLOWED_ASPECT_RATIOS))
    sizes = ", ".join(ALLOWED_SIZES)
    return f"""Image Studio: generates images with Google's Gemini image models (nano banana).

TOOL: generate_image(prompt, aspect_ratio?, reference_images?, model?, image_size?)

PARAMETERS
- prompt (required): what to draw, in any language. Be concrete: subject,
  style, lighting, mood. For text inside the image, quote the exact words.
- model (optional): which engine to use.
{model_lines}
  Accepts the alias, the full model id, or the doc-page name
  (gemini-3.1-flash-image / gemini-3-pro-image). ONLY set it when the user
  explicitly asked for a specific model or quality; never pick one on your
  own initiative. When unset, the user's dashboard default applies
  ({base}/ui), falling back to "{DEFAULT_ALIAS}".
- image_size (optional, default "{DEFAULT_SIZE}"): output resolution, one of {sizes}.
  Larger sizes cost more (see prices above); stay on {DEFAULT_SIZE} unless a large or
  print-quality result is wanted.
- aspect_ratio (optional, default "1:1"): one of {ratios}.
- reference_images (optional): filenames or URLs returned by previous
  generate_image calls, to edit or iterate on them ("same scene but at
  night", "combine these two characters"). Up to a few images.

RESULT
Each call returns a small inline preview plus the link of the share page
({base}/v/<uuid>.png): the full-size image with a download button, works on
mobile. Always give the user that link: some clients do not render the
inline preview. The filename can be passed back as a reference_images entry.
Do not try to fetch or embed the image yourself (e.g. in an artifact); just
give the link.

DASHBOARD
{base}/ui (Google login, invitation-only): per-user galleries and estimated
costs, and a "My default model" picker for the model used when a request
does not specify one.

EXAMPLES
- generate_image(prompt="watercolor fox in a misty forest")
- generate_image(prompt="birthday card that says 'Bravo Marie!'", model="pro")
- generate_image(prompt="same scene at sunset", reference_images=["<uuid>.png"])
- generate_image(prompt="mountain panorama", aspect_ratio="21:9", image_size="2K")
"""
