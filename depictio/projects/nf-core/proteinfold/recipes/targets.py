"""Target hub for nf-core/proteinfold: one row per target of the samplesheet.

proteinfold does not publish the samplesheet it ran on, so the template reads
the file named by ``METADATA_FILE`` (by default the copy under ``input/``). The
input schema fixes two columns, ``id`` (the target, the name of every output
file) and ``fasta``; every other column the sheet carries is kept under its own
name so ``GROUP_COL`` can name it. What the structures say about each target
is added: how many chains it has and whether it is a single chain or a complex
(``assembly``, the default grouping), its length, how many engines folded it
and which, and its sequence (chains joined by ``:``) as the structure reads it.

Targets folded but missing from the sheet are kept, with the sheet columns
empty, so a hand-written sheet never hides a structure.

Sources:
    samplesheet  ``input/samplesheet.csv`` (repointed to METADATA_FILE)
    structures   ``**/top_ranked_structures/*.pdb``, one text line per row
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.proteinfold import RAW_LINE_READ_KWARGS, top_model_residues

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(
        ref="structures",
        glob_pattern="**/top_ranked_structures/*.pdb",
        format="csv",
        read_kwargs=RAW_LINE_READ_KWARGS,
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "target": pl.Utf8,
    "assembly": pl.Utf8,
    "n_chains": pl.Int64,
    "n_residues": pl.Int64,
    "n_engines": pl.Int64,
    "engines": pl.Utf8,
    "sequence": pl.Utf8,
    "fasta": pl.Utf8,
}


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a tab-separated sheet that was read as comma-separated."""
    if df.width == 1 and "\t" in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=0)
    return df


def _sanitise(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Samplesheet + top-ranked structures -> one row per target."""
    sheet = _fix_delimiter(sources["samplesheet"])
    if "id" not in sheet.columns:
        raise ValueError(f"proteinfold samplesheet: no 'id' column; got {sheet.columns}")
    sheet = sheet.select(
        [pl.col(c).cast(pl.Utf8).str.strip_chars().alias(_sanitise(c)) for c in sheet.columns]
    ).rename({"id": "target"})
    if "fasta" not in sheet.columns:
        sheet = sheet.with_columns(pl.lit(None, dtype=pl.Utf8).alias("fasta"))
    sheet = sheet.unique("target", keep="first", maintain_order=True)

    residues = top_model_residues(sources["structures"])
    # The structure every engine agrees on: take the first engine's chains.
    first = (
        residues.sort(["target", "engine", "chain", "position"])
        .group_by("target", maintain_order=True)
        .agg(pl.col("engine").first().alias("_engine"))
    )
    reference = residues.join(first, on="target").filter(pl.col("engine") == pl.col("_engine"))
    per_chain = reference.group_by(["target", "chain"], maintain_order=True).agg(
        pl.col("residue").str.join("").alias("chain_sequence"),
        pl.len().alias("chain_length"),
    )
    structure = per_chain.group_by("target", maintain_order=True).agg(
        pl.len().cast(pl.Int64).alias("n_chains"),
        pl.col("chain_length").sum().cast(pl.Int64).alias("n_residues"),
        pl.col("chain_sequence").str.join(":").alias("sequence"),
    )
    engines = residues.group_by("target").agg(
        pl.col("engine").n_unique().cast(pl.Int64).alias("n_engines"),
        pl.col("engine").unique().sort().str.join(", ").alias("engines"),
    )
    derived = structure.join(engines, on="target", how="left").with_columns(
        pl.when(pl.col("n_chains") > 1)
        .then(pl.lit("complex"))
        .otherwise(pl.lit("single chain"))
        .alias("assembly")
    )
    out = sheet.join(derived, on="target", how="full", coalesce=True)
    extra = [c for c in out.columns if c not in EXPECTED_SCHEMA]
    return (
        out.select([*EXPECTED_SCHEMA, *extra])
        .with_columns(
            [pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()]
            + [pl.col(c).cast(pl.Utf8) for c in extra]
        )
        .sort("target")
    )
