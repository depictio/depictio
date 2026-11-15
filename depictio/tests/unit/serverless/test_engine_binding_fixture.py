"""The engine fixture's filter-binding and card-parity sections track the server.

``packages/depictio-static-core/fixtures/engine-expected.json`` carries, for a
set of viewer filter payloads, the rows the SERVER keeps
(``clean_filter_payload`` → ``process_metadata_and_filter``) and the card
aggregations ``_agg_value`` returns for q1/q3/percentile/skewness/kurtosis. The
vitest suite holds the TypeScript binder and kernels to those numbers; this test
holds the numbers to the server, so a change to ``add_filter`` (a new text mode,
another slider default) fails here instead of leaving the bundle silently
behind. It also checks that the ``__fe__`` companions the fixture ships are what
``build_filter_expr`` computes over the same rows.

Floats compare to within rounding: Polars sums partitions in parallel, so the
last bit of a sum can move between runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[4]
FIXTURES = REPO / "packages" / "depictio-static-core" / "fixtures"
EXPECTED = json.loads((FIXTURES / "engine-expected.json").read_text())


def _frames() -> tuple[pl.DataFrame, pl.DataFrame]:
    full = pl.read_parquet(FIXTURES / "engine-fixture.parquet")
    base = full.drop([c for c in EXPECTED["companions"] if c in full.columns])
    return full, base


def _close(a, w) -> bool:
    if isinstance(w, float) and isinstance(a, float):
        return a == pytest.approx(w, rel=1e-9, abs=1e-12)
    return a == w


@pytest.mark.parametrize("name", sorted(EXPECTED["binding"]))
def test_binding_case_matches_the_server(name):
    from depictio.api.v1.deltatables_utils import clean_filter_payload, process_metadata_and_filter

    _, base = _frames()
    case = EXPECTED["binding"][name]
    exprs = process_metadata_and_filter(
        clean_filter_payload(case["filters"]), schema=dict(base.schema)
    )
    kept = base.filter(pl.all_horizontal(exprs)) if exprs else base
    assert kept.height == case["matched"], name
    total = kept["value_f64"].sum()
    assert _close(float(total) if total is not None else 0.0, case["value_f64_sum"]), name


def test_parity_aggregations_match_agg_value():
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _agg_value

    _, base = _frames()
    masked = base.filter(pl.col("category_str").is_in(["alpha", "beta"]))
    frames = {"full": base, "masked_in_str": masked, "empty": base.head(0), "tiny": base.head(3)}
    for block, frame in frames.items():
        for col, aggs in EXPECTED["aggregates_parity"][block].items():
            for agg, want in aggs.items():
                got = _agg_value(frame[col], agg)
                assert _close(got, want), (block, col, agg, got, want)


def test_filter_expr_companions_are_build_filter_expr():
    from depictio.models.components.filter_expr import build_filter_expr

    full, base = _frames()
    fe = {k: v for k, v in EXPECTED["companions"].items() if k.startswith("__fe__")}
    assert fe, "the fixture must carry __fe__ companions"
    for name, expr in fe.items():
        want = base.select(build_filter_expr(expr).fill_null(False)).to_series().to_list()
        assert full[name].to_list() == want, expr
