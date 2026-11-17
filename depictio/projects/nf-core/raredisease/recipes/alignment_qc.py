"""nf-core/raredisease alignment QC, one row per sample, from the Picard and mosdepth reports.

raredisease aligns every sample, marks duplicates and publishes the QC the
variant interpretation relies on next to the alignment. This recipe reads each
report straight off its file instead of through MultiQC, so every number sits
in one row per sample the dashboard can filter, rank and chart:

* ``qc_bam/<S>_multiplemetrics.CollectMultipleMetrics.alignment_summary_metrics``
  (Picard CollectAlignmentSummaryMetrics): reads, alignment rate, mismatch rate,
  read length, chimeras, soft clipping. The ``PAIR`` row is read for a paired
  library, the ``UNPAIRED`` one otherwise;
* ``...insert_size_metrics`` (CollectInsertSizeMetrics): median, mean and spread
  of the insert size of the ``FR`` pairs;
* ``qc_bam/<S>_wgsmetrics.CollectWgsMetrics.coverage_metrics`` (whole genome):
  mean and median coverage and the share of the genome at 1, 10, 20 and 30x;
* ``qc_bam/<S>_hsmetrics.CollectHsMetrics.coverage_metrics`` (target capture):
  fold enrichment, mean target coverage and the share of the target at 20x;
* ``alignment/<S>_sorted_md.metrics.txt`` (MarkDuplicates): duplication rate;
* ``qc_bam/<S>_mosdepth.mosdepth.summary.txt``: the nuclear and mitochondrial
  mean depth, and their ratio (a proxy for the mitochondrial copy number).

Every source but the alignment summary is optional: a run that skipped the whole
genome metrics (exome) or the hybrid-selection metrics (genome) leaves those
columns null. Picard writes several sections per file (``## METRICS CLASS``, then
a header row and the rows, then a histogram); only the named class is read.

Output schema (a column the run did not write is null):
    sample : Utf8
    total_reads : Int64             reads in the alignment summary (PAIR row)
    aligned_pct : Float64           percent of the reads aligned
    mismatch_rate_pct : Float64     mismatches per aligned base, percent
    mean_read_length : Float64
    chimera_pct : Float64           percent of the reads that are chimeric
    softclip_pct : Float64          percent of the bases soft-clipped
    duplication_pct : Float64       MarkDuplicates PERCENT_DUPLICATION x 100
    median_insert : Float64         median insert size of the FR pairs
    mean_insert : Float64
    insert_sd : Float64             standard deviation of the insert size
    mean_coverage : Float64         CollectWgsMetrics MEAN_COVERAGE
    median_coverage : Float64
    bases_1x_pct : Float64          genome at 1x or deeper, percent
    bases_10x_pct : Float64
    bases_20x_pct : Float64
    bases_30x_pct : Float64
    excluded_pct : Float64          bases the metrics excluded (mapping quality, overlap, duplicates), percent
    nuclear_depth : Float64         length-weighted mean depth of the nuclear contigs (mosdepth)
    mito_depth : Float64            mean depth of the mitochondrion
    mito_to_nuclear : Float64       mitochondrial over nuclear depth
    hs_fold_enrichment : Float64    CollectHsMetrics FOLD_ENRICHMENT
    hs_mean_target_coverage : Float64
    hs_target_20x_pct : Float64     target bases at 20x or deeper, percent
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

_RAW = {
    "separator": "\x1e",
    "has_header": False,
    "new_columns": ["raw_line"],
    "quote_char": None,
    "infer_schema_length": 0,
}
_RAW_SCHEMA = {"raw_line": pl.Utf8, "source_path": pl.Utf8}


def _raw(ref: str, pattern: str, *, optional: bool = True) -> RecipeSource:
    return RecipeSource(
        ref=ref,
        glob_pattern=pattern,
        format="csv",
        read_kwargs=dict(_RAW),
        source_path="source_path",
        input_schema=dict(_RAW_SCHEMA),
        optional=optional,
    )


# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    _raw(
        "align",
        "qc_bam/*_multiplemetrics.CollectMultipleMetrics.alignment_summary_metrics",
        optional=False,
    ),
    _raw("insert", "qc_bam/*_multiplemetrics.CollectMultipleMetrics.insert_size_metrics"),
    _raw("wgs", "qc_bam/*_wgsmetrics.CollectWgsMetrics.coverage_metrics"),
    _raw("hs", "qc_bam/*_hsmetrics.CollectHsMetrics.coverage_metrics"),
    _raw("dups", "alignment/*_sorted_md.metrics.txt"),
    _raw("mosdepth", "qc_bam/*_mosdepth.mosdepth.summary.txt"),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "total_reads": pl.Int64,
    "aligned_pct": pl.Float64,
    "mismatch_rate_pct": pl.Float64,
    "mean_read_length": pl.Float64,
    "chimera_pct": pl.Float64,
    "softclip_pct": pl.Float64,
    "duplication_pct": pl.Float64,
    "median_insert": pl.Float64,
    "mean_insert": pl.Float64,
    "insert_sd": pl.Float64,
    "mean_coverage": pl.Float64,
    "median_coverage": pl.Float64,
    "bases_1x_pct": pl.Float64,
    "bases_10x_pct": pl.Float64,
    "bases_20x_pct": pl.Float64,
    "bases_30x_pct": pl.Float64,
    "excluded_pct": pl.Float64,
    "nuclear_depth": pl.Float64,
    "mito_depth": pl.Float64,
    "mito_to_nuclear": pl.Float64,
    "hs_fold_enrichment": pl.Float64,
    "hs_mean_target_coverage": pl.Float64,
    "hs_target_20x_pct": pl.Float64,
}

# The sample is the file name up to the tool tag the pipeline appends.
_SAMPLE_RES = {
    "align": r"([^/]+?)_multiplemetrics\.",
    "insert": r"([^/]+?)_multiplemetrics\.",
    "wgs": r"([^/]+?)_wgsmetrics\.",
    "hs": r"([^/]+?)_hsmetrics\.",
    "dups": r"([^/]+?)_sorted_md\.metrics\.txt$",
    "mosdepth": r"([^/]+?)_mosdepth\.mosdepth\.summary\.txt$",
}
_NUCLEAR = re.compile(r"^(?:chr)?(?:[1-9]|1[0-9]|2[0-2]|X|Y)$")
_MITO = {"MT", "M", "chrM", "chrMT"}


def _number(value: str | None) -> float | None:
    """A Picard cell as a float: ``?``, empty and non-numeric cells are null."""
    if value is None or value in ("", "?"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _files(source: pl.DataFrame | None, ref: str) -> dict[str, list[str]]:
    """Sample -> the lines of its file."""
    if source is None:
        return {}
    pattern = re.compile(_SAMPLE_RES[ref])
    out: dict[str, list[str]] = {}
    for path in source["source_path"].unique(maintain_order=True).to_list():
        match = pattern.search(path)
        if match:
            lines = source.filter(pl.col("source_path") == path)["raw_line"].to_list()
            out[match.group(1)] = [line or "" for line in lines]
    return out


def _section(lines: list[str], klass: str) -> list[dict[str, str]]:
    """The rows of the Picard ``## METRICS CLASS`` section named ``klass``."""
    for i, line in enumerate(lines):
        if line.startswith("## METRICS CLASS") and klass in line and i + 1 < len(lines):
            header = lines[i + 1].split("\t")
            rows = []
            for row in lines[i + 2 :]:
                if not row or row.startswith("#"):
                    break
                rows.append(dict(zip(header, row.split("\t"), strict=False)))
            return rows
    return []


def _pick(rows: list[dict[str, str]], key: str, prefer: tuple[str, ...]) -> dict[str, str]:
    """The row whose ``key`` is the first of ``prefer`` present, else the first row."""
    for want in prefer:
        for row in rows:
            if row.get(key) == want:
                return row
    return rows[0] if rows else {}


def _mosdepth(lines: list[str]) -> dict[str, float | None]:
    """Nuclear (length-weighted) and mitochondrial mean depth from a summary file."""
    length = bases = 0.0
    mito = None
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) < 4:
            continue
        contig = cells[0]
        if _NUCLEAR.match(contig):
            length += float(cells[1])
            bases += float(cells[2])
        elif contig in _MITO:
            mito = float(cells[3])
    nuclear = bases / length if length else None
    ratio = mito / nuclear if mito is not None and nuclear else None
    return {"nuclear_depth": nuclear, "mito_depth": mito, "mito_to_nuclear": ratio}


def _pct(value: float | None) -> float | None:
    return None if value is None else value * 100.0


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per sample, every column from its reports."""
    files = {ref: _files(sources.get(ref), ref) for ref in _SAMPLE_RES}
    samples = sorted({s for per_ref in files.values() for s in per_ref})
    if not samples:
        raise ValueError("raredisease alignment_qc: no Picard or mosdepth report under qc_bam/")
    rows = []
    for sample in samples:
        row: dict[str, float | int | str | None] = dict.fromkeys(OUTPUT_SCHEMA)
        row["sample"] = sample
        if sample in files["align"]:
            r = _pick(
                _section(files["align"][sample], "AlignmentSummaryMetrics"),
                "CATEGORY",
                ("PAIR", "UNPAIRED"),
            )
            reads = _number(r.get("TOTAL_READS"))
            row["total_reads"] = None if reads is None else int(reads)
            row["aligned_pct"] = _pct(_number(r.get("PCT_PF_READS_ALIGNED")))
            row["mismatch_rate_pct"] = _pct(_number(r.get("PF_MISMATCH_RATE")))
            row["mean_read_length"] = _number(r.get("MEAN_READ_LENGTH"))
            row["chimera_pct"] = _pct(_number(r.get("PCT_CHIMERAS")))
            row["softclip_pct"] = _pct(_number(r.get("PCT_SOFTCLIP")))
        if sample in files["dups"]:
            r = _pick(_section(files["dups"][sample], "DuplicationMetrics"), "LIBRARY", ())
            row["duplication_pct"] = _pct(_number(r.get("PERCENT_DUPLICATION")))
        if sample in files["insert"]:
            r = _pick(
                _section(files["insert"][sample], "InsertSizeMetrics"), "PAIR_ORIENTATION", ("FR",)
            )
            row["median_insert"] = _number(r.get("MEDIAN_INSERT_SIZE"))
            row["mean_insert"] = _number(r.get("MEAN_INSERT_SIZE"))
            row["insert_sd"] = _number(r.get("STANDARD_DEVIATION"))
        if sample in files["wgs"]:
            r = _pick(_section(files["wgs"][sample], "WgsMetrics"), "GENOME_TERRITORY", ())
            row["mean_coverage"] = _number(r.get("MEAN_COVERAGE"))
            row["median_coverage"] = _number(r.get("MEDIAN_COVERAGE"))
            for pct, key in (
                ("1", "bases_1x_pct"),
                ("10", "bases_10x_pct"),
                ("20", "bases_20x_pct"),
                ("30", "bases_30x_pct"),
            ):
                row[key] = _pct(_number(r.get(f"PCT_{pct}X")))
            row["excluded_pct"] = _pct(_number(r.get("PCT_EXC_TOTAL")))
        if sample in files["hs"]:
            r = _pick(_section(files["hs"][sample], "HsMetrics"), "BAIT_SET", ())
            row["hs_fold_enrichment"] = _number(r.get("FOLD_ENRICHMENT"))
            row["hs_mean_target_coverage"] = _number(r.get("MEAN_TARGET_COVERAGE"))
            row["hs_target_20x_pct"] = _pct(_number(r.get("PCT_TARGET_BASES_20X")))
        if sample in files["mosdepth"]:
            row.update(_mosdepth(files["mosdepth"][sample]))
        rows.append(row)
    frame = pl.DataFrame(rows, schema=OUTPUT_SCHEMA, strict=False)
    return frame.with_columns(pl.col(pl.Float64).round(4))
