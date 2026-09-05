"""Unpivot the FusionInspector Pfam fields into one row per fusion protein domain.

The abridged fusion table ends with ``PFAM_LEFT`` and ``PFAM_RIGHT``: the Pfam
domains found on the 5' and the 3' partner protein, in amino-acid coordinates of
the predicted fusion protein. Each field packs every domain into a single string,
``NAME|START-END|EVALUE`` records joined by ``^``
(``I-set|48-110|3e-06^ig|49-110|6.1e-07``), and a lone ``.`` means the partner
contributes no domain.

The recipe unpivots that into a long frame, one row per domain, so the domain
composition of a fusion protein becomes bindable. A domain the breakpoint cuts
through is flagged by FusionInspector with a ``-PARTIAL`` suffix on the name and
a ``~`` on the truncated side of the range (``NUT-PARTIAL|~101-557|5.3e-228``),
so the tilde is stripped before the coordinates are parsed. Domains are reported
per transcript pair, so the same fusion is annotated several times with a largely
identical domain list; identical ``(fusion, partner, domain, start, end)`` rows
are de-duplicated. The e-value is turned into ``-log10`` for plotting, capped at
300 so a reported 0 does not become infinity.

Like the fusion output, this table carries no sample column: the abridged file
has none and the recipe harness concatenates the globbed files without their
path, so the fusion (and within it the domain) is the unit of analysis.

Output columns:
    fusion, partner, domain, domain_start, domain_end, domain_length, evalue,
    neg_log10_evalue, prot_fusion_type
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="fusions",
        glob_pattern="fusioninspector/*/*.FusionInspector.fusions.abridged.tsv",
        format="TSV",
        # `annots` embeds JSON-ish double quotes, so quoting must stay off.
        read_kwargs={"infer_schema_length": 10000, "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "fusion": pl.Utf8,
    "partner": pl.Utf8,
    "domain": pl.Utf8,
    "domain_start": pl.Int64,
    "domain_end": pl.Int64,
    "domain_length": pl.Int64,
    "evalue": pl.Float64,
    "neg_log10_evalue": pl.Float64,
    "prot_fusion_type": pl.Utf8,
}

# PFAM_LEFT holds the 5' partner's domains, PFAM_RIGHT the 3' partner's.
_PARTNERS = {"PFAM_LEFT": "5p", "PFAM_RIGHT": "3p"}

# A capped -log10 keeps the axis finite when a hit is reported with e-value 0.
_MAX_NEG_LOG10 = 300.0


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Explode the packed Pfam records of both partners into one row per domain."""
    df = sources["fusions"].select(
        pl.col("#FusionName").cast(pl.Utf8).alias("fusion"),
        pl.col("PROT_FUSION_TYPE")
        .cast(pl.Utf8)
        .replace(".", "unknown")
        .fill_null("unknown")
        .alias("prot_fusion_type"),
        pl.col("PFAM_LEFT").cast(pl.Utf8).fill_null("."),
        pl.col("PFAM_RIGHT").cast(pl.Utf8).fill_null("."),
    )

    frames = [
        df.filter(pl.col(field) != ".")
        .with_columns(pl.lit(partner, dtype=pl.Utf8).alias("partner"))
        .with_columns(pl.col(field).str.split("^").alias("record"))
        .explode("record")
        .select("fusion", "partner", "prot_fusion_type", "record")
        for field, partner in _PARTNERS.items()
    ]
    long = pl.concat(frames, how="vertical")
    evalue = pl.col("record").str.split("|").list.get(2).cast(pl.Float64, strict=False)
    # `~` marks the side a breakpoint truncated; it is not part of the coordinate.
    span = pl.col("record").str.split("|").list.get(1).str.replace_all("~", "").str.split("-")

    return (
        long.select(
            "fusion",
            "partner",
            pl.col("record").str.split("|").list.first().alias("domain"),
            span.list.first().cast(pl.Int64, strict=False).alias("domain_start"),
            span.list.get(1).cast(pl.Int64, strict=False).alias("domain_end"),
            evalue.alias("evalue"),
            "prot_fusion_type",
        )
        .with_columns(
            (pl.col("domain_end") - pl.col("domain_start") + 1).alias("domain_length"),
            pl.when(pl.col("evalue") > 0)
            .then((-pl.col("evalue").log10()).clip(upper_bound=_MAX_NEG_LOG10))
            .otherwise(_MAX_NEG_LOG10)
            .cast(pl.Float64)
            .alias("neg_log10_evalue"),
        )
        # One fusion is reported once per transcript pair, so the same domain is
        # listed several times with identical coordinates.
        .unique(
            subset=["fusion", "partner", "domain", "domain_start", "domain_end"],
            keep="first",
            maintain_order=True,
        )
        .sort("fusion", "partner", "domain_start", "domain")
        .select(list(EXPECTED_SCHEMA))
    )
