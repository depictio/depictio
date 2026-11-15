"""Live end-to-end check of the notebook export (needs a running stack).

For each dashboard given (by id, or ``penguins`` / ``ampliseq`` for the seeded
ones), this script:

1. exports the Quarto document through the API with a state made of the
   dashboard's first two interactive filters (each set to its first two values);
2. checks that every ``{python}`` chunk parses;
3. with ``--run``, executes the chunks top to bottom (as Quarto would) against the
   API with the given token and compares every stage's ``df.height`` with
   ``POST /dashboards/funnel_values``;
4. prints the ``quarto render`` command to run by hand.

Usage::

    DEPICTIO_API_URL=http://localhost:8058 DEPICTIO_API_TOKEN=... \
        uv run python depictio/dev_scripts/verify_notebook_export.py --dashboard penguins --out /tmp/nb
"""

from __future__ import annotations

import argparse
import ast
import os
import re
from pathlib import Path

import httpx

_CHUNK_RE = re.compile(r"^(`{3,})\{python\}\n(.*?)\n\1$", re.S | re.M)

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
        qmd_path = out_dir / f"{stem}.qmd"
        source = client.notebook(dashboard_id, state, save_to=qmd_path)
        print(f"   wrote {qmd_path}")

        chunks = [m.group(2) for m in _CHUNK_RE.finditer(source)]
        broken = []
        for i, chunk in enumerate(chunks):
            try:
                ast.parse(chunk)
            except SyntaxError as exc:
                broken.append(f"chunk {i}: {exc}")
        print(f"   {len(chunks)} python chunks: {'ok' if not broken else 'FAILED'}")
        for line in broken:
            print(f"     {line}")
        failures += len(broken)

        if args.run:
            oracle = httpx.post(
                f"{client.base_url}/depictio/api/v1/dashboards/funnel_values/{dashboard_id}",
                json={"filters": filters, "target_indexes": [], "include_stages": True},
                headers={"Authorization": f"Bearer {client.token}"},
                timeout=300,
            ).json()
            defs: dict = {"__name__": f"nb_{stem}"}
            for i, chunk in enumerate(chunks):
                exec(compile(chunk, f"<{stem} chunk {i}>", "exec"), defs)  # noqa: S102
            for k, stage in enumerate(oracle.get("stages") or [], start=1):
                for dc_id, rows in (stage.get("rows_by_dc") or {}).items():
                    name = next((n for n in defs if n.startswith(f"stage_{k}_")), None)
                    got = defs[name].height if name else None
                    status = "ok" if got == rows else "MISMATCH"
                    if got != rows:
                        failures += 1
                    print(f"   stage {k} {dc_id[-6:]}: notebook={got} funnel={rows} {status}")

        print(f"   next: quarto render {qmd_path}")

    print("\nall good" if failures == 0 else f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    os.environ.setdefault("DEPICTIO_CONTEXT", "client")
    raise SystemExit(main())
