"""eager-local override of `depictio/catalog/preseq/complexity_curve.py`.

Same output contract (the dashboard binds `use: preseq/complexity_curve`, and
the schema below is byte-identical to the catalog recipe's), but eager's own
`preseq lc_extrap` step writes `<library>.filtered.preseq` with exactly two
columns (`total_reads`, `distinct_reads`) and no bootstrap confidence interval
,  unlike the `<sample>.ccurve.txt` / `-b`-bootstrapped layout the shared
catalog recipe's docstring describes for the ChIP-family pipelines.

The catalog recipe's sample-id helper
(`depictio.recipes.lib.sample_ids.strip_stage_suffixes`) only drops KNOWN
dot-separated stage tokens (`ccurve`, `mkd`, `sorted`, ...); `filtered` and
`preseq` are not in that list, so it would hand back the whole file stem
unchanged. Rather than widen a shared list on behalf of one pipeline's naming,
this recipe matches eager's fixed suffix directly. Everything else, the
`MAX_TOTAL_READS` clip and the `MAX_POINTS`-per-library decimation the
`profile` kind needs (it never samples its own frame), is unchanged from the
catalog recipe.

Input: the `preseq_ccurve_raw` data collection (see `template.yaml`), scanned
with `include_file_paths: source_path` so the library name can be read off
each file's name.

Output schema, identical to `preseq/complexity_curve.py`:
    sample : Utf8               library preseq ran on
    total_reads : Float64       sequencing depth the row extrapolates to
    expected_distinct : Float64 unique molecules expected at that depth
    lower_ci : Float64          null: eager's lc_extrap run wrote no bootstrap CI
    upper_ci : Float64          null, same reason
    ci_width : Float64          null, same reason
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "preseq_ccurve_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="curves", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "total_reads": pl.Float64,
    "expected_distinct": pl.Float64,
    "lower_ci": pl.Float64,
    "upper_ci": pl.Float64,
    "ci_width": pl.Float64,
}

SOURCE_PATH_COL = "source_path"
MAX_TOTAL_READS = 1_000_000_000.0
MAX_POINTS = 200

# "<library>.filtered.preseq", eager's fixed lc_extrap output name.
_STEM_RE = re.compile(r"^(?P<sample>.+?)\.filtered\.preseq$")


def _sample_from_path(source_path: str) -> str:
    name = source_path.replace("\\", "/").rsplit("/", 1)[-1]
    m = _STEM_RE.match(name)
    return m.group("sample") if m else name


def _thin(frame: pl.DataFrame) -> pl.DataFrame:
    clipped = frame.filter(pl.col("total_reads") <= MAX_TOTAL_READS)
    if clipped.is_empty():
        clipped = frame
    height = clipped.height
    if height <= MAX_POINTS:
        return clipped
    step = -(-height // MAX_POINTS)
    return clipped.gather_every(step).vstack(clipped.tail(1)).unique(subset=["total_reads"])


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raw = sources["curves"]
    if raw.is_empty():
        raise ValueError("eager_preseq_complexity_curve: the scanned curves are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "eager_preseq_complexity_curve: no source_path column, the DC must "
            "scan with include_file_paths: source_path"
        )
    missing = {"total_reads", "distinct_reads"} - set(raw.columns)
    if missing:
        raise ValueError(f"eager_preseq_complexity_curve: missing columns {sorted(missing)}")

    frame = raw.select(
        pl.col(SOURCE_PATH_COL)
        .map_elements(_sample_from_path, return_dtype=pl.Utf8)
        .alias("sample"),
        pl.col("total_reads").cast(pl.Float64, strict=False),
        pl.col("distinct_reads").cast(pl.Float64, strict=False).alias("expected_distinct"),
        pl.lit(None, dtype=pl.Float64).alias("lower_ci"),
        pl.lit(None, dtype=pl.Float64).alias("upper_ci"),
    ).drop_nulls(["total_reads", "expected_distinct"])

    if frame.is_empty():
        raise ValueError(
            "eager_preseq_complexity_curve: no row carried a depth and a distinct count"
        )

    thinned = pl.concat(
        [_thin(part.sort("total_reads")) for (_,), part in frame.group_by(["sample"])],
        how="vertical",
    )
    return (
        thinned.with_columns(pl.lit(None, dtype=pl.Float64).alias("ci_width"))
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "total_reads"])
    )
