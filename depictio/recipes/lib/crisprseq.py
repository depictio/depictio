"""Shared parsing for the nf-core/crisprseq targeted-analysis tables.

The CIGAR parser writes one small file per library, ``cigar/<sample>_<kind>.csv``
(R ``write.csv`` output: quoted headers, an unnamed row-name first column,
``NA`` for missing values, counts sometimes padded with spaces). The sample id is
the file name less its kind suffix, which is more reliable than the row name
(the substitution table numbers its rows instead).
"""

from __future__ import annotations

import re

import polars as pl

# Kind suffixes the CIGAR parser and the clonality classifier append to the
# sample id, longest first so ``_edits_classified`` wins over ``_edits``.
_SUFFIX = re.compile(
    r"_(edits_classified|reads-summary|QC-indels|subs-perc|cutSite|Emptyindels|Badlyindels"
    r"|indels|edits)\.(csv|json)$"
)

# Every outcome class the CIGAR parser counts, in the order of its edits table,
# with the reader-facing label the dashboards use.
OUTCOME_COLUMNS: dict[str, str] = {
    "Wt": "Wild type",
    "Template-based": "Template-based",
    "Delins": "Deletion-insertion",
    "Ins_inframe": "Insertion, in-frame",
    "Ins_outframe": "Insertion, frameshift",
    "Dels_inframe": "Deletion, in-frame",
    "Dels_outframe": "Deletion, frameshift",
}


def sample_from_path(path: str) -> str:
    """``cigar/S1_edits.csv`` -> ``S1``."""
    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    return _SUFFIX.sub("", base)


def sample_expr(column: str = "source_path") -> pl.Expr:
    """Polars expression deriving the sample id from a ``source_path`` column."""
    return pl.col(column).map_elements(sample_from_path, return_dtype=pl.Utf8).alias("sample")


def num(column: str, dtype: type[pl.DataType] = pl.Float64) -> pl.Expr:
    """Parse a text column holding a number (padded, ``NA`` for missing)."""
    expr = (
        pl.col(column)
        .cast(pl.Utf8)
        .str.strip_chars()
        .str.replace(r"\s*\(.*\)$", "")
        .cast(pl.Float64, strict=False)
    )
    if dtype == pl.Int64:
        return expr.round(0).cast(pl.Int64)
    return expr


def _normalise_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def first_matching(columns: list[str], *names: str) -> str | None:
    """The first column whose normalised name is one of ``names``."""
    by_name = {_normalise_name(c): c for c in columns}
    for name in names:
        hit = by_name.get(_normalise_name(name))
        if hit is not None:
            return hit
    return None


# Positions further than this from the cut site (bp) are left out of the
# position and size profiles: on the reference run 98% of the main-peak indel
# alleles start between 60 bp before and 83 bp after the reported cut site, and
# a wider axis only adds amplicon-end noise.
PROFILE_WINDOW = 100

# Significant figures kept on the rates and shares the tables show.
SIG_FIGS = 3


def rounded(*columns: str) -> list[pl.Expr]:
    """``columns`` rounded to :data:`SIG_FIGS` significant figures (nulls stay null)."""
    return [pl.col(c).round_sig_figs(SIG_FIGS) for c in columns]


def library_guides(samples: pl.DataFrame, summary: pl.DataFrame) -> pl.DataFrame:
    """``sample, guide, n_libraries``: the libraries that classified reads, with their guide.

    ``n_libraries`` counts the guide's libraries with at least one classified
    read, the libraries a per-guide statistic is taken over. Libraries missing
    from the sheet go under ``unassigned``.
    """
    guides = samples.select("sample", pl.col("guide").cast(pl.Utf8)).unique(subset=["sample"])
    return (
        summary.filter(pl.col("classified_reads") > 0)
        .select("sample")
        .join(guides, on="sample", how="left")
        .with_columns(pl.col("guide").fill_null("unassigned"))
        .with_columns(pl.len().over("guide").cast(pl.Int64).alias("n_libraries"))
    )


# ---------------------------------------------------------------------------
# Per-library tables derived from the collapsed indel alleles and the
# substitution table. The catalog recipes publish them as they are; the
# per-guide recipes summarise them in process instead of shipping one row per
# library and position.
# ---------------------------------------------------------------------------


def indel_sizes_per_library(indels: pl.DataFrame) -> pl.DataFrame:
    """``sample, size, reads, pct_reads, pct_indel_reads`` summed over the alleles of each size."""
    return (
        indels.filter(pl.col("size").abs() <= PROFILE_WINDOW)
        .group_by("sample", "size")
        .agg(
            pl.col("reads").sum().cast(pl.Int64),
            pl.col("pct_reads").sum().cast(pl.Float64),
            pl.col("pct_indel_reads").sum().cast(pl.Float64),
        )
        .sort("sample", "size")
    )


def cut_site_per_library(indels: pl.DataFrame) -> pl.DataFrame:
    """``sample, offset, deletion_pct, insertion_pct`` at every offset an indel touches.

    A deletion of length L starting at offset o covers o to o + L - 1; an
    insertion counts at the offset it starts at. Offsets with no indel are left
    out.
    """
    df = indels.filter(pl.col("offset").is_not_null())
    w = PROFILE_WINDOW
    dels = (
        df.filter(pl.col("indel_type") != "Insertion")
        .filter((pl.col("offset") <= w) & (pl.col("offset") + pl.col("length") > -w))
        .select(
            "sample",
            "pct_reads",
            pl.int_ranges(
                pl.max_horizontal(pl.col("offset"), pl.lit(-w)),
                pl.min_horizontal(pl.col("offset") + pl.col("length"), pl.lit(w + 1)),
                dtype=pl.Int64,
            ).alias("offset"),
        )
        .explode("offset", empty_as_null=False)
        .group_by("sample", "offset")
        .agg(pl.col("pct_reads").sum().alias("deletion_pct"))
    )
    ins = (
        df.filter((pl.col("indel_type") == "Insertion") & (pl.col("offset").abs() <= w))
        .group_by("sample", "offset")
        .agg(pl.col("pct_reads").sum().alias("insertion_pct"))
    )
    return (
        dels.join(ins, on=["sample", "offset"], how="full", coalesce=True)
        .with_columns(
            pl.col("deletion_pct").fill_null(0.0).cast(pl.Float64),
            pl.col("insertion_pct").fill_null(0.0).cast(pl.Float64),
        )
        .sort("sample", "offset")
    )


def substitutions_per_library(subs: pl.DataFrame, cut: pl.DataFrame) -> pl.DataFrame:
    """``sample, offset, position, reference_nt, substitution_pct, gap_pct`` per position.

    ``subs`` is the concatenated ``*_subs-perc.csv`` tables (with ``source_path``),
    ``cut`` the concatenated ``*_cutSite.json`` read as one ``cut_site`` column.
    The dominant base at a position is its reference; the substitution rate is
    the share of reads with any other base, the gap rate the share with ``-``.
    """
    pos = first_matching(subs.columns, "pos")
    pct = first_matching(subs.columns, "percentage")
    nt = first_matching(subs.columns, "nucleotide")
    if pos is None or pct is None or nt is None:
        raise ValueError(f"crisprseq substitution table: unexpected columns {subs.columns}")
    df = subs.select(
        sample_expr(),
        num(pos, pl.Int64).alias("position"),
        num(pct).alias("pct"),
        pl.col(nt).cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("nt"),
    ).drop_nulls(["position", "pct"])
    cut_sites = (
        cut.select(
            sample_expr(),
            pl.col("cut_site").cast(pl.Utf8).str.extract(r"(-?\d+)").cast(pl.Int64).alias("cut"),
        )
        .drop_nulls("cut")
        .unique(subset=["sample"], keep="first")
    )
    is_gap = pl.col("nt") == "-"
    per_pos = (
        df.group_by("sample", "position")
        .agg(
            pl.col("pct").filter(~is_gap).sum().alias("_bases"),
            pl.col("pct").filter(~is_gap).max().alias("_ref"),
            pl.col("nt")
            .filter(~is_gap)
            .sort_by(pl.col("pct").filter(~is_gap))
            .last()
            .alias("reference_nt"),
            pl.col("pct").filter(is_gap).sum().alias("gap_pct"),
        )
        .join(cut_sites, on="sample", how="inner")
        .with_columns((pl.col("position") - pl.col("cut")).alias("offset"))
        .filter(pl.col("offset").abs() <= PROFILE_WINDOW)
    )
    return per_pos.with_columns(
        (pl.col("_bases") - pl.col("_ref").fill_null(0.0))
        .clip(lower_bound=0.0)
        .cast(pl.Float64)
        .alias("substitution_pct"),
        pl.col("gap_pct").fill_null(0.0).cast(pl.Float64),
    ).sort("sample", "position")


# ---------------------------------------------------------------------------
# Per-guide summaries of a per-library profile
# ---------------------------------------------------------------------------


def guide_quartiles(
    per_sample: pl.DataFrame,
    libs: pl.DataFrame,
    key: str,
    values: list[str],
    *,
    fill_zero: bool,
    keys: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Median, first and third quartile of ``values`` per guide and ``key``.

    The statistics are over the guide's libraries (``libs`` from
    :func:`library_guides`), so a guide draws one median curve with an
    interquartile band instead of one curve per library.

    ``fill_zero``: a library with no row at a key counts as zero (no indel of
    that size or at that offset). Without it only the libraries with a row
    count (a position outside a library's amplicon is not a zero rate).

    ``keys`` (``guide, <key>``) sets the keys reported per guide; by default
    every key seen in any of the guide's libraries.

    Output: ``guide, <key>, median_<v>, q1_<v>, q3_<v>`` per value and
    ``libraries_with_signal`` (libraries with a row, or a non-zero value when
    ``fill_zero``). Values are rounded to :data:`SIG_FIGS` significant figures.
    """
    lib_rows = libs.select("sample", "guide")
    joined = per_sample.select("sample", key, *values).join(lib_rows, on="sample", how="inner")
    if keys is None:
        keys = joined.select("guide", key).unique()
    if fill_zero:
        dense = (
            keys.join(lib_rows, on="guide", how="inner")
            .join(joined.drop("guide"), on=["sample", key], how="left")
            .with_columns(
                pl.any_horizontal(*[pl.col(v).is_not_null() & (pl.col(v) > 0) for v in values])
                .fill_null(False)
                .alias("_signal"),
                *[pl.col(v).fill_null(0.0) for v in values],
            )
        )
    else:
        dense = keys.join(joined, on=["guide", key], how="inner").with_columns(
            pl.lit(True).alias("_signal")
        )
    stats = []
    for v in values:
        stats += [
            pl.col(v).median().alias(f"median_{v}"),
            pl.col(v).quantile(0.25, interpolation="linear").alias(f"q1_{v}"),
            pl.col(v).quantile(0.75, interpolation="linear").alias(f"q3_{v}"),
        ]
    out_cols = [f"{s}_{v}" for v in values for s in ("median", "q1", "q3")]
    out = dense.group_by("guide", key).agg(
        *stats, pl.col("_signal").sum().cast(pl.Int64).alias("libraries_with_signal")
    )
    # A guide/key with no library at all (keys given but none of its libraries
    # reach it) still gets its row: zero with fill_zero, null without.
    out = keys.join(out, on=["guide", key], how="left").with_columns(
        *[pl.col(c).cast(pl.Float64) for c in out_cols],
        pl.col("libraries_with_signal").fill_null(0),
    )
    if fill_zero:
        out = out.with_columns(*[pl.col(c).fill_null(0.0) for c in out_cols])
    return out.with_columns(rounded(*out_cols)).sort("guide", key)
