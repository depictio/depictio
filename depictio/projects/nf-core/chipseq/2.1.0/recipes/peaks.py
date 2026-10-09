"""MACS3 peak calls of either peak type, in one tidy table.

nf-core/chipseq 2.x calls peaks with MACS3 and publishes them under
``<aligner>/merged_library/macs3/<narrow_peak|broad_peak>/``. Which of the two a
run writes depends on ``--narrow_peak`` (the pipeline default is broadPeak), and
the two files are different schemas: ``*_peaks.narrowPeak`` is a BED6+4 whose
tenth column is the summit offset, ``*_peaks.broadPeak`` a BED6+3 with no summit.
The catalog has one recipe per schema (``macs2/peaks.py`` and
``macs2/broad_peaks.py``), and a recipe glob source cannot be optional, so
neither catalog recipe alone serves a template that has to ingest both routes
without a template variable.

This recipe reads whichever file the run wrote through one glob, hands the rows
to the matching catalog transform and lines the broad output up with the narrow
schema: the region centre (``midpoint``) stands in for the summit a broad region
does not have, so the Manhattan panel and every tile bound to ``summit`` keep
working on a broadPeak run.

The glob loader does not expose file names, so the peak type of a row is read
off its width: the files are read headerless and concatenated diagonally, which
leaves a narrowPeak row with 10 filled columns, a broadPeak row with 9 and a
``*_peaks.gappedPeak`` row (BED12+3, which also matches the glob) with 15. Gapped
rows are dropped. A tree holding both narrow and broad calls is refused rather
than concatenated: one run publishes one peak type, so the other one is left over
from an earlier run and would count every sample's peaks twice.

Output schema: the ``macs2/peaks.py`` schema, plus
    peak_type : Utf8   narrowPeak or broadPeak, the file type the row was read from
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Column names the catalog transforms expect, in file order. They mirror the
#: readers in depictio/catalog/macs2/peaks.py and broad_peaks.py.
_NARROWPEAK_COLUMNS = [
    "chr",
    "start",
    "end",
    "peak_id",
    "score",
    "strand",
    "fold_enrichment",
    "neg_log10_pvalue",
    "neg_log10_qvalue",
    "summit_offset",
]
_BROADPEAK_COLUMNS = _NARROWPEAK_COLUMNS[:9]
#: A gappedPeak row fills 15 columns; nothing else under the glob does.
_GAPPED_WIDTH = 15

#: peak type -> (catalog recipe, its source ref, its column names)
_READERS = {
    "narrowPeak": ("macs2/peaks.py", "narrowpeak", _NARROWPEAK_COLUMNS),
    "broadPeak": ("macs2/broad_peaks.py", "broadpeak", _BROADPEAK_COLUMNS),
}

# INPUT SCHEMA: no input_schema, the files are read headerless and classified by width.
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="peaks",
        glob_pattern="**/*_peaks.*Peak",
        format="TSV",
        read_kwargs={"has_header": False, "infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it. The catalog
# `macs2/peaks.py` schema plus `peak_type`.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "peak_id": pl.Utf8,
    "chr": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "width": pl.Int64,
    "summit": pl.Int64,
    "score": pl.Int64,
    "fold_enrichment": pl.Float64,
    "neg_log10_pvalue": pl.Float64,
    "neg_log10_qvalue": pl.Float64,
    "peak_type": pl.Utf8,
}


def _filled(df: pl.DataFrame, index: int) -> pl.Expr:
    """True where positional column ``index`` exists and holds a value."""
    name = f"column_{index}"
    if name not in df.columns:
        return pl.lit(False)
    return pl.col(name).is_not_null() & (pl.col(name).cast(pl.Utf8) != "")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pick the peak type the run wrote and parse it with the catalog reader."""
    # Imported here, not at module level: this module is itself loaded by
    # depictio.recipes, and the catalog readers are resolved through it.
    from depictio.recipes import load_recipe

    df = sources["peaks"]
    df = df.with_columns(
        pl.when(_filled(df, _GAPPED_WIDTH))
        .then(pl.lit("gappedPeak"))
        .when(_filled(df, 10))
        .then(pl.lit("narrowPeak"))
        .when(_filled(df, 9))
        .then(pl.lit("broadPeak"))
        .otherwise(None)
        .alias("_peak_type")
    )
    found = sorted(set(df.get_column("_peak_type").drop_nulls().to_list()) & set(_READERS))
    if not found:
        raise ValueError("chipseq peaks: no narrowPeak or broadPeak row among the matched files")
    if len(found) > 1:
        raise ValueError(
            "chipseq peaks: DATA_ROOT holds both narrowPeak and broadPeak calls; a run "
            "publishes one peak type, so one of the two trees is stale. Remove it."
        )

    peak_type = found[0]
    recipe, ref, columns = _READERS[peak_type]
    rows = df.filter(pl.col("_peak_type") == peak_type)
    frame = rows.select(
        [pl.col(f"column_{i}").alias(name) for i, name in enumerate(columns, start=1)]
    )

    out = load_recipe(recipe).transform({ref: frame})
    if peak_type == "broadPeak":
        out = out.rename({"midpoint": "summit"})
    return out.with_columns(pl.lit(peak_type).alias("peak_type")).select(list(OUTPUT_SCHEMA))
