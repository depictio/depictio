"""Complete BUSCOs per sequence, drawn to scale: the nf-core/genomeqc karyotype.

genomeqc's IDEOGRAM step counts, from BUSCO's full table, the complete
single-copy markers on every sequence of an assembly and writes them as a
two-column CSV (``"Chr","Complete_BUSCOs"``), one row per sequence holding at
least one, under ``busco/<mode>/<assembly>/ideogram/<assembly>[_<lineage>].csv``
(``protein`` when the run had an annotation, ``genome`` for a genome-only run).
It publishes neither the full table nor the sequence lengths, so each sequence
takes its length from ``tidk search`` (catalog ``tidk/search_windows``, whose
last window of a sequence ends at its length).

One row per assembly and sequence, the whole sequence as one interval, so an
ideogram draws every sequence to its length and shades it by its BUSCO
density. A well-assembled genome puts its markers on a few long sequences,
about one per chromosome; a fragmented one spreads them over hundreds of
scaffolds, which is what genomeqc's "sequences above x BUSCOs" counts.

Sources:
    ideograms  the IDEOGRAM CSVs (glob, with the path in ``source_path``)
    lengths    ``tidk_search_windows`` (catalog ``tidk/search_windows``); a
               sequence it does not list has no length and is left out

Output schema:
    genome : Utf8              assembly
    busco_mode : Utf8          proteins (annotation mode) or genome (genome-only mode)
    sequence : Utf8            sequence id
    start : Int64              0
    end : Int64                the sequence length
    sequence_length : Int64    bp
    complete_buscos : Int64    complete BUSCOs on the sequence
    buscos_per_mb : Float64    their density per megabase of sequence
    busco_share_pct : Float64  share of the assembly's placed BUSCOs on this sequence, percent
    sequence_rank : Int64      1 for the sequence holding the most BUSCOs, and so on
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCE_PATH_COL = "source_path"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="ideograms",
        glob_pattern="**/busco/*/*/ideogram/*.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
        source_path=SOURCE_PATH_COL,
        input_schema={"Chr": pl.Utf8, "Complete_BUSCOs": pl.Utf8, SOURCE_PATH_COL: pl.Utf8},
    ),
    RecipeSource(
        ref="lengths",
        dc_ref="tidk_search_windows",
        input_schema={
            "genome": pl.Utf8,
            "sequence": pl.Utf8,
            "sequence_length": pl.Int64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "busco_mode": pl.Utf8,
    "sequence": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "sequence_length": pl.Int64,
    "complete_buscos": pl.Int64,
    "buscos_per_mb": pl.Float64,
    "busco_share_pct": pl.Float64,
    "sequence_rank": pl.Int64,
}

#: Directory under busco/ -> the BUSCO mode it ran in.
MODES = {"protein": "proteins", "proteins": "proteins", "genome": "genome"}


def path_parts(source_path: str) -> tuple[str, str]:
    """``busco/protein/A/ideogram/A.csv`` -> ``("A", "proteins")``."""
    parts = PurePosixPath(str(source_path).replace("\\", "/")).parts
    at = len(parts) - 1 - list(reversed(parts)).index("ideogram")
    genome = parts[at - 1]
    mode_dir = parts[at - 2] if at >= 2 else ""
    return genome, MODES.get(mode_dir, mode_dir)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raw = sources["ideograms"]
    keys = {p: path_parts(p) for p in raw.get_column(SOURCE_PATH_COL).unique().to_list()}
    counts = raw.select(
        pl.col(SOURCE_PATH_COL)
        .replace_strict({p: g for p, (g, _) in keys.items()}, return_dtype=pl.Utf8)
        .alias("genome"),
        pl.col(SOURCE_PATH_COL)
        .replace_strict({p: m for p, (_, m) in keys.items()}, return_dtype=pl.Utf8)
        .alias("busco_mode"),
        pl.col("Chr").cast(pl.Utf8).str.strip_chars().alias("sequence"),
        pl.col("Complete_BUSCOs").cast(pl.Int64, strict=False).alias("complete_buscos"),
    ).filter(pl.col("sequence").is_not_null() & (pl.col("complete_buscos") > 0))

    lengths = sources["lengths"].group_by("genome", "sequence").agg(pl.col("sequence_length").max())
    out = counts.join(lengths, on=["genome", "sequence"], how="inner")
    if out.is_empty():
        raise ValueError(
            "genomeqc busco_karyotype: no BUSCO sequence matched a tidk sequence length"
        )
    per_genome = ["genome", "busco_mode"]
    return (
        out.with_columns(
            pl.lit(0, dtype=pl.Int64).alias("start"),
            pl.col("sequence_length").alias("end"),
            (pl.col("complete_buscos") * 1e6 / pl.col("sequence_length"))
            .round(2)
            .alias("buscos_per_mb"),
            (pl.col("complete_buscos") * 100.0 / pl.col("complete_buscos").sum().over(per_genome))
            .round(2)
            .alias("busco_share_pct"),
            pl.col("complete_buscos")
            .rank("ordinal", descending=True)
            .over(per_genome)
            .cast(pl.Int64)
            .alias("sequence_rank"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort([*per_genome, "sequence_rank"])
    )
