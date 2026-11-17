"""One row per structural-variant record the SV callers (Manta, TIDDIT) wrote.

Reads the raw VCF lines the ``vcf_calls_raw`` scan holds and keeps those of a
structural-variant caller, parsed by ``depictio.recipes.lib.vcf.sv_to_long``:
type (``SVTYPE``), length (``SVLEN``) and end (``END``) next to the locus, the
quality and the FILTER. A small-variant caller's VCF has no use for these
columns, so its rows stay in ``vcf_variants`` alone.

Records are kept as written, so a breakend (BND) is two rows, one per side.
``primary`` is true on one record of each event; a count of events filters on it.
``link_chrom`` / ``link_pos`` are the far end of an event, for the genome chord: the
mate of a breakend, the end of a deletion, duplication or inversion. They are null
on the second record of a breakend (one chord per event) and on an insertion, which
has a single locus.
Manta's ``candidate_*`` VCFs (the calls before its diploid model) are left out:
the genotyped ``diploid_sv`` file is the callset. Only the units of a germline sample
are read (``depictio.recipes.lib.sarek_units``): a pair's or a tumour's SV file
(Manta's ``somatic_sv``, ``tumor_sv``) is a different callset and is not read here.

A run with no SV caller has nothing to show, so the recipe raises and the
collection, being optional, is skipped: the Structural variants tab does not
appear.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sarek_units import GERMLINE, keep_unit_types
from depictio.recipes.lib.vcf import SOURCE_PATH_COL, sv_to_long

#: The callers whose VCFs are structural variants.
SV_CALLERS = ("manta", "tiddit")

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="raw",
        dc_ref="vcf_calls_raw",
        input_schema={"raw_line": pl.Utf8, "source_path": pl.Utf8},
    ),
    RecipeSource(
        ref="hub",
        dc_ref="samples",
        input_schema={"sample_id": pl.Utf8, "status": pl.Int64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "end": pl.Int64,
    "svtype": pl.Utf8,
    "svlen": pl.Int64,
    "size_bp": pl.Int64,
    "qual": pl.Float64,
    "filter_status": pl.Utf8,
    "is_pass": pl.Boolean,
    "imprecise": pl.Boolean,
    "primary": pl.Boolean,
    "mate_chrom": pl.Utf8,
    "mate_pos": pl.Int64,
    "link_chrom": pl.Utf8,
    "link_pos": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Parse the SV callers' VCF lines into one row per record."""
    name = pl.col(SOURCE_PATH_COL).str.split("/").list.last()
    callers = "|".join(SV_CALLERS)
    raw = sources["raw"].filter(
        name.str.contains(rf"^[^.]+\.(?:{callers})\.") & ~name.str.contains("candidate")
    )
    out = keep_unit_types(sv_to_long(raw), sources.get("hub"), GERMLINE)
    if out.is_empty():
        raise ValueError(
            f"sarek sv_calls: no VCF of a structural-variant caller ({', '.join(SV_CALLERS)}) "
            "among the run's calls"
        )
    linked = pl.col("primary") & (pl.col("svtype") != "INS")
    out = out.with_columns(
        pl.when(linked)
        .then(pl.coalesce(pl.col("mate_chrom"), pl.col("chrom")))
        .alias("link_chrom"),
        pl.when(linked).then(pl.coalesce(pl.col("mate_pos"), pl.col("end"))).alias("link_pos"),
    )
    return out.select(list(OUTPUT_SCHEMA)).sort(["sample", "caller", "chrom", "pos"])
