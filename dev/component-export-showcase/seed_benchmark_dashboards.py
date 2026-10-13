#!/usr/bin/env python3
"""Import the variantbenchmarking demo dashboards into this instance.

The four benchmarking dashboards ship as YAML under
``depictio/projects/init/advanced_viz_showcase/dashboards/`` rather than as
``.db_seeds/*.json``, so ``db_init`` does not create them and the export API has
nothing to serve. This posts them through the same ``/dashboards/import/yaml``
route the UI's Import tab uses.

Idempotent: ``overwrite=true`` updates a dashboard of the same title instead of
creating duplicates, so re-running after editing a YAML does the right thing.

    python seed_benchmark_dashboards.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import showcase_lib as s  # noqa: E402

DASHBOARD_DIR = (
    s.REPO_ROOT / "depictio" / "projects" / "init" / "advanced_viz_showcase" / "dashboards"
)


def import_yaml(path: Path, token: str) -> dict:
    url = f"{s.api_base()}/dashboards/import/yaml?overwrite=true"
    request = urllib.request.Request(
        url,
        data=path.read_bytes(),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def main() -> int:
    token = s.admin_token()
    candidates = sorted(p for p in DASHBOARD_DIR.glob("benchmark_*.yaml"))
    if not candidates:
        print(f"No benchmark_*.yaml under {DASHBOARD_DIR}")
        return 1

    print(f"API  {s.api_base()}\n")
    failures = 0
    for path in candidates:
        try:
            result = import_yaml(path, token)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            print(f"  {path.name:28} FAILED {exc.code}  {detail}")
            failures += 1
            continue
        dashboard_id = result.get("dashboard_id") or result.get("_id") or "?"
        print(f"  {path.name:28} -> {dashboard_id}")

    print(f"\n{len(candidates) - failures}/{len(candidates)} imported")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
