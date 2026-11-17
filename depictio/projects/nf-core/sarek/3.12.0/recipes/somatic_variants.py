"""One row per distinct somatic variant of a tumour/normal pair, the callers merged.

``somatic_calls`` has one row per call per caller, filtered ones included: the right grain
to see what each caller set aside, the wrong one to ask *what did the tumour gain*. This
recipe keeps the calls a caller kept (FILTER PASS) and folds the callers that agree on a
variant (contig, position and alleles) into one row, which is what a reader counts, plots
and ranks:

* ``callers`` / ``n_callers`` / ``support``: who made the call and how many did. A variant
  two callers or more kept is the *consensus* set (``consensus``), the one to trust for a
  burden or a gene list; a variant one caller alone made is where the false positives live;
* ``tumour_vaf`` and ``normal_vaf``: the median over the callers that made the call, with the
  tumour's and the normal's depth. A true somatic call has a tumour allele fraction well above
  0 and a normal one near 0, so ``normal_class`` says where the normal's fraction falls
  (``Clean``, ``Trace`` or ``Germline-like``);
* ``substitution``: the six classes of a single-nucleotide change, the reference taken as the
  pyrimidine of the pair (C>T is also G>A on the other strand), null for an indel;
* ``origin`` / ``germline_callers``: whether a PASS germline call of the normal is the same
  variant, a likely inherited variant the somatic callers failed to subtract;
* ``gene``, ``impact``, ``consequence``, ``hgvs_p``: SnpEff's worst consequence for the
  variant when the run annotated the pair's calls (``annotated``), null otherwise;
* ``priority``: a rank for a candidate list, by impact class, then by the callers in agreement,
  then by the tumour allele fraction (``impact_rank`` * 1000 + ``n_callers`` * 100 + the
  allele fraction in percent). It orders a list; it is not a probability of anything.

Only pairs are listed: a tumour called on its own has no normal to subtract and stays in
``somatic_calls``. A run whose pairs have no PASS call has nothing to show, so the recipe
raises and the collection, being optional, is skipped.

Output schema: see ``OUTPUT_SCHEMA``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.vcf_somatic import IMPACT_RANK, annotation_by_variant

#: The cut-offs of ``normal_class`` and of ``vaf_class``, in allele fraction.
NORMAL_TRACE = 0.03
NORMAL_GERMLINE = 0.10

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="somatic",
        dc_ref="somatic_vs_germline",
        input_schema={
            "unit": pl.Utf8,
            "patient": pl.Utf8,
            "sample": pl.Utf8,
            "normal": pl.Utf8,
            "caller": pl.Utf8,
            "chrom": pl.Utf8,
            "pos": pl.Int64,
            "ref": pl.Utf8,
            "alt": pl.Utf8,
            "variant_key": pl.Utf8,
            "variant_type": pl.Utf8,
            "is_pass": pl.Boolean,
            "tumour_vaf": pl.Float64,
            "tumour_dp": pl.Int64,
            "normal_vaf": pl.Float64,
            "normal_dp": pl.Int64,
            "germline_callers": pl.Int64,
            "in_germline": pl.Boolean,
            "origin": pl.Utf8,
        },
    ),
    # The SnpEff-annotated VCFs of the pairs' calls; a run that annotated none keeps the
    # collection without the gene columns.
    RecipeSource(
        ref="annotated",
        dc_ref="somatic_ann_vcf_raw",
        optional=True,
        input_schema={"raw_line": pl.Utf8, "source_path": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "unit": pl.Utf8,
    "patient": pl.Utf8,
    "sample": pl.Utf8,
    "normal": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "ref": pl.Utf8,
    "alt": pl.Utf8,
    "variant_key": pl.Utf8,
    "variant_type": pl.Utf8,
    "substitution": pl.Utf8,
    "callers": pl.Utf8,
    "n_callers": pl.Int64,
    "support": pl.Utf8,
    "consensus": pl.Boolean,
    "tumour_vaf": pl.Float64,
    "tumour_dp": pl.Int64,
    "normal_vaf": pl.Float64,
    "normal_dp": pl.Int64,
    "normal_class": pl.Utf8,
    "germline_callers": pl.Int64,
    "in_germline": pl.Boolean,
    "origin": pl.Utf8,
    "annotated": pl.Boolean,
    "gene": pl.Utf8,
    "gene_id": pl.Utf8,
    "impact": pl.Utf8,
    "consequence": pl.Utf8,
    "hgvs_p": pl.Utf8,
    "aa_pos": pl.Int64,
    "priority": pl.Int64,
}

NORMAL_CLEAN_LABEL = "Clean in the normal"
NORMAL_TRACE_LABEL = "Trace in the normal"
NORMAL_GERMLINE_LABEL = "Germline-like in the normal"

_COMPLEMENT = {"A": "T", "C": "G", "G": "C", "T": "A"}
_PYRIMIDINES = ("C", "T")


def _substitution() -> pl.Expr:
    """``C>T`` of a single-nucleotide change, reference folded onto the pyrimidine strand."""
    ref, alt = pl.col("ref").str.to_uppercase(), pl.col("alt").str.to_uppercase()
    flip = ref.is_in(["A", "G"])
    new_ref = pl.when(flip).then(ref.replace_strict(_COMPLEMENT, default=None)).otherwise(ref)
    new_alt = pl.when(flip).then(alt.replace_strict(_COMPLEMENT, default=None)).otherwise(alt)
    valid = (
        (pl.col("variant_type") == "SNP")
        & ref.is_in(list(_COMPLEMENT))
        & alt.is_in(list(_COMPLEMENT))
    )
    return (
        pl.when(valid & new_ref.is_in(list(_PYRIMIDINES)))
        .then(pl.concat_str([new_ref, pl.lit(">"), new_alt]))
        .otherwise(None)
    )


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Merge the callers' PASS calls of each pair into one row per variant."""
    calls = sources["somatic"].filter(pl.col("is_pass"))  # type: ignore[union-attr]
    if calls.is_empty():
        raise ValueError("sarek somatic_variants: no PASS somatic call of a tumour/normal pair")

    merged = (
        calls.group_by(["unit", "variant_key"], maintain_order=True)
        .agg(
            pl.col("patient").first(),
            pl.col("sample").first(),
            pl.col("normal").first(),
            pl.col("chrom").first(),
            pl.col("pos").first(),
            pl.col("ref").first(),
            pl.col("alt").first(),
            pl.col("variant_type").first(),
            pl.col("caller").unique().sort().str.join("+").alias("callers"),
            pl.col("caller").n_unique().cast(pl.Int64).alias("n_callers"),
            pl.col("tumour_vaf").median(),
            pl.col("tumour_dp").median().round(0).cast(pl.Int64),
            pl.col("normal_vaf").median(),
            pl.col("normal_dp").median().round(0).cast(pl.Int64),
            pl.col("germline_callers").max(),
            pl.col("in_germline").any(),
            pl.col("origin").first(),
        )
        .with_columns(
            _substitution().alias("substitution"),
            (pl.col("n_callers") >= 2).alias("consensus"),
            pl.when(pl.col("n_callers") == 1)
            .then(pl.lit("1 caller"))
            .otherwise(pl.col("n_callers").cast(pl.Utf8) + pl.lit(" callers"))
            .alias("support"),
            pl.when(pl.col("normal_vaf").is_null() | (pl.col("normal_vaf") < NORMAL_TRACE))
            .then(pl.lit(NORMAL_CLEAN_LABEL))
            .when(pl.col("normal_vaf") < NORMAL_GERMLINE)
            .then(pl.lit(NORMAL_TRACE_LABEL))
            .otherwise(pl.lit(NORMAL_GERMLINE_LABEL))
            .alias("normal_class"),
        )
    )

    annotated = sources.get("annotated")
    if annotated is not None and not annotated.is_empty():
        ann = annotation_by_variant(annotated)
        merged = merged.join(ann, on=["unit", "variant_key"], how="left")
    else:
        merged = merged.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("gene"),
            pl.lit(None, dtype=pl.Utf8).alias("gene_id"),
            pl.lit(None, dtype=pl.Utf8).alias("impact"),
            pl.lit(None, dtype=pl.Utf8).alias("consequence"),
            pl.lit(None, dtype=pl.Utf8).alias("hgvs_p"),
            pl.lit(None, dtype=pl.Int64).alias("aa_pos"),
        )

    impact_rank = pl.col("impact").replace_strict(IMPACT_RANK, default=0, return_dtype=pl.Int64)
    return (
        merged.with_columns(
            pl.col("impact").is_not_null().alias("annotated"),
            (
                impact_rank * 1000
                + pl.col("n_callers") * 100
                + (pl.col("tumour_vaf").fill_null(0.0) * 100).round(0).cast(pl.Int64)
            ).alias("priority"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(["unit", "chrom", "pos", "variant_key"])
    )
