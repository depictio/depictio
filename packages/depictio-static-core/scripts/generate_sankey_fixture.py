"""Regenerate fixtures/sankey-expected.json (sankeyFromColumns parity).

Runs the server's own ``_sankey_result_from_frame`` (depictio/api/v1/
celery_tasks.py — the post-load half of the ``compute_sankey`` task) over a
small synthetic flow table, for a set of requests, and writes the inputs and
the answers for ``test/sankey.test.ts``:

    uv run --extra dev python \\
        packages/depictio-static-core/scripts/generate_sankey_fixture.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Same defaults as the test suite's conftest (depictio/tests/conftest.py), so
# the script imports the app settings without a pre-wired environment.
os.environ.setdefault("DEPICTIO_CONTEXT", "server")
os.environ.setdefault("DEPICTIO_S3_ROOT_PASSWORD", "pytest_s3_password_aaaaaaaaaaaaa")
os.environ.setdefault("DEPICTIO_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD", "pytest_admin_password_aaaaaaaaaa")
os.environ.setdefault("DEPICTIO_BOOTSTRAP_SEED_TEST_USER", "true")
os.environ.setdefault("DEPICTIO_BOOTSTRAP_TEST_USER_PASSWORD", "test_pwd")
os.environ.setdefault("DEPICTIO_VERSION_CHECK_ENABLED", "false")
os.environ.setdefault("DEPICTIO_NOTEBOOK_EXPORT_ENABLED", "true")
os.environ.setdefault("DEPICTIO_STATIC_EXPORT_ENABLED", "true")

import polars as pl  # noqa: E402

from depictio.api.v1.celery_tasks import _sankey_result_from_frame  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "packages/depictio-static-core/fixtures/sankey-expected.json"

# A synthetic categorical flow: the edge cases the coercion, the weights and
# the sort modes have opinions about live in the frame itself — a NULL and an
# empty string in the same step column, a NULL weight, an option column wider
# than the steps, and a second cohort to mask on.
FRAME = pl.DataFrame(
    [
        ("prep", "lib_a", "seq_a", 10, "tumor"),
        ("prep", "lib_a", "seq_b", 4, "tumor"),
        ("prep", "lib_b", "seq_a", 6, "normal"),
        ("qc", "lib_a", "seq_b", 3, "tumor"),
        ("qc", "lib_b", "seq_a", 8, "normal"),
        (None, "lib_b", "seq_b", 2, "normal"),
        ("", "lib_a", "seq_a", 5, "tumor"),
        ("prep", None, "seq_b", 7, "normal"),
        ("prep", "lib_b", None, None, "tumor"),
        ("qc", "", "seq_a", 1, "normal"),
        ("prep", "lib_a", "seq_a", 9, "tumor"),
        ("qc", "lib_b", "seq_b", 2, "normal"),
    ],
    schema=["stage1", "stage2", "stage3", "reads", "cohort"],
    orient="row",
)

MASKS = {
    # A dashboard filter on the collection: only the tumour rows reach the
    # compute, like the server's filter_metadata load mask.
    "cohort_tumor": [1 if c == "tumor" else 0 for c in FRAME["cohort"].to_list()],
}

STEPS_2 = ["stage1", "stage2"]
STEPS_3 = ["stage1", "stage2", "stage3"]

# (name, request, mask name or None)
CASES = [
    # Row counts as weights (value_col null), both single-step sorts.
    (
        "row-count weights, alphabetical",
        {
            "step_cols": STEPS_2,
            "value_col": None,
            "sort_mode": "alphabetical",
            "min_link_value": 0.0,
            "step_filters": {},
            "option_cols": None,
        },
        None,
    ),
    (
        "row-count weights, input order",
        {
            "step_cols": STEPS_2,
            "value_col": None,
            "sort_mode": "input",
            "min_link_value": 0.0,
            "step_filters": {},
            "option_cols": None,
        },
        None,
    ),
    # Weighted by `reads`, total_flow ranking (the renderer's default).
    (
        "weighted, total_flow over three steps",
        {
            "step_cols": STEPS_3,
            "value_col": "reads",
            "sort_mode": "total_flow",
            "min_link_value": 0.0,
            "step_filters": {},
            "option_cols": None,
        },
        None,
    ),
    # Weak links below the cut-off vanish — and with them any node whose every
    # link vanished, so the node list itself narrows.
    (
        "min_link_value drops weak links and their nodes",
        {
            "step_cols": STEPS_2,
            "value_col": "reads",
            "sort_mode": "total_flow",
            "min_link_value": 6.0,
            "step_filters": {},
            "option_cols": None,
        },
        None,
    ),
    # A step filter narrows the flow AFTER the step options were read: the
    # pickers still list every value, the flow only keeps the picked ones.
    (
        "step filter keeps two stage2 values",
        {
            "step_cols": STEPS_2,
            "value_col": "reads",
            "sort_mode": "total_flow",
            "min_link_value": 0.0,
            "step_filters": {"stage2": ["lib_a"]},
            "option_cols": None,
        },
        None,
    ),
    # The pickers' universe is option_cols, wider than the steps themselves.
    (
        "option_cols wider than the steps",
        {
            "step_cols": STEPS_2,
            "value_col": None,
            "sort_mode": "alphabetical",
            "min_link_value": 0.0,
            "step_filters": {},
            "option_cols": ["stage1", "stage2", "stage3"],
        },
        None,
    ),
    # The dashboard-filter mask: only tumour rows reach the compute, so the
    # option lists and the flow both narrow.
    (
        "masked to the tumour cohort",
        {
            "step_cols": STEPS_3,
            "value_col": "reads",
            "sort_mode": "total_flow",
            "min_link_value": 0.0,
            "step_filters": {},
            "option_cols": None,
        },
        "cohort_tumor",
    ),
    # Alphabetical over the masked frame: the (missing) coercion of the NULL /
    # empty rows that survive, with the step filter keyed on a coerced value.
    (
        "masked, alphabetical, step filter on stage3",
        {
            "step_cols": STEPS_3,
            "value_col": "reads",
            "sort_mode": "alphabetical",
            "min_link_value": 0.0,
            "step_filters": {"stage3": ["seq_a", "seq_b"]},
            "option_cols": None,
        },
        "cohort_tumor",
    ),
]


def main() -> None:
    cases = []
    for name, request, mask_name in CASES:
        frame = FRAME if mask_name is None else FRAME.filter(pl.Series(MASKS[mask_name]) == 1)
        out = _sankey_result_from_frame(
            frame,
            step_cols=request["step_cols"],
            value_col=request["value_col"],
            sort_mode=request["sort_mode"],
            min_link_value=request["min_link_value"],
            step_filters=request["step_filters"],
            option_cols=request["option_cols"],
        )
        out.pop("compute_ms")
        cases.append({"name": name, "request": request, "mask": mask_name, "expected": out})
    OUT.write_text(
        json.dumps(
            {
                "columns": {c: FRAME[c].to_list() for c in FRAME.columns},
                "masks": MASKS,
                "cases": cases,
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    print(
        f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.1f} KiB, {FRAME.height} rows)"
    )


if __name__ == "__main__":
    main()
