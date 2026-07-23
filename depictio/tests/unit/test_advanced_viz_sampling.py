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


def _reduce(projection, cap=10_000, **kwargs):
    return routes._load_reduced(
        wf_oid="wf", dc_oid="dc", filter_metadata=None,
        projection=projection, init_data={}, cap=cap, **kwargs,
    )  # fmt: skip


def _call(projection, cap=10_000):
    """``(frame, total, sampled)`` — the uniform-sample path on its own.

    Every test below this line predates the per-kind policy and describes the
    default (no ``viz_kind``) reduction, which is still a uniform hash sample.
    """
    frame, total, sampling = _reduce(projection, cap=cap)
    return frame, total, bool(sampling and sampling["sampled"])


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


# --- Per-kind policy ---------------------------------------------------------
#
# One uniform sample for every kind is right for a marker cloud and wrong for a
# renderer that sums or ranks the rows it is handed. These pin which reduction
# each kind gets and that the pre-policy behaviour is what an absent kind still
# receives.


def test_policy_table_covers_every_kind():
    """A kind with no entry silently degrades to a sample — catch it here."""
    from typing import get_args

    from depictio.models.components.advanced_viz.sampling import KIND_SAMPLING_POLICY, TAIL_ROLE
    from depictio.models.components.types import AdvancedVizKind

    kinds = set(get_args(AdvancedVizKind))
    assert set(KIND_SAMPLING_POLICY) == kinds
    tail_kinds = {k for k, p in KIND_SAMPLING_POLICY.items() if p == "tail"}
    assert set(TAIL_ROLE) == tail_kinds, "every tail kind needs a role to keep the tail of"


def test_an_aggregating_kind_is_never_sampled(patched_scan):
    """Sampling a stacked bar's rows changes its values, not its resolution."""
    n = 200_000
    patched_scan(
        pl.DataFrame({"sample_id": [f"s{i % 500}" for i in range(n)], "abundance": range(n)})
    )

    frame, total, sampling = _reduce(
        ["sample_id", "abundance"], policy="none", viz_kind="stacked_taxonomy"
    )

    assert frame.height == n, "the whole frame, not a sample"
    assert total == n
    assert sampling == {"policy": "none", "exact": True, "sampled": False, "degraded": False}


def test_an_aggregating_kind_past_the_ceiling_says_its_values_are_estimates(
    patched_scan, monkeypatch
):
    """Serving it whole is what the kind needs and what the process can't afford.

    The fallback is a sample, and the response has to say the aggregate is now an
    estimate — a bare "10 000 / 200 000" badge reads as a display cap on a chart
    whose bars are actually off by the sampling stride.
    """
    from depictio.api.v1.configs.config import settings

    monkeypatch.setattr(settings.performance, "advanced_viz_no_sample_max_rows", 1_000)
    n = 200_000
    patched_scan(pl.DataFrame({"row_id": range(n), "v": [float(i % 977) for i in range(n)]}))

    frame, total, sampling = _reduce(["row_id", "v"], policy="none", viz_kind="stacked_taxonomy")

    assert total == n
    assert frame.height < n
    assert sampling["degraded"] is True
    assert sampling["exact"] is False


def test_an_unsamplable_frame_past_the_ceiling_is_still_bounded(patched_scan, monkeypatch):
    """The ceiling exists to bound memory, so its fallback cannot be unbounded.

    A degenerate hash normally drops the caller onto a plain full load, which is
    the right answer when the frame was merely too big to *draw*. Past the
    no-sample ceiling it was too big to *hold*, and the same fallback would
    reintroduce exactly the load the ceiling was protecting against.
    """
    from depictio.api.v1.configs.config import settings

    monkeypatch.setattr(settings.performance, "advanced_viz_no_sample_max_rows", 1_000)
    n = 400_000
    # Two distinct value tuples: the hash can only split all-or-nothing.
    patched_scan(pl.DataFrame({"flag": [i % 2 for i in range(n)]}))

    frame, total, sampling = _reduce(["flag"], policy="none", viz_kind="stacked_taxonomy")

    assert frame is not None, "must not fall through to an unbounded load"
    assert frame.height <= 10_000
    assert total == n
    assert sampling["degraded"] is True


def test_no_viz_kind_still_samples_uniformly(patched_scan):
    """The pre-policy contract: an unannotated caller must not change behaviour."""
    n = 200_000
    patched_scan(pl.DataFrame({"row_id": range(n), "v": [float(i % 977) for i in range(n)]}))

    frame, total, sampling = _reduce(["row_id", "v"])

    assert sampling["policy"] == "hash"
    assert sampling["sampled"] is True
    assert sampling["degraded"] is False
    assert total == n
    assert frame.height < n


# --- Tail-preserving reduction ----------------------------------------------


def _de_frame(n=200_000, hits=40):
    """A DE table: a dense non-significant blob plus a handful of real hits."""
    return pl.DataFrame(
        {
            "feature_id": [f"g{i}" for i in range(n)],
            "effect_size": [float(i % 13) - 6 for i in range(n)],
            # Hits are the first `hits` rows, at p ~ 1e-8; everything else is
            # spread over [0.2, 1.0] and must never be mistaken for a hit.
            "significance": [1e-8 if i < hits else 0.2 + (i % 800) / 1000.0 for i in range(n)],
        }
    )


def test_the_tail_survives_a_reduction_that_would_have_dropped_it(patched_scan):
    """A uniform sample of 10k of 200k keeps ~2 of 40 hits. The tail keeps all 40."""
    patched_scan(_de_frame())
    projection = ["feature_id", "effect_size", "significance"]
    tail = {"column": "significance", "direction": "low", "threshold": 0.05}

    frame, total, sampling = _reduce(projection, policy="tail", viz_kind="volcano", tail=tail)

    assert sampling["policy"] == "tail"
    assert total == 200_000
    kept_hits = frame.filter(pl.col("significance") <= 0.05).height
    assert kept_hits == 40, f"lost {40 - kept_hits} hits the plot exists to show"
    # And it is still a reduction, not a full load dressed up as one.
    assert frame.height <= 10_000 * 4


def test_the_tail_is_sampled_rather_than_truncated_when_it_is_the_whole_table(patched_scan):
    """A threshold that isn't selecting must not blow the cap open."""
    n = 200_000
    patched_scan(
        pl.DataFrame(
            {
                "feature_id": [f"g{i}" for i in range(n)],
                # Everything is "significant" — a mis-set threshold, or a table
                # that was already filtered upstream.
                "significance": [1e-9 + i * 1e-12 for i in range(n)],
            }
        )
    )
    tail = {"column": "significance", "direction": "low", "threshold": 0.05}

    frame, total, sampling = _reduce(
        ["feature_id", "significance"], policy="tail", viz_kind="volcano", tail=tail
    )

    assert total == n
    assert frame.height <= 10_000 * 4, "an unselective tail must still be reduced"
    assert sampling["policy"] == "tail"


def test_a_signed_effect_keeps_both_ends(patched_scan):
    """An MA plot's hits are large |log2FC| in either direction."""
    n = 120_000
    patched_scan(
        pl.DataFrame(
            {
                "feature_id": [f"g{i}" for i in range(n)],
                # 20 strongly up, 20 strongly down, the rest inside ±0.5.
                "log2fc": [
                    5.0 if i < 20 else -5.0 if i < 40 else ((i % 100) - 50) / 100.0
                    for i in range(n)
                ],
            }
        )
    )
    tail = {"column": "log2fc", "direction": "both", "threshold": 1.0}

    frame, _, _ = _reduce(["feature_id", "log2fc"], policy="tail", viz_kind="ma", tail=tail)

    assert frame.filter(pl.col("log2fc") >= 1.0).height == 20
    assert frame.filter(pl.col("log2fc") <= -1.0).height == 20


def test_rows_with_no_significance_are_sampled_not_dropped(patched_scan):
    """`~(null <= t)` is null, which would filter nulls out of *both* branches."""
    n = 100_000
    patched_scan(
        pl.DataFrame(
            {
                "feature_id": [f"g{i}" for i in range(n)],
                "significance": [None if i % 2 else 0.9 - (i % 700) / 1000.0 for i in range(n)],
            }
        )
    )
    tail = {"column": "significance", "direction": "low", "threshold": 0.05}

    frame, _, _ = _reduce(
        ["feature_id", "significance"], policy="tail", viz_kind="volcano", tail=tail
    )

    assert frame["significance"].null_count() > 0, "null-significance rows vanished entirely"


def test_a_tail_kind_with_no_usable_column_falls_back_to_a_uniform_sample(patched_scan):
    """An unbound role is a binding problem, not a reason to return nothing."""
    n = 200_000
    patched_scan(pl.DataFrame({"row_id": range(n), "v": [float(i % 977) for i in range(n)]}))

    frame, total, sampling = _reduce(["row_id", "v"], policy="tail", viz_kind="volcano", roles={})

    assert sampling["policy"] == "hash"
    assert total == n
    assert frame.height < n


def test_the_declared_direction_is_read_off_the_column_range(patched_scan):
    """Volcano's significance arrives as a p-value or as its -log10, per pipeline.

    With no tail spec from the client, the range decides: a column that leaves
    [0, 1] is a -log10 score, so the tail is its *large* end.
    """
    n = 150_000
    patched_scan(
        pl.DataFrame(
            {
                "feature_id": [f"g{i}" for i in range(n)],
                # 30 hits at -log10(p) = 8; the rest below 1.
                "significance": [8.0 if i < 30 else (i % 900) / 1000.0 for i in range(n)],
            }
        )
    )

    frame, _, sampling = _reduce(
        ["feature_id", "significance"],
        policy="tail",
        viz_kind="volcano",
        roles={"significance": "significance"},
    )

    assert sampling["policy"] == "tail"
    assert frame.filter(pl.col("significance") >= 8.0).height == 30
