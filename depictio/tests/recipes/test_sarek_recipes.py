"""nf-core/sarek 3.10.0: the recipes and wiring of the Protein tab.

The tab picks a gene on a scatter and loads its predicted structure and its
lollipop. Three pieces have to agree on column names, and none of them is
checked anywhere else:

* ``snpeff/protein_lollipop`` (the catalog recipe) writes the coding variants,
  with the reference residue the structure tile checks its numbering against;
* ``nf-core/sarek/protein_genes`` (the project recipe) folds them to one row per
  gene, under the same ``gene`` column, so a click on the scatter reaches the
  lollipop and the structure;
* the dashboard binds both, and the structure through the server's resolver.

The recipes run on hand-built rows and are checked against their own
OUTPUT_SCHEMA through ``validate_schema``, which is what ingest enforces.
"""

from __future__ import annotations

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


def test_tiles_share_the_gene_column_so_a_pick_reaches_all_three(
    protein_tab: dict[str, Any],
) -> None:
    genes_schema = load_recipe("nf-core/sarek/protein_genes.py", VERSION).OUTPUT_SCHEMA
    lollipop_schema = load_recipe("snpeff/protein_lollipop.py").OUTPUT_SCHEMA

    scatter = _tile(protein_tab, "pr-genes")
    cfg = scatter["config"]
    assert scatter["data_collection_tag"] == "protein_genes"
    assert cfg["selection_enabled"] is True
    # The click emits `gene`, and the lollipop and the structure have that column.
    assert cfg["selection_column"] == "gene"
    assert "gene" in genes_schema and "gene" in lollipop_schema
    for key in ("x_col", "y_col", "label_col", "color_col"):
        assert cfg[key] in genes_schema, key

    for index in ("pr-structure", "pr-lollipop"):
        assert _tile(protein_tab, index)["data_collection_tag"] == "snpeff_protein_lollipop"


def test_structure_tile_resolves_by_gene_and_never_sets_header_controls(
    protein_tab: dict[str, Any],
) -> None:
    tile = _tile(protein_tab, "pr-structure")
    assert tile["use"] == "snpeff/coding_variant_structure"
    cfg = tile["config"]
    # Off by default on the server: the tile says so, nothing is fetched at import.
    assert cfg["structure_source"] == "resolve"
    assert cfg["gene_col"] == "gene"
    assert cfg["entity_col"] == "gene"
    # RULES.md section 8: the dock decides where controls go.
    assert "controls_placement" not in cfg
    # The tile owns the limit a reader would otherwise meet as an empty tile.
    assert "2,700" in tile["description"]
    assert "2,700" in _tile(protein_tab, "pr-intro")["body"]
    assert "DEPICTIO_STRUCTURE_RESOLVER_ENABLED" in _tile(protein_tab, "pr-intro")["body"]


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
