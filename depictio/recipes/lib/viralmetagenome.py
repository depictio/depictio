"""Shared parsing for the nf-core/viralmetagenome outputs.

The pipeline names every per-sample output after the sample and, for a mapping,
after the reference the reads went to, and prefixes all of it with the run's
``--global_prefix`` (``<prefix>_<date>_<version>_<run name>-``):

* a mapping against a constraint reference:
  ``[<prefix>-]<sample>_<reference>-CONSTRAINT_constraint.<ext>``
  (CheckV writes the folder ``<sample>_<reference>-CONSTRAINT``);
* a de novo consensus, at one step of its refinement:
  ``[<prefix>-]<sample>_<cluster>_it<N>.<ext>``, ``..._consensus``, or
  ``..._itvariant-calling``.

The overview tables (``overview-tables/[<prefix>-]*_overview.tsv``) are the
pipeline's own merge of its MultiQC sections: one row per sample, or per
consensus genome, and one column per ``(<tool>) <metric>`` the report holds,
named the way MultiQC labels it.

Everything here keys a genome the same way, ``<sample>_<reference>``, so the
consensus, variant and coverage collections join on ``genome_id``.

Shared here rather than copied because several recipes split the same names,
and recipes may not import one another.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import polars as pl

ROUTE_CONSTRAINT = "constraint"
ROUTE_DENOVO = "de novo"

# The reads are mapped to a constraint reference (`-CONSTRAINT`, `_constraint`)
# or to a de novo consensus; the step suffix says how far the refinement went.
_CONSTRAINT = re.compile(r"-CONSTRAINT(?:_constraint)?$|_constraint$")
_STEP = re.compile(r"_(it\d+|itvariant-calling|consensus)$")
_TOOL_TAIL = re.compile(r"\.consensus(?:_[A-Za-z0-9]+)?$")


def run_prefix_free(name: str, sample: str) -> str:
    """``name`` from the first occurrence of ``sample`` on, the run prefix dropped.

    ``test_20260916_1.2.0_run-S1_cl0_it1`` with sample ``S1`` reads ``S1_cl0_it1``.
    A name that does not hold the sample is returned unchanged.
    """
    at = name.find(sample) if sample else -1
    return name[at:] if at >= 0 else name


def split_mapping_name(name: str, sample: str) -> tuple[str | None, str | None, str | None]:
    """``(reference, route, step)`` of a per-mapping output name.

    ``name`` is a file stem (or folder) without its extension, e.g.
    ``<prefix>-S1_REF-CONSTRAINT_constraint``, ``S1_cl0_it1``,
    ``S1_REF-CONSTRAINT_itvariant-calling.consensus_ivar``. The reference is the
    constraint id or the de novo cluster id; the step is null for a constraint
    mapping and for a name without one. A name that is the sample alone has no
    reference.
    """
    rest = run_prefix_free(name, sample)
    if sample and rest.startswith(sample):
        rest = rest[len(sample) :]
    rest = _TOOL_TAIL.sub("", rest.lstrip("_-"))
    if not rest:
        return None, None, None
    step: str | None = None
    m = _STEP.search(rest)
    if m:
        step = m.group(1)
        rest = rest[: m.start()]
    if _CONSTRAINT.search(rest) or rest.endswith("-CONSTRAINT"):
        reference = _CONSTRAINT.sub("", rest).removesuffix("-CONSTRAINT")
        return reference or None, ROUTE_CONSTRAINT, step
    return rest or None, ROUTE_DENOVO, step


def genome_id(sample: str | None, reference: str | None) -> str | None:
    """The key every per-genome collection joins on: ``<sample>_<reference>``."""
    if sample is None:
        return None
    return f"{sample}_{reference}" if reference else sample


def sample_from_path(path: str, generic_dirs: Iterable[str] = ()) -> str:
    """The per-sample folder a file sits in, or its stem when it sits in a tool folder.

    viralmetagenome writes ``<tool>/<sample>/<file>``; a flat layout
    (``<tool>/<file>``) has no sample folder, and the stem then names the sample.
    """
    parts = path.replace("\\", "/").split("/")
    stem = parts[-1]
    parent = parts[-2] if len(parts) > 1 else ""
    if parent and parent not in set(generic_dirs) and parent in stem:
        return parent
    return stem


def strip_extensions(name: str, extensions: Iterable[str]) -> str:
    """``name`` without the first of ``extensions`` it ends with."""
    for ext in extensions:
        if name.endswith(ext):
            return name[: -len(ext)]
    return name


def num(df: pl.DataFrame, column: str, dtype: type[pl.DataType] = pl.Float64) -> pl.Expr:
    """``column`` cast to ``dtype`` (text values like ``NA`` become null), or a null column."""
    if column not in df.columns:
        return pl.lit(None, dtype=dtype)
    expr = pl.col(column).cast(pl.Utf8).str.strip_chars()
    if dtype == pl.Int64:
        return expr.cast(pl.Float64, strict=False).round(0).cast(pl.Int64)
    return expr.cast(dtype, strict=False)


def text(df: pl.DataFrame, column: str) -> pl.Expr:
    """``column`` as stripped text with empty, ``NA`` and ``None`` values null."""
    if column not in df.columns:
        return pl.lit(None, dtype=pl.Utf8)
    value = pl.col(column).cast(pl.Utf8).str.strip_chars()
    return (
        pl.when(value.is_in(["", "NA", "N/A", "None", "nan", "null"])).then(None).otherwise(value)
    )


def first_present(
    df: pl.DataFrame, *columns: str, dtype: type[pl.DataType] = pl.Float64
) -> pl.Expr:
    """The first non-null of ``columns`` that the frame has, cast to ``dtype``."""
    present = [num(df, c, dtype) for c in columns if c in df.columns]
    if not present:
        return pl.lit(None, dtype=dtype)
    return pl.coalesce(present)


def as_percent(expr: pl.Expr) -> pl.Expr:
    """A share written as a fraction (0 to 1) read as a percentage.

    MultiQC's general statistics hold fastp's Q30 and GC rates and the annotation
    identity as fractions; a value above 1 is already a percentage.
    """
    return pl.when(expr <= 1.0).then(expr * 100.0).otherwise(expr)


def sanitise(name: str) -> str:
    """A column name every downstream store accepts: letters, digits and underscores."""
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_").lower() or "column"


# ---------------------------------------------------------------------------
# The per-genome overview tables (contigs_overview*, mapping_overview)
# ---------------------------------------------------------------------------

#: Output column -> overview column(s), first present wins. Numbers only.
GENOME_NUMERIC: dict[str, tuple[tuple[str, ...], type[pl.DataType]]] = {
    "consensus_length": (("(checkv) contig_length", "(blast) qlen", "(annotation) qlen"), pl.Int64),
    "n_bases": (("(quast) # N's",), pl.Int64),
    "n_pct": (("(quast) % N's",), pl.Float64),
    "annotation_identity_pct": (("(annotation) pident",), pl.Float64),
    "annotation_aligned_pct": (("(annotation) % contig aligned",), pl.Float64),
    "annotation_mismatches": (("(annotation) mismatch",), pl.Int64),
    "blast_identity_pct": (("(blast) pident",), pl.Float64),
    "blast_aligned_bp": (("(blast) length",), pl.Int64),
    "blast_bitscore": (("(blast) bitscore",), pl.Float64),
    "checkv_contamination": (("(checkv) contamination",), pl.Float64),
    "checkv_genes": (("(checkv) gene_count",), pl.Int64),
    "checkv_viral_genes": (("(checkv) viral_genes",), pl.Int64),
    "checkv_host_genes": (("(checkv) host_genes",), pl.Int64),
    "mapped_reads": (("(samtools Raw) reads mapped (R1+R2)",), pl.Int64),
    "mapped_pct": (("(samtools Raw) reads mapped %",), pl.Float64),
    "properly_paired_pct": (("(samtools Raw) reads properly paired %",), pl.Float64),
    "error_rate": (("(samtools Raw) error rate",), pl.Float64),
    "insert_size": (("(samtools Raw) insert size average",), pl.Float64),
    "dup_read_pairs": (("(picard) read pair duplicates",), pl.Int64),
    "dup_pct": (("(picard) % duplication",), pl.Float64),
    "dedup_mapped_reads": (("(samtools Post-dedup) reads mapped (R1+R2)",), pl.Int64),
    "mean_depth": (("(general_stats) mosdepth Mean read depth",), pl.Float64),
    "median_depth": (("(general_stats) mosdepth Median read depth",), pl.Float64),
    "max_depth": (("(general_stats) mosdepth Max read depth",), pl.Float64),
    "cov_1x_pct": (("(general_stats) mosdepth 1X coverage",), pl.Float64),
    "cov_10x_pct": (("(general_stats) mosdepth 10X coverage",), pl.Float64),
    "cov_50x_pct": (("(general_stats) mosdepth 50X coverage",), pl.Float64),
    "cov_100x_pct": (("(general_stats) mosdepth 100X coverage",), pl.Float64),
    "snps": (("(bcftools) number of SNPs", "(ivar_variants) raw SNPs"), pl.Int64),
    "indels": (("(bcftools) number of indels",), pl.Int64),
    "variant_records": (("(bcftools) number of records",), pl.Int64),
    "transitions": (("(bcftools) number of transitions",), pl.Int64),
    "transversions": (("(bcftools) number of transversions",), pl.Int64),
    "ts_tv": (
        (
            "(bcftools) transistions/transversions ratio",
            "(bcftools) transitions/transversions ratio",
        ),
        pl.Float64,
    ),
    "mash_identity": (("(mash-screen) identity",), pl.Float64),
    "cluster_members": (("(cluster) number of members",), pl.Int64),
}

#: Output column -> overview column(s), first present wins. Text.
GENOME_TEXT: dict[str, tuple[str, ...]] = {
    "annotation_name": ("(annotation) name", "(annotation) species"),
    "annotation_acronym": ("(annotation) acronym",),
    "annotation_level": ("(annotation) level",),
    "annotation_taxid": ("(annotation) taxid",),
    "annotation_segment": ("(annotation) segment",),
    "annotation_host": ("(annotation) host",),
    "annotation_subject": ("(annotation) subject",),
    "blast_hit": ("(blast) subject title", "(blast) subject"),
    "checkv_quality": ("(checkv) checkv_quality",),
    "miuvig_quality": ("(checkv) miuvig_quality",),
    "checkv_warnings": ("(checkv) warnings",),
    "mash_reference": ("(mash-screen) query-ID",),
    "mash_shared_hashes": ("(mash-screen) shared-hashes",),
    "cluster_centroid": ("(cluster) centroid",),
    "constraint_species": ("species",),
    "constraint_segment": ("segment",),
    "constraint_definition": ("definition",),
}

GENOME_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome_id": pl.Utf8,
    "sample": pl.Utf8,
    "reference": pl.Utf8,
    "route": pl.Utf8,
    "step": pl.Utf8,
    "virus": pl.Utf8,
    **{c: dtype for c, (_, dtype) in GENOME_NUMERIC.items()},
    **dict.fromkeys(GENOME_TEXT, pl.Utf8),
    "blast_query_cover_pct": pl.Float64,
}

# Placeholder strings a missing annotation is written with.
_UNNAMED = ["", "NA", "N/A", "None", "nan", "null", "-"]


def _first_text(df: pl.DataFrame, columns: tuple[str, ...]) -> pl.Expr:
    present = [text(df, c) for c in columns if c in df.columns]
    return pl.coalesce(present) if present else pl.lit(None, dtype=pl.Utf8)


def tidy_genome_overview(df: pl.DataFrame, default_route: str) -> pl.DataFrame:
    """One row per consensus genome of a ``*_overview.tsv`` table, in GENOME_SCHEMA.

    ``default_route`` is the route the table holds (``constraint`` for the
    mapping overview, ``de novo`` for the contig overviews); a row whose step is
    ``constraint`` is a constraint mapping either way.
    """
    if df.is_empty():
        return pl.DataFrame(schema=GENOME_SCHEMA)
    out = df.select(
        text(df, "sample").alias("sample"),
        text(df, "cluster").alias("reference"),
        text(df, "step").alias("step"),
        *[
            first_present(df, *cols, dtype=dtype).alias(c)
            for c, (cols, dtype) in GENOME_NUMERIC.items()
        ],
        *[_first_text(df, cols).alias(c) for c, cols in GENOME_TEXT.items()],
    )
    out = out.filter(pl.col("sample").is_not_null())
    route = (
        pl.when(pl.col("step") == ROUTE_CONSTRAINT)
        .then(pl.lit(ROUTE_CONSTRAINT))
        .otherwise(pl.lit(default_route))
    )
    out = out.with_columns(
        route.alias("route"),
        pl.when(pl.col("step") == ROUTE_CONSTRAINT)
        .then(None)
        .otherwise(pl.col("step"))
        .alias("step"),
        as_percent(pl.col("annotation_identity_pct")).round(2).alias("annotation_identity_pct"),
        as_percent(pl.col("dup_pct")).round(3).alias("dup_pct"),
        pl.when(pl.col("consensus_length") > 0)
        .then((pl.col("blast_aligned_bp") * 100.0 / pl.col("consensus_length")).round(2))
        .otherwise(None)
        .alias("blast_query_cover_pct"),
    )
    virus = pl.coalesce(
        [
            pl.when(pl.col(c).is_in(_UNNAMED)).then(None).otherwise(pl.col(c))
            for c in ("annotation_acronym", "annotation_name", "constraint_species")
        ]
    )
    out = out.with_columns(
        virus.fill_null("Unclassified").alias("virus"),
        pl.struct("sample", "reference")
        .map_elements(lambda r: genome_id(r["sample"], r["reference"]), return_dtype=pl.Utf8)
        .alias("genome_id"),
    )
    return out.select([pl.col(c).cast(t) for c, t in GENOME_SCHEMA.items()])


# ---------------------------------------------------------------------------
# Run prefix and assembler names
# ---------------------------------------------------------------------------

# `--global_prefix` reads `<prefix>_<yyyymmdd>_<version>_<run name>`, and the
# pipeline joins it to every file name with a dash.
_GLOBAL_PREFIX = re.compile(r"^[^-/]*_\d{8}_[^_/-]+_[^/-]+-")


def strip_global_prefix(name: str) -> str:
    """``name`` without the run's ``--global_prefix`` and its dash, when it has one."""
    return _GLOBAL_PREFIX.sub("", name, count=1)


_CONTIG_SIZE = re.compile(r"\|size(\d+)$")
_ASSEMBLER = re.compile(r"^(?P<asm>[A-Za-z0-9]+?)_(?:scaffold|contig|NODE|k\d+|TRINITY)", re.I)


def contig_assembler(contig: str) -> str | None:
    """The assembler a de novo contig id names (``megahit_scaffold3|size476`` reads megahit)."""
    m = _ASSEMBLER.match(contig or "")
    return m.group("asm").lower() if m else None


def contig_size(contig: str) -> int | None:
    """The length a contig id carries after ``|size``, else null."""
    m = _CONTIG_SIZE.search(contig or "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Design columns
# ---------------------------------------------------------------------------

#: Column ``GROUP_COL`` resolves to when the run gives no design table.
NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All samples"


def design_columns(metadata: pl.DataFrame | None, reserved: set[str]) -> pl.DataFrame | None:
    """The design table keyed on ``sample``, every other column as Delta-safe text.

    The sample id sits in the column named ``sample`` or, failing that, the
    first column; a column whose safe name would replace a reserved one (a
    measure of the hub) is left out.
    """
    if metadata is None or metadata.is_empty() or metadata.width < 2:
        return None
    id_col = "sample" if "sample" in metadata.columns else metadata.columns[0]
    keep: dict[str, str] = {}
    for col in metadata.columns:
        if col == id_col:
            continue
        safe = re.sub(r"[^0-9A-Za-z]+", "_", col.strip()).strip("_") or "column"
        if safe in reserved or safe in keep.values():
            continue
        keep[col] = safe
    if not keep:
        return None
    return (
        metadata.select(
            pl.col(id_col).cast(pl.Utf8).str.strip_chars().alias("sample"),
            *[pl.col(c).cast(pl.Utf8).alias(s) for c, s in keep.items()],
        )
        .filter(pl.col("sample").is_not_null())
        .unique(subset="sample", keep="first")
    )
