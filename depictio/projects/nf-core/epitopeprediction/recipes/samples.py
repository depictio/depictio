"""Sample hub for nf-core/epitopeprediction: the run's samplesheet, one row per sample.

epitopeprediction reads its samplesheet from ``--input`` and does not publish it
in this release, so the template reads the file named by ``METADATA_FILE`` (by
default the copy under ``input/``). The pipeline's input schema fixes
``sample``, ``alleles``, ``mhc_class`` and ``filename``; ``tumor_sample`` and
``germline_vcf`` are optional (variant input only).

Every sheet column is kept under its own name (sanitised to ``[0-9A-Za-z_]``),
so ``GROUP_COL`` can name any column a user adds, and three columns are derived
from the sheet's content, never from the sample names:

* ``input_type``: ``Variants`` (VCF), ``Proteins`` (FASTA) or ``Peptides``
  (a peptide table), from the extension of ``filename``. It is the template's
  default ``GROUP_COL``: the three routes make different peptides.
* ``allele_source``: ``Listed`` (alleles written in the sheet, ``;``-separated),
  ``Allele file`` (a path or URL to a file of alleles) or ``All supported``
  (``HLA-all``: every allele the tools support).
* ``alleles``: the listed alleles normalised to ``HLA-A*02:01``, the file name
  of an allele file, or ``All supported``.

``mhc_class`` reads ``Class I`` / ``Class II`` / ``H-2``, the labels the
prediction tables use; ``filename`` and ``germline_vcf`` are reduced to file
names (``input_file``, ``germline_vcf``).

Output:
    sample, input_type, mhc_class, allele_source, alleles, input_file,
    tumor_sample, germline_vcf : Utf8, <other sheet columns> : Utf8
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.epitope_predictions import normalize_allele

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    # No input_schema: a tab-separated sheet is read as one column and re-split
    # by _fix_delimiter, so the required columns only exist after transform() starts.
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "input_type": pl.Utf8,
    "mhc_class": pl.Utf8,
    "allele_source": pl.Utf8,
    "alleles": pl.Utf8,
    "input_file": pl.Utf8,
    "tumor_sample": pl.Utf8,
    "germline_vcf": pl.Utf8,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

_REQUIRED = ("sample", "alleles", "mhc_class", "filename")
_VCF_RE = re.compile(r"\.vcf(\.gz)?$", re.IGNORECASE)
_FASTA_RE = re.compile(r"\.(fasta|fa|faa|fas)(\.gz)?$", re.IGNORECASE)
_CLASS_LABELS = {"I": "Class I", "II": "Class II", "H-2": "H-2"}
_ALL_ALLELES = {"hla-all", "all"}


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a tab-separated sheet that was read with a comma separator."""
    if df.width == 1 and "\t" in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=0)
    return df


def _sanitise(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def _basename(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value).rstrip("/").split("/")[-1]


def input_type_of(filename: str | None) -> str:
    """Variants, Proteins or Peptides, from the input file's extension."""
    name = _basename(filename) or ""
    if _VCF_RE.search(name):
        return "Variants"
    if _FASTA_RE.search(name):
        return "Proteins"
    return "Peptides"


def alleles_of(value: str | None) -> tuple[str, str | None]:
    """``(allele_source, alleles)`` for one samplesheet cell."""
    text = (value or "").strip()
    if not text:
        return "Listed", None
    if text.lower() in _ALL_ALLELES:
        return "All supported", "All supported"
    if "/" in text and (text.startswith(("http", "s3:", "/", ".")) or "." in _basename(text)):
        return "Allele file", _basename(text)
    alleles = [normalize_allele(a) for a in re.split(r"[;,]", text)]
    return "Listed", ";".join(a for a in alleles if a)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    sheet = _fix_delimiter(sources["samplesheet"])
    sheet = sheet.select(
        [pl.col(c).cast(pl.Utf8).str.strip_chars().alias(_sanitise(c)) for c in sheet.columns]
    )
    missing = [c for c in _REQUIRED if c not in sheet.columns]
    if missing:
        raise ValueError(
            f"epitopeprediction samplesheet: missing required column(s) {missing}; "
            f"got {sheet.columns}"
        )
    for column in ("tumor_sample", "germline_vcf"):
        if column not in sheet.columns:
            sheet = sheet.with_columns(pl.lit(None, dtype=pl.Utf8).alias(column))
    rows = sheet.filter(pl.col("sample").is_not_null() & (pl.col("sample") != ""))
    parsed = [alleles_of(v) for v in rows.get_column("alleles").to_list()]
    out = rows.with_columns(
        pl.Series("allele_source", [p[0] for p in parsed], dtype=pl.Utf8),
        pl.Series("alleles", [p[1] for p in parsed], dtype=pl.Utf8),
        pl.col("filename").map_elements(input_type_of, return_dtype=pl.Utf8).alias("input_type"),
        pl.col("filename").map_elements(_basename, return_dtype=pl.Utf8).alias("input_file"),
        pl.col("germline_vcf").map_elements(_basename, return_dtype=pl.Utf8),
        pl.col("mhc_class").replace(_CLASS_LABELS),
        pl.when(pl.col("tumor_sample") == "")
        .then(None)
        .otherwise(pl.col("tumor_sample"))
        .alias("tumor_sample"),
    ).drop("filename")
    lead = list(OUTPUT_SCHEMA)
    return out.select(lead + [c for c in out.columns if c not in lead]).sort("sample")
