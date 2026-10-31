"""The `allele_grid` kind: config, roles, guards and the showcase tab that binds it.

A sample x locus grid of diploid genotypes (HLA typing), drawn as plain SVG
with every number in `allele_grid/alleleGridLayout.ts` (unit-tested by vitest).
Here: the model contract, the sampling and export classification, the INCUBATING
entry, and the showcase fixture and dashboard checked against the real columns.

Pure-model + fixture reads: no DB, no network.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import get_args

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import AlleleGridConfig, VizConfig
from depictio.models.components.advanced_viz.record_link import SELECTION_EMITTING_KINDS
from depictio.models.components.advanced_viz.sampling import (
    KIND_SAMPLING_POLICY,
    policy_for_kind,
)
from depictio.models.components.advanced_viz.schemas import (
    _OPTIONAL_ROLES,
    CANONICAL_SCHEMAS,
    INCUBATING,
    KIND_METADATA,
    ROLE_NAMES,
    kind_descriptors,
    role_dtype_specs,
    suggest_viz_kinds,
    validate_binding,
)
from depictio.models.components.types import AdvancedVizKind

REPO = Path(__file__).resolve().parents[3]
SHOWCASE = REPO / "depictio" / "projects" / "init" / "advanced_viz_showcase"
FIXTURE = SHOWCASE / "data" / "allele_grid_demo.tsv"
EPITOPES = SHOWCASE / "data" / "epitope_predictions_demo.tsv"
DASHBOARD = SHOWCASE / "dashboards" / "allele_grid.yaml"
PROJECT = SHOWCASE / "project.yaml"

VIZ_CONFIG = TypeAdapter(VizConfig)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _schema(path: Path) -> dict[str, str]:
    """Column -> polars dtype name, numeric against string, as a scan reports it."""
    rows = _rows(path)
    assert rows, f"{path} has a header but no data rows"
    schema: dict[str, str] = {}
    for column in rows[0]:
        values = [r[column] for r in rows if r[column] != ""]

        def _is_float(v: str) -> bool:
            try:
                float(v)
            except ValueError:
                return False
            return True

        if values and all(v.lstrip("-").isdigit() for v in values):
            schema[column] = "Int64"
        elif values and all(_is_float(v) for v in values):
            schema[column] = "Float64"
        else:
            schema[column] = "String"
    return schema


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_the_kind_is_registered_everywhere():
    assert "allele_grid" in get_args(AdvancedVizKind)
    assert set(CANONICAL_SCHEMAS["allele_grid"]) == {"sample_id", "locus", "allele"}
    assert set(_OPTIONAL_ROLES["allele_grid"]) == {"haplotype", "category", "value", "reads"}
    assert KIND_METADATA["allele_grid"]["label"] == "Allele grid"
    descriptor = next(d for d in kind_descriptors() if d["viz_kind"] == "allele_grid")
    assert descriptor["legacy"] is False
    assert descriptor["required_roles"] == ["sample_id", "locus", "allele"]
    specs = role_dtype_specs("allele_grid")
    assert all(spec["description"] for spec in specs.values())


def test_every_role_has_aliases_naming_itself():
    for role in {**CANONICAL_SCHEMAS["allele_grid"], **_OPTIONAL_ROLES["allele_grid"]}:
        assert role in ROLE_NAMES["allele_grid"][role]
    # LILAC calls the locus `gene`; OptiType's objective is the value.
    assert "gene" in ROLE_NAMES["allele_grid"]["locus"]
    assert "objective" in ROLE_NAMES["allele_grid"]["value"]


def test_it_is_incubating_until_the_oncoplot_gate_review():
    """Bound only by the showcase tab, so it carries its reason in INCUBATING."""
    assert "allele_grid" in INCUBATING


def test_the_server_never_samples_a_genotype():
    """A sampled frame drops one haplotype and turns a locus falsely homozygous."""
    assert KIND_SAMPLING_POLICY["allele_grid"] == "none"
    assert policy_for_kind("allele_grid") == "none"


def test_an_allele_pick_reaches_a_record_card_on_the_allele_column():
    assert SELECTION_EMITTING_KINDS["allele_grid"] == ("selection_column", "allele_col", "=allele")


# ---------------------------------------------------------------------------
# The config
# ---------------------------------------------------------------------------


def test_defaults_bind_the_canonical_columns_and_nothing_optional():
    config = AlleleGridConfig()
    for role in CANONICAL_SCHEMAS["allele_grid"]:
        assert getattr(config, f"{role}_col") == role
    for role in _OPTIONAL_ROLES["allele_grid"]:
        assert getattr(config, f"{role}_col") is None


def test_display_defaults():
    config = AlleleGridConfig()
    assert config.resolution == 2
    assert config.sample_order == "alphabetical"
    assert config.order_locus is None
    assert config.show_labels is True
    assert config.side_bars == ["value", "reads"]
    assert config.reads_as_opacity is False
    assert config.controls_placement == "popover"
    assert config.selection_enabled is False


@pytest.mark.parametrize("resolution", [1, 2, 3, 4])
def test_every_nomenclature_resolution_is_accepted(resolution: int):
    assert AlleleGridConfig(resolution=resolution).resolution == resolution  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [0, 5, "2 fields"])
def test_a_resolution_outside_the_nomenclature_is_refused(bad: object):
    with pytest.raises(ValidationError):
        AlleleGridConfig(resolution=bad)  # type: ignore[arg-type]


def test_guards_are_bounded_on_both_sides():
    """An unbounded guard would let a tile ask for a 100 000-row SVG."""
    assert AlleleGridConfig().max_samples == 200
    assert AlleleGridConfig().max_loci == 24
    for field, bad in (
        ("max_samples", 0),
        ("max_samples", 5000),
        ("max_loci", 0),
        ("max_loci", 61),
    ):
        with pytest.raises(ValidationError):
            AlleleGridConfig(**{field: bad})


def test_side_bars_only_name_the_two_per_sample_columns():
    assert AlleleGridConfig(side_bars=[]).side_bars == []
    with pytest.raises(ValidationError):
        AlleleGridConfig(side_bars=["objective"])  # type: ignore[list-item]


def test_unknown_keys_are_refused_and_the_union_discriminates():
    with pytest.raises(ValidationError):
        VIZ_CONFIG.validate_python({"viz_kind": "allele_grid", "colour_map": {}})
    parsed = VIZ_CONFIG.validate_python(
        {
            "viz_kind": "allele_grid",
            "locus_order": ["HLA-A", "B"],
            "sample_order": "allele",
            "order_locus": "HLA-B",
            "selection_enabled": True,
        }
    )
    assert isinstance(parsed, AlleleGridConfig)
    assert parsed.locus_order == ["HLA-A", "B"]


# ---------------------------------------------------------------------------
# The showcase fixture and tab
# ---------------------------------------------------------------------------


def test_the_fixture_is_two_calls_per_donor_and_locus():
    rows = _rows(FIXTURE)
    pairs = Counter((r["sample_id"], r["locus"]) for r in rows)
    assert len({s for s, _ in pairs}) == 24
    assert {locus for _, locus in pairs} == {"HLA-A", "HLA-B", "HLA-C", "HLA-DRB1", "HLA-DQB1"}
    assert set(pairs.values()) == {2}
    assert {r["haplotype"] for r in rows} == {"1", "2"}
    assert {r["hla_class"] for r in rows} == {"Class I", "Class II"}
    # A few homozygous loci, by design (two 8.1 homozygotes) and by chance.
    calls: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        calls.setdefault((r["sample_id"], r["locus"]), []).append(r["allele"])
    homozygous = [k for k, v in calls.items() if v[0] == v[1]]
    assert 10 <= len(homozygous) <= 30
    assert all(
        calls[("DONOR_04", locus)][0] == calls[("DONOR_04", locus)][1]
        for locus in {name for _, name in pairs}
    )
    # A*02:01 is the commonest A allele, as in any European cohort.
    a_alleles = Counter(r["allele"] for r in rows if r["locus"] == "HLA-A")
    assert a_alleles.most_common(1)[0][0] == "A*02:01"


def test_the_fixture_binds_cleanly_and_is_suggested_by_name():
    schema = _schema(FIXTURE)
    config = AlleleGridConfig(
        haplotype_col="haplotype",
        category_col="hla_class",
        value_col="objective",
        reads_col="reads",
    )
    assert validate_binding(config, schema) == []
    top = suggest_viz_kinds(schema)
    assert any(s.viz_kind == "allele_grid" for s in top)


def test_the_epitope_table_spells_alleles_as_the_genotypes_do():
    """The direct link compares raw values, so the spelling has to agree."""
    genotype_alleles = {r["allele"] for r in _rows(FIXTURE)}
    epitope_alleles = {r["allele"] for r in _rows(EPITOPES)}
    assert epitope_alleles and epitope_alleles <= genotype_alleles


def _tab() -> dict:
    return yaml.safe_load(DASHBOARD.read_text())


def test_the_tab_draws_the_grid_beside_an_oncoplot_of_the_same_rows():
    components = {c["tag"]: c for c in _tab()["components"]}
    grid = components["viz-allele-grid"]
    onco = components["viz-allele-oncoplot"]
    assert grid["viz_kind"] == "allele_grid" and onco["viz_kind"] == "oncoplot"
    assert grid["data_collection_tag"] == onco["data_collection_tag"] == "allele_grid_demo"
    assert onco["config"]["mutation_type_col"] == grid["config"]["allele_col"]
    assert onco["config"]["gene_col"] == grid["config"]["locus_col"]
    # Side by side on one row, same section, controls docked on top (w 3..7).
    assert grid["layout"]["y"] == onco["layout"]["y"]
    assert grid["layout"]["x"] + grid["layout"]["w"] == onco["layout"]["x"]
    assert grid["section"] == onco["section"]
    for tile in (grid, onco):
        assert 3 <= tile["layout"]["w"] <= 7
        assert "controls_placement" not in tile["config"]
        assert "controls_placement" not in tile
    VIZ_CONFIG.validate_python(grid["config"])
    VIZ_CONFIG.validate_python(onco["config"])


def test_the_tab_is_seeded_and_its_collections_are_registered():
    from depictio.api.v1.db_init_reference_datasets import STATIC_IDS

    ids = STATIC_IDS["advanced_viz_showcase"]
    tab = _tab()
    assert ids["dashboards"]["advanced_viz_allele_grid"] == tab["dashboard_id"]
    project = yaml.safe_load(PROJECT.read_text())
    declared = {
        dc["data_collection_tag"]: dc["id"] for dc in project["workflows"][0]["data_collections"]
    }
    for tag in ("allele_grid_demo", "epitope_predictions_demo"):
        assert declared[tag] == ids["data_collections"][tag]
    link = next(lk for lk in project["links"] if lk["source_dc_id"] == declared["allele_grid_demo"])
    assert link["target_dc_id"] == declared["epitope_predictions_demo"]
    assert link["link_config"] == {"resolver": "direct", "target_field": "allele"}
    assert (SHOWCASE / ".db_seeds" / "dashboard_allele_grid.json").exists()
