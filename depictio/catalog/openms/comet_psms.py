"""Comet database search yield per raw file, before rescoring.

OpenMS' CometAdapter writes a Percolator input table per raw file
(``<run>_pin.tsv``): the best peptide-spectrum match of every searched spectrum
against the target-decoy database, with the Comet features Percolator rescores
(``Xcorr``, ``deltCn``, ``lnExpect``, mass difference, peptide length, charge).
``Label`` is 1 for target and -1 for decoy matches.

Target-decoy competition on the raw Comet ``Xcorr`` gives a first, conservative
estimate of how many spectra identify at 1% and 5% FDR before any rescoring, so
this table isolates the search from the rescoring step: a raw file with few
confident Comet matches has an acquisition or search-space problem, not a
rescoring one. The final, rescored counts are in the peptide table.

Extra protein accessions past the ``Proteins`` column are tab-separated in the
pin format, so rows are read with ragged lines truncated.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="pin",
        glob_pattern="**/*_pin.tsv",
        format="tsv",
        read_kwargs={
            "infer_schema_length": 0,
            "truncate_ragged_lines": True,
            "quote_char": None,
            "columns": ["Label", "ScanNr", "ExpMass", "CalcMass", "Xcorr", "PepLen", "Peptide"],
        },
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "run_id": pl.Utf8,
    "spectra_searched": pl.Int64,
    "target_psms": pl.Int64,
    "decoy_psms": pl.Int64,
    "psms_1pct_fdr": pl.Int64,
    "psms_5pct_fdr": pl.Int64,
    "identification_rate": pl.Float64,
    "median_xcorr_target": pl.Float64,
    "median_xcorr_decoy": pl.Float64,
    "median_mass_error_ppm": pl.Float64,
    "median_peptide_length": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def _tda(frame: pl.DataFrame) -> pl.DataFrame:
    """Target-decoy q-value of every target PSM, ranked by descending Xcorr."""
    ranked = frame.sort("xcorr", descending=True).with_columns(
        pl.col("is_decoy").cum_sum().alias("_d"),
        (~pl.col("is_decoy")).cum_sum().alias("_t"),
    )
    fdr = (pl.col("_d") / pl.max_horizontal(pl.col("_t"), pl.lit(1))).alias("_fdr")
    # q-value: the lowest FDR at which the PSM is still accepted.
    return ranked.with_columns(fdr).with_columns(
        pl.col("_fdr").reverse().cum_min().reverse().alias("q_value")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    pin = (
        sources["pin"]
        .with_columns(
            pl.col("source_path")
            .str.split("/")
            .list.last()
            .str.replace(r"_pin\.tsv$", "")
            .alias("run_id"),
            pl.col("Label").cast(pl.Int64, strict=False).alias("label"),
            pl.col("Xcorr").cast(pl.Float64, strict=False).alias("xcorr"),
            pl.col("ExpMass").cast(pl.Float64, strict=False).alias("_exp"),
            pl.col("CalcMass").cast(pl.Float64, strict=False).alias("_calc"),
            pl.col("PepLen").cast(pl.Float64, strict=False).alias("_len"),
        )
        .filter(pl.col("label").is_in([1, -1]))
    )
    pin = pin.with_columns(
        (pl.col("label") == -1).alias("is_decoy"),
        ((pl.col("_exp") - pl.col("_calc")) / pl.col("_calc") * 1e6).alias("_ppm"),
    )
    rows = []
    for (run_id,), frame in pin.group_by("run_id"):
        q = _tda(frame).filter(~pl.col("is_decoy"))
        target = frame.filter(~pl.col("is_decoy"))
        decoy = frame.filter(pl.col("is_decoy"))
        spectra = frame.select(pl.col("ScanNr").n_unique()).item()
        at_1 = q.filter(pl.col("q_value") <= 0.01).height
        rows.append(
            {
                "run_id": run_id,
                "spectra_searched": spectra,
                "target_psms": target.height,
                "decoy_psms": decoy.height,
                "psms_1pct_fdr": at_1,
                "psms_5pct_fdr": q.filter(pl.col("q_value") <= 0.05).height,
                "identification_rate": at_1 / spectra if spectra else None,
                "median_xcorr_target": target["xcorr"].median(),
                "median_xcorr_decoy": decoy["xcorr"].median(),
                "median_mass_error_ppm": target["_ppm"].median(),
                "median_peptide_length": target["_len"].median(),
            }
        )
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA).sort("run_id")
