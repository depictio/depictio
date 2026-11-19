"""UMI read counts of nf-core/viralmetagenome, from the umi_tools logs (``--with_umi``).

With ``--with_umi`` the pipeline moves the UMI of every read into its name
(``umi_tools extract``, log under ``preprocessing/umi/umitools/log/``) and, with
``--umi_deduplicate mapping`` (or ``both``), collapses the reads of one UMI at
one position after mapping (``umi_tools dedup``, log under
``variants/mapping-info/deduplicate/log/<sample>/``, one per mapping). The logs
are the only place the counts are written:

* extract: ``Input Reads: N`` and ``Reads output: N``;
* dedup: ``Reads: Input Reads: N``, ``Number of reads out: N``, ``Total number
  of positions deduplicated: N``, ``Mean number of unique UMIs per position: X``
  and ``Max. number of unique UMIs per position: N``.

A run without UMIs has no log and the collection is pruned. ``--umi_deduplicate
read`` (the default) deduplicates with HUMID instead, whose log this recipe
does not read: those runs keep the extract rows only.

Sources:
    extract  ``preprocessing/umi/umitools/log/*.log``, optional
    dedup    ``variants/mapping-info/deduplicate/log/*/*.log``, optional

Output schema:
    sample, genome_id, step : Utf8   step is ``extract`` or ``dedup``; genome_id null for extract
    input_reads, output_reads : Int64
    removed_pct : Float64            reads the step dropped, percent of its input
    positions : Int64                positions deduplicated (dedup only)
    mean_umis_per_position : Float64 (dedup only)
    max_umis_per_position : Int64    (dedup only)
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import (
    genome_id,
    split_mapping_name,
    strip_global_prefix,
)

_LINE = "line"
_PATH = "source_path"
_READ_KWARGS = {
    "separator": "\x1e",
    "has_header": False,
    "quote_char": None,
    "new_columns": [_LINE],
    "infer_schema_length": 0,
}

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="extract",
        glob_pattern="preprocessing/umi/umitools/log/*.log",
        format="csv",
        optional=True,
        read_kwargs=_READ_KWARGS,
        source_path=_PATH,
        input_schema={_LINE: pl.Utf8, _PATH: pl.Utf8},
    ),
    RecipeSource(
        ref="dedup",
        glob_pattern="variants/mapping-info/deduplicate/log/*/*.log",
        format="csv",
        optional=True,
        read_kwargs=_READ_KWARGS,
        source_path=_PATH,
        input_schema={_LINE: pl.Utf8, _PATH: pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "genome_id": pl.Utf8,
    "step": pl.Utf8,
    "input_reads": pl.Int64,
    "output_reads": pl.Int64,
    "removed_pct": pl.Float64,
    "positions": pl.Int64,
    "mean_umis_per_position": pl.Float64,
    "max_umis_per_position": pl.Int64,
}

#: Output column -> (regex on a log line, dtype), per step. The first match wins.
_FIELDS: dict[str, dict[str, tuple[str, type[pl.DataType]]]] = {
    "extract": {
        "input_reads": (r"Input Reads:\s*(\d+)", pl.Int64),
        "output_reads": (r"Reads output:\s*(\d+)", pl.Int64),
    },
    "dedup": {
        "input_reads": (r"Reads: Input Reads:\s*(\d+)", pl.Int64),
        "output_reads": (r"Number of reads out:\s*(\d+)", pl.Int64),
        "positions": (r"Total number of positions deduplicated:\s*(\d+)", pl.Int64),
        "mean_umis_per_position": (
            r"Mean number of unique UMIs per position:\s*([0-9.eE+-]+)",
            pl.Float64,
        ),
        "max_umis_per_position": (r"Max\. number of unique UMIs per position:\s*(\d+)", pl.Int64),
    },
}
_EXTRACT_SUFFIX = (".umi_extract.log", ".log")
_DEDUP_SUFFIX = (".umi_deduplicated.log", ".log")


def _strip(name: str, suffixes: tuple[str, ...]) -> str:
    for s in suffixes:
        if name.endswith(s):
            return name[: -len(s)]
    return name


def log_ids(path: str, step: str) -> list[str | None]:
    """``[sample, genome_id]`` a log's place names."""
    p = PurePosixPath(path)
    if step == "extract":
        stem = strip_global_prefix(_strip(p.name, _EXTRACT_SUFFIX))
        # `<sample>` or `<sample>_<previous step>` (umi_tools extract runs on the raw reads).
        return [stem.split(".")[0], None]
    sample = p.parent.name
    stem = strip_global_prefix(_strip(p.name, _DEDUP_SUFFIX))
    reference, _route, _step = split_mapping_name(stem, sample)
    return [sample, genome_id(sample, reference)]


def _parse(raw: pl.DataFrame, step: str) -> pl.DataFrame:
    fields = _FIELDS[step]
    per_file = (
        raw.filter(pl.col(_LINE).is_not_null())
        .group_by(_PATH)
        .agg(
            *[
                pl.col(_LINE).str.extract(rx, 1).drop_nulls().first().cast(t, strict=False).alias(c)
                for c, (rx, t) in fields.items()
            ]
        )
        .filter(pl.col("input_reads").is_not_null())
    )
    ids = per_file[_PATH].map_elements(lambda p: log_ids(p, step), return_dtype=pl.List(pl.Utf8))
    return per_file.with_columns(
        ids.list.get(0).alias("sample"),
        ids.list.get(1).alias("genome_id"),
        pl.lit(step).alias("step"),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    parts = [
        _parse(sources[step], step)
        for step in ("extract", "dedup")
        if sources.get(step) is not None and not sources[step].is_empty()
    ]
    parts = [p for p in parts if not p.is_empty()]
    if not parts:
        raise ValueError("viralmetagenome umi_stats: no umi_tools log with read counts was found")
    out = pl.concat(parts, how="diagonal_relaxed")
    for col, dtype in OUTPUT_SCHEMA.items():
        if col not in out.columns:
            out = out.with_columns(pl.lit(None, dtype=dtype).alias(col))
    out = out.with_columns(
        pl.when(pl.col("input_reads") > 0)
        .then(
            (
                (pl.col("input_reads") - pl.col("output_reads")) * 100.0 / pl.col("input_reads")
            ).round(2)
        )
        .otherwise(None)
        .alias("removed_pct")
    )
    return out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["step", "sample", "genome_id"], nulls_last=True
    )
