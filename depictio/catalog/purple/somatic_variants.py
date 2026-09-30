"""PURPLE's somatic small variants, one row per PASS call, with PAVE's impact.

In oncoanalyser SAGE calls somatic SNVs and indels, PAVE annotates them and
PURPLE enriches the same VCF with the purity-adjusted view of each call; the
result is ``<tumor>.purple.somatic.vcf.gz``. The INFO fields read here:

* ``IMPACT`` (PAVE, 10 comma-separated values): gene, canonical transcript,
  canonical effect, canonical coding effect, splice region flag, HGVS coding
  change, HGVS protein change, other reportable effects, worst coding effect,
  genes affected;
* ``PURPLE_AF`` (purity-adjusted allele frequency), ``PURPLE_CN`` (copy number
  at the locus), ``PURPLE_VCN`` (copy number of the variant), ``PURPLE_MACN``
  (minor-allele copy number), ``SUBCL`` (subclonal likelihood), ``BIALLELIC``,
  ``HOTSPOT``, ``REPORTED`` (in the driver catalog), ``TIER``, ``KT``
  (kataegis), ``TNC`` (trinucleotide context), ``GND_FREQ``, ``MAPPABILITY``.

The file is read line by line (one ``raw_line`` column, meta lines dropped)
because its sample columns are named after the run's samples. The tumor is the
last sample column (SAGE writes the reference first), which gives the raw
allele fraction, depth and alt read count. Only ``FILTER == PASS`` calls are
kept: the rest are panel-of-normals and germline artefacts PURPLE never uses.
The tumor id is the file name before ``.purple.somatic.vcf.gz``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="vcf",
        glob_pattern="**/purple/*.purple.somatic.vcf.gz",
        format="csv",
        read_kwargs={
            "separator": "\x1e",
            "has_header": False,
            "comment_prefix": "#",
            "new_columns": ["raw_line"],
            "infer_schema_length": 0,
            "quote_char": None,
        },
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "variant_key": pl.Utf8,
    "sample": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "ref": pl.Utf8,
    "alt": pl.Utf8,
    "variant_type": pl.Utf8,
    "tier": pl.Utf8,
    "gene": pl.Utf8,
    "transcript": pl.Utf8,
    "canonical_effect": pl.Utf8,
    "coding_effect": pl.Utf8,
    "hgvs_c": pl.Utf8,
    "hgvs_p": pl.Utf8,
    "worst_coding_effect": pl.Utf8,
    "splice_region": pl.Boolean,
    "tumor_af": pl.Float64,
    "tumor_depth": pl.Int64,
    "tumor_alt_reads": pl.Int64,
    "purple_af": pl.Float64,
    "copy_number": pl.Float64,
    "variant_copy_number": pl.Float64,
    "minor_allele_copy_number": pl.Float64,
    "subclonal_likelihood": pl.Float64,
    "biallelic": pl.Boolean,
    "hotspot": pl.Boolean,
    "reported": pl.Boolean,
    "kataegis": pl.Boolean,
    "trinucleotide_context": pl.Utf8,
    "germline_status": pl.Utf8,
    "gnomad_frequency": pl.Float64,
    "mappability": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_SAMPLE_RE = r"([^/]+)\.purple\.somatic\.vcf(?:\.gz)?$"


def _info(key: str) -> pl.Expr:
    return pl.col("info").str.extract(rf"(?:^|;){key}=([^;]*)", 1)


def _flag(key: str) -> pl.Expr:
    return pl.col("info").str.contains(rf"(?:^|;){key}(?:;|=|$)")


def _float(expr: pl.Expr) -> pl.Expr:
    return expr.cast(pl.Float64, strict=False)


def _format_value(key: str) -> pl.Expr:
    keys = pl.col("format").str.split(":")
    values = pl.col("tumor_field").str.split(":")
    index = keys.list.eval(pl.element() == key).list.arg_max()
    return pl.when(keys.list.contains(key)).then(values.list.get(index, null_on_oob=True))


def _nullable(expr: pl.Expr) -> pl.Expr:
    return pl.when(expr.is_in(["", "."])).then(None).otherwise(expr)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raw = sources["vcf"].filter(pl.col("raw_line").str.contains(r"^[^\t#]+\t\d+\t"))
    fields = pl.col("raw_line").str.split("\t")
    calls = raw.select(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
        fields.list.get(0).alias("chrom"),
        fields.list.get(1).cast(pl.Int64, strict=False).alias("pos"),
        fields.list.get(3).alias("ref"),
        fields.list.get(4).alias("alt"),
        fields.list.get(6).alias("filter"),
        fields.list.get(7).alias("info"),
        fields.list.get(8, null_on_oob=True).alias("format"),
        fields.list.last().alias("tumor_field"),
    ).filter(pl.col("filter") == "PASS")

    impact = _info("IMPACT").str.split(",")
    n = impact.list.len()
    ref_len, alt_len = pl.col("ref").str.len_chars(), pl.col("alt").str.len_chars()
    ad = _format_value("AD").str.split(",")
    out = calls.with_columns(
        pl.concat_str(
            [pl.col("chrom"), pl.col("pos").cast(pl.Utf8), pl.col("ref"), pl.col("alt")],
            separator=":",
        ).alias("variant_key"),
        pl.when((ref_len == 1) & (alt_len == 1))
        .then(pl.lit("SNV"))
        .when(ref_len == alt_len)
        .then(pl.lit("MNV"))
        .otherwise(pl.lit("INDEL"))
        .alias("variant_type"),
        _info("TIER").alias("tier"),
        _nullable(impact.list.get(0, null_on_oob=True)).alias("gene"),
        _nullable(impact.list.get(1, null_on_oob=True)).alias("transcript"),
        _nullable(impact.list.get(2, null_on_oob=True)).alias("canonical_effect"),
        _nullable(impact.list.get(3, null_on_oob=True)).alias("coding_effect"),
        (impact.list.get(4, null_on_oob=True) == "true").fill_null(False).alias("splice_region"),
        _nullable(impact.list.get(5, null_on_oob=True)).alias("hgvs_c"),
        _nullable(impact.list.get(6, null_on_oob=True)).alias("hgvs_p"),
        # Counted from the right: OtherReportableEffects may itself be empty.
        _nullable(impact.list.get(n - 2, null_on_oob=True)).alias("worst_coding_effect"),
        _float(_format_value("AF")).alias("tumor_af"),
        _format_value("DP").cast(pl.Int64, strict=False).alias("tumor_depth"),
        ad.list.get(1, null_on_oob=True).cast(pl.Int64, strict=False).alias("tumor_alt_reads"),
        _float(_info("PURPLE_AF")).alias("purple_af"),
        _float(_info("PURPLE_CN")).alias("copy_number"),
        _float(_info("PURPLE_VCN")).alias("variant_copy_number"),
        _float(_info("PURPLE_MACN")).alias("minor_allele_copy_number"),
        _float(_info("SUBCL")).fill_null(0.0).alias("subclonal_likelihood"),
        _flag("BIALLELIC").alias("biallelic"),
        _flag("HOTSPOT").alias("hotspot"),
        _flag("REPORTED").alias("reported"),
        _info("KT").is_not_null().alias("kataegis"),
        _info("TNC").alias("trinucleotide_context"),
        _info("PURPLE_GERMLINE").alias("germline_status"),
        _float(_info("GND_FREQ")).alias("gnomad_frequency"),
        _float(_info("MAPPABILITY")).alias("mappability"),
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(["sample", "chrom", "pos"])
