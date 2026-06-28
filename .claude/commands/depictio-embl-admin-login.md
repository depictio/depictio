---
description: Auth as Depictio admin on an EMBL K8s deployment by injecting the on-pod long-lived token into the React /dashboards hand-off — no login form, no password.
argument-hint: "[namespace | hostname]   (default: datasci-depictio-project-demo-dev → dev.api.demo.depictio.embl.org)"
allowed-tools: Bash, Read
---

You are running `/depictio-embl-admin-login`.

## Goal

Open a Chrome tab already logged in as the deployment's **bootstrap admin** on
the target deployment, by minting a `SessionPayload` from the backend pod's
exported admin agent-config and using the React viewer's built-in cross-origin session
hand-off (`#auth=<base64 JSON>` fragment), which `viewer/src/main.tsx`
(`consumeCrossOriginSessionHandoff`) decodes and writes to
`localStorage['local-store']` on boot, then strips from the URL.

## Inputs

`$ARGUMENTS` may be:
- **empty** → default ns `datasci-depictio-project-demo-dev`, host `dev.api.demo.depictio.embl.org`
- **a namespace** (e.g. `datasci-depictio-project-demo`) → resolve host from that ns's ingress
- **a hostname** (e.g. `demo.depictio.embl.org`, contains a dot) → look up the owning namespace via `kubectl get ingress -A`

## Steps

1. **Pre-flight**: Verify `kubectl config current-context` resolves the cluster. If `kubectl get ns` fails with a DNS error on `capsule.embl.de`, **stop and tell the user the EMBL VPN is down**. Do not retry blindly.

2. **Resolve `NS` and `HOST`** from `$ARGUMENTS` per the rules above. When given a namespace, read the host with:
   ```bash
   kubectl -n "$NS" get ingress -o jsonpath='{.items[*].spec.rules[*].host}'
   ```
   Prefer hosts starting with `api.` or matching `*api.*` (that's where `/dashboards` is served from); if there are multiple, pick the one containing `api`.

3. **Find the backend pod**:
   ```bash
   POD=$(kubectl -n "$NS" get pods -o name | grep -m1 'depictio-backend' | sed 's|pod/||')
   ```
   Abort with a clear error if empty.

4. **Mint the session URL** by running the python block below. It **discovers** the admin agent-config on the pod — the API exports it as `{username}_config.yaml` (`username = adminEmail.split("@")[0]`), so it is **not** always `admin_config.yaml` (on EMBL the admin is `thomas.weber@embl.de` → `thomas.weber_config.yaml`). It globs `*_config.yaml` under the pod's `.depictio/`, prefers the file matching `$DEPICTIO_BOOTSTRAP_ADMIN_EMAIL`, verifies each candidate against `/depictio/api/v1/auth/me` and uses the first `is_admin` one, builds the `SessionPayload`, base64-encodes it, opens Chrome, and copies a DevTools-console fallback to the clipboard. Substitute `$NS`, `$POD`, `$HOST` before running:

   ```bash
   python3 <<PY
   import json, base64, subprocess, sys, os, urllib.request
   ns, pod, host = "$NS", "$POD", "$HOST"

   def kx(*cmd):
       return subprocess.check_output(
           ["kubectl","-n",ns,"exec",pod,"-c","depictio-backend","--", *cmd], text=True)

   # Lightweight YAML parse — only need user.{email,id,token.*}. The backend
   # image ships PyYAML, but local mac may not; fall back to a tolerant
   # line-based parse keyed on the known shape.
   def parse_cfg(raw):
       try:
           import yaml; return yaml.safe_load(raw)
       except ImportError:
           cfg = {"user": {"token": {}}}; section = []
           for line in raw.splitlines():
               indent = len(line) - len(line.lstrip()); stripped = line.strip()
               if not stripped or stripped.startswith("#"): continue
               if stripped.endswith(":") and indent == 0:
                   section = [stripped[:-1]]; continue
               if stripped.endswith(":"):
                   while len(section) > indent//2: section.pop()
                   section.append(stripped[:-1]); continue
               if ":" in stripped:
                   k, _, v = stripped.partition(":"); v = v.strip().strip("'\"")
                   node = cfg
                   for s in section[: indent//2]: node = node.setdefault(s, {})
                   node[k] = v
           return cfg

   # Discover the admin agent-config. The API writes "{username}_config.yaml"
   # (username = adminEmail.split('@')[0]), so it is NOT always admin_config.yaml
   # — on EMBL it's e.g. thomas.weber_config.yaml.
   listing = kx("sh","-c",
       'find /app -maxdepth 6 -path "*/.depictio/*_config.yaml" 2>/dev/null').split()
   if not listing:
       sys.exit("No *_config.yaml under any .depictio/ on the pod — the admin agent "
                "config was never exported. Check DEPICTIO_BOOTSTRAP_ADMIN_EMAIL/PASSWORD "
                "are set and the bootstrap ran (mongodb may have been wiped).")

   # Prefer the file matching $DEPICTIO_BOOTSTRAP_ADMIN_EMAIL, if exposed.
   admin_email = kx("sh","-c",'printf %s "$DEPICTIO_BOOTSTRAP_ADMIN_EMAIL"').strip()
   want = f'{admin_email.split("@")[0]}_config.yaml' if admin_email else None
   listing.sort(key=lambda p: 0 if os.path.basename(p) == want else 1)

   session = me = chosen = None
   for path in listing:
       u = (parse_cfg(kx("cat", path)) or {}).get("user") or {}
       t = u.get("token") or {}
       if not t.get("access_token"):
           continue
       try:
           req = urllib.request.Request(
               f"https://{host}/depictio/api/v1/auth/me",
               headers={"Authorization": f"Bearer {t['access_token']}"})
           with urllib.request.urlopen(req, timeout=10) as r:
               cand = json.load(r)
       except Exception as e:
           print(f"[skip] {os.path.basename(path)}: /auth/me failed ({e})"); continue
       if cand.get("is_admin"):
           chosen, me = path, cand
           session = {
               "logged_in": True,
               "email": u["email"],
               "user_id": str(u["id"]),
               "access_token": t["access_token"],
               "refresh_token": t["refresh_token"],
               "expire_datetime": str(t["expire_datetime"]),
               "refresh_expire_datetime": str(t["refresh_expire_datetime"]),
               "token_lifetime": t.get("token_lifetime","long-lived"),
               "token_type": t.get("token_type","bearer"),
               "name": t.get("name","default_token"),
               "is_temporary": False,
               "is_anonymous": False,
           }
           break
       print(f"[skip] {os.path.basename(path)}: token not admin ({cand.get('email')})")

   if not session:
       sys.exit("Found config file(s) but none authenticated as admin via /auth/me — "
                "tokens may be rotated (mongodb_wipe / JWT-secret change). Abort.")

   print(f"[verified] {me['email']}  is_admin={me['is_admin']}  user_id={me['id']}  "
         f"({os.path.basename(chosen)})")
   print(f"[token]    expires {session['expire_datetime']}  ({session['token_lifetime']})")
   js = json.dumps(session, separators=(",",":"))
   b64 = base64.b64encode(js.encode()).decode()
   url = f"https://{host}/dashboards#auth={b64}"
   subprocess.run(["open","-a","Google Chrome",url], check=True)
   fallback = f"localStorage.setItem('local-store', JSON.stringify({js})); location.replace('/dashboards');"
   subprocess.run(["pbcopy"], input=fallback.encode(), check=False)
   print(f"[opened]   {host}/dashboards  (Chrome)")
   print("[clipboard] DevTools console fallback ready to paste if the tab cached anonymous")
   PY
   ```

5. **Report to the user**: target `NS` + `HOST`, the resolved admin email + user_id (from the chosen `*_config.yaml`), token expiry, and how to verify — top-right avatar should show that admin email, and DevTools → Application → Local Storage → key `local-store` should hold a JSON with `"logged_in":true` and the admin email.

## Why this works (one-paragraph mental model)

`viewer/src/main.tsx` runs `consumeCrossOriginSessionHandoff()` **before**
`validateSession()` during boot, so a hand-off fragment overrides any anonymous
session already cached in localStorage. The hand-off only requires
`typeof session.access_token === 'string'`, but emitting the full
`SessionPayload` (defined in `packages/depictio-react-core/src/api.ts`) makes the
refresh flow happy and avoids a premature re-login. The same `local-store` key
is shared by the legacy Dash app and the React viewer
(`SESSION_KEY = 'local-store'`). The pod's exported `{username}_config.yaml`
token is long-lived (years-long), minted at backend bootstrap.

## Safety / failure modes

- VPN required: `capsule.embl.de` and the `*.depictio.embl.org` ingresses are EMBL-internal. DNS-lookup errors → tell the user to bring up the VPN, then stop.
- Never echo the access token into a tool that logs it; the hand-off fragment is consumed and stripped by the SPA on first boot.
- If `/auth/me` returns `is_admin:false` or 401, the on-pod token has been rotated (rare — usually means a `mongodb_wipe` or a JWT-secret change). Abort and tell the user.
- This skill **reads** only — it does not modify cluster state, no `kubectl exec` write commands.
