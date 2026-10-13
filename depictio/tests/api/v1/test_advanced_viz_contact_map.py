"""Choosing a resolution, and cutting a window out of a Hi-C matrix.

The contact-map window endpoint is the only advanced-viz route that decides
*what data to read* from a number the client sends (the visible span and how
many pixels it has to draw it in). Get that wrong and the tile is either a
blurry 8-bin square or a 40 MB download, and both look like a rendering bug
rather than a routing one, so the arithmetic is pinned here.

Two levels, mirroring `test_advanced_viz_group_compare.py`: the pure functions
against spans whose right answer is known by construction, and the endpoint
against the contract Celery cannot defend itself from (a payload naming no
columns would fail inside the worker and surface as a cached failure, not a
400).
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.api.v1.services.contact_map import (
    DEFAULT_BINS_PER_PIXEL,
    DEFAULT_RESOLUTION_COLUMN,
    apply_window,
    choose_resolution,
    coarsest_within_budget,
    resolve_resolution_column,
    summarise,
    window_expr,
)

MEGATEST_LEVELS = [500_000, 1_000_000]
DERIVED_LEVELS = [500_000, 1_000_000, 2_000_000, 4_000_000]


# ---------------------------------------------------------------------------
# Which resolution
# ---------------------------------------------------------------------------


def test_a_whole_chromosome_opens_on_the_coarsest_level() -> None:
    """Mouse chr1 is 195 Mb. At 500 kb that is 390 bins per side and 76k cells
    for a tile 800 px wide; 1 Mb is the level that fits the screen."""
    assert choose_resolution(MEGATEST_LEVELS, 195_000_000, pixels=800) == 1_000_000


def test_zooming_to_a_few_megabases_picks_the_fine_level() -> None:
    assert choose_resolution(MEGATEST_LEVELS, 4_000_000, pixels=800) == 500_000


def test_with_no_span_the_coarsest_level_wins() -> None:
    """No region filter has reached the tile yet: the opening view is the whole
    contig, which is the cheapest level's job."""
    assert choose_resolution(DERIVED_LEVELS, None, pixels=800) == 4_000_000
    assert choose_resolution(DERIVED_LEVELS, float("inf"), pixels=800) == 4_000_000


def test_closeness_is_measured_in_log_space() -> None:
    """Halving and doubling the ideal bin size are equally wrong. With an ideal
    of exactly 1 Mb between a 500 kb and a 2 Mb level, the tie goes to the
    coarser one, which is the cheaper read."""
    span = 1_000_000 * 800 * DEFAULT_BINS_PER_PIXEL
    assert choose_resolution([500_000, 2_000_000], span, pixels=800) == 2_000_000


def test_a_wider_tile_earns_a_finer_level() -> None:
    """Same region, more pixels to draw it in: more bins are readable."""
    narrow = choose_resolution(DERIVED_LEVELS, 100_000_000, pixels=200)
    wide = choose_resolution(DERIVED_LEVELS, 100_000_000, pixels=1600)
    assert wide < narrow


def test_no_resolutions_at_all_means_no_choice() -> None:
    assert choose_resolution([], 1_000_000, pixels=800) is None
    assert choose_resolution([0, -1], 1_000_000, pixels=800) is None


# ---------------------------------------------------------------------------
# The cell budget
# ---------------------------------------------------------------------------


def test_a_level_too_fine_for_the_window_steps_coarser_rather_than_truncating() -> None:
    """A 195 Mb view at 500 kb is 76k cells. Truncating it would draw a
    complete-looking matrix of the first corner of the chromosome."""
    assert (
        coarsest_within_budget(DERIVED_LEVELS, 500_000, 195_000_000, max_cells=40_000) == 1_000_000
    )


def test_a_level_that_already_fits_is_left_alone() -> None:
    assert coarsest_within_budget(DERIVED_LEVELS, 500_000, 4_000_000, max_cells=40_000) == 500_000


def test_the_budget_never_steps_finer_than_the_chosen_level() -> None:
    """The budget is a ceiling, not a second opinion on sharpness."""
    got = coarsest_within_budget(DERIVED_LEVELS, 2_000_000, 4_000_000, max_cells=40_000)
    assert got == 2_000_000


def test_a_single_fine_level_with_nothing_coarser_stays_put() -> None:
    assert coarsest_within_budget([500_000], 500_000, 195_000_000, max_cells=40_000) == 500_000


# ---------------------------------------------------------------------------
# Which column
# ---------------------------------------------------------------------------


def test_the_recipes_own_column_is_found_without_being_declared() -> None:
    """A dashboard YAML written before multi-resolution existed still zooms."""
    assert resolve_resolution_column(["chrom1", "start1", "resolution"], None) == (
        DEFAULT_RESOLUTION_COLUMN
    )


def test_a_declared_column_wins_when_it_exists() -> None:
    assert resolve_resolution_column(["chrom1", "bin_size", "resolution"], "bin_size") == "bin_size"


def test_a_declared_column_that_is_not_there_falls_back() -> None:
    assert resolve_resolution_column(["chrom1", "resolution"], "bin_size") == "resolution"


def test_a_flat_dc_has_no_resolution_column() -> None:
    """The backward-compatible path: no column, no partition, today's tile."""
    assert resolve_resolution_column(["chrom1", "start1", "count"], None) is None


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


def _matrix(resolution: int = 1_000_000, n: int = 8, chrom: str = "chr1") -> pl.DataFrame:
    rows = [
        (
            chrom,
            i * resolution,
            (i + 1) * resolution,
            chrom,
            j * resolution,
            (j + 1) * resolution,
            1.0,
        )
        for i in range(n)
        for j in range(i, n)
    ]
    return pl.DataFrame(
        rows,
        schema=["chrom1", "start1", "end1", "chrom2", "start2", "end2", "count"],
        orient="row",
    )


def _window(df: pl.DataFrame, chrom, start, end, resolution=1_000_000, ends=True) -> pl.DataFrame:
    return apply_window(
        df,
        chrom1_col="chrom1",
        start1_col="start1",
        chrom2_col="chrom2",
        start2_col="start2",
        end1_col="end1" if ends else None,
        end2_col="end2" if ends else None,
        chrom=chrom,
        start=start,
        end=end,
        resolution=resolution,
    )


def test_a_window_is_square_not_a_stripe() -> None:
    """Both axes are cut, so what comes back is a submatrix. Cutting only the
    row axis returns every column the region ever contacts, which for a whole
    chromosome is the thing the window was meant to avoid."""
    out = _window(_matrix(), "chr1", 2_000_000, 5_000_000)

    assert set(out["start1"].to_list()) <= {2_000_000, 3_000_000, 4_000_000}
    assert set(out["start2"].to_list()) <= {2_000_000, 3_000_000, 4_000_000}


def test_the_bin_straddling_the_left_edge_is_kept() -> None:
    """A bin is kept when it overlaps the window, not when its start is inside
    it. Dropping it leaves a notch at the start of every zoomed view."""
    out = _window(_matrix(), "chr1", 2_500_000, 5_000_000)

    assert 2_000_000 in out["start1"].to_list()


def test_the_resolution_stands_in_for_a_missing_end_column() -> None:
    """`end1_col` / `end2_col` are optional on the config, so the straddling
    bin has to be recognised from the bin width instead."""
    no_ends = _matrix().drop(["end1", "end2"])
    out = _window(no_ends, "chr1", 2_500_000, 5_000_000, ends=False)

    assert 2_000_000 in out["start1"].to_list()


def test_another_chromosome_is_not_in_the_window() -> None:
    both = pl.concat([_matrix(), _matrix(chrom="chr2")])
    out = _window(both, "chr2", 0, 3_000_000)

    assert set(out["chrom1"].to_list()) == {"chr2"}


def test_a_chromosome_with_no_range_is_the_whole_contig() -> None:
    out = _window(_matrix(), "chr1", None, None)

    assert out.height == _matrix().height


def test_an_inverted_range_is_ignored_rather_than_returning_nothing() -> None:
    """An empty tile is indistinguishable from a broken one; a bad range is a
    caller bug and the contig is the honest answer."""
    out = _window(_matrix(), "chr1", 5_000_000, 2_000_000)

    assert out.height == _matrix().height


# ---------------------------------------------------------------------------
# What the tile is told
# ---------------------------------------------------------------------------


def test_the_summary_reports_the_levels_and_the_one_in_use() -> None:
    df = _matrix().with_columns(pl.lit(1_000_000).alias("resolution"))
    summary = summarise(
        df,
        chrom1_col="chrom1",
        start1_col="start1",
        resolution_col="resolution",
        sample_col=None,
        resolutions=MEGATEST_LEVELS,
        resolution=1_000_000,
        region={"chrom": "chr1", "start": 0, "end": 8_000_000},
        pixels=800,
        truncated=False,
    )

    assert summary["resolutions"] == MEGATEST_LEVELS
    assert summary["resolution"] == 1_000_000
    assert summary["multi_resolution"] is True
    assert summary["bin_count"] == 8
    assert summary["bins_per_pixel"] == pytest.approx(8_000_000 / 1_000_000 / 800)


def test_a_flat_dc_is_reported_as_single_resolution() -> None:
    summary = summarise(
        _matrix(),
        chrom1_col="chrom1",
        start1_col="start1",
        resolution_col=None,
        sample_col=None,
        resolutions=[],
        resolution=None,
        region=None,
        pixels=800,
        truncated=False,
    )

    assert summary["multi_resolution"] is False
    assert summary["resolution"] is None
    assert summary["bins_per_pixel"] is None


def test_window_expr_is_an_expression_not_a_frame_operation() -> None:
    """It is composed into one `filter` per axis, so it must stay an Expr."""
    assert isinstance(window_expr("start1", "end1", 1_000_000, 0, 10), pl.Expr)


# ---------------------------------------------------------------------------
# The endpoint guard
# ---------------------------------------------------------------------------


def test_the_dispatcher_rejects_a_payload_with_no_data_collection() -> None:
    """`_dispatch_compute` is the shared guard; without it the payload reaches
    Celery, fails there, and is cached as a failed job."""
    from fastapi import HTTPException

    from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import _dispatch_compute

    with pytest.raises(HTTPException) as exc:
        _dispatch_compute({"wf_id": "wf"}, "contact_map", None, None)
    assert exc.value.status_code == 400


def test_the_contact_map_routes_are_registered_as_a_dispatch_poll_pair() -> None:
    """Same shape as coverage_track: a POST that returns a job and a GET that
    polls it. The renderer's fetch depends on both existing."""
    from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import (
        advanced_viz_endpoint_router,
    )

    paths = {(r.path, tuple(sorted(r.methods))) for r in advanced_viz_endpoint_router.routes}  # type: ignore[attr-defined]
    assert ("/compute_contact_map", ("POST",)) in paths
    assert ("/compute_contact_map/{job_id}", ("GET",)) in paths
