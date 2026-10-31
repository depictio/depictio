"""Read the VCFs of a tumour/normal pair, or of a tumour on its own, with Polars alone.

``depictio.recipes.lib.vcf.vcf_to_long`` reads a germline VCF: one sample column, a
genotype, an allele fraction. A somatic VCF is different in the one way that matters: its
genotype columns are a *pair* (normal and tumour), the callers do not agree on which comes
first, and each writes its allele evidence under its own FORMAT keys. This module reads the
callers sarek runs on a pair by default, one parser each:

``mutect2`` (``<tumour>_vs_<normal>.mutect2.filtered.vcf.gz``)
    FORMAT ``GT:AD:AF:DP...`` on each of two samples. Which column is the tumour is written
    in the header (``##tumor_sample=`` / ``##normal_sample=``), so the header lines must be
    in the frame; without them the normal is taken as the first column. Allele fraction is
    ``AF``, else ``AD[1] / (AD[0] + AD[1])``. The unfiltered ``.mutect2.vcf.gz`` is left out,
    its calls are the filtered file's before ``FilterMutectCalls``.
``strelka`` (``<pair>.strelka.somatic_snvs.vcf.gz``, ``....somatic_indels.vcf.gz``)
    Two fixed columns, ``NORMAL`` and ``TUMOR``. A SNV carries per-base tier-1 counts
    (``AU``, ``CU``, ``GU``, ``TU``): the fraction is the ALT base's count over the four.
    An indel carries ``TIR`` (reads supporting the indel) and ``TAR`` (reads supporting the
    other allele): the fraction is ``TIR / (TIR + TAR)``. Depth is ``DP`` for both.

A tumour sample called on its own (no matched normal) has one genotype column and is read
like a germline callset: allele fraction from ``AF`` (Mutect2), ``VAF`` or ``AD``. The
paired parsers need a normal, so a pair called by any other caller is left out rather than
guessed at: its genotype columns could be either way round.

Structural-variant callers (Manta, TIDDIT) and gVCFs are not point variants and are left to
their own collections.

The frame holds one row per call with the key ``variant_key`` the germline tables use
(``chrom:pos:ref:alt``), so a somatic call can be matched to a germline one.
"""

from __future__ import annotations

import re
from collections import defaultdict

import polars as pl

from depictio.recipes.lib.sarek_units import is_pair
from depictio.recipes.lib.vcf import (
    _ANNOTATOR_ANN_SUFFIX_RE,
    _DATA_LINE_RE,
    _VCF_SUFFIX_RE,
    ALLELE_KEY_CHARS,
    RAW_LINE_COL,
    SOURCE_PATH_COL,
    _variant_type,
)

#: The callers whose calls are structural variants, read by ``sv_to_long``.
SV_CALLERS = frozenset({"manta", "tiddit"})
#: The callers a pair is read with.
PAIRED_CALLERS = ("mutect2", "strelka")

#: Columns every ``somatic_to_long`` frame carries, in order.
SOMATIC_COLUMNS = [
    "unit",
    "caller",
    "chrom",
    "pos",
    "variant_key",
    "ref",
    "alt",
    "variant_type",
    "qual",
    "score",
    "filter_status",
    "is_pass",
    "tumour_vaf",
    "tumour_dp",
    "normal_vaf",
    "normal_dp",
]

SOMATIC_SCHEMA: dict[str, type[pl.DataType]] = {
    "unit": pl.Utf8,
    "caller": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "variant_key": pl.Utf8,
    "ref": pl.Utf8,
    "alt": pl.Utf8,
    "variant_type": pl.Utf8,
    "qual": pl.Float64,
    "score": pl.Float64,
    "filter_status": pl.Utf8,
    "is_pass": pl.Boolean,
    "tumour_vaf": pl.Float64,
    "tumour_dp": pl.Int64,
    "normal_vaf": pl.Float64,
    "normal_dp": pl.Int64,
}

_INFO_SOMATIC_EVS_RE = r"(?:^|;)SomaticEVS=([^;]+)"
_INFO_TLOD_RE = r"(?:^|;)TLOD=([^;,]+)"
_INFO_DP_RE = r"(?:^|;)DP=(\d+)"

#: Column offset of the first genotype column of a VCF.
_FIRST_SAMPLE = 9
#: Out-of-range column index: ``list.get`` answers null for it.
_NO_COLUMN = 999


def _tokens(path: str) -> list[str]:
    """``[unit, caller, qualifier...]`` of a VCF's file name (see ``vcf.sample_and_caller``)."""
    name = path.rsplit("/", 1)[-1]
    stem = re.sub(_ANNOTATOR_ANN_SUFFIX_RE, "", re.sub(_VCF_SUFFIX_RE, "", name))
    return stem.split(".")


def _headers(raw: pl.DataFrame) -> dict[str, dict]:
    """Per file: its genotype column names and the tumour and normal the header names."""
    info: dict[str, dict] = defaultdict(dict)
    lines = raw.filter(pl.col(RAW_LINE_COL).str.starts_with("#")).select(
        RAW_LINE_COL, SOURCE_PATH_COL
    )
    for line, path in zip(
        lines[RAW_LINE_COL].to_list(), lines[SOURCE_PATH_COL].to_list(), strict=True
    ):
        if line.startswith("#CHROM"):
            info[path]["columns"] = line.split("\t")[_FIRST_SAMPLE:]
        elif line.startswith("##tumor_sample="):
            info[path]["tumour"] = line.split("=", 1)[1].strip()
        elif line.startswith("##normal_sample="):
            info[path]["normal"] = line.split("=", 1)[1].strip()
    return info


def _index(columns: list[str] | None, name: str | None, default: int) -> int:
    """Position of ``name`` among the genotype columns, ``default`` when the header lacks it."""
    if columns and name:
        lowered = [c.lower() for c in columns]
        if name.lower() in lowered:
            return lowered.index(name.lower())
    return default


def plan_files(raw: pl.DataFrame) -> pl.DataFrame:
    """One row per VCF to read: its unit, caller, parser and tumour and normal column.

    A file no parser covers is not in the plan (and its rows are not in the result).
    ``t_col`` and ``n_col`` are positions among the genotype columns; ``n_col`` is
    ``_NO_COLUMN`` for a tumour on its own.
    """
    headers = _headers(raw)
    rows: list[dict] = []
    for path in raw[SOURCE_PATH_COL].unique().to_list():
        tokens = _tokens(path)
        if len(tokens) < 2:
            continue
        unit, caller, qualifiers = tokens[0], tokens[1].lower(), [t.lower() for t in tokens[2:]]
        if caller in SV_CALLERS or "genome" in qualifiers or "g" in qualifiers:
            continue
        head = headers.get(path, {})
        columns = head.get("columns")
        if is_pair(unit):
            if caller == "mutect2" and "filtered" in qualifiers:
                parser = "mutect2"
                t_col = _index(columns, head.get("tumour"), 1)
                n_col = _index(columns, head.get("normal"), 0)
            elif caller == "strelka" and "somatic_snvs" in qualifiers:
                parser = "strelka_snv"
                t_col, n_col = _index(columns, "TUMOR", 1), _index(columns, "NORMAL", 0)
            elif caller == "strelka" and "somatic_indels" in qualifiers:
                parser = "strelka_indel"
                t_col, n_col = _index(columns, "TUMOR", 1), _index(columns, "NORMAL", 0)
            else:
                continue
        else:
            # A tumour on its own: the unfiltered Mutect2 file is the filtered one before its filters.
            if caller == "mutect2" and "filtered" not in qualifiers:
                continue
            parser, t_col, n_col = "single", 0, _NO_COLUMN
        rows.append(
            {
                SOURCE_PATH_COL: path,
                "unit": unit,
                "caller": caller,
                "parser": parser,
                "t_col": t_col,
                "n_col": n_col,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            SOURCE_PATH_COL: pl.Utf8,
            "unit": pl.Utf8,
            "caller": pl.Utf8,
            "parser": pl.Utf8,
            "t_col": pl.Int64,
            "n_col": pl.Int64,
        },
    )


def _fmt(field: str, key: str) -> pl.Expr:
    """The value of FORMAT key ``key`` in genotype column ``field`` (null when absent)."""
    keys = pl.col("format").str.split(":")
    values = pl.col(field).str.split(":")
    index = keys.list.eval(pl.element() == key).list.arg_max()
    return (
        pl.when(keys.list.contains(key))
        .then(values.list.get(index, null_on_oob=True))
        .otherwise(None)
    )


def _first_number(expr: pl.Expr) -> pl.Expr:
    """The first value of a comma list, as a float (``.`` and absent become null)."""
    return expr.str.split(",").list.get(0, null_on_oob=True).cast(pl.Float64, strict=False)


def _ratio(num: pl.Expr, den: pl.Expr) -> pl.Expr:
    return pl.when(den > 0).then(num / den).otherwise(None).cast(pl.Float64)


def _ad_fraction(field: str) -> pl.Expr:
    """``AD[1] / (AD[0] + AD[1])``: the first ALT allele's share of the two allele depths."""
    depths = _fmt(field, "AD").str.split(",")
    ref = depths.list.get(0, null_on_oob=True).cast(pl.Float64, strict=False)
    alt = depths.list.get(1, null_on_oob=True).cast(pl.Float64, strict=False)
    return _ratio(alt, ref + alt)


def _depth(field: str) -> pl.Expr:
    return _fmt(field, "DP").cast(pl.Int64, strict=False)


def _evidence(parser: str, field: str) -> tuple[pl.Expr, pl.Expr]:
    """``(allele fraction, depth)`` of one genotype column under one parser."""
    if parser == "strelka_snv":
        counts = {b: _first_number(_fmt(field, f"{b}U")) for b in "ACGT"}
        alt_base = pl.col("alt_first").str.slice(0, 1).str.to_uppercase()
        alt = pl.coalesce(
            *[pl.when(alt_base == base).then(count) for base, count in counts.items()]
        )
        total = counts["A"] + counts["C"] + counts["G"] + counts["T"]
        return _ratio(alt, total), _depth(field)
    if parser == "strelka_indel":
        indel, other = _first_number(_fmt(field, "TIR")), _first_number(_fmt(field, "TAR"))
        return _ratio(indel, indel + other), _depth(field)
    if parser == "mutect2":
        return pl.coalesce(_first_number(_fmt(field, "AF")), _ad_fraction(field)), _depth(field)
    # A tumour on its own, whatever the caller: the germline-style fields.
    vaf = pl.coalesce(
        _first_number(_fmt(field, "AF")), _first_number(_fmt(field, "VAF")), _ad_fraction(field)
    )
    depth = pl.coalesce(
        _depth(field), pl.col("info").str.extract(_INFO_DP_RE, 1).cast(pl.Int64, strict=False)
    )
    return vaf, depth


def somatic_to_long(raw: pl.DataFrame) -> pl.DataFrame:
    """One row per somatic call, from a raw ``raw_line`` / ``source_path`` frame.

    The frame may hold the VCF header lines (``#``): the genotype column names and the
    ``##tumor_sample=`` / ``##normal_sample=`` lines say which column is the tumour.
    Returns :data:`SOMATIC_COLUMNS`; empty when no file of the frame has a parser.
    """
    plan = plan_files(raw)
    empty = pl.DataFrame(schema=SOMATIC_SCHEMA)
    if plan.is_empty():
        return empty
    data = raw.filter(
        pl.col(RAW_LINE_COL).is_not_null() & pl.col(RAW_LINE_COL).str.contains(_DATA_LINE_RE)
    ).join(plan, on=SOURCE_PATH_COL, how="inner")
    if data.is_empty():
        return empty

    fields = pl.col(RAW_LINE_COL).str.split("\t")
    data = data.with_columns(
        fields.list.get(0, null_on_oob=True).alias("chrom"),
        fields.list.get(1, null_on_oob=True).cast(pl.Int64, strict=False).alias("pos"),
        fields.list.get(3, null_on_oob=True).alias("ref"),
        fields.list.get(4, null_on_oob=True).alias("alt"),
        fields.list.get(5, null_on_oob=True).alias("qual_text"),
        fields.list.get(6, null_on_oob=True).alias("filter_status"),
        fields.list.get(7, null_on_oob=True).alias("info"),
        fields.list.get(8, null_on_oob=True).alias("format"),
        fields.list.get(_FIRST_SAMPLE + pl.col("t_col"), null_on_oob=True).alias("tumour_field"),
        fields.list.get(_FIRST_SAMPLE + pl.col("n_col"), null_on_oob=True).alias("normal_field"),
    ).with_columns(pl.col("alt").str.split(",").list.get(0, null_on_oob=True).alias("alt_first"))

    frames: list[pl.DataFrame] = []
    for parser in plan["parser"].unique().to_list():
        part = data.filter(pl.col("parser") == parser)
        t_vaf, t_dp = _evidence(parser, "tumour_field")
        if parser == "single":
            n_vaf, n_dp = pl.lit(None, dtype=pl.Float64), pl.lit(None, dtype=pl.Int64)
        else:
            n_vaf, n_dp = _evidence(parser, "normal_field")
        frames.append(
            part.with_columns(
                t_vaf.alias("tumour_vaf"),
                t_dp.alias("tumour_dp"),
                n_vaf.alias("normal_vaf"),
                n_dp.alias("normal_dp"),
            )
        )
    out = pl.concat(frames, how="vertical_relaxed")

    qual = pl.col("qual_text").cast(pl.Float64, strict=False)
    return out.with_columns(
        qual.alias("qual"),
        pl.coalesce(
            pl.col("info").str.extract(_INFO_SOMATIC_EVS_RE, 1).cast(pl.Float64, strict=False),
            pl.col("info").str.extract(_INFO_TLOD_RE, 1).cast(pl.Float64, strict=False),
            qual,
        ).alias("score"),
        _variant_type().alias("variant_type"),
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
    ).select(SOMATIC_COLUMNS)
