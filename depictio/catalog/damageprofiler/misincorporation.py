"""Ancient-DNA misincorporation frequency by position, both read ends, one row
per (sample, end, position, base_change).

DamageProfiler writes `5p_freq_misincorporations.txt` and
`3p_freq_misincorporations.txt` per sample directory: a real TSV (three `#`
comment lines, then a header) with one column per substitution type
(`C>T`, `G>A`, `A>C`, ... fourteen in all) and one row per distance from the
read end. The sample lives only in the parent directory name
(`<sample>_rmdup/`, DamageProfiler's report is titled after the BAM it read,
not the sample), so this is the raw-scan-plus-`dc_ref` idiom
`preseq/complexity_curve.py` documents, a plain TSV scan this time (the file
IS tabular), not the line-per-row trick `samtools/flagstat.py` and
`qualimap/bamqc_genome_results.py` need for freeform reports.

`end` comes from the filename (`5p_freq_misincorporations.txt` -> `5p`), not
from a column, DamageProfiler never puts it in the file itself.

Binds `depictio.models.components.advanced_viz` kind `damage_profile`
(sample, end, position, base_change, frequency): a run's authenticity read is
the C>T / G>A excess at the read ends over a flat "other substitutions"
background, so those two known deamination signatures are kept as their own
category and the other twelve (A>C, A>G, A>T, C>A, C>G, G>C, G>T, T>A, T>C,
T>G, and the two indel-adjacent `->ACGT` / `ACGT>-` columns) are SUMMED per
position into `other`: the combined non-deamination background the two
signatures are read against, not a thing anyone reads as its own curve.

Input: the `damageprofiler_misincorporation_raw` data collection, declared by
the template as::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*_freq_misincorporations\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          comment_prefix: "#"
          include_file_paths: "source_path"

Output schema:
    sample : Utf8         library DamageProfiler ran on
    end : Utf8             "5p" or "3p"
    position : Int64        distance from that read end
    base_change : Utf8      "C>T", "G>A" or "other"
    frequency : Float64      substitution frequency at that position ("other" is the sum of the twelve remaining columns)
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the template must scan the raw reports into (see module
#: docstring). Any pipeline reusing this recipe declares a DC with this tag.
RAW_DC_TAG = "damageprofiler_misincorporation_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="misinc", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "end": pl.Utf8,
    "position": pl.Int64,
    "base_change": pl.Utf8,
    "frequency": pl.Float64,
}

SOURCE_PATH_COL = "source_path"

# The two deamination signatures kept as their own curve; every other
# substitution (and the two indel-adjacent columns DamageProfiler appends)
# collapses into "other".
_KEEP_AS_IS = {"C>T", "G>A"}

# Trailing directory tokens that describe a processing stage rather than the
# sample (the dedupper stage run before DamageProfiler).
_DIR_STAGE_TOKENS = ("rmdup", "dedup", "results", "stats")


def _sample_from_dir(source_path: str) -> str:
    dirname = Path(source_path).parent.name
    tokens = dirname.split("_")
    while len(tokens) > 1 and tokens[-1].lower() in _DIR_STAGE_TOKENS:
        tokens.pop()
    return "_".join(tokens)


def _end_from_filename(source_path: str) -> str:
    name = Path(source_path).name.lower()
    if name.startswith("5p"):
        return "5p"
    if name.startswith("3p"):
        return "3p"
    raise ValueError(f"damageprofiler_misincorporation: cannot read end from {source_path!r}")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Melt the wide per-position substitution table to long, sample + end labelled."""
    raw = sources["misinc"]
    if raw.is_empty():
        raise ValueError("damageprofiler_misincorporation: the scanned reports are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "damageprofiler_misincorporation: no source_path column, the DC must "
            "scan with include_file_paths: source_path"
        )
    if "Pos" not in raw.columns:
        raise ValueError(f"damageprofiler_misincorporation: no 'Pos' column, got {raw.columns}")

    value_cols = [c for c in raw.columns if c not in ("Pos", SOURCE_PATH_COL)]
    frame = raw.with_columns(
        pl.col(SOURCE_PATH_COL)
        .map_elements(_sample_from_dir, return_dtype=pl.Utf8)
        .alias("sample"),
        pl.col(SOURCE_PATH_COL).map_elements(_end_from_filename, return_dtype=pl.Utf8).alias("end"),
        pl.col("Pos").cast(pl.Int64, strict=False).alias("position"),
    ).with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in value_cols])

    keep = [c for c in value_cols if c in _KEEP_AS_IS]
    other_cols = [c for c in value_cols if c not in _KEEP_AS_IS]

    kept = frame.unpivot(
        index=["sample", "end", "position"],
        on=keep,
        variable_name="base_change",
        value_name="frequency",
    )
    other = frame.select(
        "sample",
        "end",
        "position",
        pl.sum_horizontal(other_cols).alias("frequency"),
    ).with_columns(pl.lit("other").alias("base_change"))

    out = pl.concat([kept, other.select(kept.columns)], how="vertical")
    return out.select(list(EXPECTED_SCHEMA)).sort(["sample", "end", "position", "base_change"])
