"""Identified peptides, one row per sample and precursor (peptidoform and charge).

mhcquant's last step (``SUMMARIZE_RESULTS``, pyOpenMS) writes one tab-separated
table per sample at the top of the output directory, ``<sample>.tsv``: every
peptide that passed the FDR filter with its best score, PSM count, precursor
m/z, charge and retention time, the source protein accessions and flanking
residues, the rescoring features (DeepLC retention-time prediction, MS2PIP
spectrum correlation) and, when the run quantified (``--quantify``), a consensus
intensity plus one ``rt_<k>``/``mz_<k>``/``intensity_<k>`` triple per raw
replicate. Missing replicate values are written as the text ``nan``.

The recipe keeps the columns a reader filters and plots on, under stable names,
and derives the descriptors an immunopeptidome is judged by: peptide length and
its class window (8 to 12 residues for MHC class I, 13 to 25 for class II), the
P2 and C-terminal anchor residues, the Kyte-Doolittle hydropathy (GRAVY) that
retention time should follow, the neutral mass, and how many replicates the
peptide was quantified in. Fragment-ion annotations (``--annotate_ions``) are
joined when present.

Sources:
    peptides  ``*.tsv`` at the output root (the sample id is the file stem)
    ions      the ``mhcquant_fragment_ions`` collection (optional, ``--annotate_ions``)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

IONS_DC_TAG = "mhcquant_fragment_ions"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="peptides",
        glob_pattern="*.tsv",
        format="tsv",
        # `start`/`end` hold `;`-joined positions for shared peptides and the
        # replicate columns hold the text `nan`: read as text, cast below.
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
    # Fragment-ion summary, only written by runs with --annotate_ions.
    RecipeSource(ref="ions", dc_ref=IONS_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "peptide": pl.Utf8,
    "sequence": pl.Utf8,
    "length": pl.Int64,
    "length_class": pl.Utf8,
    "length_window": pl.Utf8,
    "modification_state": pl.Utf8,
    "score": pl.Float64,
    "score_type": pl.Utf8,
    "psms": pl.Int64,
    "rt_min": pl.Float64,
    "predicted_rt_min": pl.Float64,
    "rt_error_min": pl.Float64,
    "mz": pl.Float64,
    "charge": pl.Int64,
    "charge_state": pl.Utf8,
    "neutral_mass": pl.Float64,
    "gravy": pl.Float64,
    "anchor_p2": pl.Utf8,
    "anchor_c_term": pl.Utf8,
    "protein": pl.Utf8,
    "protein_entry": pl.Utf8,
    "proteins": pl.Utf8,
    "n_proteins": pl.Int64,
    "aa_before": pl.Utf8,
    "aa_after": pl.Utf8,
    "start": pl.Utf8,
    "spectrum_correlation": pl.Float64,
    "log10_intensity": pl.Float64,
    "replicates_quantified": pl.Int64,
    "replicates_total": pl.Int64,
    "fragment_ions": pl.Int64,
    "fragment_error_ppm": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

PROTON = 1.007276
# Kyte & Doolittle (1982) hydropathy index.
KYTE_DOOLITTLE: dict[str, float] = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "Q": -3.5, "E": -3.5,
    "G": -0.4, "H": -3.2, "I": 4.5, "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8,
    "P": -1.6, "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}  # fmt: skip
_OUTPUT_SUFFIXES = ("_pin", "_speclib", "_matching_ions", "_all_peaks")


def _float(col: str, frame: pl.DataFrame) -> pl.Expr:
    if col not in frame.columns:
        return pl.lit(None, dtype=pl.Float64)
    return pl.col(col).cast(pl.Utf8).replace("nan", None).cast(pl.Float64, strict=False)


def _text(col: str, frame: pl.DataFrame) -> pl.Expr:
    if col not in frame.columns:
        return pl.lit(None, dtype=pl.Utf8)
    return pl.col(col).cast(pl.Utf8)


def _gravy(seq: str | None) -> float | None:
    if not seq:
        return None
    values = [KYTE_DOOLITTLE[a] for a in seq if a in KYTE_DOOLITTLE]
    return round(sum(values) / len(values), 4) if values else None


def _stem(col: str, suffix: str = "") -> pl.Expr:
    return (
        pl.col(col)
        .str.split("/")
        .list.last()
        .str.replace(r"\.tsv$", "")
        .str.replace(f"{suffix}$", "")
    )


def _ion_summary(ions: pl.DataFrame | None) -> pl.DataFrame | None:
    if ions is None or ions.is_empty() or "fragment_ions" not in ions.columns:
        return None
    return ions.select("sample", "peptide", "fragment_ions", "fragment_error_ppm")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raw = sources["peptides"]
    # The root glob also sees any other TSV a user left there; keep the files
    # that carry the peptide table's own columns.
    if "sequence" not in raw.columns:
        raise ValueError(f"mhcquant peptides: no `sequence` column in {raw.columns}")
    raw = raw.filter(pl.col("sequence").is_not_null())
    raw = raw.with_columns(_stem("source_path").alias("sample")).filter(
        ~pl.col("sample").str.contains("(" + "|".join(_OUTPUT_SUFFIXES) + ")$")
    )

    rep_cols = sorted(
        (c for c in raw.columns if c.startswith("intensity_") and c[10:].isdigit()),
        key=lambda c: int(c[10:]),
    )
    if rep_cols:
        rep_values = [_float(c, raw) for c in rep_cols]
        quantified = pl.sum_horizontal([v.is_not_null().cast(pl.Int64) for v in rep_values])
        # A sample with fewer replicates than the widest one has all-null columns
        # for the extra indices after the diagonal concat: count only the columns
        # the sample actually wrote.
        written = pl.sum_horizontal(
            [pl.col(c).is_not_null().any().over("sample").cast(pl.Int64) for c in rep_cols]
        )
    else:
        quantified = pl.lit(None, dtype=pl.Int64)
        written = pl.lit(None, dtype=pl.Int64)
    consensus = _float("intensity_cf", raw)

    accessions = _text("accessions", raw)
    first = accessions.str.split(";").list.first()
    rt = _float("rt", raw)
    mz = _float("mz", raw)
    charge = _text("charge", raw).cast(pl.Int64, strict=False)
    peptidoform = pl.coalesce(_text("peptidoform", raw), pl.col("sequence"))

    out = raw.select(
        pl.col("sample"),
        peptidoform.alias("peptide"),
        pl.col("sequence").cast(pl.Utf8),
        pl.col("sequence").str.len_chars().cast(pl.Int64).alias("length"),
        _float("score", raw).alias("score"),
        _text("score_type", raw).alias("score_type"),
        _text("psm", raw).cast(pl.Int64, strict=False).alias("psms"),
        (rt / 60).alias("rt_min"),
        (_float("predicted_retention_time_best", raw) / 60).alias("predicted_rt_min"),
        mz.alias("mz"),
        charge.alias("charge"),
        ((mz - PROTON) * charge.cast(pl.Float64)).alias("neutral_mass"),
        first.str.extract(r"^[a-z]{2}\|([^|]+)\|", 1).fill_null(first).alias("protein"),
        first.str.extract(r"^[a-z]{2}\|[^|]+\|(.+)$", 1).fill_null(first).alias("protein_entry"),
        accessions.alias("proteins"),
        accessions.str.split(";").list.len().cast(pl.Int64).alias("n_proteins"),
        _text("aa_before", raw).alias("aa_before"),
        _text("aa_after", raw).alias("aa_after"),
        _text("start", raw).alias("start"),
        _float("spec_pearson", raw).alias("spectrum_correlation"),
        pl.when(consensus > 0).then(consensus.log10()).alias("log10_intensity"),
        quantified.cast(pl.Int64).alias("replicates_quantified"),
        written.cast(pl.Int64).alias("replicates_total"),
    )
    length = pl.col("length")
    out = out.with_columns(
        (length.cast(pl.Utf8) + "-mer").alias("length_class"),
        pl.when(length.is_between(8, 12))
        .then(pl.lit("Class I range"))
        .when(length.is_between(13, 25))
        .then(pl.lit("Class II range"))
        .otherwise(pl.lit("Outside both"))
        .alias("length_window"),
        pl.when(pl.col("peptide") != pl.col("sequence"))
        .then(pl.lit("Modified"))
        .otherwise(pl.lit("Unmodified"))
        .alias("modification_state"),
        (pl.col("rt_min") - pl.col("predicted_rt_min")).alias("rt_error_min"),
        (pl.col("charge").cast(pl.Utf8) + "+").alias("charge_state"),
        pl.col("sequence").map_elements(_gravy, return_dtype=pl.Float64).alias("gravy"),
        pl.col("sequence").str.slice(1, 1).alias("anchor_p2"),
        pl.col("sequence").str.slice(-1, 1).alias("anchor_c_term"),
    )

    ion_summary = _ion_summary(sources.get("ions"))
    if ion_summary is not None:
        out = out.join(ion_summary, on=["sample", "peptide"], how="left")
    else:
        out = out.with_columns(
            pl.lit(None, dtype=pl.Int64).alias("fragment_ions"),
            pl.lit(None, dtype=pl.Float64).alias("fragment_error_ppm"),
        )
    return out.select(list(EXPECTED_SCHEMA)).sort(["sample", "score"], descending=[False, True])
