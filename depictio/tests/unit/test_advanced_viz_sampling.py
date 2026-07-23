"""Scan-level sampling for the advanced-viz ``/data`` endpoint.

The endpoint used to cap the scan at 100 000 rows and then ``df.sample()`` the
result. Polars pushes that cap into the scan, and Delta scan order is ingest
order, so the "sample" was drawn from a *prefix* — on the 1 GB benchmark DC that
prefix contained 3 of the dataset's 500 samples. Sampling it afterwards dressed
a biased subset up as a random one, and ``total_rows`` was measured after the
cap, so the badge reported "10 000 of 100 000" for a 17 M-row table.

These tests pin the properties that broke: the sample spans the whole frame, the
reported total is the pre-sample count, and a projection whose value tuples are
too coarse to hash cleanly falls back instead of returning a thinned frame.
"""

import polars as pl
import pytest

from depictio.api.v1.endpoints.advanced_viz_endpoints import routes


@pytest.fixture
def patched_scan(monkeypatch):
    """Install a LazyFrame in place of the Delta scan the helper would open."""

    def _install(frame: pl.DataFrame | None):
        def fake_open(**kwargs):
            return None if frame is None else frame.lazy().select(kwargs["select_columns"])

        monkeypatch.setattr("depictio.api.v1.deltatables_utils.open_deltatable_scan", fake_open)

    return _install


def _call(projection, cap=10_000):
    return routes._load_uniform_sample(
        wf_oid="wf", dc_oid="dc", filter_metadata=None,
        projection=projection, init_data={}, cap=cap,
    )  # fmt: skip


def test_sample_spans_the_whole_frame_not_a_prefix(patched_scan):
    """The regression this replaced: a prefix looks like a sample but isn't.

    ``row_id`` is monotonic, so a prefix would return only small values. A
    uniform sample must reach the far end of the frame.
    """
    n = 500_000
    patched_scan(pl.DataFrame({"row_id": range(n), "v": [float(i % 977) for i in range(n)]}))

    frame, total, sampled = _call(["row_id", "v"])

    assert sampled is True
    assert total == n
    ids = frame["row_id"].to_list()
    assert max(ids) > 0.95 * n, "sample never reached the end of the frame — still a prefix"
    assert min(ids) < 0.05 * n
    # Spread across the whole range, not clustered at either end.
    assert 0.4 * n < sum(ids) / len(ids) < 0.6 * n


def test_sample_keeps_every_category(patched_scan):
    """Hashing a struct of all projected columns keeps the decision per-row.

    Hashing one column instead would take whole categories in or out — the
    failure mode that would empty a volcano's rarest class.
    """
    n = 300_000
    patched_scan(
        pl.DataFrame(
            {
                "row_id": range(n),
                # 'rare' is 1 row in 1000; a per-value hash would drop it wholesale.
                "cls": ["rare" if i % 1000 == 0 else f"c{i % 7}" for i in range(n)],
            }
        )
    )

    frame, _, sampled = _call(["row_id", "cls"])

    assert sampled is True
    assert "rare" in set(frame["cls"].to_list())


def test_total_rows_is_the_pre_sample_count(patched_scan):
    """The badge's "of M" half must describe the table, not the response."""
    n = 250_000
    patched_scan(pl.DataFrame({"row_id": range(n)}))

    frame, total, sampled = _call(["row_id"], cap=1_000)

    assert total == n
    assert sampled is True
    assert frame.height < n


def test_small_frames_are_returned_whole(patched_scan):
    """Below the cap there is nothing to reduce — and nothing to flag."""
    patched_scan(pl.DataFrame({"row_id": range(300)}))

    frame, total, sampled = _call(["row_id"])

    assert sampled is False
    assert total == 300
    assert frame.height == 300


@pytest.mark.parametrize("n_distinct", [1, 2, 3])
def test_a_degenerate_hash_split_falls_back(patched_scan, n_distinct):
    """Few distinct value tuples ⇒ the modulus becomes all-or-nothing per tuple.

    ``struct(cols).hash() % stride`` decides per distinct value tuple, not per
    row. With a handful of tuples over hundreds of thousands of rows the split
    degenerates in one of two directions, and *both* are wrong:

    * every tuple hashes non-zero → a near-empty frame, i.e. a plot drawn from
      nothing while claiming to summarise millions of rows;
    * one tuple hashes to zero → that tuple's entire population comes back, so
      the response is a large multiple of the cap *and* is a single category
      rather than a cross-section.

    Which direction a given value falls in is a property of the hash, so this is
    parametrised over several shapes rather than relying on one landing a
    particular way.
    """
    n = 400_000
    patched_scan(pl.DataFrame({"flag": [i % n_distinct for i in range(n)]}))

    frame, total, sampled = _call(["flag"])

    assert frame is None, "a degenerate split must not be returned as a sample"
    assert total is None
    assert sampled is False


def test_an_unavailable_scan_falls_back(patched_scan):
    """``open_deltatable_scan`` returning None must not raise — just fall back."""
    patched_scan(None)

    assert _call(["row_id"]) == (None, None, False)
