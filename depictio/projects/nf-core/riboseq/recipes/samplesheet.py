"""nf-core/riboseq samplesheet as the sample hub every panel filters through.

The pipeline's ``--input`` sheet is
``sample,fastq_1,fastq_2,strandedness,type[,<design columns>]``: ``type`` says
which assay the library is (``rnaseq`` for total mRNA, ``riboseq`` for
ribosome footprints, ``tiseq`` for initiating-ribosome footprints), and the
translational-efficiency contrasts add whatever design columns they name
(for example a treatment and a pairing column). This recipe keeps every column
except the FASTQ paths, so any design column the run declared reaches the
filters and the sample sheet table without the template naming it.

Sources:
    samplesheet  the run's ``--input`` sheet (CSV or TSV). The template
                 repoints it at ``{SAMPLESHEET_FILE}``, auto-detected from
                 ``input/``.

Output: ``sample``, ``type``, ``read_type`` (``paired-end`` / ``single-end``),
then the sheet's other columns as text (``strandedness`` and the design
columns).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "type": pl.Utf8,
    "read_type": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "strandedness": pl.Utf8,
}

_FASTQ = ("fastq_1", "fastq_2")


def fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """A TSV sheet read as CSV arrives as one tab-joined column: split it."""
    if df.width != 1 or "\t" not in df.columns[0]:
        return df
    header = df.columns[0].split("\t")
    rows = [str(v).split("\t") for v in df[df.columns[0]].to_list()]
    return pl.DataFrame(
        {h: [r[i] if i < len(r) else None for r in rows] for i, h in enumerate(header)}
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per library: id, assay type, read layout, then the design columns."""
    sheet = fix_delimiter(sources["samplesheet"])
    sheet = sheet.rename({c: c.strip() for c in sheet.columns})
    sample_col = next(
        (c for c in sheet.columns if c.lower() in ("sample", "sample_id", "sampleid")),
        sheet.columns[0],
    )
    fastq2 = next((c for c in sheet.columns if c.lower() == "fastq_2"), None)
    if fastq2 is not None:
        read_type = (
            pl.when(
                pl.col(fastq2).is_null() | (pl.col(fastq2).cast(pl.Utf8).str.strip_chars() == "")
            )
            .then(pl.lit("single-end"))
            .otherwise(pl.lit("paired-end"))
        )
    else:
        read_type = pl.lit("single-end")
    type_col = next((c for c in sheet.columns if c.lower() == "type"), None)
    out = sheet.with_columns(
        pl.col(sample_col).cast(pl.Utf8).alias("_sample"),
        (pl.col(type_col).cast(pl.Utf8) if type_col else pl.lit("riboseq")).alias("_type"),
        read_type.alias("read_type"),
    )
    extra = [
        c
        for c in sheet.columns
        if c not in (sample_col, type_col) and c.lower() not in _FASTQ and c != "read_type"
    ]
    return out.select(
        pl.col("_sample").alias("sample"),
        pl.col("_type").alias("type"),
        pl.col("read_type"),
        *[pl.col(c).cast(pl.Utf8) for c in extra],
    ).unique(subset="sample", keep="first", maintain_order=True)
