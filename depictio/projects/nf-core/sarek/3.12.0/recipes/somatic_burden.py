"""Mutation burden of each tumour/normal pair: somatic variants per megabase of the target.

The count of somatic variants means little without the size of what was looked at, so the
burden is per megabase of the capture target: the intervals the run was given (the ``intervals``
parameter, an exome's baits) summed from the per-target depth table the coverage tab
already reads (``mosdepth_targets``, primary contigs only, one mosdepth pass). A whole-genome run
has no such table and the burden per megabase is left empty; the counts stay.

One row per pair and *basis*, the set of variants counted:

* ``consensus``: variants two callers or more kept (``somatic_variants.consensus``), the
  figure to quote;
* ``any caller``: the union of the callers' PASS calls, the upper bound;
* one row per caller: what that caller alone kept, to see which one drives the burden.

``variants`` is every kept variant, split in ``snvs`` and ``indels`` (a multi-nucleotide change
counts as neither); ``protein_altering`` is the part SnpEff ranks HIGH or MODERATE, null when the
pair was not annotated. The per-megabase columns divide by ``target_mb``.

A run whose pairs have no PASS somatic variant has nothing to show, so the recipe raises and the
collection, being optional, is skipped.

Output schema: see ``OUTPUT_SCHEMA``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_KIND_ORDER = {"consensus": 0, "union": 1, "caller": 2}
CONSENSUS = "consensus (2+ callers)"
UNION = "any caller"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="variants",
        dc_ref="somatic_variants",
        input_schema={
            "unit": pl.Utf8,
            "patient": pl.Utf8,
            "sample": pl.Utf8,
            "normal": pl.Utf8,
            "variant_type": pl.Utf8,
            "callers": pl.Utf8,
            "consensus": pl.Boolean,
            "annotated": pl.Boolean,
            "impact": pl.Utf8,
        },
    ),
    # The capture target, summed from the per-target depth table; a run without it keeps the
    # counts and leaves the per-megabase columns empty.
    RecipeSource(
        ref="targets",
        dc_ref="mosdepth_targets",
        optional=True,
        input_schema={"sample": pl.Utf8, "target_bp": pl.Int64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "unit": pl.Utf8,
    "patient": pl.Utf8,
    "sample": pl.Utf8,
    "normal": pl.Utf8,
    "basis": pl.Utf8,
    "basis_kind": pl.Utf8,
    "variants": pl.Int64,
    "snvs": pl.Int64,
    "indels": pl.Int64,
    "protein_altering": pl.Int64,
    "target_mb": pl.Float64,
    "per_mb": pl.Float64,
    "protein_altering_per_mb": pl.Float64,
}


def _target_mb(targets: pl.DataFrame | None, samples: pl.Series) -> pl.DataFrame:
    """``sample`` and ``target_mb``: the capture target of each tumour, in megabases.

    The size is summed from the sample's own targets; a sample the table lacks takes the median
    over the samples it holds. Without the table every size is null.
    """
    frame = pl.DataFrame({"sample": samples.unique()}, schema={"sample": pl.Utf8})
    if targets is None or targets.is_empty():
        return frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("target_mb"))
    per_sample = targets.group_by("sample").agg(
        (pl.col("target_bp").sum() / 1e6).alias("target_mb")
    )
    fallback = per_sample["target_mb"].median()
    return frame.join(per_sample, on="sample", how="left").with_columns(
        pl.col("target_mb").fill_null(fallback)
    )


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per pair and basis: the variants kept, their kinds and the burden per Mb."""
    variants = sources["variants"]
    if variants is None or variants.is_empty():
        raise ValueError("sarek somatic_burden: no somatic variant of a tumour/normal pair")
    callers = sorted({c for row in variants["callers"].unique().to_list() for c in row.split("+")})
    bases: list[tuple[str, str, pl.Expr]] = [
        (CONSENSUS, "consensus", pl.col("consensus")),
        (UNION, "union", pl.lit(True)),
        *[(c, "caller", pl.col("callers").str.split("+").list.contains(c)) for c in callers],
    ]
    pairs = variants.select("unit", "patient", "sample", "normal").unique(
        subset="unit", keep="first", maintain_order=True
    )
    sizes = _target_mb(sources.get("targets"), pairs["sample"])

    annotated = variants["annotated"].any()
    frames: list[pl.DataFrame] = []
    for basis, kind, keep in bases:
        counted = (
            variants.filter(keep)
            .group_by("unit")
            .agg(
                pl.len().cast(pl.Int64).alias("variants"),
                (pl.col("variant_type") == "SNP").sum().cast(pl.Int64).alias("snvs"),
                (pl.col("variant_type") == "INDEL").sum().cast(pl.Int64).alias("indels"),
                pl.col("impact")
                .is_in(["HIGH", "MODERATE"])
                .sum()
                .cast(pl.Int64)
                .alias("protein_altering"),
            )
        )
        frames.append(
            pairs.join(counted, on="unit", how="left").with_columns(
                pl.lit(basis).alias("basis"),
                pl.lit(kind).alias("basis_kind"),
            )
        )
    out = (
        pl.concat(frames)
        .join(sizes, on="sample", how="left")
        .with_columns(
            pl.col("variants", "snvs", "indels", "protein_altering").fill_null(0).cast(pl.Int64)
        )
    )
    if not annotated:
        out = out.with_columns(pl.lit(None, dtype=pl.Int64).alias("protein_altering"))
    return (
        out.with_columns(
            pl.when(pl.col("target_mb") > 0)
            .then(pl.col("variants") / pl.col("target_mb"))
            .otherwise(None)
            .alias("per_mb"),
            pl.when(pl.col("target_mb") > 0)
            .then(pl.col("protein_altering") / pl.col("target_mb"))
            .otherwise(None)
            .alias("protein_altering_per_mb"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(["unit", pl.col("basis_kind").replace_strict(_KIND_ORDER, default=9), "basis"])
    )
