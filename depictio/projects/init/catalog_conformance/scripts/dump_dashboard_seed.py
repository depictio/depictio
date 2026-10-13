"""Build the conformance dashboard's boot seed from its YAML.

    venv/bin/python -m depictio.projects.init.catalog_conformance.scripts.dump_dashboard_seed

Run after editing `dashboards/overview.yaml`. A thin entry point kept at its
original path; the work happens in the shared offline generator, which builds
this seed the same way it builds the two showcase projects'.

This used to dump the document out of MongoDB after a real
`depictio dashboard import`, on the argument that the importer does things to a
component that an offline build would have to reimplement. That argument does
not hold for *this* board: it writes no `use:` catalog binding — every tile
declares its own `component_type` and config — so `DashboardDataLite.to_full()`
produces the same document, field for field. Rebuilding it from a real import
was verified to differ only in the runtime bindings the generator injects
anyway (`wf_id` / `dc_id` / `dc_config`) and in envelope fields.

What the dump path did cost: the conformance project is opt-in
(`DEPICTIO_SEED_EXTRA_PROJECTS`), so regenerating this seed required a machine
that had seeded it *and* materialised its Delta tables. Editing the YAML on any
other machine meant not being able to ship the change.

The dashboard id comes from `dashboards/overview.yaml` and is cross-checked
against `static_ids.json`, so a reseed updates the dashboard in place instead of
accumulating copies.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from depictio.dev_scripts.generate_dashboard_seeds import generate  # noqa: E402

if __name__ == "__main__":
    generate("catalog_conformance")
