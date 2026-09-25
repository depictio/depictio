"""Sample hub for nf-core/mhcquant: the run's samplesheet, one row per MS raw file.

mhcquant does not publish the samplesheet it ran on, so the template reads the
file named by ``METADATA_FILE`` (by default the copy under ``input/``). The
pipeline's input schema fixes the columns this recipe relies on: ``ID`` (one per
raw file), ``Sample``, ``Condition`` and ``ReplicateFileName``; ``Fasta`` and
``SearchPreset`` are optional. Every sheet column is kept under its own name, so
``GROUP_COL`` can name any of them, and four join keys are added:

* ``sample_id``: ``<Sample>_<Condition>``, the id mhcquant writes its
  per-sample outputs under (``<sample_id>.tsv``, ``<sample_id>.mzTab``);
* ``run_id``: the raw file name without its extension, the id of every
  per-file output (``<run_id>_pin.tsv``, MultiQC chromatograms);
* ``replicate``: 1..n, the raw file's rank by ``ID`` within its sample, which
  is the order mhcquant feeds the files to feature linking, so it is also the
  order of the ``intensity_<k>`` columns of the peptide table;
* ``raw_file``: the raw file's base name.

Output:
    sample_id, run_id, raw_file : Utf8, replicate : Int64, <sheet columns> : Utf8
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "run_id": pl.Utf8,
    "replicate": pl.Int64,
    "raw_file": pl.Utf8,
    "Sample": pl.Utf8,
    "Condition": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# Extensions the mhcquant input schema accepts, longest first so `.d.tar.gz`
# is stripped whole rather than leaving `.d.tar`.
_RAW_SUFFIX = re.compile(r"\.(d\.tar\.gz|d\.tar|d\.zip|mzml\.gz|mzml|raw|d)$", re.IGNORECASE)
_REQUIRED = ("ID", "Sample", "Condition", "ReplicateFileName")


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a comma-separated sheet that was read with a tab separator."""
    if df.width == 1 and "," in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), infer_schema_length=0)
    return df


def _sanitise(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def run_id_of(path: str) -> str:
    """Raw file name without directory or MS extension."""
    base = path.rstrip("/").split("/")[-1]
    return _RAW_SUFFIX.sub("", base)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    sheet = _fix_delimiter(sources["samplesheet"])
    missing = [c for c in _REQUIRED if c not in sheet.columns]
    if missing:
        raise ValueError(
            f"mhcquant samplesheet: missing required column(s) {missing}; got {sheet.columns}"
        )
    sheet = sheet.select(
        [pl.col(c).cast(pl.Utf8).str.strip_chars().alias(_sanitise(c)) for c in sheet.columns]
    )
    raw = pl.col("ReplicateFileName")
    out = sheet.with_columns(
        (pl.col("Sample") + "_" + pl.col("Condition")).alias("sample_id"),
        raw.map_elements(run_id_of, return_dtype=pl.Utf8).alias("run_id"),
        raw.str.split("/").list.last().alias("raw_file"),
        pl.col("ID").cast(pl.Int64, strict=False).alias("_id_num"),
    )
    if "Fasta" in out.columns:
        out = out.with_columns(pl.col("Fasta").str.split("/").list.last().alias("Fasta"))
    out = out.with_columns(
        pl.col("_id_num").rank(method="ordinal").over("sample_id").cast(pl.Int64).alias("replicate")
    ).drop("_id_num")
    lead = ["sample_id", "run_id", "replicate", "raw_file"]
    return out.select(lead + [c for c in out.columns if c not in lead]).sort(
        ["sample_id", "replicate"]
    )
