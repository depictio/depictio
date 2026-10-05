"""Top-expressed genes of Bambu's gene-level count matrix, for ComplexHeatmap.

``bambu`` writes ``counts_gene.txt`` as a single TSV with a header line that
names only the SAMPLE columns (the row-id column is unnamed) and a row per
Bambu gene: a GTF-style attribute string (``ccds_id ...; gene_biotype ...;
ENSG...``) followed by one integer count per sample. The ragged header (one
fewer field than every data row) means a normal ``has_header`` read fails with
"found more fields than defined in Schema", so this recipe reads the header
and the data as two separate passes over the same file and stitches them back
together.

Sources:
    header  the file's first line only (``n_rows: 1``, no header row of its
            own), giving the raw sample names in column order
    counts  the data rows (``skip_rows: 1``), generic ``column_1..column_N``
            names because polars was given no header to read

Output: wide matrix, ``gene_id`` (Utf8, the heatmap index, extracted from the
attribute string) + ``gene_biotype`` (Utf8) + one Float64 column per sample
(``.sorted`` suffix stripped), kept to the ``TOP_N`` genes with the highest
total count across samples, 208k rows of exon-level attribute strings (this
GTF's "gene" entries are exon-granular, not a real gene model) is neither
readable nor useful as a heatmap.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="header",
        glob_pattern="**/bambu/counts_gene.txt",
        format="tsv",
        # `truncate_ragged_lines`: this read only wants the header line, whose
        # 6 fields are one short of every data row below it (see module
        # docstring); without it polars scans ahead and raises on the width
        # mismatch even though `n_rows=1` never returns those rows.
        read_kwargs={
            "has_header": False,
            "n_rows": 1,
            "infer_schema_length": 0,
            "truncate_ragged_lines": True,
        },
    ),
    RecipeSource(
        ref="counts",
        glob_pattern="**/bambu/counts_gene.txt",
        format="tsv",
        read_kwargs={"has_header": False, "skip_rows": 1, "infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "gene_biotype": pl.Utf8,
}
# Sample columns are run-dependent, so they sit outside the declared schema
# and go unchecked (see deseq2/vst_top_variable.py for the same contract).

TOP_N = 50
_GENE_RE = r"(ENSG\d+)"
_BIOTYPE_RE = r"gene_biotype\s+([^;]+)"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Header + ragged data -> a top-N gene x sample count matrix."""
    header_row = sources["header"].row(0)
    sample_names = [strip_stage_suffixes(str(v)) for v in header_row]

    counts = sources["counts"]
    descriptor_col, *sample_generic_cols = counts.columns
    if len(sample_generic_cols) != len(sample_names):
        raise ValueError(
            f"bambu counts_gene: {len(sample_generic_cols)} data columns after the "
            f"descriptor but {len(sample_names)} sample names in the header"
        )

    df = counts.rename(dict(zip(sample_generic_cols, sample_names, strict=True)))
    df = df.with_columns(
        [pl.col(c).cast(pl.Float64, strict=False) for c in sample_names]
        + [
            pl.col(descriptor_col).str.extract(_GENE_RE, 1).alias("gene_id"),
            pl.col(descriptor_col).str.extract(_BIOTYPE_RE, 1).alias("gene_biotype"),
        ]
    )
    df = df.filter(pl.col("gene_id").is_not_null())
    df = df.with_columns(pl.sum_horizontal(sample_names).alias("_total"))
    df = df.sort("_total", descending=True).head(TOP_N).drop([descriptor_col, "_total"])
    return df.select(["gene_id", "gene_biotype", *sample_names])
