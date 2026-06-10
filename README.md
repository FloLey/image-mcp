# Image Studio MCP

An MCP server that generates images with Google's Gemini image models ("nano
banana"), meant to be shared with a few friends: anyone can try to connect
with their Google account, but only the email addresses in
`IMG_ALLOWED_EMAILS` can actually call the tool.

Two models and three output sizes, chosen per request by use case (Google
list prices per generated image):

| Alias | Model id | 1K | 2K | 4K | Use for |
|---|---|---|---|---|---|
| `flash` | `gemini-3.1-flash-image-preview` (Nano Banana 2) | $0.067 | $0.101 | $0.151 | drafts, iterations, simple scenes |
| `pro` | `gemini-3-pro-image-preview` (Nano Banana Pro) | $0.134 | $0.134 | $0.24 | final renders, text in image, complex compositions |

The tool's `model` parameter accepts the alias, the full id, or the doc-page
name (`gemini-3.1-flash-image` / `gemini-3-pro-image`). The **per-user
default** chosen in the `/ui` dashboard always takes precedence; the
parameter only applies for callers without a dashboard default, falling back
to `flash`. `image_size` is `1K` (default), `2K`, or `4K`. Ids and
prices are env-overridable (`IMG_MODEL_FLASH`, `IMG_MODEL_PRO`,
`IMG_COST_{FLASH|PRO}_{1K|2K|4K}`) so a model rename or price change needs no
code change.

Like `memory-wiki/`, this is a self-contained folder inside the
`FloLey-public-website` repo so it can be lifted out later.

## What it does

One MCP tool:

- `generate_image(prompt, aspect_ratio?, reference_images?, model?,
  image_size?)` - generates a PNG, stores it under the `images_data` volume
  with a random uuid name, and returns a small inline preview plus the
  full-size URL (`https://images.florent-lejoly.be/i/{uuid}.png`). Passing the
  filenames of previous generations as `reference_images` lets you iterate
  ("same scene but at night"); `model` picks flash or pro and `image_size`
  picks 1K/2K/4K (see above).

Public routes (not tools): `GET /health` for the container healthcheck, and
`GET /i/{name}` serving the generated PNGs (the unguessable uuid4 filename is
the access control, and Claude.ai needs to fetch the URL to show the image).

Every generation writes a sidecar JSON (`{uuid}.json`, never served publicly)
recording the caller's email, the prompt, the model and size used, the
timestamp, and the estimated cost (the list price of that model at that
size). That feeds the dashboard.

## Web dashboard (`/ui`)

A browser-facing dashboard served by the same process at
`https://images.florent-lejoly.be/ui`:

- a **cost per user** table (image count + estimated cost, with a total);
- a **gallery per user** (thumbnails, prompt, date, model, cost per image);
- a **"My default model" picker**: each user chooses the model used when a
  generation does not specify one (stored in `prefs.json` in the data volume).

Auth: a browser Google login using the **same** OAuth client as the MCP
endpoint, restricted to the allow-listed emails, with a signed
HttpOnly/Secure session cookie (same mechanics as the wiki console). Emails
in `IMG_ADMIN_EMAILS` (default `florent.lejoly@gmail.com`) see every user;
other allow-listed users only see their own images and cost. The dashboard is
read-only. In local dev (`IMG_AUTH_DISABLED=1`) the login is bypassed and
everything is visible.

> **One-time Google change required:** add
> `https://images.florent-lejoly.be/ui/auth/callback` as a **second
> authorized redirect URI** on the OAuth client. Unlike GitHub, Google
> matches redirect URIs exactly, so the MCP callback (`/auth/callback`) does
> not cover the dashboard one.

## Authentication: Google OAuth + email allow-list

The server uses FastMCP's `GoogleProvider` (an OAuth proxy that runs the
OAuth 2.1 + PKCE discovery flow Claude.ai expects). On top of "any valid
Google login", `AllowedEmailsMiddleware` restricts tool calls to the emails in
`IMG_ALLOWED_EMAILS` (comma-separated, case-insensitive).

Environment:

- `IMG_AUTH_DISABLED=1` runs the server open. The **dev compose sets this**,
  so local development needs no secrets.
- Otherwise `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` are
  **required**; the server refuses to start without them. Set
  `IMG_JWT_SIGNING_KEY` to a stable random value so issued tokens survive
  redeploys (e.g. `openssl rand -hex 32`).
- `IMG_ALLOWED_EMAILS=me@gmail.com,friend1@gmail.com,friend2@gmail.com`
- `GEMINI_API_KEY` for the image generation itself.
- Optional: `IMG_MODEL_FLASH` / `IMG_MODEL_PRO` to override the model ids,
  `IMG_COST_{FLASH|PRO}_{1K|2K|4K}` for the estimated per-image prices, and
  `IMG_ADMIN_EMAILS` for who sees everyone in the dashboard.

### Google OAuth client setup (one time)

In the [Google Cloud console](https://console.cloud.google.com/):

1. Create (or reuse) a project, then **APIs & Services -> OAuth consent
   screen**: External, fill in the app name and contact email. The only scopes
   used are `openid` and `userinfo.email` (non-sensitive, no verification
   needed).
2. While the consent screen is in **Testing** mode, add yourself and your
   friends as **test users** (their Gmail addresses). This is a second gate on
   top of `IMG_ALLOWED_EMAILS`; alternatively, publish the app so any Google
   account can reach the (still allow-listed) server.
3. **APIs & Services -> Credentials -> Create credentials -> OAuth client
   ID**, type **Web application**, with **two** authorized redirect URIs:
   - `https://images.florent-lejoly.be/auth/callback` (MCP / Claude.ai)
   - `https://images.florent-lejoly.be/ui/auth/callback` (web dashboard)
4. Copy the client ID and secret into the repository Actions secrets below.

### Repository Actions secrets (one time)

`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
`IMG_JWT_SIGNING_KEY`, `IMG_ALLOWED_EMAILS`, `GEMINI_API_KEY`. The deploy
workflow injects them into the VPS `.env` (gitignored) for compose
substitution. **Set them before merging to main**, otherwise the deploy fails
(the server refuses to boot without its OAuth secrets and compose `--wait`
times out).

## Architecture

- **Transport:** Streamable HTTP, MCP mounted at `/mcp`, listening on `:8766`.
- **Data:** a Docker named volume `images_data` mounted at `/srv/images`, so
  generated images survive redeploys.
- **Public URL:** `https://images.florent-lejoly.be/mcp`, fronted by Caddy
  (auto-HTTPS) in the main `docker-compose.yml`.

## Tests

Pure-logic tests (allow-list, storage naming/path safety) need only pytest, no
API key or network; they run in CI on every push. From `image-mcp/`:

```sh
pip install pytest
pytest -q
```

## Run locally

From the repo root:

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build image-mcp
```

Auth is disabled in dev; generation still needs a real key, so put
`GEMINI_API_KEY=...` in the repo-root `.env` first. Then:

```sh
curl -s localhost:8766/health        # -> {"ok": true}

npx @modelcontextprotocol/inspector
#   connect to: http://localhost:8766/mcp
#   call generate_image with a prompt
```

## Connect Claude.ai (after deploy + DNS)

1. Add a DNS record for `images.florent-lejoly.be` pointing to the same public
   IP as `florent-lejoly.be` (same one-time step as the wiki).
2. In Claude.ai: Settings -> Connectors -> Add custom connector.
3. URL: `https://images.florent-lejoly.be/mcp`.
4. Claude redirects to Google to log in and consent. Any Google account can
   log in (if a test user / published app), but only allow-listed emails can
   call the tool.
5. Friends do the same from their own Claude accounts: send them the URL,
   make sure their email is in `IMG_ALLOWED_EMAILS` (and in the OAuth test
   users while the consent screen is in Testing mode).

## Layout

```
image-mcp/
  Dockerfile
  pyproject.toml
  src/image_mcp/
    server.py    # FastMCP app: auth, middleware, tool, /health, /i/{name}
    access.py    # email allow-list logic (pure, unit-tested)
    storage.py   # uuid-named PNG storage under IMG_ROOT (pure, unit-tested)
    metadata.py  # per-generation sidecar JSON + per-user totals (pure, unit-tested)
    models.py    # flash/pro registry: ids, prices, alias resolution (pure, unit-tested)
    prefs.py     # per-user default model in prefs.json (pure, unit-tested)
    generate.py  # the Gemini call + inline preview downscale
    ui.py        # /ui dashboard: Google browser login + galleries + costs + prefs
  tests/
```
