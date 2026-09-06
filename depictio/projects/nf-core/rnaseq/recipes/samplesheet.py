"""nf-core/rnaseq samplesheet with the condition and replicate it encodes.

The pipeline's ``--input`` sheet is ``sample,fastq_1,fastq_2,strandedness``:
the biological grouping every cross-sample panel needs is not a column, it is
inside the sample name. nf-core names its RNA-seq samples ``<condition>_REP<n>``
(the convention the pipeline's own DESeq2 QC step relies on), so this recipe
splits that name into ``condition`` and ``replicate`` and hands the dashboard a
sheet it can filter and group on.

A sheet whose names do not carry a replicate suffix still ingests: ``condition``
falls back to the sample name and ``replicate`` to 1, which leaves the sample
filter working and only makes the condition filter a no-op.

Sources:
    samplesheet  the run's ``--input`` sheet, CSV. The template repoints it at
                 the auto-detected ``{SAMPLESHEET_FILE}``.

Output: ``sample``, ``condition``, ``replicate`` (Int64), ``strandedness``,
``read_type`` (``paired-end`` / ``single-end``), then the FASTQ columns the
sheet declared, so the table stays a faithful record of what was run.
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "condition": pl.Utf8,
    "replicate": pl.Int64,
    "read_type": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "strandedness": pl.Utf8,
}

# `GM12878_REP1`, `treated_rep2`, `ctrl_R3`: condition, then the replicate index.
_REPLICATE = re.compile(r"^(?P<condition>.+?)[._-](?:rep|r)?(?P<replicate>\d+)$", re.IGNORECASE)


def split_sample_name(name: str) -> tuple[str, int]:
    """``GM12878_REP1`` -> ``("GM12878", 1)``; anything else -> ``(name, 1)``."""
    match = _REPLICATE.match(name)
    if not match:
        return name, 1
    return match.group("condition"), int(match.group("replicate"))


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """The sheet plus condition / replicate / read_type, sample column first."""
    sheet = sources["samplesheet"]
    sample_col = next(
        (c for c in sheet.columns if c.lower() in ("sample", "sample_id", "sampleid")),
        sheet.columns[0],
    )
    samples = sheet[sample_col].cast(pl.Utf8).to_list()
    split = [split_sample_name(s) for s in samples]

    fastq2 = next((c for c in sheet.columns if c.lower() == "fastq_2"), None)
    read_type = (
        [
            "single-end" if v is None or str(v).strip() == "" else "paired-end"
            for v in sheet[fastq2].cast(pl.Utf8).to_list()
        ]
        if fastq2
        else ["single-end"] * sheet.height
    )

    result = sheet.rename({sample_col: "sample"}).with_columns(
        [
            pl.col("sample").cast(pl.Utf8),
            pl.Series("condition", [c for c, _ in split], dtype=pl.Utf8),
            pl.Series("replicate", [r for _, r in split], dtype=pl.Int64),
            pl.Series("read_type", read_type, dtype=pl.Utf8),
        ]
    )
    if "strandedness" in result.columns:
        result = result.with_columns(pl.col("strandedness").cast(pl.Utf8))
    lead = ["sample", "condition", "replicate", "read_type"]
    if "strandedness" in result.columns:
        lead.append("strandedness")
    return result.select(lead + [c for c in result.columns if c not in lead])
