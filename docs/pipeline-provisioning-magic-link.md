# Pipeline provisioning + passwordless login

Pipelines auto-create user accounts and hand each user a **one-click login link** to their dashboard. Gated by **one shared secret**; no passwords.

## Setup (once, server side)

```bash
DEPICTIO_AUTH_PROVISIONING_API_KEY=<long-random-secret>   # the instance gate
DEPICTIO_VIEWER_PUBLIC_URL=https://depictio.example.org    # used to build the link
# (TLS in front is required)
```

Unset key → provisioning endpoints return `503` (feature off).

## Use (pipeline side)

```bash
export DEPICTIO_AUTH_PROVISIONING_API_KEY=<secret>
depictio-cli run --template <id> --data-root /data/alice --user alice@lab.org
# → prints: https://INSTANCE/auth/magic#ticket=...&next=/dashboard-beta/<id>
```

The CLI provisions Alice, runs the pipeline **as Alice** (project + dashboard owned by her), and prints a login link. Send it to her — she clicks and lands on her dashboard, logged in.

## How it works

1. `POST /auth/provision_user` (shared key) → create-or-get a passwordless user + a long-lived run token.
2. Pipeline runs as that user via a temporary `0600` CLI config.
3. `POST /auth/me/magic_link` (as the user) → a **single-use, short-lived ticket**.
4. User opens the link → `POST /auth/magic/exchange` validates + **burns** the ticket → real session in the browser.

## Security model

- One secret = the **instance gate** (keeps bots out). Not meant to isolate users from each other — only to separate them.
- The link carries only a **single-use, ~15 min** ticket, in the URL **fragment** (`#`) so it stays out of server logs / `Referer`. A leaked link is already used or expired.
- The real session token is minted server-side at click time — never in a URL.
- **HTTPS is mandatory.**
