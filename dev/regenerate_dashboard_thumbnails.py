#!/usr/bin/env python3
"""Regenerate dashboard thumbnails on a live Depictio deployment.

Drives the backend's ``/depictio/api/v1/utils/screenshot-react-dual/{id}``
endpoint (Playwright in the Celery workers) for every dashboard returned by
``/dashboards/list_all``, capturing both light and dark themes in one call.

Auth: pass a long-lived admin bearer token via ``--token-file`` (one line).
On an EMBL K8s deployment you can mint one from the backend pod's per-admin
config, e.g.::

    NS=datasci-depictio-project-demo-dev
    POD=$(kubectl -n $NS get pods -o name | grep -m1 depictio-backend | sed 's|pod/||')
    kubectl -n $NS exec $POD -c depictio-backend -- python3 -c \
      "import yaml;print(yaml.safe_load(open('/app/depictio/.depictio/thomas.weber_config.yaml'))['user']['token']['access_token'])" \
      > /tmp/devdemo_admin_token

Example::

    python dev/regenerate_dashboard_thumbnails.py \
        --host dev.api.demo.depictio.embl.org \
        --token-file /tmp/devdemo_admin_token \
        --concurrency 3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def _api_get(host: str, path: str, token: str, timeout: float) -> dict | list:
    req = urllib.request.Request(
        f"https://{host}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def list_targets(host: str, token: str, include_private: bool) -> list[dict]:
    docs = _api_get(
        host,
        "/depictio/api/v1/dashboards/list_all?include_child_tabs=true",
        token,
        timeout=30,
    )
    if not isinstance(docs, list):
        raise SystemExit(f"Unexpected list_all payload: {type(docs)}")
    if not include_private:
        docs = [d for d in docs if d.get("is_public")]
    return docs


def regenerate_one(host: str, token: str, dashboard_id: str, timeout: float) -> dict:
    """Call the dual-theme screenshot endpoint for one dashboard.

    The endpoint blocks until the Celery task finishes (server-side timeout
    ~180s), so the client timeout is set a little higher.
    """
    started = time.monotonic()
    try:
        result = _api_get(
            host,
            f"/depictio/api/v1/utils/screenshot-react-dual/{dashboard_id}",
            token,
            timeout=timeout,
        )
        return {
            "id": dashboard_id,
            "ok": True,
            "status": (result or {}).get("status", "?"),
            "elapsed": time.monotonic() - started,
        }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:200]
        return {
            "id": dashboard_id,
            "ok": False,
            "status": f"HTTP {exc.code}: {body}",
            "elapsed": time.monotonic() - started,
        }
    except Exception as exc:  # noqa: BLE001 — surface every failure mode in the report
        return {
            "id": dashboard_id,
            "ok": False,
            "status": f"{type(exc).__name__}: {exc}",
            "elapsed": time.monotonic() - started,
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="dev.api.demo.depictio.embl.org", help="API hostname (no scheme)")
    ap.add_argument("--token-file", default="/tmp/devdemo_admin_token", help="File holding the admin bearer token")
    ap.add_argument("--concurrency", type=int, default=3, help="Parallel in-flight requests (keep near worker count)")
    ap.add_argument("--timeout", type=float, default=210.0, help="Per-request client timeout in seconds")
    ap.add_argument("--include-private", action="store_true", help="Also regenerate non-public dashboards")
    ap.add_argument("--only", nargs="*", default=None, help="Restrict to these dashboard ids")
    ap.add_argument("--dry-run", action="store_true", help="List targets and exit without regenerating")
    args = ap.parse_args()

    token = open(args.token_file).read().strip()
    if not token:
        raise SystemExit(f"Empty token in {args.token_file}")

    me = _api_get(args.host, "/depictio/api/v1/auth/me", token, timeout=10)
    print(f"[auth] {me.get('email')}  is_admin={me.get('is_admin')}  host={args.host}")

    docs = list_targets(args.host, token, args.include_private)
    if args.only:
        wanted = set(args.only)
        docs = [d for d in docs if d.get("dashboard_id") in wanted]

    print(f"[targets] {len(docs)} dashboards  (include_private={args.include_private}, concurrency={args.concurrency})")
    for d in docs:
        print(f"   - {d.get('dashboard_id')}  pub={int(bool(d.get('is_public')))}  {d.get('title')!r}")
    if args.dry_run:
        print("[dry-run] no screenshots generated")
        return 0

    results: list[dict] = []
    done = 0
    total = len(docs)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(regenerate_one, args.host, token, d["dashboard_id"], args.timeout): d
            for d in docs
        }
        for fut in as_completed(futures):
            d = futures[fut]
            r = fut.result()
            results.append(r)
            done += 1
            mark = "✓" if r["ok"] else "✗"
            print(
                f"[{done:>2}/{total}] {mark} {r['id']}  {r['status']:<28} "
                f"{r['elapsed']:5.1f}s  {d.get('title')!r}",
                flush=True,
            )

    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    print(f"\n[summary] {len(ok)}/{total} regenerated, {len(bad)} failed")
    for r in bad:
        print(f"   FAILED {r['id']}: {r['status']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
