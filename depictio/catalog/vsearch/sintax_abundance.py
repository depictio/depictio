"""Per-sample Phylum-level relative abundance from a SINTAX classification.

VSEARCH's ``--sintax`` classifier is the route amplicon pipelines take when
QIIME 2 is skipped (ITS, PacBio, IonTorrent), and it publishes a per-ASV
taxonomy table only: no abundance table of its own. The counts live in the
DADA2 ASV table written beside it, one column per sample. Joining the two and
aggregating to Phylum level yields the same ``sample`` / ``taxonomy`` /
``rel_abundance`` shape a QIIME 2 relative-abundance table has, so a dashboard
renders the SINTAX route with the components it already uses for the QIIME 2
one instead of degrading to MultiQC panels.

When a metadata data collection is present, its columns are joined generically,
so a grouped or facetted figure works on this table exactly as it does on the
QIIME 2 one. Without metadata only the core columns are returned.

Output schema:
    sample : Utf8               sample the counts came from
    taxonomy : Utf8             ``Kingdom;Phylum``, the joined lineage
    rel_abundance : Float64     share of the sample's classified counts
    Kingdom : Utf8              rank column, ``Unclassified`` when unresolved
    Phylum : Utf8               rank column, ``Unclassified`` when unresolved
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="asv", path="dada2/ASV_table.tsv", format="TSV"),
    # The sintax filename carries the reference-DB tag (e.g. `unite-fungi_8_2`),
    # so glob on it. The clean table's stem ends in the DB version digit
    # (`..._8_2.tsv`), so `*[0-9].tsv` matches it; the `.raw.tsv` variant always
    # has `raw` (no trailing digit) immediately before `.tsv`, so it never matches.
    RecipeSource(ref="tax", glob_pattern="sintax/ASV_tax_sintax.*[0-9].tsv", format="TSV"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "taxonomy": pl.Utf8,
    "rel_abundance": pl.Float64,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
}
# Metadata columns are user-defined; validated dynamically via OPTIONAL_SCHEMA = {}.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_UNCLASSIFIED = "Unclassified"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join ASV counts with sintax taxonomy, aggregate to per-sample Phylum abundance."""
    asv = sources["asv"]
    tax = sources["tax"]

    sample_cols = [c for c in asv.columns if c != "ASV_ID"]
    long = (
        asv.with_columns(pl.col(sample_cols).cast(pl.Float64))
        .unpivot(on=sample_cols, index="ASV_ID", variable_name="sample", value_name="count")
        .filter(pl.col("count") > 0)
    )

    tax_slim = tax.select(
        "ASV_ID",
        pl.col("Kingdom").cast(pl.Utf8).fill_null(_UNCLASSIFIED),
        pl.col("Phylum").cast(pl.Utf8).fill_null(_UNCLASSIFIED),
    )
    long = long.join(tax_slim, on="ASV_ID", how="left").with_columns(
        pl.col("Kingdom").fill_null(_UNCLASSIFIED),
        pl.col("Phylum").fill_null(_UNCLASSIFIED),
    )

    # Aggregate ASV counts to Phylum level per sample, then normalise to per-sample
    # relative abundance.
    phylum = long.group_by(["sample", "Kingdom", "Phylum"]).agg(
        pl.col("count").sum().alias("count")
    )
    totals = phylum.group_by("sample").agg(pl.col("count").sum().alias("_total"))
    phylum = (
        phylum.join(totals, on="sample", how="left")
        .with_columns((pl.col("count") / pl.col("_total")).alias("rel_abundance"))
        .with_columns((pl.col("Kingdom") + ";" + pl.col("Phylum")).alias("taxonomy"))
        .filter(pl.col("rel_abundance") > 0)
    )

    df = phylum.select("sample", "taxonomy", "rel_abundance", "Kingdom", "Phylum")

    # Join ALL metadata columns generically when metadata is available.
    metadata = sources.get("metadata")
    if metadata is not None and metadata.height > 0:
        id_col = next((c for c in ("ID", "sample") if c in metadata.columns), metadata.columns[0])
        if id_col != "sample":
            metadata = metadata.rename({id_col: "sample"})
        df = df.join(metadata, on="sample", how="left")

    return df.sort(["sample", "Phylum"])
