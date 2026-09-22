"""How many bins each binning run recovered per taxon, one row per rank.

The same GTDB-Tk summaries `gtdbtk/summary.py` reads, counted instead of
listed: for every binning run and every rank from domain to genus, how many
bins carry each name. That long shape is what a stacked composition bar with a
rank dropdown consumes, and it is the only view in which two binners on the
same assembly can be compared as communities rather than as bin lists.

`sample_id` is the binning run, `<assembler>-<binner>-<sample>`, not the
sample. Summing bins per sample across binners would count the same organism
once per binner and read as a five-fold deeper community than the sample holds.
The `sample`, `assembler` and `binner` columns are kept beside it so the
dashboard's own filters still reach the rows. A file name the run-label parser
does not recognise keeps its raw label rather than losing its rows.

Species is left out of the rank list: at species level almost every count is 1,
which draws as a hundred one-bin stripes and says nothing the table does not.

Output schema:
    sample_id : Utf8    binning run, <assembler>-<binner>-<sample>
    sample : Utf8       sample the assembly was built from
    assembler : Utf8    assembler part of the run label
    binner : Utf8       binner part of the run label
    rank : Utf8         domain, phylum, class, order, family or genus
    taxon : Utf8        the name at that rank
    abundance : Int64   bins of this run carrying that name
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mag_bins import file_stem, label_lookup

RAW_DC_TAG = "gtdbtk_summary_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="summaries", dc_ref=RAW_DC_TAG),
]

#: Ranks counted, root first. Species is excluded (see the module docstring).
COUNTED_RANKS: tuple[tuple[str, str], ...] = (
    ("d", "domain"),
    ("p", "phylum"),
    ("c", "class"),
    ("o", "order"),
    ("f", "family"),
    ("g", "genus"),
)

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "sample": pl.Utf8,
    "assembler": pl.Utf8,
    "binner": pl.Utf8,
    "rank": pl.Utf8,
    "taxon": pl.Utf8,
    "abundance": pl.Int64,
}

SOURCE_PATH_COL = "source_path"
_SUMMARY_SUFFIX = ".summary.tsv"
_NULL_TOKENS = frozenset({"", "n/a", "na", "none", "null", "-"})


def _run_label(path: str) -> str:
    stem = file_stem(path, _SUMMARY_SUFFIX)
    head, sep, _ = stem.rpartition(".")
    return head if sep else stem


def _rank_name(classification: str | None, prefix: str) -> str | None:
    """The name at one GTDB rank, or None when the bin was not placed that deep."""
    if classification is None:
        return None
    for part in str(classification).split(";"):
        token = part.strip()
        if not token.startswith(f"{prefix}__"):
            continue
        name = token[len(prefix) + 2 :].strip()
        return None if name.lower() in _NULL_TOKENS else name
    return None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Count bins per binning run and taxon, once per rank, stacked into one frame."""
    raw = sources["summaries"]
    if raw.is_empty():
        raise ValueError("gtdbtk_rank_composition: the scanned GTDB-Tk summaries are empty")
    if "classification" not in raw.columns:
        raise ValueError(f"gtdbtk_rank_composition: no `classification` column in {raw.columns}")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "gtdbtk_rank_composition: the scan must set "
            f"`include_file_paths: {SOURCE_PATH_COL}`; the binning run lives only in the file name"
        )

    labelled = raw.with_columns(
        pl.col(SOURCE_PATH_COL).map_elements(_run_label, return_dtype=pl.Utf8).alias("run_label")
    )
    labelled = labelled.join(
        label_lookup(labelled["run_label"].to_list()), on="run_label", how="left"
    )

    classifications = labelled["classification"].to_list()
    blocks: list[pl.DataFrame] = []
    for prefix, rank in COUNTED_RANKS:
        names = [_rank_name(value, prefix) for value in classifications]
        blocks.append(
            labelled.select(
                pl.concat_str(
                    [pl.col("assembler"), pl.col("binner"), pl.col("sample")],
                    separator="-",
                    ignore_nulls=False,
                )
                .fill_null(pl.col("run_label"))
                .alias("sample_id"),
                pl.col("sample"),
                pl.col("assembler"),
                pl.col("binner"),
                pl.lit(rank, dtype=pl.Utf8).alias("rank"),
            )
            .with_columns(pl.Series("taxon", names, dtype=pl.Utf8))
            .drop_nulls(["taxon"])
        )

    stacked = pl.concat(blocks, how="vertical")
    if stacked.is_empty():
        raise ValueError("gtdbtk_rank_composition: no bin carried a lineage")

    return (
        stacked.group_by(["sample_id", "sample", "assembler", "binner", "rank", "taxon"])
        .agg(pl.len().cast(pl.Int64).alias("abundance"))
        .select(list(EXPECTED_SCHEMA))
        .sort(["rank", "sample_id", "abundance", "taxon"], descending=[False, False, True, False])
    )
