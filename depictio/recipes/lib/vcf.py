"""Read a bgzipped VCF into a long per-variant frame with Polars alone.

No pipeline in this repo ships a VCF reader dependency (no cyvcf2, no pysam, no
bcftools binary), and every variant-level panel a variant-calling template wants
(per-caller concordance, VAF against depth, a lollipop along a gene, a rainfall
plot) needs one row per variant. bgzip is gzip-compatible, so Polars reads a
``.vcf.gz`` with its own decompressor and the whole reader is three regexes and
a list index.

The raw DC scans with a separator that never occurs in a VCF (``\\x1e``), so one
full line lands in a single ``raw_line`` text column. That sidesteps two traps a
tab-separated scan walks into:

* a VCF's last column is named after the sample, and nf-core writes that name
  differently per caller (``NA12878_75M`` for DeepVariant,
  ``NA12878_75M_NA12878_75M`` for GATK, Manta and Strelka), so a header-based
  scan across a run's files has no single schema;
* a truncated or dangling object in the bucket (sarek's megatest publishes two
  FreeBayes VCFs as a 196-byte Fusion symlink target, see the template's
  VALIDATION_REPORT) is one junk line here instead of a scan that raises.

Both ids come off the file NAME, ``<sample>.<caller>[.<qualifier>]...vcf.gz``,
which is the only place that survives the layouts the calls are published under
(``variant_calling/<caller>/<sample>/`` in the megatest, ``<sample>/<caller>/``
in sarek's own docs, flat elsewhere). Same rule as
``depictio.recipes.lib.bcftools_stats``.
"""

from __future__ import annotations

import polars as pl

#: Column holding one full VCF line (see the module docstring for why).
RAW_LINE_COL = "raw_line"
#: Column carrying the VCF's path (``include_file_paths`` on the raw DC).
SOURCE_PATH_COL = "source_path"

#: Longest REF/ALT allele kept inside ``variant_key``. A Manta deletion carries a
#: 335-base REF; the key exists to match a variant across callers, not to store
#: the allele, and the frame keeps ``ref``/``alt`` in full anyway.
ALLELE_KEY_CHARS = 20

_VCF_SUFFIX_RE = r"\.(?:vcf|bcf)(?:\.b?gz)?$"
#: The annotator an nf-core pipeline appends to the caller's own file-name
#: token (``deepvariant_snpEff``, ``haplotypecaller.filtered_VEP``), on the
#: stem itself and on the ``.ann`` sidecar the annotated call is published with.
_ANNOTATOR = r"(?:snpEff|snpeff|VEP|vep)"
_ANNOTATOR_SUFFIX_RE = rf"_{_ANNOTATOR}$"
_ANNOTATOR_ANN_SUFFIX_RE = rf"_{_ANNOTATOR}\.ann$"
#: A data line starts with a contig name and a numeric POS.
_DATA_LINE_RE = r"^[^\t]+\t\d+\t"
#: snpEff writes its per-variant annotations into an ``ANN=`` INFO key.
_ANN_INFO_RE = r"(?:^|;)ANN=([^;\t]+)"
_INFO_DP_RE = r"(?:^|;)DP=(\d+)"
#: ``p.Arg123Gly`` / ``p.Ter45*`` -> 123 / 45.
_HGVS_P_POS_RE = r"p\.[A-Za-z]{3}(\d+)"


def sample_and_caller(raw: pl.DataFrame) -> pl.DataFrame:
    """One row per ``source_path`` with the ``sample`` and ``caller`` it holds.

    Join the result back onto the raw frame on ``source_path``.
    """
    stem = (
        pl.col(SOURCE_PATH_COL)
        .str.split("/")
        .list.last()
        .str.replace(_VCF_SUFFIX_RE, "")
        # Annotated calls keep the caller in the stem but append the annotator:
        # NA12878_75M.haplotypecaller.filtered_snpEff.ann -> ...filtered.
        .str.replace(_ANNOTATOR_ANN_SUFFIX_RE, "")
    )
    tokens = stem.str.split(".")
    # DeepVariant's calls carry no qualifier, so the annotator lands on the
    # caller token itself (NA12878_75M.deepvariant_snpEff.genes.txt) where the
    # other callers keep it on a third one (....filtered_snpEff.genes.txt).
    caller = tokens.list.get(1, null_on_oob=True).str.replace(_ANNOTATOR_SUFFIX_RE, "")
    return (
        raw.select(pl.col(SOURCE_PATH_COL))
        .unique()
        .with_columns(
            tokens.list.get(0, null_on_oob=True).alias("sample"),
            pl.coalesce(caller, pl.lit("unknown")).alias("caller"),
        )
    )


def _format_value(key: str) -> pl.Expr:
    """The value of FORMAT key ``key`` in the per-sample genotype column.

    FORMAT key order differs per caller (DeepVariant ``GT:GQ:DP:AD:VAF:PL``,
    GATK ``GT:AD:DP:GQ:PL``, Manta ``GT:FT:GQ:PL:PR`` with no depth at all), so
    the key is located in the FORMAT list and the same index read off the
    genotype list rather than assumed.
    """
    keys = pl.col("format").str.split(":")
    values = pl.col("sample_field").str.split(":")
    index = keys.list.eval(pl.element() == key).list.arg_max()
    return (
        pl.when(keys.list.contains(key))
        .then(values.list.get(index, null_on_oob=True))
        .otherwise(None)
    )


def _variant_type() -> pl.Expr:
    """SNP / MNP / INDEL / SV from the first ALT allele."""
    ref = pl.col("ref")
    alt = pl.col("alt_first")
    return (
        pl.when(alt.str.starts_with("<") | alt.str.contains(r"[\[\]]"))
        .then(pl.lit("SV"))
        .when((ref.str.len_chars() == 1) & (alt.str.len_chars() == 1))
        .then(pl.lit("SNP"))
        .when(ref.str.len_chars() == alt.str.len_chars())
        .then(pl.lit("MNP"))
        .otherwise(pl.lit("INDEL"))
    )


#: Columns every ``vcf_to_long`` frame carries, in order.
CORE_COLUMNS = [
    "sample",
    "caller",
    "chrom",
    "pos",
    "variant_key",
    "ref",
    "alt",
    "variant_type",
    "qual",
    "filter_status",
    "is_pass",
    "gt",
    "dp",
    "vaf",
]
#: Extra columns ``vcf_to_long(..., with_annotation=True)`` adds.
ANNOTATION_COLUMNS = ["gene", "gene_id", "impact", "consequence", "hgvs_p", "aa_pos"]


def finite_float(column: str) -> pl.Expr:
    """Cast to Float64, turning vcftools' ``-nan`` into a null rather than a NaN.

    vcftools writes ``-nan`` for a ratio with an empty denominator (a Ts/Tv
    over zero transversions); ``strict=False`` reads it as NaN, which is not
    JSON and sorts above every real value, so it is nulled here.
    """
    value = pl.col(column).cast(pl.Float64, strict=False)
    return pl.when(value.is_finite()).then(value).otherwise(None)


def vcf_to_long(raw: pl.DataFrame, *, with_annotation: bool = False) -> pl.DataFrame:
    """One row per variant call, from a raw ``raw_line`` / ``source_path`` frame.

    ``with_annotation`` additionally splits snpEff's first ``ANN`` entry into
    gene, impact, consequence and protein change. snpEff emits one ANN entry per
    overlapping transcript, ordered by severity, so the first entry is the
    canonical "worst consequence" the summary reports are built on.

    ``vaf`` is the first ALT allele's fraction: the caller's own ``VAF`` field
    when it writes one, else ``AD[1] / (AD[0] + AD[1])``, which leaves the
    remaining alt depths of a multi-allelic record out of both numerator and
    denominator. That is the same first-ALT convention ``variant_type`` and
    ``variant_key`` follow, so the three columns describe one allele.
    """
    fields = pl.col(RAW_LINE_COL).str.split("\t")
    df = (
        raw.filter(
            pl.col(RAW_LINE_COL).is_not_null() & pl.col(RAW_LINE_COL).str.contains(_DATA_LINE_RE)
        )
        .with_columns(
            fields.list.get(0, null_on_oob=True).alias("chrom"),
            fields.list.get(1, null_on_oob=True).cast(pl.Int64, strict=False).alias("pos"),
            fields.list.get(3, null_on_oob=True).alias("ref"),
            fields.list.get(4, null_on_oob=True).alias("alt"),
            fields.list.get(5, null_on_oob=True).alias("qual_text"),
            fields.list.get(6, null_on_oob=True).alias("filter_status"),
            fields.list.get(7, null_on_oob=True).alias("info"),
            fields.list.get(8, null_on_oob=True).alias("format"),
            fields.list.get(9, null_on_oob=True).alias("sample_field"),
        )
        .join(sample_and_caller(raw), on=SOURCE_PATH_COL, how="left")
    )

    allele_depths = _format_value("AD").str.split(",")
    ad_ref = allele_depths.list.get(0, null_on_oob=True).cast(pl.Float64, strict=False)
    ad_alt = allele_depths.list.get(1, null_on_oob=True).cast(pl.Float64, strict=False)

    df = df.with_columns(
        pl.col("alt").str.split(",").list.get(0, null_on_oob=True).alias("alt_first"),
        pl.col("qual_text").cast(pl.Float64, strict=False).alias("qual"),
        _format_value("GT").alias("gt"),
        pl.coalesce(
            _format_value("DP").cast(pl.Int64, strict=False),
            pl.col("info").str.extract(_INFO_DP_RE, 1).cast(pl.Int64, strict=False),
        ).alias("dp"),
        pl.coalesce(
            _format_value("VAF").cast(pl.Float64, strict=False),
            pl.when((ad_ref + ad_alt) > 0).then(ad_alt / (ad_ref + ad_alt)).otherwise(None),
        ).alias("vaf"),
    ).with_columns(
        _variant_type().alias("variant_type"),
        # PASS is spelled "PASS" by every caller here; Strelka and GATK also
        # write a semicolon-joined list of failed filters, and DeepVariant
        # writes "." when it applied none.
        pl.col("filter_status").is_in(["PASS", ".", ""]).alias("is_pass"),
        pl.concat_str(
            [
                pl.col("chrom"),
                pl.col("pos").cast(pl.Utf8),
                pl.col("ref").str.slice(0, ALLELE_KEY_CHARS),
                pl.col("alt_first").str.slice(0, ALLELE_KEY_CHARS),
            ],
            separator=":",
        ).alias("variant_key"),
    )

    if not with_annotation:
        return df.select(CORE_COLUMNS)

    ann = pl.col("info").str.extract(_ANN_INFO_RE, 1).str.split(",").list.get(0, null_on_oob=True)
    ann_fields = ann.str.split("|")
    df = df.with_columns(
        ann_fields.list.get(3, null_on_oob=True).alias("gene"),
        ann_fields.list.get(4, null_on_oob=True).alias("gene_id"),
        ann_fields.list.get(2, null_on_oob=True).alias("impact"),
        # snpEff joins co-occurring consequences with "&"; the first one is the
        # most severe and is what every summary counts.
        ann_fields.list.get(1, null_on_oob=True)
        .str.split("&")
        .list.get(0, null_on_oob=True)
        .alias("consequence"),
        ann_fields.list.get(10, null_on_oob=True).alias("hgvs_p"),
    ).with_columns(
        pl.col("hgvs_p").str.extract(_HGVS_P_POS_RE, 1).cast(pl.Int64, strict=False).alias("aa_pos")
    )
    return df.select(CORE_COLUMNS + ANNOTATION_COLUMNS)
