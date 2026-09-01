"""Live end-to-end check of the notebook export (needs a running stack).

For each dashboard given (by id, or ``penguins`` / ``ampliseq`` for the seeded
ones), this script:

1. exports the marimo notebook through the API with a state made of the
   dashboard's first two interactive filters (each set to its first two values);
2. runs ``marimo check --strict`` on it and derives the ``.ipynb`` and the
   Quarto variant;
3. executes the notebook (``App.run()``) against the API with the given token and
   compares every stage's ``df.height`` with ``POST /dashboards/funnel_values``;
4. prints the ``quarto render`` command to run by hand.

Usage::

    DEPICTIO_API_URL=http://localhost:8058 DEPICTIO_API_TOKEN=... \
        uv run python depictio/dev_scripts/verify_notebook_export.py --dashboard penguins --out /tmp/nb
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import httpx

SEEDED = {
    "penguins": "6824cb3b89d2b72169309738",
    "penguins_island_season": "6a75a191f5e6ff34386c8f0c",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dashboard", action="append", required=True, help="dashboard id or seeded alias"
    )
    parser.add_argument("--out", default="/tmp/depictio-notebooks")
    parser.add_argument("--run", action="store_true", help="execute the notebook against the API")
    args = parser.parse_args()

    from depictio.notebook import DepictioClient

    client = DepictioClient()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0

    for ref in args.dashboard:
        dashboard_id = SEEDED.get(ref, ref)
        doc = client.dashboard(dashboard_id)
        title = doc.get("title")
        print(f"\n== {title} ({dashboard_id})")
        interactive = [
            m for m in doc.get("stored_metadata") or [] if m.get("component_type") == "interactive"
        ]
        filters = []
        for meta in interactive[:2]:
            column = meta.get("column_name")
            itype = meta.get("interactive_component_type")
            if itype in ("Select", "MultiSelect", "SegmentedControl"):
                values = client.unique_values(str(meta.get("dc_id")), column)[:2]
                if values:
                    filters.append(client.filter(dashboard_id, str(meta.get("index")), values))
        state = client.state(dashboard_id, filters=filters)
        print(f"   filters: {[(f['column_name'], f['value']) for f in filters]}")

        pre = client.preflight(dashboard_id, state)
        print(f"   preflight: {pre.get('counts')}")

        stem = "".join(c if c.isalnum() else "_" for c in str(title).lower()).strip("_")
        py_path = out_dir / f"{stem}.py"
        client.notebook(dashboard_id, state, "marimo", save_to=py_path)
        client.notebook(dashboard_id, state, "ipynb", save_to=out_dir / f"{stem}.ipynb")
        client.notebook(dashboard_id, state, "quarto", save_to=out_dir / f"{stem}.quarto.ipynb")
        print(f"   wrote {py_path}, .ipynb and .quarto.ipynb")

        check = subprocess.run(
            [sys.executable, "-m", "marimo", "check", "--strict", str(py_path)],
            capture_output=True,
            text=True,
        )
        print(f"   marimo check: {'ok' if check.returncode == 0 else 'FAILED'}")
        if check.returncode != 0:
            print(check.stdout, check.stderr)
            failures += 1

        if args.run:
            oracle = httpx.post(
                f"{client.base_url}/depictio/api/v1/dashboards/funnel_values/{dashboard_id}",
                json={"filters": filters, "target_indexes": [], "include_stages": True},
                headers={"Authorization": f"Bearer {client.token}"},
                timeout=300,
            ).json()
            spec = importlib.util.spec_from_file_location(f"nb_{stem}", py_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _outputs, defs = module.app.run()
            for k, stage in enumerate(oracle.get("stages") or [], start=1):
                for dc_id, rows in (stage.get("rows_by_dc") or {}).items():
                    name = next((n for n in defs if n.startswith(f"stage_{k}_")), None)
                    got = defs[name].height if name else None
                    status = "ok" if got == rows else "MISMATCH"
                    if got != rows:
                        failures += 1
                    print(f"   stage {k} {dc_id[-6:]}: notebook={got} funnel={rows} {status}")

        print(f"   next: quarto render {out_dir / (stem + '.quarto.ipynb')}")

    print("\nall good" if failures == 0 else f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    os.environ.setdefault("DEPICTIO_CONTEXT", "client")
    raise SystemExit(main())
