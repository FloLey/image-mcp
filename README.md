# Image Studio MCP

An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any MCP
client) **generate images** with Google's Gemini image models ("nano banana").
It is meant to be shared with a few friends: anyone can connect with their
Google account, but only the email addresses in `IMG_ALLOWED_EMAILS` can
actually generate. It also ships a small web dashboard to browse what everyone
generated and track the cost.

This is a standalone Python service. It is deployed alongside the rest of
[florent-lejoly.be](https://florent-lejoly.be) and is reachable at
`https://images.florent-lejoly.be/mcp`. See [Deployment](#deployment) for how
that works now that it lives in its own repo.

## What it does

A single MCP tool:

- `generate_image(prompt, aspect_ratio?, reference_images?, model?, image_size?)`
  generates a PNG, stores it under the `images_data` volume with a random uuid
  name, and returns a small inline preview plus the full-size URL
  (`https://images.florent-lejoly.be/i/{uuid}.png`). Passing the filenames of
  previous generations as `reference_images` lets you iterate ("same scene but
  at night"); `model` picks flash or pro and `image_size` picks 1K/2K/4K.

Two models and three output sizes, chosen per request by use case (Google list
prices per generated image):

| Alias | Model id | 1K | 2K | 4K | Use for |
|---|---|---|---|---|---|
| `flash` | `gemini-3.1-flash-image-preview` (Nano Banana 2) | $0.067 | $0.101 | $0.151 | drafts, iterations, simple scenes |
| `pro` | `gemini-3-pro-image-preview` (Nano Banana Pro) | $0.134 | $0.134 | $0.24 | final renders, text in image, complex compositions |

The `model` parameter accepts the alias, the full id, or the doc-page name
(`gemini-3.1-flash-image` / `gemini-3-pro-image`). The tool contract tells the
model to only pass it when the human **explicitly asked** for a specific model;
otherwise the **per-user default** chosen in the `/ui` dashboard applies,
falling back to `flash`. `image_size` is `1K` (default), `2K`, or `4K`. Ids and
prices are env-overridable (`IMG_MODEL_FLASH`, `IMG_MODEL_PRO`,
`IMG_COST_{FLASH|PRO}_{1K|2K|4K}`), so a model rename or price change needs no
code change.

Public routes (not tools): `GET /health` for the container healthcheck, and
`GET /i/{name}` serving the generated PNGs (the unguessable uuid4 filename is
the access control, and Claude.ai needs to fetch the URL to show the image).

Every generation writes a sidecar JSON (`{uuid}.json`, never served publicly)
recording the caller's email, the prompt, the model and size used, the
timestamp, and the estimated cost. That feeds the dashboard.

## Web dashboard (`/ui`)

A browser-facing dashboard served by the same process at
`https://images.florent-lejoly.be/ui`:

- a **cost per user** table (image count + estimated cost, with a total);
- a **gallery per user** (thumbnails, prompt, date, model, cost per image);
- a **"My default model" picker**: each user chooses the model used when a
  generation does not specify one (stored in `prefs.json` in the data volume).

Auth: a browser Google login using the **same** OAuth client as the MCP
endpoint, restricted to the allow-listed emails, with a signed HttpOnly/Secure
session cookie. Emails in `IMG_ADMIN_EMAILS` see every user; other allow-listed
users only see their own images and cost. The dashboard is read-only. In local
dev (`IMG_AUTH_DISABLED=1`) the login is bypassed and everything is visible.

## Authentication: Google OAuth + email allow-list

The server uses FastMCP's `GoogleProvider` (an OAuth proxy that runs the OAuth
2.1 + PKCE discovery flow Claude.ai expects). On top of "any valid Google
login", `AllowedEmailsMiddleware` restricts tool calls to the emails in
`IMG_ALLOWED_EMAILS` (comma-separated, case-insensitive).

### Configuration (environment variables)

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | yes | the image generation itself |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | yes (prod) | OAuth login; the server refuses to start without them unless auth is disabled |
| `IMG_JWT_SIGNING_KEY` | recommended | stable random value so issued tokens survive redeploys (`openssl rand -hex 32`) |
| `IMG_ALLOWED_EMAILS` | yes (prod) | who may generate, e.g. `me@gmail.com,friend@gmail.com` |
| `IMG_ADMIN_EMAILS` | no | who sees everyone in the dashboard (default `florent.lejoly@gmail.com`) |
| `IMG_MODEL_FLASH` / `IMG_MODEL_PRO`, `IMG_COST_*` | no | override model ids / estimated prices |
| `IMG_AUTH_DISABLED=1` | dev only | run open, no secrets needed |

In production these are set in the deploy of the
[FloLey-public-website](https://github.com/FloLey/FloLey-public-website) repo,
which writes them into the VPS `.env`. They are **not** stored in this repo. See
[Deployment](#deployment).

### Google OAuth client setup (one time)

In the [Google Cloud console](https://console.cloud.google.com/):

1. Create (or reuse) a project, then **APIs & Services -> OAuth consent
   screen**: External, fill in the app name and contact email. The only scopes
   used are `openid` and `userinfo.email` (non-sensitive, no verification
   needed).
2. While the consent screen is in **Testing** mode, add yourself and your
   friends as **test users**. This is a second gate on top of
   `IMG_ALLOWED_EMAILS`; alternatively, publish the app.
3. **APIs & Services -> Credentials -> Create credentials -> OAuth client ID**,
   type **Web application**, with **two** authorized redirect URIs (Google
   matches them exactly, so both are needed):
   - `https://images.florent-lejoly.be/auth/callback` (MCP / Claude.ai)
   - `https://images.florent-lejoly.be/ui/auth/callback` (web dashboard)

## Architecture

- **Transport:** Streamable HTTP, MCP mounted at `/mcp`, listening on `:8766`.
- **Data:** a Docker named volume `images_data` mounted at `/srv/images`, so
  generated images survive redeploys.
- **Public URL:** `https://images.florent-lejoly.be/mcp`, fronted by Caddy
  (auto-HTTPS) in the FloLey-public-website stack.

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

## Run locally

The fast way, with auth disabled (no OAuth needed; generation still needs a
real Gemini key):

```sh
docker build -t image-mcp .
docker run --rm -p 8766:8766 \
  -e IMG_AUTH_DISABLED=1 \
  -e GEMINI_API_KEY=your_key \
  -v "$PWD/.localdata:/srv/images" \
  image-mcp
```

Then:

```sh
curl -s localhost:8766/health        # -> {"ok": true}

npx @modelcontextprotocol/inspector
#   connect to: http://localhost:8766/mcp
#   call generate_image with a prompt
```

## Tests

Pure-logic tests (allow-list, storage naming/path safety, model registry) need
only pytest, no API key or network. They run in CI on every push.

```sh
pip install pytest        # or: pip install -e ".[dev]"
pytest -q
```

## Deployment

This repo deploys itself. On every push, GitHub Actions
(`.github/workflows/ci.yml`):

1. runs the test suite;
2. on `main`, builds and pushes the image to
   `ghcr.io/floley/image-mcp:latest`;
3. connects to the VPS (over Tailscale, then SSH) and restarts just this
   service: `docker compose pull image-mcp && docker compose up -d --no-deps image-mcp`.

The VPS runs the **full stack** (the website frontend, this server, the memory
wiki, and a Caddy reverse proxy) from the
[FloLey-public-website](https://github.com/FloLey/FloLey-public-website) repo's
`docker-compose.yml`. That repo's deploy is what writes the runtime secrets
(`GEMINI_API_KEY`, the Google OAuth values, etc.) into the VPS `.env`, which
this container reads. So the **application secrets live in that repo**, not
here.

This repo only needs the four infrastructure secrets used to reach the VPS:
`VPS_USER`, `VPS_SSH_KEY`, `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`.

DNS is the one manual prerequisite: `images.florent-lejoly.be` must resolve to
the same public IP as `florent-lejoly.be`. Caddy issues HTTPS automatically on
the first request.

## Connect Claude.ai

1. In Claude.ai: Settings -> Connectors -> Add custom connector.
2. URL: `https://images.florent-lejoly.be/mcp`.
3. Claude redirects to Google to log in and consent. Any Google account can log
   in (if a test user, or once the app is published), but only allow-listed
   emails can call the tool.
4. Friends do the same from their own Claude accounts: send them the URL and
   make sure their email is in `IMG_ALLOWED_EMAILS` (and in the OAuth test users
   while the consent screen is in Testing mode).
