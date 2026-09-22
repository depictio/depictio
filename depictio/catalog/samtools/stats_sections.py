"""The distribution sections of a `samtools stats` report, as one long table.

`samtools stats` writes far more than the summary MultiQC surfaces: alongside
the ``SN`` key/value block it carries a read-length histogram (``RL``), a
coverage-depth histogram (``COV``), an indel-length spectrum (``ID``) and,
for paired data, an insert-size distribution (``IS``). On a long-read run
those three histograms are the alignment tab: read-length is the library, the
indel spectrum is the error mode, and the coverage histogram is how evenly the
reference was hit.

Row width varies by section (``SN`` is 4 tab-separated fields, ``ID`` is 4,
``IS`` is 6) and a normal CSV read infers the width from the first data row,
truncating everything wider. So the raw DC scans with a separator that never
occurs in the file, one whole line per row, and this recipe splits on ``\\t``
itself, exactly as the two `bcftools stats` recipes do.

Output: one row per (sample, section, bin). The sections do not share a y
axis, so each has its own value column and the others are null on that row,
which is what lets three separate profile tiles read the same collection
without a filter between them: the renderer drops a point whose y is null, so
a curve only ever draws the section it belongs to.

    sample, section, series, metric, bin
    n_reads   RL: reads at that read length
    n_bases   COV: bases at that depth
    n_indels  ID: insertions or deletions of that length (``series`` says which)
    n_pairs   IS: read pairs at that insert size
    reads_total .. supplementary_alignments
              the ``SN`` block, on the one ``section: SN`` row per sample, so
              a card reads six values rather than six times a bin count

``identity_pct`` is ``100 * (1 - error rate)``: the per-base agreement with
the reference, which is the number a long-read run is judged on and the one
`samtools stats` reports inverted.

Histograms are decimated to ``MAX_POINTS`` geometric bins per sample and
section before they leave the recipe: ``RL`` alone is 5060 rows per sample on
the nanoseq megatest, and a profile is never sampled downstream.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

RAW_DC_TAG = "samtools_stats_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

#: Column holding one full report line (raw DC scanned with a separator that
#: never occurs in the file).
RAW_LINE_COL = "raw_line"
#: Column carrying the report's path (``include_file_paths`` on the raw DC).
SOURCE_PATH_COL = "source_path"

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "section": pl.Utf8,
    "series": pl.Utf8,
    "metric": pl.Utf8,
    "bin": pl.Float64,
    "n_reads": pl.Float64,
    "n_bases": pl.Float64,
    "n_indels": pl.Float64,
    "n_pairs": pl.Float64,
    "reads_total": pl.Float64,
    "reads_mapped": pl.Float64,
    "reads_mapped_pct": pl.Float64,
    "bases_mapped": pl.Float64,
    "error_rate": pl.Float64,
    "identity_pct": pl.Float64,
    "average_length": pl.Float64,
    "maximum_length": pl.Float64,
    "average_quality": pl.Float64,
    "supplementary_alignments": pl.Float64,
}

#: Points kept per sample and section. A profile is rendered whole.
MAX_POINTS = 200

#: `SN` key (colon stripped) -> output column.
_SN_KEYS: dict[str, str] = {
    "raw total sequences": "reads_total",
    "reads mapped": "reads_mapped",
    "bases mapped (cigar)": "bases_mapped",
    "error rate": "error_rate",
    "average length": "average_length",
    "maximum length": "maximum_length",
    "average quality": "average_quality",
    "supplementary alignments": "supplementary_alignments",
}
_SN_COLUMNS = [
    "reads_total",
    "reads_mapped",
    "reads_mapped_pct",
    "bases_mapped",
    "error_rate",
    "identity_pct",
    "average_length",
    "maximum_length",
    "average_quality",
    "supplementary_alignments",
]
_VALUE_COLUMNS = ["n_reads", "n_bases", "n_indels", "n_pairs"]


def _sample_of(path: str) -> str:
    """`minimap2/samtools_stats/A549_R1.sorted.bam.stats` -> `A549_R1`.

    ``.stats`` is dropped here rather than in ``strip_stage_suffixes``: that
    list is shared with every other recipe, and ``stats`` is a plausible
    sample-name token in a way that ``sorted`` or ``mkD`` is not.
    """
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    for suffix in (".stats", ".stat"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return strip_stage_suffixes(name)


def _number(text: str | None) -> float | None:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def _decimate(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sum a histogram into at most ``MAX_POINTS`` geometric bins.

    Geometric rather than linear because every one of these distributions is
    heavy-tailed: 200 equal-width bins over a 5 to 16 679 read-length range
    would put the whole library in the first bin.
    """
    if len(points) <= MAX_POINTS:
        return points
    xs = np.array([p[0] for p in points], dtype=np.float64)
    ys = np.array([p[1] for p in points], dtype=np.float64)
    low = max(float(xs.min()), 1e-9)
    high = max(float(xs.max()), low * (1.0 + 1e-9))
    edges = np.geomspace(low, high, MAX_POINTS + 1)
    index = np.clip(np.searchsorted(edges, xs, side="right") - 1, 0, MAX_POINTS - 1)
    centres = np.sqrt(edges[:-1] * edges[1:])
    summed = np.bincount(index, weights=ys, minlength=MAX_POINTS)
    used = np.bincount(index, minlength=MAX_POINTS) > 0
    return [(float(centres[i]), float(summed[i])) for i in range(MAX_POINTS) if used[i]]


def _rows_for(
    sample: str, section: str, metric: str, series: str, column: str, points
) -> list[dict]:
    return [
        {
            "sample": sample,
            "section": section,
            "series": series,
            "metric": metric,
            "bin": x,
            column: y,
        }
        for x, y in _decimate(list(points))
    ]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Raw report lines -> long rows, one per (sample, section, bin)."""
    raw = sources["raw"]
    rows: list[dict[str, object]] = []

    for (path,), block in raw.group_by(SOURCE_PATH_COL, maintain_order=True):
        sample = _sample_of(str(path))
        summary: dict[str, float | None] = {}
        read_lengths: list[tuple[float, float]] = []
        coverage: list[tuple[float, float]] = []
        insertions: list[tuple[float, float]] = []
        deletions: list[tuple[float, float]] = []
        inserts: list[tuple[float, float]] = []

        for line in block[RAW_LINE_COL].to_list():
            fields = str(line or "").split("\t")
            tag = fields[0]
            if tag == "SN" and len(fields) >= 3:
                column = _SN_KEYS.get(fields[1].rstrip(":").strip())
                if column:
                    summary[column] = _number(fields[2])
            elif tag == "RL" and len(fields) >= 3:
                x, y = _number(fields[1]), _number(fields[2])
                if x is not None and y is not None:
                    read_lengths.append((x, y))
            elif tag == "COV" and len(fields) >= 4:
                x, y = _number(fields[2]), _number(fields[3])
                if x is not None and y is not None:
                    coverage.append((x, y))
            elif tag == "ID" and len(fields) >= 4:
                x, ins, dele = _number(fields[1]), _number(fields[2]), _number(fields[3])
                if x is not None:
                    if ins is not None:
                        insertions.append((x, ins))
                    if dele is not None:
                        deletions.append((x, dele))
            elif tag == "IS" and len(fields) >= 3:
                x, y = _number(fields[1]), _number(fields[2])
                if x is not None and y is not None:
                    inserts.append((x, y))

        mapped, total = summary.get("reads_mapped"), summary.get("reads_total")
        summary["reads_mapped_pct"] = (mapped / total * 100.0) if mapped and total else None
        error = summary.get("error_rate")
        summary["identity_pct"] = (1.0 - error) * 100.0 if error is not None else None
        rows.append(
            {
                "sample": sample,
                "section": "SN",
                "series": sample,
                "metric": "summary",
                "bin": None,
                **{c: summary.get(c) for c in _SN_COLUMNS},
            }
        )

        rows += _rows_for(sample, "RL", "read_length", sample, "n_reads", read_lengths)
        rows += _rows_for(sample, "COV", "coverage_depth", sample, "n_bases", coverage)
        rows += _rows_for(
            sample, "ID", "insertions", f"{sample} insertions", "n_indels", insertions
        )
        rows += _rows_for(sample, "ID", "deletions", f"{sample} deletions", "n_indels", deletions)
        rows += _rows_for(sample, "IS", "insert_size", sample, "n_pairs", inserts)

    if not rows:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)

    frame = pl.DataFrame(rows, infer_schema_length=None)
    for column, dtype in EXPECTED_SCHEMA.items():
        if column not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=dtype).alias(column))
    return (
        frame.with_columns(
            pl.col("sample").cast(pl.Utf8),
            pl.col("section").cast(pl.Utf8),
            pl.col("series").cast(pl.Utf8),
            pl.col("metric").cast(pl.Utf8),
            *[
                pl.col(c).cast(pl.Float64, strict=False)
                for c in ("bin", *_VALUE_COLUMNS, *_SN_COLUMNS)
            ],
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "section", "series", "bin"], nulls_last=False)
    )
