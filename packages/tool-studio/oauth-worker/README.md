# Tool Studio — GitHub OAuth worker

A ~60-line stateless [Cloudflare Worker](https://developers.cloudflare.com/workers/) that lets the
static Tool Studio open a pull request with **"Sign in with GitHub"** (no PAT, no pasted token).
The Studio is a GitHub-Pages SPA, so it can't hold the OAuth **client secret** — this worker does the
single step that needs it (exchanging the authorize `code` for a user token). The fork + multi-file
commit + PR all happen in the browser afterwards with that token.

This is **optional infrastructure**. Until it's deployed and the app is configured, the Studio falls
back to the zip download + GitHub web-upload flow — nothing breaks.

## One-time setup

1. **Register a GitHub OAuth App** (org `depictio` → Settings → Developer settings → OAuth Apps):
   - Homepage URL: `https://depictio.github.io/depictio-tool-studio/`
   - Authorization callback URL: `https://depictio.github.io/depictio-tool-studio/oauth-callback.html`
   - Copy the **Client ID**; generate a **Client secret**.

2. **Deploy the worker.** `wrangler.toml` already carries the client id and the
   Pages origin, so there is nothing to edit:
   ```bash
   cd packages/tool-studio/oauth-worker
   npm install          # wrangler, pinned here as a devDependency
   npm run check        # compiles the worker + echoes its bindings, no deploy
   npm run login        # authorises your Cloudflare account
   npm run secret       # paste the OAuth App client secret
   npm run deploy
   ```
   Note the deployed URL, e.g. `https://depictio-tool-studio-oauth.<subdomain>.workers.dev`.

   wrangler is pinned to **4.86.0**, the last release that accepts Node 20
   (`>=20.3.0`); 4.87 onwards requires Node 22, while both this repo's workflows
   run Node 20. Installing from this `package.json` therefore works on the same
   Node the rest of the project uses — `npx wrangler@latest` does not, and fails
   with "Wrangler requires at least Node.js v22.0.0".

   This directory is deliberately **outside** the pnpm workspace
   (`pnpm-workspace.yaml` globs `packages/*`, which does not reach it), so
   wrangler never enters the root lockfile: nothing in the app build, the CI
   drift check or the Pages deploy depends on it. Install it with plain `npm`,
   here, only when you actually deploy the worker.

3. **Configure the Studio build** — set these Vite env vars (e.g. in the
   `deploy-tool-studio.yaml` workflow or a `.env.production`):
   ```
   VITE_GH_CLIENT_ID=<OAuth App client id>
   VITE_GH_OAUTH_WORKER_URL=https://depictio-tool-studio-oauth.<subdomain>.workers.dev/exchange
   ```

With those set, the Export step shows **Sign in with GitHub → Open pull request**. Without them, it
shows **Download zip + Contribute on GitHub (web upload)**.

## Try it locally (before deploying)

Two ways, easiest first:

**A. Fastest — test the fork/commit/PR flow with a throwaway token (no worker, no OAuth App).**
```bash
cd packages/tool-studio
cp .env.example .env.local
# in .env.local:
#   VITE_GH_TOKEN=$(gh auth token)         # short-lived, your account, gitignored
#   VITE_GH_TARGET=your-user/catalog-sandbox   # optional: don't hit depictio/depictio
pnpm dev
```
The Export step shows **Open pull request**; it runs the real fork → commit → PR against the target.
This exercises the risky part (`github.ts`) end-to-end. `VITE_GH_TOKEN` is DEV-only and never ships.

**B. Faithful — full popup OAuth locally with `wrangler dev`.**
1. In your OAuth App, add a second callback: `http://localhost:5173/depictio-tool-studio/oauth-callback.html`.
2. `cd oauth-worker && cp .dev.vars.example .dev.vars` and put the client secret in `.dev.vars`.
3. `npm run dev -- --var GH_CLIENT_ID:<id> --var ALLOWED_ORIGIN:http://localhost:5173` (serves `:8787`).
4. `packages/tool-studio/.env.local`: `VITE_GH_CLIENT_ID=<id>` and
   `VITE_GH_OAUTH_WORKER_URL=http://localhost:8787/exchange`, then `pnpm dev`.

## Security

- The client secret lives **only** in the worker (`wrangler secret`), never in the static bundle.
- Scope requested is `public_repo` (fork + PR on the public repo; no private access).
- The worker only accepts its configured `ALLOWED_ORIGIN` and returns only the access token.
- The app validates the OAuth `state` (CSRF) and drives the popup from a user click.
