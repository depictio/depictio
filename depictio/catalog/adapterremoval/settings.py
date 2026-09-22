"""Trimming and collapsing statistics from an AdapterRemoval settings report.

AdapterRemoval writes one ``.settings`` report per input unit, in sections whose
lines are ``Key: value``::

    [Trimming statistics]
    Total number of read pairs: 13154136
    Number of discarded mate 1 reads: 1121960
    Number of full-length collapsed pairs: 11668135
    Number of retained reads: 12261041
    Average length of retained reads: 52.3426

Everything a read-fate accounting needs is in that one section, and the counts
balance exactly: twice the pair count equals the retained reads, plus the reads
merged away by collapsing, plus the discarded mates. That identity is what lets
a flow diagram be drawn from these numbers without apportioning anything.

Collapsing matters for ancient DNA specifically: fragments are usually shorter
than the read length, so the two mates overlap and are merged into one sequence.
A high collapse rate is the expected shape of an ancient library, not a warning,
and a low one on an aDNA extract usually means the insert size is modern.

A single-end run writes ``Total number of reads`` and no pair or collapse lines;
those columns come back null rather than failing the collection.

The report does not name its sample, so the id is its own file name with the
``.settings`` suffix and the ``.pe`` / ``.se`` mode token removed. A pipeline
that runs AdapterRemoval per lane gets one row per lane, which is the level the
report is written at; collapsing lanes onto libraries needs the samplesheet and
belongs in the pipeline, not here.

Input: a data collection reading every matched report one LINE per row (a
separator the report cannot contain), with ``include_file_paths: source_path``.

Output schema:
    sample : Utf8                    report id (usually a lane or a library)
    total_read_pairs : Int64         read pairs given to AdapterRemoval
    total_reads : Int64              reads given to it (twice the pairs, or the SE count)
    well_aligned_read_pairs : Int64  pairs whose mates overlapped
    unaligned_read_pairs : Int64     pairs whose mates did not
    discarded_reads : Int64          reads dropped on quality or length
    singleton_reads : Int64          reads kept without their mate
    collapsed_pairs : Int64          pairs merged into one sequence (full length + truncated)
    truncated_collapsed_pairs : Int64  of those, the ones trimmed after merging
    retained_reads : Int64           sequences written out, the mapper's input
    retained_nucleotides : Int64     bases in them
    average_retained_length : Float64  mean length of a retained sequence, bp
    collapse_rate : Float64          collapsed pairs over total pairs, 0-1
    discard_rate : Float64           discarded reads over total reads, 0-1
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the template must scan the reports into.
RAW_DC_TAG = "adapterremoval_settings_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="reports", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "total_read_pairs": pl.Int64,
    "total_reads": pl.Int64,
    "well_aligned_read_pairs": pl.Int64,
    "unaligned_read_pairs": pl.Int64,
    "discarded_reads": pl.Int64,
    "singleton_reads": pl.Int64,
    "collapsed_pairs": pl.Int64,
    "truncated_collapsed_pairs": pl.Int64,
    "retained_reads": pl.Int64,
    "retained_nucleotides": pl.Int64,
    "average_retained_length": pl.Float64,
    "collapse_rate": pl.Float64,
    "discard_rate": pl.Float64,
}

RAW_LINE_COL = "raw"
SOURCE_PATH_COL = "source_path"

#: Report key (lower-cased, colon stripped) -> the field it feeds. The value is
#: an intermediate field name rather than an output column: the mate 1 and
#: mate 2 discards, the two singleton counts and the two collapsed-pair counts
#: are each summed into one output column below.
_KEYS: dict[str, str] = {
    "total number of read pairs": "total_read_pairs",
    "total number of reads": "total_reads_se",
    "number of well aligned read pairs": "well_aligned_read_pairs",
    "number of unaligned read pairs": "unaligned_read_pairs",
    "number of discarded mate 1 reads": "discarded_mate_1",
    "number of discarded mate 2 reads": "discarded_mate_2",
    "number of discarded reads": "discarded_se",
    "number of singleton mate 1 reads": "singleton_mate_1",
    "number of singleton mate 2 reads": "singleton_mate_2",
    "number of full-length collapsed pairs": "full_length_collapsed_pairs",
    "number of truncated collapsed pairs": "truncated_collapsed_pairs",
    "number of retained reads": "retained_reads",
    "number of retained nucleotides": "retained_nucleotides",
    "average length of retained reads": "average_retained_length",
}

#: Trailing dot-separated tokens of the report name that name the run mode or
#: the format rather than the unit the report is about.
_NAME_TOKENS = ("settings", "pe", "se", "collapsed", "paired", "single")


def _sample_from_path(source_path: str) -> str:
    stem = str(source_path).replace("\\", "/").rsplit("/", 1)[-1]
    tokens = stem.split(".")
    while len(tokens) > 1 and tokens[-1].lower() in _NAME_TOKENS:
        tokens.pop()
    return ".".join(tokens)


def _parse(source_path: str, lines: list[str]) -> dict:
    record: dict = {"sample": _sample_from_path(source_path)}
    for line in lines:
        text = (line or "").strip()
        if ":" not in text or text.startswith("["):
            continue
        key, _, value = text.partition(":")
        field = _KEYS.get(key.strip().lower())
        if field is None:
            continue
        # A count may be followed by a percentage in parentheses on some builds.
        token = value.strip().split(" ")[0].replace(",", "")
        try:
            record[field] = float(token)
        except ValueError:
            continue
    return record


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per settings report."""
    raw = sources["reports"]
    if raw.is_empty():
        raise ValueError("adapterremoval_settings: the scanned reports are empty")
    for column in (RAW_LINE_COL, SOURCE_PATH_COL):
        if column not in raw.columns:
            raise ValueError(
                f"adapterremoval_settings: no {column} column, the data collection must "
                f"scan one line per row with include_file_paths: source_path"
            )

    records = [
        _parse(str(path), group[RAW_LINE_COL].to_list())
        for (path,), group in raw.group_by([SOURCE_PATH_COL], maintain_order=True)
    ]
    records = [r for r in records if len(r) > 1]
    if not records:
        raise ValueError(
            "adapterremoval_settings: no report carried a [Trimming statistics] section"
        )

    frame = pl.DataFrame(records, infer_schema_length=None)
    # A report that carried none of a key's lines leaves its field out entirely,
    # so every field is materialised before anything reads it.
    fields = sorted(set(_KEYS.values()))
    frame = frame.with_columns(
        [pl.lit(None, dtype=pl.Float64).alias(f) for f in fields if f not in frame.columns]
    ).with_columns([pl.col(f).cast(pl.Float64, strict=False) for f in fields])

    pairs = pl.col("total_read_pairs")
    collapsed = pl.col("full_length_collapsed_pairs").fill_null(0) + pl.col(
        "truncated_collapsed_pairs"
    ).fill_null(0)
    discarded = (
        pl.col("discarded_mate_1").fill_null(0)
        + pl.col("discarded_mate_2").fill_null(0)
        + pl.col("discarded_se").fill_null(0)
    )
    singletons = pl.col("singleton_mate_1").fill_null(0) + pl.col("singleton_mate_2").fill_null(0)
    total_reads = pl.coalesce(pairs * 2, pl.col("total_reads_se"))

    out = frame.with_columns(
        pairs.cast(pl.Int64).alias("total_read_pairs"),
        total_reads.cast(pl.Int64).alias("total_reads"),
        pl.col("well_aligned_read_pairs").cast(pl.Int64),
        pl.col("unaligned_read_pairs").cast(pl.Int64),
        discarded.cast(pl.Int64).alias("discarded_reads"),
        singletons.cast(pl.Int64).alias("singleton_reads"),
        collapsed.cast(pl.Int64).alias("collapsed_pairs"),
        pl.col("truncated_collapsed_pairs").cast(pl.Int64),
        pl.col("retained_reads").cast(pl.Int64),
        pl.col("retained_nucleotides").cast(pl.Int64),
        pl.col("average_retained_length").cast(pl.Float64),
        pl.when(pairs > 0).then(collapsed / pairs).otherwise(None).alias("collapse_rate"),
        pl.when(total_reads > 0)
        .then(discarded / total_reads)
        .otherwise(None)
        .alias("discard_rate"),
    )
    return out.select(list(EXPECTED_SCHEMA)).sort("sample")
