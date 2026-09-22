"""comBGC regions as coordinates: one row per BGC interval on its contig.

``summary.py`` is the analytic table (counts, classes, domain richness);
this one is the coordinate view the track renderers read. It keeps the same
rows but adds what a genome track needs and a summary table does not: a stable
per-region identifier (tool, product class, contig and interval, which is what
makes it unique per row: two tools can call the same class on the same
interval, and two contigs can carry a region at the same coordinates), the
region length as a float in kilobases (a track's score axis is numeric and
kilobases read better than bases), and a strand.

comBGC reports no orientation for a region, so ``strand`` is the GFF "no
strand" value ``.`` for every row. The arrow renderer only turns an arrow round
for ``-``, so every region is drawn left to right; that is a drawing
convention, not a claim about the cluster.

Output columns:
    sample, contig, region_id, tool, product_class, start, end, strand,
    length_kb, cds_count, complete
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        path="reports/combgc/combgc_complete_summary.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000, "null_values": ["NA", ""], "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "contig": pl.Utf8,
    "region_id": pl.Utf8,
    "tool": pl.Utf8,
    "product_class": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "length_kb": pl.Float64,
    "cds_count": pl.Int64,
    "complete": pl.Utf8,
}

# GFF's "orientation not known". comBGC reports none for a BGC region.
_NO_STRAND = "."


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename the comBGC coordinates and mint one identifier per region."""
    df = sources["summary"]

    def _col(name: str, dtype: type[pl.DataType]) -> pl.Expr:
        if name in df.columns:
            return pl.col(name).cast(dtype, strict=False)
        return pl.lit(None).cast(dtype)

    start = _col("BGC_start", pl.Int64)
    end = _col("BGC_end", pl.Int64)
    contig = _col("contig_id", pl.Utf8)
    tool = _col("Prediction_tool", pl.Utf8)
    product = _col("Product_class", pl.Utf8).fill_null("Unknown")
    return (
        df.select(
            _col("sample_id", pl.Utf8).alias("sample"),
            contig.alias("contig"),
            # Unique per row: the tool and the product class name the call, the
            # contig and the interval place it. The arrow label is the product
            # class (see the yaml), so this can afford to be long.
            pl.concat_str(
                [
                    tool.fill_null("unknown"),
                    pl.lit(" "),
                    product,
                    pl.lit(" "),
                    contig,
                    pl.lit(":"),
                    start.cast(pl.Utf8),
                    pl.lit("-"),
                    end.cast(pl.Utf8),
                ]
            ).alias("region_id"),
            tool.alias("tool"),
            product.alias("product_class"),
            start.alias("start"),
            end.alias("end"),
            pl.lit(_NO_STRAND, dtype=pl.Utf8).alias("strand"),
            (_col("BGC_length", pl.Int64) / 1000.0).cast(pl.Float64).alias("length_kb"),
            _col("CDS_count", pl.Int64).alias("cds_count"),
            _col("BGC_complete", pl.Utf8).fill_null("unknown").alias("complete"),
        )
        .drop_nulls(["contig", "start", "end"])
        .sort("sample", "contig", "start")
        .select(list(EXPECTED_SCHEMA))
    )
