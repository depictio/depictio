#!/usr/bin/env python3
"""
Render-figure latency benchmark.

Usage (stack must be running):
    # Steady-state per-render latency (the number to compare across stacks):
    python dev/benchmark_render.py --filtered
    # Capacity / saturation ceiling (load test):
    python dev/benchmark_render.py --filtered --concurrency 10

Two distinct measurements, controlled by --concurrency:
  - Default --concurrency 1: every discovered figure runs its reps sequentially,
    all components in parallel (~N_components in flight). This isolates per-render
    cost — no artificial queue pile-up. USE THIS to compare perf vs no-perf stacks.
  - --concurrency K > 1: drives ~K*N_components requests simultaneously, which on
    a small dev worker pool (4 gunicorn + 4 celery) measures the queue/saturation
    ceiling, NOT per-render cost. Latency there is dominated by queue wait.

Modes:
  - default: unfiltered render (cold→warm).
  - --filtered: warm caches first (--warmup discarded reps), then each rep applies
    a different RangeSlider value — the interactive filter-drag / projection path.

If --token is omitted the script auto-logs in with the default dev credentials
(auto-read from docker-compose/.env, or DEPICTIO_BENCHMARK_EMAIL/PASSWORD env vars).

Output:
  Per-component: p50 / p95 / p99 / max latency + Celery routing breakdown.
  Overall summary across all components.
"""

import argparse
import asyncio
import os
import statistics
import sys
import time
from collections import defaultdict

import httpx

ADMIN_EMAIL = os.getenv("DEPICTIO_BENCHMARK_EMAIL", "admin@depictio.io")
ADMIN_PASSWORD = os.getenv("DEPICTIO_BENCHMARK_PASSWORD", "changeme")


def _read_env_file(path: str) -> dict[str, str]:
    result = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    result[k.strip()] = v.strip()
    except OSError:
        pass
    return result


def _discover_api_url() -> str:
    """Read FASTAPI_PORT from .env.instance (worktree-local) and build the URL."""
    root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    env = _read_env_file(os.path.join(root, ".env.instance"))
    port = env.get("FASTAPI_PORT") or env.get("DEPICTIO_FASTAPI_EXTERNAL_PORT")
    return f"http://localhost:{port}" if port else "http://localhost:8058"


def _discover_credentials() -> tuple[str, str]:
    """Read admin email/password from docker-compose/.env."""
    root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    env = _read_env_file(os.path.join(root, "docker-compose", ".env"))
    email = env.get("DEPICTIO_BOOTSTRAP_ADMIN_EMAIL", ADMIN_EMAIL)
    password = env.get("DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD", ADMIN_PASSWORD)
    return email, password

# ─── helpers ──────────────────────────────────────────────────────────────────

def _pct(data: list[float], p: int) -> float:
    if not data:
        return float("nan")
    data = sorted(data)
    idx = int(len(data) * p / 100)
    return data[min(idx, len(data) - 1)]


def _fmt(ms: float) -> str:
    return f"{ms:7.1f} ms"


# ─── auth ─────────────────────────────────────────────────────────────────────

def get_token(base_url: str, email: str, password: str) -> str:
    r = httpx.post(
        f"{base_url}/depictio/api/v1/auth/login",
        data={"username": email, "password": password},
        timeout=15,
    )
    if r.status_code != 200:
        sys.exit(f"Login failed ({r.status_code}): {r.text[:200]}")
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        sys.exit(f"No token in login response: {data}")
    print(f"  Authenticated as {email}")
    return token


# ─── discovery ────────────────────────────────────────────────────────────────

def discover_figure_targets(base_url: str, headers: dict) -> list[dict]:
    r = httpx.get(f"{base_url}/depictio/api/v1/dashboards/list", headers=headers, timeout=15)
    if r.status_code != 200:
        sys.exit(f"Cannot list dashboards ({r.status_code}): {r.text[:200]}")
    stubs = r.json()
    if not stubs:
        sys.exit("No dashboards found — is the stack seeded?")

    targets = []
    for stub in stubs:
        did = stub.get("dashboard_id") or stub.get("_id") or stub.get("id")
        # /list returns a lightweight view without stored_metadata — fetch full object
        full = httpx.get(f"{base_url}/depictio/api/v1/dashboards/get/{did}", headers=headers, timeout=15)
        if full.status_code != 200:
            continue
        dash = full.json()
        label = dash.get("name") or dash.get("title") or str(did)
        metas = dash.get("stored_metadata") or []

        # Index numeric RangeSlider interactive components by the dc they filter,
        # so a figure on the same dc can be exercised with a real filter drag.
        filters_by_dc: dict[str, dict] = {}
        for m in metas:
            if m.get("component_type") != "interactive":
                continue
            ictype = m.get("interactive_component_type")
            col = m.get("column_name")
            coltype = (m.get("column_type") or "").lower()
            if ictype == "RangeSlider" and col and ("float" in coltype or "int" in coltype):
                filters_by_dc.setdefault(str(m.get("dc_id")), {
                    "interactive_component_type": ictype,
                    "column_name": col,
                    "column_type": coltype,
                })

        for meta in metas:
            if meta.get("component_type") == "figure":
                dc_id = str(meta.get("dc_id"))
                targets.append({
                    "dashboard_id": did,
                    "component_id": str(meta["index"]),
                    "visu_type": meta.get("visu_type")
                    or (meta.get("figure_config") or {}).get("visu_type", "?"),
                    "label": label,
                    "filter": filters_by_dc.get(dc_id),  # None if no numeric slider on this dc
                })
    if not targets:
        sys.exit("No figure components found in any dashboard.")
    return targets


def _make_filter(filter_spec: dict | None, rep: int) -> list[dict]:
    """Build a per-rep-varying RangeSlider filter payload (simulates slider drags).

    Returns [] when the figure's dc has no numeric slider, so the caller still
    exercises the unfiltered path rather than crashing.
    """
    if not filter_spec:
        return []
    # Walk the lower bound across a sweep so each rep is a distinct subset —
    # defeats any identical-request result caching and exercises a real
    # filtered re-render every time. Range tuned for iris-scale numeric cols;
    # values outside the data domain just widen/empty the selection harmlessly.
    lo = 4.0 + (rep % 20) * 0.15  # 4.0 .. ~6.85
    hi = 9.0
    return [{
        "interactive_component_type": filter_spec["interactive_component_type"],
        "column_name": filter_spec["column_name"],
        "value": [round(lo, 3), hi],
    }]


# ─── async benchmark ──────────────────────────────────────────────────────────

async def _bench_component(
    client: httpx.AsyncClient,
    target: dict,
    base_url: str,
    reps: int,
    concurrency: int,
    theme: str,
    filtered: bool,
    warmup: int,
) -> dict:
    url = (
        f"{base_url}/depictio/api/v1/dashboards/"
        f"render_figure/{target['dashboard_id']}/{target['component_id']}"
    )
    spec = target.get("filter") if filtered else None
    times: list[float] = []
    routing_seen: list[str] = []
    errors = 0
    sem = asyncio.Semaphore(concurrency)

    async def _one(rep: int, measure: bool) -> None:
        nonlocal errors
        async with sem:
            payload = {"filters": _make_filter(spec, rep), "theme": theme}
            try:
                t0 = time.perf_counter()
                r = await client.post(url, json=payload, timeout=60)
                elapsed = (time.perf_counter() - t0) * 1000
                if r.status_code == 200:
                    if measure:
                        times.append(elapsed)
                        routing_seen.append(r.headers.get("x-celery-path", "unknown"))
                elif measure:
                    errors += 1
            except Exception:
                if measure:
                    errors += 1

    # Warm-up phase (discarded): populate delta-table + schema caches so the
    # measured phase reflects warm interactive re-renders, not first-load cost.
    if warmup:
        await asyncio.gather(*[_one(i, measure=False) for i in range(warmup)])

    await asyncio.gather(*[_one(i, measure=True) for i in range(reps)])

    return {
        "times": times,
        "routing_seen": routing_seen,
        "errors": errors,
        "filtered_applied": bool(spec),
        **target,
    }


async def run_benchmark(
    base_url: str,
    token: str,
    reps: int,
    concurrency: int,
    theme: str,
    filtered: bool,
    warmup: int,
) -> None:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    print("\n[1/3] Discovering figure components …")
    targets = discover_figure_targets(base_url, headers)
    n_filterable = sum(1 for t in targets if t.get("filter"))
    print(f"  Found {len(targets)} figure component(s)")
    mode = "WARM + interactive filter" if filtered else "cold→warm, no filter"
    if filtered:
        print(f"  {n_filterable}/{len(targets)} have a numeric RangeSlider to drag; "
              f"warm-up = {warmup} discarded reps/component")

    print(
        f"\n[2/3] Benchmarking {len(targets)} component(s) concurrently [{mode}] "
        f"— {reps} reps × {concurrency} in-flight per component …\n"
    )

    async with httpx.AsyncClient(headers=headers) as client:
        component_results = await asyncio.gather(
            *[
                _bench_component(client, t, base_url, reps, concurrency, theme, filtered, warmup)
                for t in targets
            ]
        )

    # ── print table ──────────────────────────────────────────────────────────
    col_w = 122
    print(f"  {'Dashboard':<30} {'Component':<12} {'VisuType':<14} {'flt':<4}  {'p50':>9}  {'p95':>9}  {'p99':>9}  {'max':>9}  routing")
    print("  " + "-" * col_w)

    routing_counts: dict[str, int] = defaultdict(int)
    all_times: list[float] = []

    for res in component_results:
        times = res["times"]
        routing_seen = res["routing_seen"]
        errors = res["errors"]

        if not times:
            print(f"  {'(all failed)':<30} {res['component_id']:<12} {'—':<18}  all {reps} reps errored")
            continue

        all_times.extend(times)
        for r in routing_seen:
            routing_counts[r] += 1

        p50 = _pct(times, 50)
        p95 = _pct(times, 95)
        p99 = _pct(times, 99)
        mx = max(times)
        routing_str = ", ".join(
            f"{k}:{v}"
            for k, v in sorted({r: routing_seen.count(r) for r in set(routing_seen)}.items())
        )
        err_note = f"  [{errors} err]" if errors else ""
        flt = "yes" if res.get("filtered_applied") else "—"
        print(
            f"  {res['label'][:30]:<30} {res['component_id']:<12} {str(res['visu_type'])[:14]:<14} {flt:<4}"
            f"  {_fmt(p50)}  {_fmt(p95)}  {_fmt(p99)}  {_fmt(mx)}  {routing_str}{err_note}"
        )

    # ── summary ──────────────────────────────────────────────────────────────
    print("\n[3/3] Summary\n")
    total = sum(routing_counts.values())
    if total:
        for path, cnt in sorted(routing_counts.items()):
            print(f"  Celery path '{path}': {cnt}/{total} ({cnt/total:.0%})")
    if all_times:
        print(f"\n  Overall across all components ({len(all_times)} samples):")
        print(f"    mean = {_fmt(statistics.mean(all_times))}")
        print(f"    p50  = {_fmt(_pct(all_times, 50))}")
        print(f"    p95  = {_fmt(_pct(all_times, 95))}")
        print(f"    p99  = {_fmt(_pct(all_times, 99))}")
        print(f"    max  = {_fmt(max(all_times))}")

    print("\n  Branch: perf/combined (gb-dataframe-optimizations + column-projection-schema-cache)")
    print("  Save this output as the WITH-PERF baseline before switching to unoptimized stack.\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Depictio render-figure latency benchmark")
    parser.add_argument("--url", default=_discover_api_url(), help="API base URL")
    parser.add_argument("--reps", type=int, default=100, help="Requests per component")
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="Max in-flight requests PER component (default 1 = steady-state "
             "per-render latency). Raise it to load-test: e.g. 10 drives ~10x "
             "components simultaneously and measures the saturation/queue ceiling, "
             "not per-render cost.",
    )
    parser.add_argument("--token", default="", help="Bearer JWT (skip auto-login)")
    _default_email, _default_password = _discover_credentials()
    parser.add_argument("--email", default=_default_email)
    parser.add_argument("--password", default=_default_password)
    parser.add_argument("--theme", default="light", choices=["light", "dark"])
    parser.add_argument(
        "--filtered", action="store_true",
        help="WARM mode: warm caches, then each rep applies a different RangeSlider "
             "value (simulates interactive filter drags / the filter-column-union path)",
    )
    parser.add_argument(
        "--warmup", type=int, default=5,
        help="Discarded warm-up reps per component before measuring (default 5)",
    )
    args = parser.parse_args()

    print(
        f"\nDepictio render-figure benchmark  →  {args.url}"
        f"  ({args.reps} reps × {args.concurrency} concurrency per component"
        f"{', WARM+filter' if args.filtered else ''})"
    )

    token = args.token
    if not token:
        print("\n[0/3] Logging in …")
        token = get_token(args.url, args.email, args.password)

    asyncio.run(run_benchmark(
        args.url, token, args.reps, args.concurrency, args.theme, args.filtered, args.warmup
    ))


if __name__ == "__main__":
    main()
