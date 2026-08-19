# Deploying Library OS to Cloudflare

Your app itself (`app/` folder — app.py, templates, static files, everything)
is **completely untouched**. Two small new files were added at the top level
so Cloudflare knows how to run your existing Docker container:

- `src/index.js` — a thin gateway; it doesn't contain any of your app logic
- `wrangler.jsonc` — points Cloudflare at your existing `app/Dockerfile`

## One-time setup

1. Install Docker Desktop if you don't have it (Cloudflare needs it running
   locally to build/push your container image): https://www.docker.com/products/docker-desktop
2. Install Node.js if you don't have it: https://nodejs.org
3. Open a terminal in this folder and run:
   ```
   npm install
   npx wrangler login
   ```
   This opens a browser to connect your Cloudflare account.

## Required settings (env vars — no code changes)

Your app already reads these from environment variables
(`config.py`/`app.py` — unchanged), so just set them in Cloudflare instead of
your `.env` file:

- `SECRET_KEY` — required in production (your `config.py` raises an error
  without it)
- `DATABASE_URL` — **important:** see the note below
- `GEMINI_API_KEY` / `GEMINI_ENDPOINT` / `GEMINI_MODEL` — only if you use the
  AI enrich-book feature

Set them with:
```
npx wrangler secret put SECRET_KEY
npx wrangler secret put DATABASE_URL
```
(it'll prompt you to paste each value)

### About `DATABASE_URL`

Your app defaults to a local SQLite file if `DATABASE_URL` isn't set. On
Cloudflare, the container's disk isn't guaranteed to survive restarts or
scale-to-zero — so a school's real book/loan records could vanish. Nothing in
your code needs to change to fix this: your `config.py` already supports
`DATABASE_URL` pointing at a real Postgres database. Point it at a Neon
Postgres database (same service you already use for your other two projects)
and your existing SQLAlchemy models will just work against it, unchanged.

If you skip this and rely on the container's local SQLite file, treat any
data in it as temporary.

## Deploy — two options

### Option A: one-time manual deploy (simplest for a first test)
```
npx wrangler deploy
```
Wrangler builds your existing Dockerfile, pushes it, and gives you a
`*.workers.dev` URL when it's done.

### Option B: GitHub auto-deploy (same idea as your For-You app)
This is the "push to GitHub, Cloudflare deploys it" workflow you're used to.
One extra step compared to a Pages project, because this is a Docker
container rather than a plain Worker:

1. Push this whole folder (as-is — `app/`, `src/`, `wrangler.jsonc`, etc.) to
   a GitHub repo, same as `coder-girl-tom`.
2. In the Cloudflare dashboard: **Workers & Pages → Create → Connect to
   Git** → pick the repo.
3. Under the Worker's **Settings → Builds**, set the build command to:
   ```
   npx wrangler deploy
   ```
   This part is the difference from For-You — Cloudflare's default build
   command for Containers doesn't rebuild the Docker image, so it has to be
   set explicitly or your app code changes won't actually roll out.
4. Add `SECRET_KEY` and `DATABASE_URL` as encrypted environment variables in
   that same Build/Settings screen (instead of running `wrangler secret put`
   locally).

After that, every `git push` to the connected branch rebuilds and redeploys
automatically — same as For-You.

## Notes on your traffic scale (one school, <=500 requests/day)

- `max_instances: 1` in `wrangler.jsonc` is intentional — you don't need more
  than one running copy at this volume, keeps cost minimal.
- `sleepAfter: '10m'` in `src/index.js` means the container spins down after
  10 minutes idle and takes a few seconds to wake up on the next request.
  Fine for a library front desk; if that wake-up delay ever bothers you,
  raise or remove `sleepAfter`.
- Your APScheduler nightly backup job works exactly as it does today —
  Containers run a real, persistent Linux process (unlike Cloudflare
  Workers), so nothing about your background scheduler needed to change.
