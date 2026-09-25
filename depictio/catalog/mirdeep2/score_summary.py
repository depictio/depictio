"""The miRDeep2 score-cutoff summary, one row per sample and cutoff.

The first block of a miRDeep2 ``result_<sample>.csv`` tabulates, for every
integer score cutoff from 10 down to -10, how many novel candidates pass it,
how many of those are expected to be false positives (estimated by rerunning
the scoring on permuted structures), how many known miRBase miRNAs it
recovers, and the signal-to-noise ratio between the real and permuted runs.
It is the curve miRDeep2's authors read to pick a cutoff: the score where
signal-to-noise stays high while known-miRNA recovery has flattened.

Estimates read ``1 +/- 1`` and the recovery ``396 (40%)``; each is split into
its number (the spread and the percentage are recomputable or noise).

Input: the same one-line-per-row scan as ``mirdeep2/predictions.py``.

Output schema:
    sample : Utf8
    score_cutoff : Int64             miRDeep2 score threshold
    novel_reported : Int64           novel candidates at or above the cutoff
    novel_false_positives : Float64  estimated false positives among them
    novel_true_positives : Float64   estimated true positives among them
    known_in_species : Int64         miRBase precursors of the species
    known_in_data : Int64            of those, with reads in the sample
    known_detected : Int64           of those, recovered by miRDeep2 at this cutoff
    known_detected_pct : Float64     known_detected over known_in_data, %
    signal_to_noise : Float64        real over permuted candidate counts
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "mirdeep2_results_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="results", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "score_cutoff": pl.Int64,
    "novel_reported": pl.Int64,
    "novel_false_positives": pl.Float64,
    "novel_true_positives": pl.Float64,
    "known_in_species": pl.Int64,
    "known_in_data": pl.Int64,
    "known_detected": pl.Int64,
    "known_detected_pct": pl.Float64,
    "signal_to_noise": pl.Float64,
}

RAW_LINE_COL = "raw"
SOURCE_PATH_COL = "source_path"
_HEADER = "mirdeep2 score"
_LEADING_NUMBER = re.compile(r"^\s*(-?[\d.]+)")


def _sample_from_path(source_path: str) -> str:
    name = str(source_path).replace("\\", "/").rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return stem[len("result_") :] if stem.startswith("result_") else stem


def _number(value: str | None) -> float | None:
    match = _LEADING_NUMBER.match(value or "")
    return float(match.group(1)) if match else None


def _parse(source_path: str, lines: list[str | None]) -> list[dict]:
    sample = _sample_from_path(source_path)
    rows: list[dict] = []
    in_block = False
    for line in lines:
        text = (line or "").rstrip("\r\n")
        if not in_block:
            in_block = text.lower().startswith(_HEADER)
            continue
        if not text.strip():
            break
        cells = text.split("\t") + [""] * 9
        cutoff = _number(cells[0])
        if cutoff is None:
            continue
        in_data = _number(cells[5])
        detected = _number(cells[6])
        rows.append(
            {
                "sample": sample,
                "score_cutoff": int(cutoff),
                "novel_reported": _number(cells[1]),
                "novel_false_positives": _number(cells[2]),
                "novel_true_positives": _number(cells[3]),
                "known_in_species": _number(cells[4]),
                "known_in_data": in_data,
                "known_detected": detected,
                "known_detected_pct": (
                    100.0 * detected / in_data if in_data and detected is not None else None
                ),
                "signal_to_noise": _number(cells[7]),
            }
        )
    return rows


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (sample, score cutoff)."""
    raw = sources["results"]
    if raw.is_empty() or RAW_LINE_COL not in raw.columns or SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "mirdeep2_score_summary: expected a one-line-per-row scan with a source_path column"
        )
    rows: list[dict] = []
    for (path,), group in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        rows.extend(_parse(str(path), group[RAW_LINE_COL].to_list()))
    if not rows:
        raise ValueError("mirdeep2_score_summary: no table carried a score summary block")
    frame = pl.DataFrame(rows, infer_schema_length=None)
    frame = frame.with_columns(
        [pl.col(c).cast(t, strict=False) for c, t in EXPECTED_SCHEMA.items()]
    )
    return frame.select(list(EXPECTED_SCHEMA)).sort(["sample", "score_cutoff"])
