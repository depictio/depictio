"""Per-gene selector recipes of the protein tabs (oncoanalyser 3.0.0, sarek 3.10.0).

Each folds a variant table to one row per gene under the column name the
protein views read (`entity` for oncoanalyser, `gene` for sarek), so a click on
the gene scatter moves the lollipop and the 3D structure. Hand-built rows,
checked against each recipe's own EXPECTED_SCHEMA through `validate_schema`.
"""

from __future__ import annotations

import polars as pl

from depictio.recipes import load_recipe, validate_schema


def _run(ref: str, version: str, sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    module = load_recipe(ref, version)
    out = module.transform(sources)
    validate_schema(out, module.EXPECTED_SCHEMA, ref, getattr(module, "OPTIONAL_SCHEMA", None))
    return out


def _changes() -> pl.DataFrame:
    rows = [
        ("GENE1", "T1", "MISSENSE", 0.40, True),
        ("GENE1", "T1", "NONSENSE_OR_FRAMESHIFT", 0.35, False),
        ("GENE2", "T1", "SYNONYMOUS", 0.10, None),
        ("GENE1", "T2", "MISSENSE", 0.20, False),
    ]
    return pl.DataFrame(
        rows,
        schema={
            "entity": pl.Utf8,
            "sample": pl.Utf8,
            "category": pl.Utf8,
            "value": pl.Float64,
            "hotspot": pl.Boolean,
        },
        orient="row",
    )


def _drivers() -> pl.DataFrame:
    rows = [
        ("GENE1", "T1", "MUTATION", "somatic", "TSG", 0.9, True),
        ("GENE1", "T1", "LOH", "somatic", "TSG", 1.0, True),
        ("GENE1", "T1", "GERMLINE_MUTATION", "germline", "TSG", 1.0, True),
        ("GENE2", "T1", "AMP", "somatic", "ONCO", 1.0, False),
    ]
    return pl.DataFrame(
        rows,
        schema={
            "gene": pl.Utf8,
            "sample": pl.Utf8,
            "driver": pl.Utf8,
            "origin": pl.Utf8,
            "category": pl.Utf8,
            "driver_likelihood": pl.Float64,
            "reported": pl.Boolean,
        },
        orient="row",
    )


def test_oncoanalyser_protein_genes_folds_per_tumor_and_gene() -> None:
    out = _run(
        "nf-core/oncoanalyser/protein_genes.py",
        "3.0.0",
        {"changes": _changes(), "drivers": _drivers()},
    )
    rows = {(r["entity"], r["sample"]): r for r in out.iter_rows(named=True)}
    assert set(rows) == {("GENE1", "T1"), ("GENE2", "T1"), ("GENE1", "T2")}

    g1 = rows[("GENE1", "T1")]
    assert g1["changes"] == 2
    assert g1["hotspots"] == 1
    assert g1["max_af"] == 0.40
    assert g1["worst_effect"] == "NONSENSE_OR_FRAMESHIFT"
    # The MUTATION row's likelihood, not the LOH one; germline rows ignored.
    assert g1["driver_likelihood"] == 0.9
    assert g1["gene_role"] == "TSG"
    assert g1["driver_types"] == "LOH, MUTATION"
    assert g1["reported"] is True

    # A driver without a MUTATION row keeps the gene at likelihood 0.
    g2 = rows[("GENE2", "T1")]
    assert g2["driver_likelihood"] == 0.0
    assert g2["gene_role"] == "ONCO"
    assert g2["reported"] is False

    # Not in the catalog for that tumor.
    other = rows[("GENE1", "T2")]
    assert other["driver_likelihood"] == 0.0
    assert other["gene_role"] == "unlisted"
    assert other["driver_types"] == ""

    # Driver candidates first.
    assert out.row(0, named=True)["entity"] == "GENE1"
    assert out.row(0, named=True)["sample"] == "T1"


def test_oncoanalyser_protein_genes_without_driver_catalog() -> None:
    out = _run(
        "nf-core/oncoanalyser/protein_genes.py",
        "3.0.0",
        {"changes": _changes(), "drivers": None},
    )
    assert out.height == 3
    assert out["driver_likelihood"].to_list() == [0.0, 0.0, 0.0]
    assert set(out["gene_role"].to_list()) == {"unlisted"}


def test_sarek_protein_genes_counts_caller_agreement() -> None:
    rows = [
        # gene, sample, caller, aa_pos, impact, variant_key, vaf
        ("GA", "S1", "c1", 10, "MODERATE", "v1", 0.5),
        ("GA", "S1", "c2", 10, "MODERATE", "v1", 0.4),
        ("GA", "S1", "c1", 20, "HIGH", "v2", 0.3),
        ("GA", "S2", "c1", 10, "MODERATE", "v1", 0.6),
        ("GB", "S1", "c2", 5, "LOW", "v3", 1.0),
    ]
    lolli = pl.DataFrame(
        rows,
        schema={
            "gene": pl.Utf8,
            "sample": pl.Utf8,
            "caller": pl.Utf8,
            "aa_pos": pl.Int64,
            "impact": pl.Utf8,
            "variant_key": pl.Utf8,
            "vaf": pl.Float64,
        },
        orient="row",
    )
    out = _run("nf-core/sarek/protein_genes.py", "3.10.0", {"variants": lolli})
    by_gene = {r["gene"]: r for r in out.iter_rows(named=True)}

    ga = by_gene["GA"]
    assert ga["variants"] == 2
    assert ga["positions"] == 2
    # (S1, v1) by two callers, (S1, v2) and (S2, v1) by one: 1 of 3 shared.
    assert ga["calls"] == 3
    assert abs(ga["shared_pct"] - 100 / 3) < 1e-9
    assert ga["samples"] == 2
    assert ga["callers"] == 2
    assert ga["high_variants"] == 1
    assert ga["moderate_variants"] == 1
    assert ga["worst_impact"] == "HIGH"

    gb = by_gene["GB"]
    assert gb["shared_pct"] == 0.0
    assert gb["worst_impact"] == "LOW"
    assert out["gene"].to_list() == ["GA", "GB"]
