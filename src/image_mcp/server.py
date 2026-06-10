"""Image generation MCP server ("nano banana" via the Gemini API).

One tool for Claude: ``generate_image`` (text prompt -> PNG, optionally
iterating on previous generations). The full-size file is stored under
``IMG_ROOT`` and served back at an unguessable URL (``/i/{uuid}.png``); the
tool also returns a small inline preview so the image shows up directly in
the conversation.

Authentication: the server is protected by Google OAuth via FastMCP's
``GoogleProvider`` (an OAuth proxy that runs the standard OAuth 2.1 + PKCE
discovery flow Claude.ai expects). On top of "any valid Google login", an
allow-list middleware restricts tool calls to a small set of email addresses
(``IMG_ALLOWED_EMAILS``), so the server can be shared with a few friends and
nobody else.

Controlled by environment:
- ``IMG_AUTH_DISABLED=1`` runs the server open (local development only).
- Otherwise ``GOOGLE_OAUTH_CLIENT_ID`` / ``GOOGLE_OAUTH_CLIENT_SECRET`` are
  required and the server fails loudly if they are missing, so production can
  never come up silently unauthenticated.

``/health`` and ``/i/{name}`` stay public: the former for the container
healthcheck, the latter because uuid4 filenames are the access control (and
Claude.ai must be able to fetch the URL to show it to the user).
"""

from __future__ import annotations

import html
import os

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware
from fastmcp.utilities.types import Image as MCPImage
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from image_mcp import generate, metadata, models, prefs, storage, usage
from image_mcp.access import is_allowed_email, parse_allowed_emails
from image_mcp.ui import register_ui

DEFAULT_PUBLIC_URL = "http://localhost:8766"
DEFAULT_ADMIN_EMAILS = ""


def _build_auth():
    """Build the auth provider from the environment, or ``None`` when auth is
    explicitly disabled for local development."""
    if os.environ.get("IMG_AUTH_DISABLED") == "1":
        return None

    # Imported lazily so the open/dev path has no hard dependency on the
    # provider stack.
    from fastmcp.server.auth.providers.google import GoogleProvider

    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Auth is enabled but GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET "
            "are not set. Set them, or set IMG_AUTH_DISABLED=1 for local development."
        )

    kwargs = {
        "client_id": client_id,
        "client_secret": client_secret,
        "base_url": os.environ.get("IMG_PUBLIC_URL", DEFAULT_PUBLIC_URL),
        # openid alone does not populate the email claim; ask for it.
        "required_scopes": [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
    }
    # A stable signing key keeps issued tokens valid across restarts/redeploys,
    # so users are not forced to re-authorize on every deploy.
    signing_key = os.environ.get("IMG_JWT_SIGNING_KEY")
    if signing_key:
        kwargs["jwt_signing_key"] = signing_key

    return GoogleProvider(**kwargs)


class AllowedEmailsMiddleware(Middleware):
    """Restrict every tool call to an allow-list of Google account emails.

    Google OAuth on its own lets *any* Google account through. This narrows it
    to the configured emails by checking the ``email`` claim that the Google
    token verifier attaches to the access token.
    """

    def __init__(self, allowed_emails: frozenset[str]):
        if not allowed_emails:
            # Fail closed: an empty allow-list combined with a missing email
            # claim could otherwise let an unintended caller through.
            raise ValueError(
                "IMG_ALLOWED_EMAILS must list at least one email address."
            )
        self.allowed_emails = allowed_emails

    async def on_call_tool(self, context, call_next):
        token = get_access_token()
        if token is None:
            raise ToolError("Access denied: unauthenticated request.")
        claims = getattr(token, "claims", {}) or {}
        if not is_allowed_email(claims.get("email"), self.allowed_emails):
            raise ToolError("Access denied: this server is invitation-only.")
        # Google reports whether it verified the address; deny an explicit
        # False so an unverified lookalike address cannot impersonate a friend.
        # Checked in both the standard OIDC claim and Google's userinfo field,
        # whichever the provider populated.
        user_data = claims.get("google_user_data") or {}
        if (
            claims.get("email_verified") is False
            or user_data.get("email_verified") is False
            or user_data.get("verified_email") is False
        ):
            raise ToolError("Access denied: email address is not verified.")
        return await call_next(context)


_auth = _build_auth()
mcp = FastMCP(name="image-studio", auth=_auth)

if _auth is not None:
    mcp.add_middleware(
        AllowedEmailsMiddleware(
            parse_allowed_emails(os.environ.get("IMG_ALLOWED_EMAILS"))
        )
    )

# Browser dashboard at /ui (per-user galleries and costs), gated by a Google
# login restricted to the allow-listed emails (or open in local dev). Reuses
# the same Google OAuth client as the MCP endpoint.
register_ui(
    mcp,
    allowed_emails=parse_allowed_emails(os.environ.get("IMG_ALLOWED_EMAILS")),
    admin_emails=parse_allowed_emails(
        os.environ.get("IMG_ADMIN_EMAILS", DEFAULT_ADMIN_EMAILS)
    ),
    client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
    client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
    public_url=os.environ.get("IMG_PUBLIC_URL", DEFAULT_PUBLIC_URL),
    secret_key=os.environ.get("IMG_JWT_SIGNING_KEY", "dev-insecure-key"),
    auth_disabled=os.environ.get("IMG_AUTH_DISABLED") == "1",
)


def _caller_email() -> str:
    """Email of the authenticated caller, for attribution in the dashboard."""
    token = get_access_token()
    if token is None:
        return "dev@local"
    claims = getattr(token, "claims", {}) or {}
    email = claims.get("email")
    return email.strip().lower() if isinstance(email, str) and email.strip() else "unknown"


def _public_url(name: str) -> str:
    base = os.environ.get("IMG_PUBLIC_URL", DEFAULT_PUBLIC_URL).rstrip("/")
    return f"{base}/i/{name}"


# output_schema=None: the tool returns content blocks (an inline image plus
# text), which must not be serialized again as structured JSON output.
@mcp.tool(output_schema=None)
def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    reference_images: list[str] | None = None,
    model: str | None = None,
    image_size: str = "1K",
) -> list:
    """Generate an image from a text prompt with Google's Gemini image models
    (nano banana). Returns an inline preview plus the URL of the full-size PNG;
    always give the user that URL.

    ``model``: in almost every call you MUST leave this unset. Leaving it
    unset applies the user's own dashboard default (flash unless they changed
    it), which is the intended behaviour. ONLY pass a value when the user, in
    their own latest message, literally named a model or quality tier (e.g.
    "use pro", "en qualite max", "avec flash"). Then ``"flash"`` is Nano
    Banana 2 (fast, cheap) and ``"pro"`` is Nano Banana Pro (pricier). Do NOT
    infer a model from the prompt's content (text in the image, "high
    quality", complex scene, etc.), do NOT pick pro because it is "better",
    and do NOT offer to switch models unprompted. When in doubt, leave it
    unset.

    ``image_size`` is the output resolution: ``"1K"`` (default), ``"2K"``, or
    ``"4K"``. Price per image rises with size (flash $0.067/$0.101/$0.151,
    pro $0.134/$0.134/$0.24), so stay on 1K unless the user wants a large or
    print-quality result.

    ``aspect_ratio`` is one of 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9,
    21:9. To edit or iterate on previously generated images, pass their
    filenames or URLs as ``reference_images`` and describe the change in the
    prompt.
    """
    root = storage.images_root()
    email = _caller_email()

    try:
        requested = models.resolve_alias(model)
        size = models.resolve_size(image_size)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    pref = prefs.get_default_model(root, email)
    alias = models.choose_alias(requested, pref)
    chosen_model_id = models.model_id(alias)

    refs: list[bytes] = []
    for ref_name in reference_images or []:
        # Models often pass the full /i/{uuid}.png URL back; accept it by
        # keeping only the last path segment.
        name = ref_name.strip().rstrip("/").rsplit("/", 1)[-1]
        data = storage.load_image(name, root)
        if data is None:
            raise ToolError(
                f"Unknown reference image {ref_name!r}. Pass the exact filename "
                "or URL returned by a previous generate_image call."
            )
        refs.append(data)

    try:
        image_data = generate.generate_image(
            prompt,
            chosen_model_id,
            aspect_ratio=aspect_ratio,
            image_size=size,
            reference_images=refs or None,
        )
    except generate.GenerationError as exc:
        raise ToolError(str(exc)) from exc

    name = storage.save_image(image_data, root)
    metadata.save_meta(
        root,
        name,
        email=email,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        cost=models.cost_for(alias, size),
        model=chosen_model_id,
        model_alias=alias,
        image_size=size,
    )
    preview = generate.make_preview(image_data)
    base = os.environ.get("IMG_PUBLIC_URL", DEFAULT_PUBLIC_URL).rstrip("/")
    # One link only: the share page (image + download button). Giving the raw
    # PNG URL as well made models hand the user the button-less one. Always
    # surface the title (the filename): the user references it later to look
    # the image up with image_info or to iterate on it via reference_images.
    return [
        MCPImage(data=preview, format="jpeg"),
        f"Image ready (model: {alias}, size: {size}). "
        f"Title: {name} — ALWAYS show this title to the user next to the image. "
        f"Give the user this link to view and download it: {base}/v/{name} "
        f"(the title doubles as a reference_images entry and as the argument "
        f"to image_info).",
    ]


@mcp.tool(output_schema=None)
def image_info(image: str) -> str:
    """Look up everything recorded about a previously generated image and
    return it as readable text: the prompt, the model used (alias and id),
    the size, aspect ratio, estimated price, creation time, who generated it,
    and the view/download links.

    ``image`` is the image's title as shown to the user — its filename
    (``{uuid}.png``). A full ``/v/`` or ``/i/`` URL is also accepted; only the
    last path segment matters. Use this whenever the user asks for the details
    of an image they already have (e.g. "what was the prompt for <title>?").
    """
    name = image.strip().rstrip("/").rsplit("/", 1)[-1]
    if not storage.is_safe_image_name(name):
        raise ToolError(
            f"{image!r} is not a valid image title. Pass the title (filename) "
            "shown with the image, e.g. '0123...89ab.png'."
        )
    root = storage.images_root()
    meta = metadata.load_meta(root, name)
    if meta is None:
        if (root / name).is_file():
            raise ToolError(
                f"No metadata recorded for {name} (it exists but predates "
                "metadata tracking)."
            )
        raise ToolError(f"Unknown image {name}: no such generated image.")

    base = os.environ.get("IMG_PUBLIC_URL", DEFAULT_PUBLIC_URL).rstrip("/")
    alias = str(meta.get("model_alias") or "")
    model = str(meta.get("model") or "")
    model_line = f"{alias} ({model})" if alias and model else (alias or model or "-")
    try:
        price = f"${float(meta.get('cost') or 0):.3f}"
    except (TypeError, ValueError):
        price = "-"
    lines = [
        f"Title: {name}",
        f"Prompt: {meta.get('prompt') or '-'}",
        f"Model: {model_line}",
        f"Size: {meta.get('image_size') or '-'}",
        f"Aspect ratio: {meta.get('aspect_ratio') or '-'}",
        f"Estimated price: {price}",
        f"Created: {meta.get('created') or '-'}",
        f"Generated by: {meta.get('email') or '-'}",
        f"View / download: {base}/v/{name}",
    ]
    return "\n".join(lines)


@mcp.tool(name="help")
def usage_help() -> str:
    """Full usage guide for this server: every generate_image parameter with
    its allowed values, the models and their prices per size, how to iterate
    on previous images, and the dashboard URL. Call it whenever the user asks
    what this connector can do, how a parameter works, or what it costs.
    """
    return usage.build_help(os.environ.get("IMG_PUBLIC_URL", DEFAULT_PUBLIC_URL))


@mcp.custom_route("/i/{name}", methods=["GET"])
async def serve_image(request: Request) -> Response:
    """Serve a generated PNG. Public on purpose: the uuid4 filename is the
    access control, and Claude.ai fetches this URL to display the result."""
    name = request.path_params["name"]
    data = storage.load_image(name, storage.images_root())
    if data is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            # The image is already public-by-link; CORS lets other pages
            # (e.g. a friend's site) embed or fetch it without a proxy.
            "Access-Control-Allow-Origin": "*",
        },
    )


@mcp.custom_route("/d/{name}", methods=["GET"])
async def download_image(request: Request) -> Response:
    """Serve a generated PNG as a forced download. The ``download`` attribute
    on an ``<a>`` is silently ignored on several mobile browsers (notably iOS
    Safari), which open the image instead of saving it; a
    ``Content-Disposition: attachment`` header makes the download work
    everywhere. Public for the same reason as ``/i/{name}``."""
    name = request.path_params["name"]
    data = storage.load_image(name, storage.images_root())
    if data is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, max-age=31536000, immutable",
            "Access-Control-Allow-Origin": "*",
        },
    )


@mcp.custom_route("/v/{name}", methods=["GET"])
async def view_image(request: Request) -> Response:
    """A minimal share page for one image: the picture plus a working
    download button. Served from the same origin as the PNG, so it works
    everywhere a plain link works (mobile included), unlike inline tool
    images or sandboxed artifacts."""
    name = request.path_params["name"]
    if not storage.is_safe_image_name(name) or storage.load_image(name, storage.images_root()) is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    meta = metadata.load_meta(storage.images_root(), name) or {}
    alias = str(meta.get("model_alias") or "")
    model = str(meta.get("model") or "")
    model_label = f"{alias} ({model})" if alias and model else (alias or model or "")
    try:
        price = f"${float(meta.get('cost') or 0):.3f}" if meta.get("cost") is not None else ""
    except (TypeError, ValueError):
        price = ""

    def info_row(label: str, value: str) -> str:
        if not value:
            return ""
        return (
            f"<div class='row'><span class='k'>{html.escape(label)}</span>"
            f"<span class='v'>{html.escape(value)}</span></div>"
        )

    info_rows = (
        info_row("Prompt", str(meta.get("prompt") or ""))
        + info_row("Model", model_label)
        + info_row("Size", str(meta.get("image_size") or ""))
        + info_row("Aspect", str(meta.get("aspect_ratio") or ""))
        + info_row("Price", price)
        + info_row("Created", str(meta.get("created") or "").replace("T", " ").rstrip("Z")[:19])
        + info_row("Title", name)
    )
    info_block = f"<div class='info'>{info_rows}</div>" if info_rows else ""
    html_doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Image Studio</title>
<style>
body {{ margin: 0; min-height: 100vh; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 1.2rem; background: #16171a; color: #e8e8ea;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 1rem; box-sizing: border-box; }}
img {{ max-width: min(95vw, 1024px); max-height: 70vh; border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,.5); }}
a.btn {{ display: inline-block; padding: .7rem 1.4rem; border-radius: 10px;
  background: #6ea8e0; color: #10131a; text-decoration: none; font-weight: 600; }}
.info {{ width: min(95vw, 640px); background: #1f2126; border: 1px solid #2c2f36;
  border-radius: 12px; padding: .9rem 1.1rem; font-size: .85rem; line-height: 1.5; }}
.info .row {{ display: flex; gap: .8rem; padding: .15rem 0; }}
.info .k {{ flex: 0 0 5rem; color: #9a9aa2; text-transform: uppercase;
  letter-spacing: .04em; font-size: .7rem; padding-top: .1rem; }}
.info .v {{ flex: 1; word-break: break-word; overflow-wrap: anywhere; }}
</style></head><body>
<img src="/i/{name}" alt="Generated image">
<a class="btn" href="/d/{name}">Download PNG</a>
{info_block}
</body></html>"""
    return HTMLResponse(html_doc)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """Liveness probe used by the Docker healthcheck and deploy ``--wait``.
    Stays public (unauthenticated) on purpose."""
    return JSONResponse({"ok": True})


def main() -> None:
    storage.images_root().mkdir(parents=True, exist_ok=True)
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8766"))
    # Streamable HTTP transport at /mcp, the URL Claude.ai connects to.
    mcp.run(transport="http", host=host, port=port, path="/mcp")


if __name__ == "__main__":
    main()
