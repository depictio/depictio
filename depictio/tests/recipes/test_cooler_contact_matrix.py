"""The contact matrix is a stack of resolutions, not one.

``cooler/contact_matrix.py`` used to keep the finest resolution a run dumped
and throw the rest away, because two bin sizes drawn on one axis is nonsense.
The `resolution` column is the partition key now: every dumped resolution is
kept and the reader picks exactly one before drawing, which is what lets a
contact map re-bin itself as someone zooms in.

Two things can go wrong with that and neither is visible in the rendered tile:

  * the bin ids restart at 0 in every ``cooler_bins_<res>.bed``, so a join that
    forgets the resolution silently reads 1 Mb coordinates off the 500 kb bed
    and puts contacts at the wrong locus;
  * a run that dumped one resolution has nothing to zoom between, so the recipe
    derives the coarser levels by merging bins. A merge that averaged instead
    of summing, or that recomputed the end from the start, would look plausible
    and be wrong at the chromosome edge.

Both are pinned below against the shape the nf-core/hic megatest really writes
(HIC_ES_4 at 500 kb and 1 Mb).
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema

RECIPE = "cooler/contact_matrix.py"


@pytest.fixture(scope="module")
def recipe():
    return load_recipe(RECIPE)


def _contacts(rows: list[tuple[str, int, int, int, float]]) -> pl.DataFrame:
    """A `cooler dump` scan frame: every column arrives as text.

    The DC declares ``infer_schema_length: 0`` so polars types the headerless
    triplet as Utf8 and the recipe is the thing that casts.
    """
    return pl.DataFrame(
        {
            "source_path": [
                f"/run/contact_maps/txt/{s}.{res}_balanced.txt" for s, res, _, _, _ in rows
            ],
            "bin1_id": [str(b1) for _, _, b1, _, _ in rows],
            "bin2_id": [str(b2) for _, _, _, b2, _ in rows],
            "count": [repr(c) for _, _, _, _, c in rows],
        },
        schema={"source_path": pl.Utf8, "bin1_id": pl.Utf8, "bin2_id": pl.Utf8, "count": pl.Utf8},
    )


def _bins(per_resolution: dict[int, list[tuple[str, int, int]]]) -> pl.DataFrame:
    """A `cooler makebins` scan frame: one bed per resolution, ids restart at 0."""
    paths: list[str] = []
    chrom: list[str] = []
    start: list[int] = []
    end: list[int] = []
    for res, entries in per_resolution.items():
        for c, s, e in entries:
            paths.append(f"/run/contact_maps/bins/cooler_bins_{res}.bed")
            chrom.append(c)
            start.append(s)
            end.append(e)
    return pl.DataFrame({"source_path": paths, "chrom": chrom, "start": start, "end": end})


def _grid(chrom: str, n: int, resolution: int) -> list[tuple[str, int, int]]:
    return [(chrom, i * resolution, (i + 1) * resolution) for i in range(n)]


# ---------------------------------------------------------------------------
# Partitions
# ---------------------------------------------------------------------------


def test_every_dumped_resolution_survives_as_its_own_partition(recipe) -> None:
    """The megatest shape: 500 kb and 1 Mb dumped side by side."""
    contacts = _contacts(
        [
            ("HIC_ES_4", 500_000, 0, 0, 0.47),
            ("HIC_ES_4", 500_000, 0, 1, 0.12),
            ("HIC_ES_4", 1_000_000, 0, 0, 0.69),
        ]
    )
    bins = _bins({500_000: _grid("chr1", 4, 500_000), 1_000_000: _grid("chr1", 2, 1_000_000)})

    out = recipe.transform({"contacts": contacts, "bins": bins})

    validate_schema(out, recipe.EXPECTED_SCHEMA, RECIPE)
    assert sorted(set(out["resolution"].to_list())) == [500_000, 1_000_000]


def test_a_bin_id_is_read_off_the_bed_of_its_own_resolution(recipe) -> None:
    """Bin 1 means 500 kb at 500 kb and 1 Mb at 1 Mb, never the other way."""
    contacts = _contacts(
        [
            ("HIC_ES_4", 500_000, 1, 1, 1.0),
            ("HIC_ES_4", 1_000_000, 1, 1, 2.0),
        ]
    )
    bins = _bins({500_000: _grid("chr1", 4, 500_000), 1_000_000: _grid("chr1", 2, 1_000_000)})

    out = recipe.transform({"contacts": contacts, "bins": bins})

    starts = dict(zip(out["resolution"].to_list(), out["start1"].to_list()))
    assert starts == {500_000: 500_000, 1_000_000: 1_000_000}


def test_trans_pairs_are_dropped_at_every_resolution(recipe) -> None:
    contacts = _contacts(
        [
            ("HIC_ES_4", 500_000, 0, 0, 1.0),
            ("HIC_ES_4", 500_000, 0, 2, 0.5),  # chr1 x chr2
            ("HIC_ES_4", 1_000_000, 0, 1, 0.5),  # chr1 x chr2
        ]
    )
    bins = _bins(
        {
            500_000: [*_grid("chr1", 2, 500_000), *_grid("chr2", 2, 500_000)],
            1_000_000: [("chr1", 0, 1_000_000), ("chr2", 0, 1_000_000)],
        }
    )

    out = recipe.transform({"contacts": contacts, "bins": bins})

    # The 1 Mb dump held a trans pair only, so it disappears entirely and the
    # 500 kb level is left alone (and therefore coarsened, hence `filter`).
    assert out.filter(pl.col("resolution") == 500_000).height == 1
    assert set(out["chrom1"].to_list()) == {"chr1"}
    assert set(out["chrom2"].to_list()) == {"chr1"}


def test_an_empty_dump_returns_the_output_schema_not_a_crash(recipe) -> None:
    empty = _contacts([])
    out = recipe.transform({"contacts": empty, "bins": _bins({500_000: _grid("chr1", 2, 500_000)})})

    assert out.height == 0
    assert list(out.columns) == list(recipe.EXPECTED_SCHEMA)


# ---------------------------------------------------------------------------
# Derived levels
# ---------------------------------------------------------------------------


def _single_resolution(resolution: int = 500_000, n_bins: int = 16):
    """One dumped resolution: a dense 4-bin block plus a truncated last bin."""
    rows = [
        ("HIC_ES_4", resolution, i, j, float(10 - abs(i - j)))
        for i in range(n_bins)
        for j in range(i, n_bins)
    ]
    grid = _grid("chr1", n_bins, resolution)
    # cooler truncates the final bin at the contig end.
    grid[-1] = (grid[-1][0], grid[-1][1], grid[-1][1] + resolution // 4)
    return _contacts(rows), _bins({resolution: grid})


def test_a_single_dumped_resolution_gains_the_coarser_levels(recipe) -> None:
    contacts, bins = _single_resolution()

    out = recipe.transform({"contacts": contacts, "bins": bins})

    assert sorted(set(out["resolution"].to_list())) == [500_000, 1_000_000, 2_000_000, 4_000_000]


def test_a_derived_cell_is_the_sum_of_the_cells_it_merged(recipe) -> None:
    """Summing, not averaging: `cooler coarsen`'s rule, and the only one that
    keeps the coarse matrix on the same scale as the reads behind it."""
    contacts, bins = _single_resolution()

    out = recipe.transform({"contacts": contacts, "bins": bins})

    fine = out.filter(pl.col("resolution") == 500_000)
    coarse = out.filter(pl.col("resolution") == 1_000_000)
    # The 1 Mb cell at (0, 0) merges the 500 kb cells (0,0), (0,1), (1,1)  - 
    # (1,0) is not in the dump, only its mirror is.
    merged = fine.filter(pl.col("start1") < 1_000_000, pl.col("start2") < 1_000_000)
    got = coarse.filter(pl.col("start1") == 0, pl.col("start2") == 0)["count"].to_list()
    assert got == pytest.approx([merged["count"].sum()])


def test_a_derived_bin_keeps_the_truncated_end_of_the_contig(recipe) -> None:
    """The last bin of a chromosome is shorter than the resolution. Recomputing
    the end as `start + resolution` would run it past the contig."""
    contacts, bins = _single_resolution()

    out = recipe.transform({"contacts": contacts, "bins": bins})

    last_fine = out.filter(pl.col("resolution") == 500_000)["end2"].max()
    for resolution in (1_000_000, 2_000_000, 4_000_000):
        level = out.filter(pl.col("resolution") == resolution)
        assert level["end2"].max() == last_fine


def test_derived_bin_boundaries_are_nested_in_the_dumped_ones(recipe) -> None:
    """Powers of two, so no coarse boundary falls inside a fine bin."""
    contacts, bins = _single_resolution()

    out = recipe.transform({"contacts": contacts, "bins": bins})

    fine_starts = set(out.filter(pl.col("resolution") == 500_000)["start1"].to_list())
    for resolution in (1_000_000, 2_000_000, 4_000_000):
        coarse_starts = set(out.filter(pl.col("resolution") == resolution)["start1"].to_list())
        assert coarse_starts <= fine_starts


def test_a_run_that_dumped_two_resolutions_derives_nothing(recipe) -> None:
    """Deriving is the fallback for a single-level dump, never an addition to
    what the run actually computed."""
    contacts = _contacts(
        [
            ("HIC_ES_4", 500_000, 0, 0, 1.0),
            ("HIC_ES_4", 1_000_000, 0, 0, 1.0),
        ]
    )
    bins = _bins({500_000: _grid("chr1", 2, 500_000), 1_000_000: _grid("chr1", 1, 1_000_000)})

    out = recipe.transform({"contacts": contacts, "bins": bins})

    assert sorted(set(out["resolution"].to_list())) == [500_000, 1_000_000]


def test_derivation_stops_at_the_coarseness_ceiling(recipe) -> None:
    """Past `MAX_DERIVED_RESOLUTION` a chromosome is a handful of bins."""
    resolution = recipe.MAX_DERIVED_RESOLUTION // 2
    contacts = _contacts([("HIC_ES_4", resolution, 0, 0, 1.0), ("HIC_ES_4", resolution, 0, 1, 1.0)])
    bins = _bins({resolution: _grid("chr1", 2, resolution)})

    out = recipe.transform({"contacts": contacts, "bins": bins})

    levels = sorted(set(out["resolution"].to_list()))
    assert levels == [resolution, recipe.MAX_DERIVED_RESOLUTION]


def test_samples_are_coarsened_apart(recipe) -> None:
    """Two libraries in one DC must not pool into one derived cell."""
    contacts = _contacts(
        [
            ("HIC_ES_4", 500_000, 0, 0, 1.0),
            ("HIC_ES_4", 500_000, 0, 1, 2.0),
            ("HIC_ES_5", 500_000, 0, 0, 10.0),
            ("HIC_ES_5", 500_000, 0, 1, 20.0),
        ]
    )
    bins = _bins({500_000: _grid("chr1", 2, 500_000)})

    out = recipe.transform({"contacts": contacts, "bins": bins})

    coarse = out.filter(pl.col("resolution") == 1_000_000)
    got = dict(zip(coarse["sample"].to_list(), coarse["count"].to_list()))
    assert got == pytest.approx({"HIC_ES_4": 3.0, "HIC_ES_5": 30.0})
