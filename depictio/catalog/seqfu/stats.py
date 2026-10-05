"""One row per file SeqFu ``stats`` summarised, with its sample and stage.

Consumes the raw ``seqfu_stats_raw`` scan: the SeqFu TSV read with its header
(``File``, ``#Seq``, ``Total bp``, ``Avg``, ``N50``, ``N75``, ``N90``, ``auN``,
``Min``, ``Max``) plus ``source_path``. The sample and the stage live only in
the file name: ``<sample>_<stage>.tsv`` when the pipeline runs SeqFu before and
after a filter (stage ``before`` / ``after``), else ``<sample>.tsv`` (stage
``stats``). Rows read without a path fall back to the ``File`` column.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "seqfu_stats_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "stage": pl.Utf8,
    "file": pl.Utf8,
    "sequences": pl.Int64,
    "total_length": pl.Int64,
    "mean_length": pl.Float64,
    "n50": pl.Int64,
    "n75": pl.Int64,
    "n90": pl.Int64,
    "aun": pl.Float64,
    "min_length": pl.Int64,
    "max_length": pl.Int64,
}

_COLUMNS = {
    "File": ("file", pl.Utf8),
    "#Seq": ("sequences", pl.Int64),
    "Total bp": ("total_length", pl.Int64),
    "Avg": ("mean_length", pl.Float64),
    "N50": ("n50", pl.Int64),
    "N75": ("n75", pl.Int64),
    "N90": ("n90", pl.Int64),
    "auN": ("aun", pl.Float64),
    "Min": ("min_length", pl.Int64),
    "Max": ("max_length", pl.Int64),
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Type the SeqFu columns and split the file name into sample and stage."""
    raw = sources["raw"]
    if raw is None or raw.is_empty():
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    typed = raw.select(
        *[
            (
                pl.col(src).cast(dtype, strict=False) if src in raw.columns else pl.lit(None, dtype)
            ).alias(name)
            for src, (name, dtype) in _COLUMNS.items()
        ],
        (
            pl.col("source_path").cast(pl.Utf8)
            if "source_path" in raw.columns
            else pl.lit(None, pl.Utf8)
        ).alias("_path"),
    )
    stem = pl.coalesce(
        pl.col("_path").str.extract(r"([^/\\]+)\.tsv$", 1),
        pl.col("file").str.replace(r"\.[^.]+$", ""),
    )
    staged = stem.str.extract(r"^(.+)_(before|after)$", 1)
    out = typed.with_columns(
        pl.coalesce(staged, stem).alias("sample"),
        pl.coalesce(stem.str.extract(r"_(before|after)$", 1), pl.lit("stats")).alias("stage"),
    ).filter(pl.col("sample").is_not_null())
    return out.select(list(EXPECTED_SCHEMA)).sort(["sample", "stage"])
