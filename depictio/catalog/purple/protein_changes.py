"""Protein-changing somatic variants in the protein module's variant contract.

Reads the ``purple_somatic_variants`` collection and keeps the calls whose
canonical HGVS protein change (PAVE ``IMPACT``) names a residue, e.g.
``p.Glu1608Gln``. The change is split into the canonical variant-table columns
the protein kinds bind (lollipop, molecule_3d, sequence_track):

* ``entity``: the gene symbol, the protein the residue belongs to;
* ``position``: the residue number (``1608``);
* ``ref_aa`` / ``alt_aa``: one-letter residues (``E`` / ``Q``); ``*`` for a
  stop gain, ``=`` resolved to the reference for a synonymous change, and null
  for a frameshift, deletion, insertion or duplication (no single new residue);
* ``category``: PAVE's canonical coding effect (``MISSENSE``,
  ``NONSENSE_OR_FRAMESHIFT``, ``SPLICE``, ``SYNONYMOUS``);
* ``value``: the purity-adjusted allele frequency (``PURPLE_AF``);
* ``label``: the short one-letter change, e.g. ``p.E1608Q``.

Splice-site calls with no residue (``p.?``) and non-coding calls are dropped.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [RecipeSource(ref="variants", dc_ref="purple_somatic_variants")]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "position": pl.Int64,
    "ref_aa": pl.Utf8,
    "alt_aa": pl.Utf8,
    "category": pl.Utf8,
    "value": pl.Float64,
    "label": pl.Utf8,
    "sample": pl.Utf8,
    "hgvs_p": pl.Utf8,
    "hgvs_c": pl.Utf8,
    "transcript": pl.Utf8,
    "canonical_effect": pl.Utf8,
    "variant_key": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "variant_copy_number": pl.Float64,
    "biallelic": pl.Boolean,
    "hotspot": pl.Boolean,
    "reported": pl.Boolean,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

THREE_TO_ONE: dict[str, str] = {
    "Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C", "Gln": "Q", "Glu": "E",
    "Gly": "G", "His": "H", "Ile": "I", "Leu": "L", "Lys": "K", "Met": "M", "Phe": "F",
    "Pro": "P", "Ser": "S", "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V", "Sec": "U",
    "Pyl": "O", "Ter": "*", "Xaa": "X",
}  # fmt: skip

#: p.<Ref3><pos><rest>; rest is the new residue, Ter/*, =, fs..., del, ins, dup, delins.
_HGVS_P_RE = r"^p\.\(?([A-Z][a-z]{2})(\d+)(.*?)\)?$"


def _one(three: pl.Expr) -> pl.Expr:
    return three.replace_strict(THREE_TO_ONE, default=None, return_dtype=pl.Utf8)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["variants"].filter(pl.col("hgvs_p").is_not_null() & pl.col("gene").is_not_null())
    ref3 = pl.col("hgvs_p").str.extract(_HGVS_P_RE, 1)
    rest = pl.col("hgvs_p").str.extract(_HGVS_P_RE, 3)
    ref1 = _one(ref3)
    alt1 = (
        pl.when(rest == "=")
        .then(ref1)
        .when(rest.is_in(["*", "Ter"]))
        .then(pl.lit("*"))
        .when(rest.str.contains(r"^[A-Z][a-z]{2}$"))
        .then(_one(rest))
        .otherwise(None)
    )
    short_rest = (
        pl.when(rest == "=")
        .then(pl.lit("="))
        .when(rest.str.contains(r"^[A-Z][a-z]{2}$|^\*$|^Ter$"))
        .then(alt1)
        .otherwise(rest.str.replace_all(r"[A-Z][a-z]{2}", ""))
    )
    out = df.with_columns(
        pl.col("gene").alias("entity"),
        pl.col("hgvs_p").str.extract(_HGVS_P_RE, 2).cast(pl.Int64, strict=False).alias("position"),
        ref1.alias("ref_aa"),
        alt1.alias("alt_aa"),
        pl.coalesce(pl.col("coding_effect"), pl.lit("OTHER")).alias("category"),
        pl.col("purple_af").alias("value"),
        pl.concat_str(
            [pl.lit("p."), ref1, pl.col("hgvs_p").str.extract(_HGVS_P_RE, 2), short_rest]
        ).alias("label"),
    ).filter(pl.col("position").is_not_null() & pl.col("ref_aa").is_not_null())
    return out.select(list(EXPECTED_SCHEMA)).sort(["entity", "position", "sample"])
