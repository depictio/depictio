"""One row per read set, from GenomeScope's summary table.

GenomeScope prints a fixed-width table with a `min` and a `max` column per
property (percentages with `%`, lengths with thousands separators and `bp`).
GenomeScope 1 names the heterozygosity row `Heterozygosity`; GenomeScope 2 adds
the ploidy (`p = 2`) and splits it into `Homozygous (aa)` and `Heterozygous
(ab)` (and more rows for higher ploidy, which this recipe does not keep). Both
layouts are read.

The read set is named after the file: `<name>_genomescope.txt` (the
nf-core/genomeassembler name), `<name>_summary.txt` (the nf-core genomescope2
module), or a bare `summary.txt`, which takes the parent directory's name.

Input: the ``genomescope_raw`` data collection, a recursive Table scan reading
one line per row::

    dc_specific_properties:
      format: TSV
      polars_kwargs: {separator: "\\x1f", has_header: false, new_columns: [raw],
                      include_file_paths: source_path, infer_schema_length: 0}

Output schema:
    read_set : Utf8                  the read set the spectrum was counted from
    genomescope_version : Utf8       as printed
    k : Int64                        k-mer length
    ploidy : Int64                   GenomeScope 2 ploidy (null for GenomeScope 1)
    heterozygosity_min : Float64     percent
    heterozygosity_max : Float64     percent
    haploid_length_min : Int64       bp
    haploid_length_max : Int64       bp
    repeat_length_min : Int64        bp
    repeat_length_max : Int64        bp
    unique_length_min : Int64        bp
    unique_length_max : Int64        bp
    repeat_fraction : Float64        repeat_length_max / haploid_length_max, percent
    model_fit_min : Float64          percent
    model_fit_max : Float64          percent
    read_error_rate_min : Float64    percent
    read_error_rate_max : Float64    percent
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "genomescope_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lines", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "read_set": pl.Utf8,
    "genomescope_version": pl.Utf8,
    "k": pl.Int64,
    "ploidy": pl.Int64,
    "heterozygosity_min": pl.Float64,
    "heterozygosity_max": pl.Float64,
    "haploid_length_min": pl.Int64,
    "haploid_length_max": pl.Int64,
    "repeat_length_min": pl.Int64,
    "repeat_length_max": pl.Int64,
    "unique_length_min": pl.Int64,
    "unique_length_max": pl.Int64,
    "repeat_fraction": pl.Float64,
    "model_fit_min": pl.Float64,
    "model_fit_max": pl.Float64,
    "read_error_rate_min": pl.Float64,
    "read_error_rate_max": pl.Float64,
}

SOURCE_PATH_COL = "source_path"

#: Row label in the summary -> output column stem.
PROPERTIES: dict[str, str] = {
    "Heterozygosity": "heterozygosity",
    "Heterozygous (ab)": "heterozygosity",
    "Genome Haploid Length": "haploid_length",
    "Genome Repeat Length": "repeat_length",
    "Genome Unique Length": "unique_length",
    "Model Fit": "model_fit",
    "Read Error Rate": "read_error_rate",
}

_VALUE = re.compile(r"(NA|-?[\d,]+(?:\.\d+)?(?:e[-+]?\d+)?)\s*(%|bp)?", re.IGNORECASE)


def read_set_name(source_path: str) -> str:
    """The read set a summary belongs to, from its path."""
    path = PurePosixPath(source_path.replace("\\", "/"))
    for suffix in ("_genomescope.txt", "_summary.txt"):
        if path.name.endswith(suffix):
            return path.name.removesuffix(suffix)
    if path.name == "summary.txt":
        return path.parent.name
    return path.stem


def _number(token: str) -> float | None:
    return None if token.upper() == "NA" else float(token.replace(",", ""))


def parse_summary(read_set: str, lines: list[str]) -> dict:
    """Parse one GenomeScope summary into an output row."""
    row: dict = {name: None for name in EXPECTED_SCHEMA}
    row["read_set"] = read_set
    for line in lines:
        text = line.rstrip()
        if text.startswith("GenomeScope version"):
            row["genomescope_version"] = text.removeprefix("GenomeScope version").strip()
            continue
        simple = re.match(r"^\s*(k|p)\s*=\s*(\d+)\s*$", text)
        if simple:
            row["k" if simple.group(1) == "k" else "ploidy"] = int(simple.group(2))
            continue
        for label, stem in PROPERTIES.items():
            if text.startswith(label):
                values = _VALUE.findall(text[len(label) :])
                if len(values) >= 2:
                    low, high = (_number(values[0][0]), _number(values[1][0]))
                    as_int = stem.endswith("_length")
                    row[f"{stem}_min"] = int(low) if (as_int and low is not None) else low
                    row[f"{stem}_max"] = int(high) if (as_int and high is not None) else high
                break
    haploid, repeat = row["haploid_length_max"], row["repeat_length_max"]
    row["repeat_fraction"] = 100.0 * repeat / haploid if haploid and repeat is not None else None
    return row


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Parse every scanned GenomeScope summary."""
    raw = sources["lines"]
    if raw.is_empty():
        raise ValueError("genomescope_summary: the scanned summaries are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError("genomescope_summary: the scan must include_file_paths: source_path")
    text_col = next(c for c in raw.columns if c != SOURCE_PATH_COL)
    rows = [
        parse_summary(read_set_name(str(path)), [ln or "" for ln in group[text_col].to_list()])
        for (path,), group in raw.group_by([SOURCE_PATH_COL], maintain_order=True)
    ]
    out = pl.DataFrame(rows, schema=EXPECTED_SCHEMA)
    out = out.filter(pl.col("haploid_length_max").is_not_null() | pl.col("k").is_not_null())
    if out.is_empty():
        raise ValueError("genomescope_summary: no file parsed as a GenomeScope summary")
    return out.unique(subset=["read_set"], keep="first", maintain_order=True).sort("read_set")
