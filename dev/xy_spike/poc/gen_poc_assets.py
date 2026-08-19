"""Build the PoC's chart payload from data loaded through the real read path.

Uses the 100k-row Delta table (direct tier -> browser-local selection works)
via load_deltatable_lite, then Figure.build_payload() — the exact server-side
flow a real integration endpoint would run.

Run:  venv/bin/python dev/xy_spike/poc/gen_poc_assets.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

POC = Path(__file__).parent
SPIKE = POC.parent
REPO = SPIKE.parent.parent

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SPIKE))

import _env  # noqa: E402, F401

X, Y, SEL = "bill_length_mm", "bill_depth_mm", "individual_id"


def main() -> None:
    import xy
    from bson import ObjectId

    from depictio.api.v1 import deltatables_utils

    deltatables_utils._get_aggregation_version = lambda _dc: None  # no Mongo here

    path = SPIKE / "data" / "points_100000"
    dc_id = "64b000000000000000000100"
    df = deltatables_utils.load_deltatable_lite(
        ObjectId("64b0000000000000000000aa"),
        dc_id,
        init_data={dc_id: {"delta_location": str(path), "dc_type": "Table", "size_bytes": 1}},
        select_columns=[X, Y, SEL],
    )
    ch = xy.chart(
        xy.scatter(df[X].to_numpy(), df[Y].to_numpy()),
        xy.interaction_config(hover=True, click=True, select=True, brush=True),
    )
    spec, blob = ch.figure().build_payload()
    (POC / "poc_spec.json").write_text(json.dumps(spec))
    (POC / "poc_blob.bin").write_bytes(blob)
    (POC / "poc_ids.json").write_text(json.dumps(df[SEL].to_list()))
    shutil.copy(Path(xy.__file__).parent / "static/standalone.js", POC / "standalone.js")
    print(f"poc assets: {df.height} rows, blob {len(blob)} bytes")


if __name__ == "__main__":
    main()
