"""nf-core/sarek 3.10.0: the recipes and wiring of the Protein tab.

The tab picks a gene on a scatter and narrows the lollipop to it. Three pieces
have to agree on column names, and none of them is checked anywhere else:

* ``snpeff/protein_lollipop`` (the catalog recipe) writes the coding variants,
  with the reference residue of each protein change;
* ``nf-core/sarek/protein_genes`` (the project recipe) folds them to one row per
  gene, under the same ``gene`` column, so a click on the scatter reaches the
  lollipop;
* the dashboard binds both. It draws no 3D structure, so the structure resolver
  is not involved.

The recipes run on hand-built rows and are checked against their own
OUTPUT_SCHEMA through ``validate_schema``, which is what ingest enforces.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import polars as pl
import pytest
import yaml

from depictio.models.components.advanced_viz.catalog import load_catalog_entries
from depictio.recipes import load_recipe, validate_schema

VERSION = "3.10.0"
DASHBOARD = (
    Path(__file__).resolve().parents[2]
    / "projects/nf-core/sarek"
    / VERSION
    / "dashboards/base.yaml"
)


def _run(ref: str, sources: dict[str, pl.DataFrame], version: str | None = None) -> pl.DataFrame:
    module = load_recipe(ref, version)
    out = module.transform(sources)
    validate_schema(out, module.OUTPUT_SCHEMA, ref, getattr(module, "OPTIONAL_OUTPUT_SCHEMA", None))
    return out


def _annotated(rows: list[tuple[Any, ...]]) -> pl.DataFrame:
    """Rows shaped like ``snpeff_ann_variants``, the lollipop recipe's source."""
    return pl.DataFrame(
        rows,
        schema={
            "sample": pl.Utf8,
            "caller": pl.Utf8,
            "gene": pl.Utf8,
            "aa_pos": pl.Int64,
            "impact": pl.Utf8,
            "consequence": pl.Utf8,
            "hgvs_p": pl.Utf8,
            "variant_key": pl.Utf8,
            "vaf": pl.Float64,
        },
        orient="row",
    )


def _lollipop(rows: list[tuple[Any, ...]]) -> pl.DataFrame:
    """Rows shaped like ``snpeff_protein_lollipop``, the gene recipe's source."""
    return pl.DataFrame(
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


# ---------------------------------------------------------------------------
# snpeff/protein_lollipop: the reference residue
# ---------------------------------------------------------------------------


def test_lollipop_names_the_reference_residue_of_each_protein_change() -> None:
    rows = [
        ("S1", "c1", "GA", 344, "MODERATE", "missense_variant", "p.Trp344Arg", "v1", 0.5),
        ("S1", "c1", "GA", 209, "LOW", "synonymous_variant", "p.Leu209Leu", "v2", 1.0),
        ("S1", "c1", "GA", 1, "HIGH", "start_lost", "p.Met1?", "v3", 0.4),
        ("S1", "c1", "GA", 12, "HIGH", "frameshift_variant", "p.Gly12fs", "v4", 0.3),
        # A stop-loss names the stop codon, which is no residue of any model.
        ("S1", "c1", "GA", 100, "HIGH", "stop_lost", "p.Ter100Glnext*?", "v5", 0.2),
    ]
    out = _run("snpeff/protein_lollipop.py", {"variants": _annotated(rows)})
    ref = dict(zip(out["variant_key"].to_list(), out["ref_aa"].to_list(), strict=True))
    assert ref == {"v1": "Trp", "v2": "Leu", "v3": "Met", "v4": "Gly", "v5": None}


def test_lollipop_keeps_coding_variants_only_and_the_columns_the_gene_recipe_reads() -> None:
    rows = [
        ("S1", "c1", "GA", 10, "MODERATE", "missense_variant", "p.Ala10Val", "v1", 0.5),
        ("S1", "c1", "GA", None, "MODIFIER", "intron_variant", None, "v2", 0.5),
        ("S1", "c1", "", 5, "LOW", "synonymous_variant", "p.Ala5Ala", "v3", 0.5),
        ("S1", "c1", "GB", 7, "MODIFIER", "upstream_gene_variant", "p.Ala7Ala", "v4", 0.5),
    ]
    out = _run("snpeff/protein_lollipop.py", {"variants": _annotated(rows)})
    assert out["variant_key"].to_list() == ["v1"]

    gene_recipe = load_recipe("nf-core/sarek/protein_genes.py", VERSION)
    needed = gene_recipe.SOURCES[0].input_schema
    assert needed is not None
    assert set(needed) <= set(out.columns)


# ---------------------------------------------------------------------------
# nf-core/sarek/protein_genes
# ---------------------------------------------------------------------------


def test_protein_genes_counts_caller_agreement() -> None:
    rows = [
        # gene, sample, caller, aa_pos, impact, variant_key, vaf
        ("GA", "S1", "c1", 10, "MODERATE", "v1", 0.5),
        ("GA", "S1", "c2", 10, "MODERATE", "v1", 0.4),
        ("GA", "S1", "c1", 20, "HIGH", "v2", 0.3),
        ("GA", "S2", "c1", 10, "MODERATE", "v1", 0.6),
        ("GB", "S1", "c2", 5, "LOW", "v3", 1.0),
    ]
    out = _run("nf-core/sarek/protein_genes.py", {"variants": _lollipop(rows)}, VERSION)
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
    assert ga["median_vaf"] == 0.45

    gb = by_gene["GB"]
    assert gb["shared_pct"] == 0.0
    assert gb["worst_impact"] == "LOW"
    assert gb["high_variants"] == 0
    # Busiest gene first.
    assert out["gene"].to_list() == ["GA", "GB"]


def test_protein_genes_breaks_a_tie_on_the_gene_name() -> None:
    rows = [
        ("GZ", "S1", "c1", 1, "LOW", "v1", 0.5),
        ("GA", "S1", "c1", 1, "LOW", "v2", 0.5),
    ]
    out = _run("nf-core/sarek/protein_genes.py", {"variants": _lollipop(rows)}, VERSION)
    assert out["gene"].to_list() == ["GA", "GZ"]


def test_protein_genes_on_an_empty_lollipop_keeps_its_schema() -> None:
    out = _run("nf-core/sarek/protein_genes.py", {"variants": _lollipop([])}, VERSION)
    assert out.height == 0
    assert out.columns == list(load_recipe("nf-core/sarek/protein_genes.py", VERSION).OUTPUT_SCHEMA)


def test_protein_genes_has_no_sample_or_caller_column() -> None:
    """The scatter reads the whole run: a sample or caller picker must not reach it."""
    schema = load_recipe("nf-core/sarek/protein_genes.py", VERSION).OUTPUT_SCHEMA
    assert "sample" not in schema
    assert "caller" not in schema


# ---------------------------------------------------------------------------
# nf-core/sarek/caller_overlap
# ---------------------------------------------------------------------------


def _calls(rows: list[tuple[Any, ...]]) -> pl.DataFrame:
    """Rows shaped like ``snpeff_ann_variants``, the overlap recipe's source."""
    return pl.DataFrame(
        rows,
        schema={
            "sample": pl.Utf8,
            "caller": pl.Utf8,
            "variant_key": pl.Utf8,
            "variant_type": pl.Utf8,
            "is_pass": pl.Boolean,
        },
        orient="row",
    )


def test_caller_overlap_has_one_set_column_per_caller_and_counts_agreement() -> None:
    rows = [
        # sample, caller, variant_key, variant_type, is_pass
        ("S1", "c1", "v1", "SNP", True),
        ("S1", "c2", "v1", "SNP", True),
        ("S1", "c1", "v2", "SNP", True),
        ("S1", "c2", "v3", "INDEL", True),
        ("S2", "c1", "v1", "SNP", True),
        # Neither a filtered call nor a structural variant is a membership.
        ("S1", "c2", "v9", "SNP", False),
        ("S1", "c3", "v1", "SNP", False),
        ("S1", "c3", "sv1", "SV", True),
    ]
    out = _run("nf-core/sarek/caller_overlap.py", {"variants": _calls(rows)}, VERSION)
    assert out.columns == ["sample", "variant_key", "n_callers", "sample_shared_pct", "c1", "c2"]

    s1 = {r["variant_key"]: r for r in out.filter(pl.col("sample") == "S1").iter_rows(named=True)}
    assert set(s1) == {"v1", "v2", "v3"}
    assert (s1["v1"]["c1"], s1["v1"]["c2"], s1["v1"]["n_callers"]) == (1, 1, 2)
    assert (s1["v2"]["c1"], s1["v2"]["c2"]) == (1, 0)
    # One of the sample's three PASS calls is made by two callers.
    assert abs(s1["v1"]["sample_shared_pct"] - 100 / 3) < 1e-9
    s2 = out.filter(pl.col("sample") == "S2")
    assert s2["sample_shared_pct"].to_list() == [0.0]


def test_caller_overlap_keeps_the_most_shared_calls_when_it_caps() -> None:
    module = load_recipe("nf-core/sarek/caller_overlap.py", VERSION)
    rows = [("S1", "c1", f"v{i}", "SNP", True) for i in range(5)]
    rows += [("S1", "c2", "v0", "SNP", True)]
    original = module.MAX_ELEMENTS
    module.MAX_ELEMENTS = 2
    try:
        out = module.transform({"variants": _calls(rows)})
    finally:
        module.MAX_ELEMENTS = original
    assert out.height == 2
    assert "v0" in out["variant_key"].to_list()
    # The share is counted before the cap: 1 of the 5 calls is shared.
    assert out["sample_shared_pct"].to_list() == [20.0, 20.0]


def test_caller_overlap_is_wired_to_the_dashboard() -> None:
    dashboard = yaml.safe_load(DASHBOARD.read_text())
    tab = next(t for t in dashboard["tabs"] if t["title"] == "Caller concordance")
    tile = _tile(tab, "cc-variant-upset")
    assert tile["data_collection_tag"] == "snpeff_variant_upset"
    # The two numeric helper columns are 0/1 on a one-caller run: they are not sets.
    pattern = tile["config"]["set_columns_pattern"]
    assert re.search(pattern, "n_callers") is None
    assert re.search(pattern, "sample_shared_pct") is None
    assert re.search(pattern, "deepvariant") is not None


# ---------------------------------------------------------------------------
# The dashboard's Protein tab
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def protein_tab() -> dict[str, Any]:
    dashboard = yaml.safe_load(DASHBOARD.read_text())
    return next(t for t in dashboard["tabs"] if t["title"] == "Protein")


def _tile(tab: dict[str, Any], index: str) -> dict[str, Any]:
    return next(c for c in tab["components"] if c.get("index") == index)


def test_structure_render_is_bound_by_gene_and_checks_its_numbering() -> None:
    tool = next(e for e in load_catalog_entries() if e.id == "snpeff")
    output = next(o for o in tool.outputs if o.id == "snpeff_protein_lollipop")
    render = next(r for r in output.renders_as if r.id == "coding_variant_structure")
    assert render.kind == "molecule_3d"
    # The resolver looks the gene up; the entity the tile shows is that gene.
    assert render.roles["gene"] == "gene"
    assert render.roles["entity"] == "gene"
    # The numbering check: without it a variant lands on the wrong residue.
    assert render.roles["ref_aa"] == "ref_aa"
    recipe = load_recipe(output.recipe)
    assert set(render.roles.values()) <= set(recipe.OUTPUT_SCHEMA)


def test_tiles_share_the_gene_column_so_a_pick_reaches_the_lollipop(
    protein_tab: dict[str, Any],
) -> None:
    genes_schema = load_recipe("nf-core/sarek/protein_genes.py", VERSION).OUTPUT_SCHEMA
    lollipop_schema = load_recipe("snpeff/protein_lollipop.py").OUTPUT_SCHEMA

    scatter = _tile(protein_tab, "pr-genes")
    cfg = scatter["config"]
    assert scatter["data_collection_tag"] == "protein_genes"
    assert cfg["selection_enabled"] is True
    # The click emits `gene`, and the lollipop has that column.
    assert cfg["selection_column"] == "gene"
    assert "gene" in genes_schema and "gene" in lollipop_schema
    for key in ("x_col", "y_col", "label_col", "color_col"):
        assert cfg[key] in genes_schema, key

    assert _tile(protein_tab, "pr-lollipop")["data_collection_tag"] == "snpeff_protein_lollipop"
    # The tab draws no 3D structure tile.
    assert all(c.get("index") != "pr-structure" for c in protein_tab["components"])


def test_every_protein_card_reads_a_column_its_collection_has(
    protein_tab: dict[str, Any],
) -> None:
    schemas = {
        "protein_genes": load_recipe("nf-core/sarek/protein_genes.py", VERSION).OUTPUT_SCHEMA,
        "snpeff_protein_lollipop": load_recipe("snpeff/protein_lollipop.py").OUTPUT_SCHEMA,
    }
    cards = [c for c in protein_tab["components"] if c["component_type"] == "card"]
    assert len(cards) == 4
    for card in cards:
        schema = schemas[card["data_collection_tag"]]
        assert card["column_name"] in schema, card["index"]
        if card.get("breakdown_col"):
            assert card["breakdown_col"] in schema, card["index"]
