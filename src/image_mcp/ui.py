"""Web dashboard for the Image Studio, served at /ui by the same process.

Shows, per user, the number of generated images, the estimated cost, and a
gallery of the images themselves. Gated by a browser Google login (the same
OAuth client as the MCP endpoint) restricted to the allow-listed emails:
admins (IMG_ADMIN_EMAILS) see every user, anyone else only sees their own
images and cost. In local dev (IMG_AUTH_DISABLED=1) the login is bypassed.

Same session mechanics as memory-wiki's console: a signed (stdlib HMAC),
HttpOnly/Secure cookie scoped to /ui. The only write is the per-user default
model preference, posted with a signed CSRF token.

> One-time Google change required: add ``{IMG_PUBLIC_URL}/ui/auth/callback``
> as a second authorized redirect URI on the OAuth client (Google matches
> redirect URIs exactly, unlike GitHub).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from image_mcp import metadata, models, prefs, spend, storage
from image_mcp.access import is_allowed_email

SESSION_COOKIE = "img_ui_session"
STATE_COOKIE = "img_ui_state"
SESSION_TTL = 7 * 24 * 3600


# ---- signing helpers (stdlib HMAC; same scheme as memory-wiki) ----

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(secret: str, payload: dict) -> str:
    raw = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{sig}"


def _verify(secret: str, token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    raw, sig = token.split(".", 1)
    expected = _b64e(hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64d(raw))
        if not isinstance(payload, dict):
            return None
        exp = float(payload.get("exp", 0))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if exp < time.time():
        return None
    return payload


# ---- HTML shell ----

_CSS = """
:root {
  --bg: #f7f7f5; --panel: #ffffff; --ink: #1d1d1f; --muted: #6b6b70;
  --line: #e3e3e0; --accent: #3a6ea5; --accent-ink: #fff;
  --shadow: 0 1px 2px rgba(0,0,0,.05), 0 8px 24px rgba(0,0,0,.04);
  --radius: 12px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #16171a; --panel: #1f2126; --ink: #e8e8ea; --muted: #9a9aa2;
    --line: #2c2f36; --accent: #6ea8e0; --accent-ink: #10131a;
    --shadow: 0 1px 2px rgba(0,0,0,.3), 0 8px 24px rgba(0,0,0,.25);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink); line-height: 1.6;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.topbar {
  position: sticky; top: 0; z-index: 10; backdrop-filter: blur(8px);
  background: color-mix(in srgb, var(--bg) 82%, transparent);
  border-bottom: 1px solid var(--line);
}
.topbar .inner {
  max-width: 980px; margin: 0 auto; padding: .8rem 1.25rem;
  display: flex; align-items: center; justify-content: space-between;
  gap: .5rem 1rem; flex-wrap: wrap;
}
.brand { font-weight: 700; letter-spacing: -.01em; text-decoration: none; color: var(--ink); }
.brand span { color: var(--accent); }
.topbar nav a { color: var(--muted); text-decoration: none; margin-left: 1rem; font-size: .92rem; }
.topbar nav a:hover { color: var(--ink); }
.who { color: var(--muted); font-size: .85rem; margin-right: .25rem; }
main { max-width: 980px; margin: 0 auto; padding: 1.75rem 1.25rem 4rem; }
h1 { font-size: 1.5rem; letter-spacing: -.02em; margin: .2rem 0 1.25rem; }
a { color: var(--accent); }
.muted { color: var(--muted); font-size: .85rem; }
.card {
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius);
  box-shadow: var(--shadow); padding: 1rem 1.25rem; margin-bottom: 1.1rem;
  overflow-x: auto;
}
.card h2 {
  font-size: .8rem; text-transform: uppercase; letter-spacing: .08em;
  color: var(--muted); margin: 0 0 .6rem; font-weight: 600;
}
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { border: 1px solid var(--line); padding: .45rem .7rem; text-align: left; }
th { background: color-mix(in srgb, var(--ink) 5%, transparent); }
.gallery {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: .9rem; margin: 0; padding: 0;
}
.gallery figure {
  margin: 0; background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; overflow: hidden; display: flex; flex-direction: column;
}
.gallery img {
  width: 100%; aspect-ratio: 1 / 1; object-fit: cover; display: block;
  border-bottom: 1px solid var(--line); background: var(--bg);
}
.gallery figcaption { font-size: .76rem; color: var(--muted); padding: .55rem .6rem;
  display: flex; flex-direction: column; gap: .5rem; }
.meta { display: flex; flex-direction: column; gap: .15rem; }
.meta-row { display: flex; gap: .4rem; }
.meta-k { flex: 0 0 3.6rem; color: var(--muted); text-transform: uppercase;
  letter-spacing: .04em; font-size: .66rem; padding-top: .05rem; }
.meta-v { flex: 1; color: var(--ink); word-break: break-word;
  overflow-wrap: anywhere; }
/* Prompts can be very long; clamp to two lines and let the user expand the
   one they care about, so a card stays compact instead of a wall of text. */
.prompt { flex: 1; min-width: 0; }
.prompt summary { display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; cursor: pointer;
  color: var(--ink); word-break: break-word; overflow-wrap: anywhere;
  list-style: none; white-space: pre-wrap; }
.prompt summary::-webkit-details-marker { display: none; }
.prompt summary:hover { color: var(--accent); }
.prompt[open] summary { -webkit-line-clamp: unset; display: block; }
.actions { display: flex; flex-wrap: wrap; gap: .35rem; align-items: center; }
.actions form { margin: 0; }
.chip {
  display: inline-block; padding: .3rem .6rem; border-radius: 7px;
  border: 1px solid var(--line); background: var(--bg); color: var(--ink);
  text-decoration: none; font-size: .76rem; font-weight: 500; cursor: pointer;
  font-family: inherit; line-height: 1.2;
}
.chip:hover { border-color: var(--accent); }
.chip.danger { color: #d9534f; border-color: color-mix(in srgb, #d9534f 40%, var(--line)); }
.chip.danger:hover { background: #d9534f; color: #fff; border-color: #d9534f; }
.btn {
  display: inline-block; padding: .5rem .9rem; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--accent); background: var(--accent); color: var(--accent-ink);
  text-decoration: none; font-size: .9rem; font-weight: 500;
}
select {
  padding: .5rem .7rem; border: 1px solid var(--line); border-radius: 8px;
  background: var(--bg); color: var(--ink); font-size: .9rem; max-width: 100%;
}
.field { margin-bottom: .8rem; }
.empty { color: var(--muted); text-align: center; padding: 2rem 0; }
.login-wrap { max-width: 380px; margin: 12vh auto; text-align: center; }
.login-wrap .card { padding: 2rem 1.5rem; }
@media (max-width: 640px) {
  main { padding: 1.25rem 1rem 3rem; }
  h1 { font-size: 1.3rem; }
  .gallery { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
}
"""


def _figure(m: dict, csrf: str) -> str:
    """One gallery card: the image plus its full metadata and per-image
    actions (open, download, delete)."""
    name = str(m["name"])
    prompt = str(m.get("prompt") or "")
    created = str(m.get("created") or "").replace("T", " ").rstrip("Z")
    alias = str(m.get("model_alias") or "")
    model_id = str(m.get("model") or "")
    size = str(m.get("image_size") or "")
    ratio = str(m.get("aspect_ratio") or "")
    try:
        cost = f"${float(m.get('cost') or 0):.3f}"
    except (TypeError, ValueError):
        cost = "-"

    def row(label: str, value: str) -> str:
        if not value:
            return ""
        return (
            f"<div class='meta-row'><span class='meta-k'>{html.escape(label)}</span>"
            f"<span class='meta-v'>{html.escape(value)}</span></div>"
        )

    def prompt_row(value: str) -> str:
        if not value:
            return ""
        # <details>: the prompt shows clamped (CSS) and expands on click, with
        # the full text also in the tooltip. Keeps tall prompts from blowing up
        # the card while staying readable without leaving the gallery.
        return (
            "<div class='meta-row'><span class='meta-k'>Prompt</span>"
            f"<details class='prompt'><summary title='{html.escape(value)}'>"
            f"{html.escape(value)}</summary></details></div>"
        )

    model_label = alias
    if alias and model_id:
        model_label = f"{alias} ({model_id})"
    elif model_id:
        model_label = model_id

    meta_rows = (
        prompt_row(prompt)
        + row("Model", model_label)
        + row("Size", size)
        + row("Aspect", ratio)
        + row("Price", cost)
        + row("Created", created[:19])
        + row("File", name)
    )
    actions = (
        f"<div class='actions'>"
        f"<a class='chip' href='/i/{name}' target='_blank' rel='noopener'>Open</a>"
        f"<a class='chip' href='/d/{name}'>Download</a>"
        f"<form method='post' action='/ui/delete' "
        f"onsubmit=\"return confirm('Delete this image? This cannot be undone.')\">"
        f"<input type='hidden' name='csrf' value='{csrf}'>"
        f"<input type='hidden' name='name' value='{name}'>"
        f"<button class='chip danger' type='submit'>Delete</button>"
        f"</form></div>"
    )
    return (
        f"<figure><a href='/i/{name}' target='_blank' rel='noopener'>"
        f"<img src='/i/{name}' loading='lazy' alt=''></a>"
        f"<figcaption><div class='meta'>{meta_rows}</div>{actions}</figcaption></figure>"
    )


def _page(title: str, body: str, *, email: str | None = None) -> HTMLResponse:
    nav = ""
    who = ""
    if email:
        nav = '<nav><a href="/ui">Dashboard</a><a href="/ui/logout">Logout</a></nav>'
        who = f'<span class="who">{html.escape(email)}</span>'
    doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)} - Image Studio</title><style>{_CSS}</style></head>"
        "<body><div class='topbar'><div class='inner'>"
        "<a class='brand' href='/ui'>Image<span>Studio</span></a>"
        f"<div>{who}{nav}</div></div></div>"
        f"<main><h1>{html.escape(title)}</h1>{body}</main></body></html>"
    )
    return HTMLResponse(doc)


def register_ui(
    mcp,
    *,
    allowed_emails: frozenset[str],
    admin_emails: frozenset[str],
    client_id: str,
    client_secret: str,
    public_url: str,
    secret_key: str,
    auth_disabled: bool,
) -> None:
    """Register the /ui routes on the FastMCP app."""
    if not auth_disabled and (not secret_key or secret_key == "dev-insecure-key"):
        raise RuntimeError(
            "IMG_JWT_SIGNING_KEY must be set to a secure, private value in "
            "production; it signs the web dashboard session cookies."
        )
    base = public_url.rstrip("/")
    callback_url = f"{base}/ui/auth/callback"

    def current_email(request: Request) -> str | None:
        if auth_disabled:
            return "dev@local"
        payload = _verify(secret_key, request.cookies.get(SESSION_COOKIE))
        return payload.get("email") if payload else None

    def is_admin(email: str) -> bool:
        return auth_disabled or email.strip().lower() in admin_emails

    def csrf_token(email: str) -> str:
        return _sign(secret_key, {"k": "csrf", "email": email, "exp": time.time() + SESSION_TTL})

    def csrf_ok(email: str, token: str | None) -> bool:
        payload = _verify(secret_key, token)
        return bool(payload and payload.get("k") == "csrf" and payload.get("email") == email)

    # ---- login flow ----
    @mcp.custom_route("/ui/login", methods=["GET"])
    async def ui_login(request: Request) -> Response:
        if auth_disabled or current_email(request):
            return RedirectResponse("/ui")
        state = _sign(secret_key, {"k": "state", "n": secrets.token_urlsafe(8), "exp": time.time() + 600})
        params = urlencode({
            "client_id": client_id,
            "redirect_uri": callback_url,
            "response_type": "code",
            "scope": "openid email",
            "state": state,
        })
        resp = RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")
        resp.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, secure=True, samesite="lax", path="/ui")
        return resp

    @mcp.custom_route("/ui/auth/callback", methods=["GET"])
    async def ui_callback(request: Request) -> Response:
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        state_payload = _verify(secret_key, state) if state else None
        if (
            not code
            or not state
            or state != request.cookies.get(STATE_COOKIE)
            or not state_payload
            or state_payload.get("k") != "state"
        ):
            return PlainTextResponse("Invalid OAuth state.", status_code=400)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                tok = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code,
                        "redirect_uri": callback_url,
                        "grant_type": "authorization_code",
                    },
                )
                tok.raise_for_status()
                access = (tok.json() or {}).get("access_token")
                if not access:
                    return PlainTextResponse("OAuth exchange failed.", status_code=400)
                user = await client.get(
                    "https://openidconnect.googleapis.com/v1/userinfo",
                    headers={"Authorization": f"Bearer {access}"},
                )
                user.raise_for_status()
                info = user.json() or {}
        except (httpx.HTTPError, ValueError) as exc:
            return PlainTextResponse(f"Google authentication failed: {exc}", status_code=502)
        email = str(info.get("email") or "").strip().lower()
        if not is_allowed_email(email, allowed_emails) or info.get("email_verified") is False:
            return PlainTextResponse("Access denied: this dashboard is invitation-only.", status_code=403)
        session = _sign(secret_key, {"email": email, "exp": time.time() + SESSION_TTL})
        resp = RedirectResponse("/ui", status_code=303)
        resp.set_cookie(SESSION_COOKIE, session, max_age=SESSION_TTL, httponly=True, secure=True, samesite="lax", path="/ui")
        resp.delete_cookie(STATE_COOKIE, path="/ui", secure=True, httponly=True, samesite="lax")
        return resp

    @mcp.custom_route("/ui/logout", methods=["GET"])
    async def ui_logout(request: Request) -> Response:
        # Land on a standalone page rather than /ui/login: redirecting into the
        # login flow would silently re-authenticate via the still-active Google
        # session, making logout look like a no-op.
        page = _page(
            "Logged out",
            "<div class='login-wrap'><div class='card'>"
            "<p>You are logged out.</p>"
            "<p><a class='btn' href='/ui/login'>Log in again</a></p>"
            "</div></div>",
        )
        page.delete_cookie(SESSION_COOKIE, path="/ui", secure=True, httponly=True, samesite="lax")
        return page

    # ---- dashboard ----
    @mcp.custom_route("/ui", methods=["GET"])
    async def ui_dashboard(request: Request) -> Response:
        email = current_email(request)
        if not email:
            return RedirectResponse("/ui/login")
        root = storage.images_root()
        metas = metadata.load_all_meta(root)
        per_user = metadata.summarize_by_user(metas)
        admin = is_admin(email)
        if not admin:
            per_user = [(e, s) for e, s in per_user if e == email]

        # Cost comes from the cumulative ledger (money already spent), never
        # from the live images: deleting an image must not lower the total.
        # The image count still reflects what currently exists.
        spend_totals = spend.totals(root)
        counts = {e: s["count"] for e, s in per_user}
        if admin:
            row_emails = sorted(
                set(spend_totals) | set(counts),
                key=lambda e: spend_totals.get(e, 0.0),
                reverse=True,
            )
        else:
            row_emails = [email]

        def cost_of(e: str) -> float:
            return spend_totals.get(e, 0.0)

        total_count = sum(counts.get(e, 0) for e in row_emails)
        total_cost = sum(cost_of(e) for e in row_emails)
        summary_rows = "".join(
            f"<tr><td>{html.escape(e)}</td><td>{counts.get(e, 0)}</td>"
            f"<td>${cost_of(e):.3f}</td></tr>"
            for e in row_emails
        )
        scope_note = "" if admin else " (your generations only)"
        prices = " · ".join(
            f"{alias} "
            + "/".join(
                f"{size} ${models.cost_for(alias, size):.3f}"
                for size in models.ALLOWED_SIZES
            )
            for alias in models.MODELS
        )
        summary = (
            f"<section class='card'><h2>Cost per user{html.escape(scope_note)}</h2>"
            "<table><thead><tr><th>User</th><th>Images</th><th>Estimated cost</th></tr></thead>"
            f"<tbody>{summary_rows}"
            f"<tr><th>Total</th><th>{total_count}</th><th>${total_cost:.3f}</th></tr>"
            "</tbody></table>"
            "<p class='muted'>Cumulative spend, estimated from the list price per "
            f"generated image: {html.escape(prices)}. Deleting an image does not "
            "lower it — the generation was already paid for.</p>"
            "</section>"
        )

        # Per-user default model picker (each user sets their own).
        current = prefs.get_default_model(root, email) or models.DEFAULT_ALIAS
        options = "".join(
            f"<option value='{alias}'{' selected' if alias == current else ''}>"
            f"{html.escape(spec['label'])} (${models.cost_for(alias):.3f}/image in 1K)</option>"
            for alias, spec in models.MODELS.items()
        )
        prefs_card = (
            "<section class='card'><h2>My default model</h2>"
            "<p class='muted'>Used for every generation unless you tell Claude "
            "otherwise. Pro gives higher quality (legible text, complex scenes) "
            "but costs more; flash is fast and cheap. To use the other one for a "
            "single image, just ask Claude (\"use pro\") — Claude won't switch on "
            "its own.</p>"
            "<form method='post' action='/ui/prefs' style='border:0;box-shadow:none;padding:0'>"
            f"<input type='hidden' name='csrf' value='{csrf_token(email)}'>"
            f"<div class='field'><select name='model'>{options}</select></div>"
            "<button class='btn' type='submit'>Save</button>"
            "</form></section>"
        )

        token = csrf_token(email)
        galleries = ""
        for e, s in per_user:
            figures = "".join(
                _figure(m, token) for m in s["images"]
                if storage.is_safe_image_name(str(m.get("name", "")))
            )
            galleries += (
                f"<section class='card'><h2>{html.escape(e)} · {s['count']} image(s)</h2>"
                f"<div class='gallery'>{figures}</div></section>"
            )
        if not per_user:
            galleries = "<div class='empty'>No images generated yet.</div>"

        return _page("Dashboard", summary + prefs_card + galleries, email=email)

    @mcp.custom_route("/ui/delete", methods=["POST"])
    async def ui_delete(request: Request) -> Response:
        email = current_email(request)
        if not email:
            return PlainTextResponse("Unauthorized.", status_code=401)
        form = await request.form()
        csrf_val = form.get("csrf")
        if not isinstance(csrf_val, str) or not csrf_ok(email, csrf_val):
            return PlainTextResponse("Bad CSRF token.", status_code=403)
        name = form.get("name")
        if not isinstance(name, str) or not storage.is_safe_image_name(name):
            return PlainTextResponse("Unknown image.", status_code=400)
        # Only the owner (or an admin) may delete an image: look up who
        # generated it from its sidecar before touching the file.
        root = storage.images_root()
        meta = metadata.load_meta(root, name)
        owner = str(meta.get("email") or "") if meta else None
        if not is_admin(email) and (owner is None or owner != email):
            return PlainTextResponse("Forbidden.", status_code=403)
        storage.delete_image(name, root)
        return RedirectResponse("/ui", status_code=303)

    @mcp.custom_route("/ui/prefs", methods=["POST"])
    async def ui_prefs(request: Request) -> Response:
        email = current_email(request)
        if not email:
            return PlainTextResponse("Unauthorized.", status_code=401)
        form = await request.form()
        csrf_val = form.get("csrf")
        if not isinstance(csrf_val, str) or not csrf_ok(email, csrf_val):
            return PlainTextResponse("Bad CSRF token.", status_code=403)
        alias = form.get("model")
        if not isinstance(alias, str) or alias not in models.MODELS:
            return PlainTextResponse("Unknown model.", status_code=400)
        prefs.set_default_model(storage.images_root(), email, alias)
        return RedirectResponse("/ui", status_code=303)
