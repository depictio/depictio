"""nf-core/raredisease sample hub: one row per sample, from the pedigree to the ranked calls.

raredisease runs on a family, and a family analysis starts from who is who. The hub
takes that from the pedigree file the run publishes (``pedigree/<family>.ped``: family,
sample, father, mother, sex, phenotype) and enriches it with what the other collections
hold. Every source but the pedigree-or-QC pair is optional: a missing one leaves its
columns null rather than failing the collection.

* ``role``: the sample's place in the family, from the pedigree alone. A sample that is
  somebody's father is ``Father``, somebody's mother ``Mother``; an affected sample with a
  declared parent is ``Proband``, an unaffected one ``Sibling``; anything else is ``Other``
  (a singleton, an affected parent keeps the role of parent). The group filter and every
  group colour of the dashboard use it, so the same word means the same thing everywhere;
* ``status``: Affected or Unaffected from the pedigree phenotype (2 or 1), Unknown otherwise;
* ``sex``: the declared sex (Male, Female, Unknown); ``x_relative_depth`` and
  ``y_relative_depth`` are the mean depth of the X and Y chromosomes over the sample's
  autosomal mean (``contig_depth``), null without that contig. They are shown as measured:
  no cut-off turns them into an inferred sex, because no published or tool-defined one
  is read by this template (peddy's own sex check is not an input);
* ``alignment_qc``: reads, alignment rate, mismatch rate, duplication, insert size, mean
  coverage, the share of the genome at 10x and 20x, and the mitochondrial depth;
* ``vcf_callset_summary``: the sample's PASS calls, SNVs, indels, Ts/Tv, het/hom ratio and
  median depth;
* ``ranked_genotypes``: how many ranked variants the sample carries, how many sit in the
  clinical set, fit a de novo model, or have a HIGH or MODERATE impact;
* ``family_checks``: ``parent_check``, the worst status over the sample's declared
  parent-child pairs (Check beats Consistent), null for a sample without one.

Output schema (a column a missing source would have filled is null):
    sample : Utf8, family_id : Utf8
    father : Utf8, mother : Utf8        declared parents, null when 0
    role : Utf8                          Proband / Father / Mother / Sibling / Other
    status : Utf8                        Affected / Unaffected / Unknown
    sex : Utf8, x_relative_depth : Float64, y_relative_depth : Float64
    total_reads : Int64, aligned_pct, mismatch_rate_pct, duplication_pct : Float64
    median_insert, mean_coverage, bases_10x_pct, bases_20x_pct, mito_depth : Float64
    pass_calls, snvs, indels : Int64
    ts_tv, het_hom_ratio, median_dp : Float64
    ranked_carried, clinical_carried, de_novo_carried, high_impact_carried : Int64
    parent_check : Utf8                  Consistent / Check / Too few sites
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="ped",
        glob_pattern="pedigree/*.ped",
        format="tsv",
        read_kwargs={
            "has_header": False,
            "new_columns": ["family_id", "sample_id", "father", "mother", "sex", "phenotype"],
            "infer_schema_length": 0,
        },
        input_schema={
            "family_id": pl.Utf8,
            "sample_id": pl.Utf8,
            "father": pl.Utf8,
            "mother": pl.Utf8,
            "sex": pl.Utf8,
            "phenotype": pl.Utf8,
        },
        optional=True,
    ),
    RecipeSource(
        ref="qc",
        dc_ref="alignment_qc",
        input_schema={"sample": pl.Utf8},
        optional=True,
    ),
    RecipeSource(
        ref="contigs",
        dc_ref="contig_depth",
        input_schema={"sample": pl.Utf8, "contig_class": pl.Utf8, "relative_depth": pl.Float64},
        optional=True,
    ),
    RecipeSource(
        ref="callset",
        dc_ref="vcf_callset_summary",
        input_schema={"sample": pl.Utf8},
        optional=True,
    ),
    RecipeSource(
        ref="genotypes",
        dc_ref="ranked_genotypes",
        input_schema={
            "sample": pl.Utf8,
            "variant_key": pl.Utf8,
            "is_clinical": pl.Boolean,
            "de_novo": pl.Boolean,
            "impact": pl.Utf8,
        },
        optional=True,
    ),
    RecipeSource(
        ref="checks",
        dc_ref="family_checks",
        input_schema={"sample": pl.Utf8, "relation": pl.Utf8, "check_status": pl.Utf8},
        optional=True,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "family_id": pl.Utf8,
    "father": pl.Utf8,
    "mother": pl.Utf8,
    "role": pl.Utf8,
    "status": pl.Utf8,
    "sex": pl.Utf8,
    "x_relative_depth": pl.Float64,
    "y_relative_depth": pl.Float64,
    "total_reads": pl.Int64,
    "aligned_pct": pl.Float64,
    "mismatch_rate_pct": pl.Float64,
    "duplication_pct": pl.Float64,
    "median_insert": pl.Float64,
    "mean_coverage": pl.Float64,
    "bases_10x_pct": pl.Float64,
    "bases_20x_pct": pl.Float64,
    "mito_depth": pl.Float64,
    "pass_calls": pl.Int64,
    "snvs": pl.Int64,
    "indels": pl.Int64,
    "ts_tv": pl.Float64,
    "het_hom_ratio": pl.Float64,
    "median_dp": pl.Float64,
    "ranked_carried": pl.Int64,
    "clinical_carried": pl.Int64,
    "de_novo_carried": pl.Int64,
    "high_impact_carried": pl.Int64,
    "parent_check": pl.Utf8,
}

_QC_COLUMNS = [
    "total_reads",
    "aligned_pct",
    "mismatch_rate_pct",
    "duplication_pct",
    "median_insert",
    "mean_coverage",
    "bases_10x_pct",
    "bases_20x_pct",
    "mito_depth",
]
_CALLSET_COLUMNS = ["pass_calls", "snvs", "indels", "ts_tv", "het_hom_ratio", "median_dp"]


def _pedigree(ped: pl.DataFrame | None) -> pl.DataFrame:
    """One row per sample: family, parents, role, status and declared sex."""
    if ped is None:
        return pl.DataFrame(schema={"sample": pl.Utf8})
    rows = ped.filter(~pl.col("family_id").str.starts_with("#")).with_columns(
        pl.col("father", "mother").replace(["0", "", "-9"], None)
    )
    fathers = set(rows["father"].drop_nulls().to_list())
    mothers = set(rows["mother"].drop_nulls().to_list())
    has_parent = pl.col("father").is_not_null() | pl.col("mother").is_not_null()
    affected = pl.col("phenotype") == "2"
    return rows.select(
        pl.col("sample_id").alias("sample"),
        pl.col("family_id"),
        pl.col("father"),
        pl.col("mother"),
        pl.when(pl.col("sample_id").is_in(list(fathers)))
        .then(pl.lit("Father"))
        .when(pl.col("sample_id").is_in(list(mothers)))
        .then(pl.lit("Mother"))
        .when(has_parent & affected)
        .then(pl.lit("Proband"))
        .when(has_parent)
        .then(pl.lit("Sibling"))
        .otherwise(pl.lit("Other"))
        .alias("role"),
        pl.when(affected)
        .then(pl.lit("Affected"))
        .when(pl.col("phenotype") == "1")
        .then(pl.lit("Unaffected"))
        .otherwise(pl.lit("Unknown"))
        .alias("status"),
        pl.when(pl.col("sex") == "1")
        .then(pl.lit("Male"))
        .when(pl.col("sex") == "2")
        .then(pl.lit("Female"))
        .otherwise(pl.lit("Unknown"))
        .alias("sex"),
    ).unique(subset="sample", keep="first", maintain_order=True)


def _sex_chromosome_depth(contigs: pl.DataFrame | None) -> pl.DataFrame:
    """Relative depth of X and Y per sample, as measured (null without that contig)."""
    if contigs is None:
        return pl.DataFrame(
            schema={
                "sample": pl.Utf8,
                "x_relative_depth": pl.Float64,
                "y_relative_depth": pl.Float64,
            }
        )
    per_class = contigs.filter(pl.col("contig_class").is_in(["X", "Y"])).pivot(
        on="contig_class", index="sample", values="relative_depth", aggregate_function="mean"
    )
    for need in ("X", "Y"):
        if need not in per_class.columns:
            per_class = per_class.with_columns(pl.lit(None, dtype=pl.Float64).alias(need))
    return per_class.select(
        "sample",
        pl.col("X").alias("x_relative_depth"),
        pl.col("Y").alias("y_relative_depth"),
    )


def _carried(genotypes: pl.DataFrame | None) -> pl.DataFrame:
    if genotypes is None:
        return pl.DataFrame(schema={"sample": pl.Utf8})
    return genotypes.group_by("sample").agg(
        pl.len().cast(pl.Int64).alias("ranked_carried"),
        pl.col("is_clinical").fill_null(False).sum().cast(pl.Int64).alias("clinical_carried"),
        pl.col("de_novo").fill_null(False).sum().cast(pl.Int64).alias("de_novo_carried"),
        pl.col("impact")
        .is_in(["HIGH", "MODERATE"])
        .sum()
        .cast(pl.Int64)
        .alias("high_impact_carried"),
    )


def _parent_check(checks: pl.DataFrame | None) -> pl.DataFrame:
    if checks is None:
        return pl.DataFrame(schema={"sample": pl.Utf8, "parent_check": pl.Utf8})
    rank = {"Check": 0, "Too few sites": 1, "Consistent": 2}
    pairs = checks.filter(
        (pl.col("relation") == "Parent-child") & pl.col("check_status").is_in(list(rank))
    )
    return (
        pairs.with_columns(pl.col("check_status").replace_strict(rank).alias("_rank"))
        .sort("_rank")
        .group_by("sample", maintain_order=True)
        .agg(pl.col("check_status").first().alias("parent_check"))
    )


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per sample of the pedigree, the QC or the callset."""
    ped = _pedigree(sources.get("ped"))
    qc = sources.get("qc")
    callset = sources.get("callset")
    names: list[str] = []
    for frame in (ped, qc, callset):
        if frame is not None and "sample" in frame.columns:
            names.extend(frame["sample"].drop_nulls().to_list())
    names = list(dict.fromkeys(names))
    if not names:
        raise ValueError(
            "raredisease samples: no pedigree, alignment QC or callset to name a sample"
        )
    hub = pl.DataFrame({"sample": names}, schema={"sample": pl.Utf8}).join(
        ped, on="sample", how="left"
    )
    if qc is not None:
        hub = hub.join(
            qc.select("sample", *[c for c in _QC_COLUMNS if c in qc.columns]),
            on="sample",
            how="left",
        )
    if callset is not None:
        hub = hub.join(
            callset.select("sample", *[c for c in _CALLSET_COLUMNS if c in callset.columns]),
            on="sample",
            how="left",
        )
    hub = (
        hub.join(_sex_chromosome_depth(sources.get("contigs")), on="sample", how="left")
        .join(_carried(sources.get("genotypes")), on="sample", how="left")
        .join(_parent_check(sources.get("checks")), on="sample", how="left")
    )
    for column, dtype in OUTPUT_SCHEMA.items():
        if column not in hub.columns:
            hub = hub.with_columns(pl.lit(None, dtype=dtype).alias(column))
    hub = hub.with_columns(
        pl.col("role").fill_null("Other"),
        pl.col("status").fill_null("Unknown"),
        pl.col("sex").fill_null("Unknown"),
    )
    return hub.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["family_id", "sample"], nulls_last=True
    )
