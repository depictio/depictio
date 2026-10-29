"""The `ranked_table` kind: config, roles, guards and the showcase tab that binds it.

A leaderboard drawn as an HTML table: medals, badges coloured by value, bars,
a hover popover and, optionally, a pinned popover with the family of a variant.
Ordering, dense ranks, bar scales and badge colours live in
`ranked_table/rankedTable.ts` and the genotype fills in `ranked_table/familyData.ts`
(both unit-tested by vitest). Here: the model contract, the sampling and export
classification, the record-card link, and the showcase fixtures and dashboard
checked against the real columns.

Pure-model + fixture reads: no DB, no network.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import get_args

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import (
    RankedTableColumn,
    RankedTableConfig,
    VizConfig,
)
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
DATA = SHOWCASE / "data"
DASHBOARD = SHOWCASE / "dashboards" / "ranked_table.yaml"
PROJECT = SHOWCASE / "project.yaml"
SEED = SHOWCASE / ".db_seeds" / "dashboard_ranked_table.json"

VIZ_CONFIG = TypeAdapter(VizConfig)

REQUIRED = {"title", "score"}
OPTIONAL = {"subtitle", "rank"}


def _rows(name: str) -> list[dict[str, str]]:
    with (DATA / name).open() as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _schema(name: str) -> dict[str, str]:
    """Column -> polars dtype name as a scan reports it: numbers against strings."""
    rows = _rows(name)
    assert rows, f"{name} has a header but no data rows"
    schema: dict[str, str] = {}
    for column in rows[0]:
        values = [r[column] for r in rows if r[column] != ""]
        if values and all(v.lstrip("-").isdigit() for v in values):
            schema[column] = "Int64"
        elif values and all(_is_float(v) for v in values):
            schema[column] = "Float64"
        else:
            schema[column] = "String"
    return schema


def _is_float(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_the_kind_is_registered_everywhere():
    assert "ranked_table" in get_args(AdvancedVizKind)
    assert set(CANONICAL_SCHEMAS["ranked_table"]) == REQUIRED
    assert set(_OPTIONAL_ROLES["ranked_table"]) == OPTIONAL
    assert KIND_METADATA["ranked_table"]["label"] == "Ranked table"
    assert KIND_METADATA["ranked_table"]["icon"] == "mdi:podium"
    descriptor = next(d for d in kind_descriptors() if d["viz_kind"] == "ranked_table")
    assert descriptor["legacy"] is False
    assert descriptor["required_roles"] == ["title", "score"]
    specs = role_dtype_specs("ranked_table")
    assert set(specs) == REQUIRED | OPTIONAL
    assert all(spec["description"] for spec in specs.values())
    assert all(specs[role]["required"] for role in REQUIRED)
    assert not any(specs[role]["required"] for role in OPTIONAL)


def test_every_role_has_aliases_naming_itself():
    for role in REQUIRED | OPTIONAL:
        assert role in ROLE_NAMES["ranked_table"][role]
    assert "rank_score" in ROLE_NAMES["ranked_table"]["score"]
    assert "gene" in ROLE_NAMES["ranked_table"]["title"]


def test_it_is_reachable_without_the_incubating_escape():
    """The showcase tab binds it, so no INCUBATING entry is needed."""
    assert "ranked_table" not in INCUBATING


def test_the_server_never_samples_a_ranking():
    """A sampled frame drops candidates and every rank under them shifts."""
    assert KIND_SAMPLING_POLICY["ranked_table"] == "none"
    assert policy_for_kind("ranked_table") == "none"


def test_a_pick_reaches_a_record_card_on_the_selection_column():
    assert SELECTION_EMITTING_KINDS["ranked_table"] == (
        "selection_column",
        "title_col",
        "=title",
    )


def test_it_is_drawn_in_the_browser():
    from depictio.api.v1.services.export.capabilities import AV_JSON_SOURCE

    assert AV_JSON_SOURCE["ranked_table"] == "client_only"


# ---------------------------------------------------------------------------
# The config
# ---------------------------------------------------------------------------


def test_defaults_bind_the_canonical_columns_and_nothing_optional():
    config = RankedTableConfig()
    assert config.title_col == "title"
    assert config.score_col == "score"
    assert config.subtitle_col is None
    assert config.rank_col is None
    assert config.columns == []


def test_display_defaults():
    config = RankedTableConfig()
    assert config.descending is True
    assert config.top_n == 50
    assert config.medals is True
    assert config.popover_columns == []
    assert config.popover_grid_columns == []
    assert config.controls_placement == "popover"
    # Opt-in, like the other non-protein kinds
    assert config.selection_enabled is False
    assert config.selection_column is None


def test_the_family_section_is_off_by_default():
    config = RankedTableConfig()
    assert config.family_dc_tag is None
    assert config.family_dc_id is None
    assert config.genotype_columns is None
    assert config.genotypes_dc_tag is None
    assert config.family_open is False
    assert config.family_individual_col == "individual"
    assert config.genotypes_key_col == "variant_key"
    assert config.genotypes_genotype_col == "gt_class"


def test_top_n_is_bounded_on_both_sides():
    """An unbounded count would let a tile ask for a 100 000-row DOM table."""
    for bad in (0, 1001):
        with pytest.raises(ValidationError):
            RankedTableConfig(top_n=bad)
    assert RankedTableConfig(top_n=1000).top_n == 1000


def test_unknown_keys_are_refused_and_the_union_discriminates():
    with pytest.raises(ValidationError):
        VIZ_CONFIG.validate_python({"viz_kind": "ranked_table", "sort_by": "rank_score"})
    parsed = VIZ_CONFIG.validate_python(
        {
            "viz_kind": "ranked_table",
            "title_col": "gene",
            "score_col": "rank_score",
            "subtitle_col": "hgvs_p",
            "descending": False,
            "columns": [
                {"column": "impact", "label": "Impact", "display": "badge"},
                {"column": "rank_score", "display": "bar", "max": 25, "decimals": 1},
            ],
            "selection_enabled": True,
            "selection_column": "variant_key",
        }
    )
    assert isinstance(parsed, RankedTableConfig)
    assert parsed.descending is False
    assert [c.display for c in parsed.columns] == ["badge", "bar"]
    assert parsed.columns[1].max == 25


def test_a_bare_viz_kind_validates_to_the_defaults():
    parsed = VIZ_CONFIG.validate_python({"viz_kind": "ranked_table"})
    assert isinstance(parsed, RankedTableConfig)
    assert parsed.title_col == "title"


def test_a_column_is_checked():
    with pytest.raises(ValidationError):
        RankedTableColumn(column="x", display="sparkline")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RankedTableColumn(column="x", extra_key=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        RankedTableColumn(column="x", decimals=9)
    with pytest.raises(ValidationError):
        RankedTableColumn(column="x", display="bar", min=5, max=5)
    column = RankedTableColumn(column="x")
    assert column.display == "text"
    assert column.label is None


# ---------------------------------------------------------------------------
# The family section
# ---------------------------------------------------------------------------


def test_genotypes_from_row_columns_on_a_family():
    config = RankedTableConfig(
        family_dc_tag="samples",
        family_proband_col="proband",
        family_family_col="case_id",
        family_row_col="case_id",
        genotype_columns={"proband": "gt_proband", "mother": "gt_mother", "father": "gt_father"},
    )
    assert config.genotype_columns == {
        "proband": "gt_proband",
        "mother": "gt_mother",
        "father": "gt_father",
    }


def test_genotypes_from_a_long_table_on_a_family():
    config = RankedTableConfig(family_dc_tag="samples", genotypes_dc_tag="genotypes")
    assert config.genotypes_dc_tag == "genotypes"


def test_a_family_without_genotypes_is_allowed():
    """The tree is drawn with its affected members and no carriers."""
    assert RankedTableConfig(family_dc_tag="samples").family_dc_tag == "samples"


def test_genotypes_missing_as_defaults_to_missing_and_takes_ref():
    base = {"family_dc_tag": "samples", "genotypes_dc_tag": "genotypes"}
    assert RankedTableConfig(**base).genotypes_missing_as == "missing"
    assert RankedTableConfig(**base, genotypes_missing_as="ref").genotypes_missing_as == "ref"
    # The row-columns source reads empty cells the same way.
    config = RankedTableConfig(
        family_dc_tag="samples",
        genotype_columns={"proband": "gt"},
        genotypes_missing_as="ref",
    )
    assert config.genotypes_missing_as == "ref"


def test_genotypes_missing_as_is_a_closed_choice():
    with pytest.raises(ValidationError):
        RankedTableConfig(
            family_dc_tag="samples", genotypes_dc_tag="genotypes", genotypes_missing_as="hom_ref"
        )


def test_genotypes_missing_as_ref_needs_genotypes():
    with pytest.raises(ValidationError, match="genotypes_missing_as"):
        RankedTableConfig(family_dc_tag="samples", genotypes_missing_as="ref")


def test_two_genotype_sources_are_refused():
    with pytest.raises(ValidationError, match="two sources"):
        RankedTableConfig(
            family_dc_tag="samples",
            genotype_columns={"proband": "gt"},
            genotypes_dc_tag="genotypes",
        )


def test_genotypes_without_a_family_are_refused():
    with pytest.raises(ValidationError, match="family_dc_tag"):
        RankedTableConfig(genotype_columns={"proband": "gt"})
    with pytest.raises(ValidationError, match="family_dc_tag"):
        RankedTableConfig(genotypes_dc_tag="genotypes")


def test_a_row_family_column_needs_the_table_column_to_match():
    with pytest.raises(ValidationError, match="family_family_col"):
        RankedTableConfig(family_dc_tag="samples", family_row_col="case_id")


def test_the_import_resolves_the_tags_to_ids_by_name():
    """The importer rewrites any top-level `<x>_dc_tag` into `<x>_dc_id` / `<x>_wf_id`."""
    fields = set(RankedTableConfig.model_fields)
    for base in ("family", "genotypes"):
        assert {f"{base}_dc_tag", f"{base}_dc_id", f"{base}_wf_id"} <= fields


# ---------------------------------------------------------------------------
# Binding to a table
# ---------------------------------------------------------------------------


def test_a_title_and_a_score_bind():
    schema = {"gene": "String", "rank_score": "Float64"}
    assert (
        validate_binding(RankedTableConfig(title_col="gene", score_col="rank_score"), schema) == []
    )


def test_an_integer_score_and_an_integer_title_bind():
    schema = {"gene_id": "Int64", "rank_score": "Int64"}
    assert (
        validate_binding(RankedTableConfig(title_col="gene_id", score_col="rank_score"), schema)
        == []
    )


def test_a_text_score_is_refused():
    schema = {"gene": "String", "rank_score": "String"}
    errors = validate_binding(RankedTableConfig(title_col="gene", score_col="rank_score"), schema)
    assert [e.role for e in errors] == ["score"]


def test_a_missing_score_column_is_reported():
    errors = validate_binding(RankedTableConfig(title_col="gene"), {"gene": "String"})
    assert [e.role for e in errors] == ["score"]


def test_a_title_and_a_number_are_not_enough_to_be_recommended():
    """Any results table has a name and a number: only a rank-like column recommends it."""
    plain = {"gene": "String", "score": "Float64", "other": "Float64"}
    ranked = {"gene": "String", "rank_score": "Float64", "other": "Float64"}
    by_kind = {s.viz_kind: s for s in suggest_viz_kinds(plain)}
    assert by_kind["ranked_table"].match == "weak"
    by_kind = {s.viz_kind: s for s in suggest_viz_kinds(ranked)}
    assert by_kind["ranked_table"].match == "named"
    assert by_kind["ranked_table"].score >= 0.8


# ---------------------------------------------------------------------------
# The showcase fixtures and tab
# ---------------------------------------------------------------------------


def test_the_variants_table_ranks_with_ties_and_every_badge_value():
    rows = _rows("ranked_variants_demo.tsv")
    keys = [r["variant_key"] for r in rows]
    assert len(keys) == len(set(keys)), "the selection key must be unique"
    assert {r["impact"] for r in rows} == {"HIGH", "MODERATE", "LOW"}
    assert {r["case_id"] for r in rows} == {"CASE_A", "CASE_B"}
    scores = [float(r["rank_score"]) for r in rows]
    assert len(set(scores)) == len(scores)
    # a repeated gene: the title is not a key
    genes = [r["gene"] for r in rows]
    assert len(genes) > len(set(genes))
    assert any(r["gnomad_af"] == "absent" for r in rows)


def test_the_family_table_has_one_proband_per_case_and_parents_in_the_table():
    rows = _rows("ranked_family_demo.tsv")
    for case in {r["case_id"] for r in rows}:
        members = [r for r in rows if r["case_id"] == case]
        assert sum(r["proband"] == "1" for r in members) == 1
        ids = {r["individual"] for r in members}
        for r in members:
            for parent in (r["father"], r["mother"]):
                assert parent == "0" or parent in ids


def test_the_genotypes_cover_every_variant_and_name_known_people():
    variants = {r["variant_key"]: r["case_id"] for r in _rows("ranked_variants_demo.tsv")}
    people = {(r["case_id"], r["individual"]) for r in _rows("ranked_family_demo.tsv")}
    long_rows = _rows("ranked_genotypes_demo.tsv")
    assert {r["variant_key"] for r in long_rows} == set(variants)
    for r in long_rows:
        assert (variants[r["variant_key"]], r["sample"]) in people
    assert {r["gt_class"] for r in long_rows} >= {"0/0", "0/1", "1/1", "./."}


def test_the_long_genotypes_agree_with_the_row_columns():
    gts = {}
    for r in _rows("ranked_genotypes_demo.tsv"):
        gts.setdefault(r["variant_key"], {})[r["sample"]] = r["gt_class"]
    family = {
        (r["case_id"], r["proband"]): r["individual"] for r in _rows("ranked_family_demo.tsv")
    }
    for v in _rows("ranked_variants_demo.tsv"):
        proband = next(
            r["individual"]
            for r in _rows("ranked_family_demo.tsv")
            if r["case_id"] == v["case_id"] and r["proband"] == "1"
        )
        assert gts[v["variant_key"]][proband] == v["gt_proband"], (v["variant_key"], family)


def test_the_outliers_table_binds_by_name_and_ties_nothing_to_the_variants():
    config = RankedTableConfig(title_col="gene", score_col="neg_log10_p")
    assert validate_binding(config, _schema("ranked_outliers_demo.tsv")) == []
    rows = _rows("ranked_outliers_demo.tsv")
    assert len({r["sample"] for r in rows}) == 3
    assert {r["status"] for r in rows} == {"Called", "Candidate", "Not called"}


def _tab() -> dict:
    return yaml.safe_load(DASHBOARD.read_text())


def _tiles() -> dict[str, dict]:
    return {c["tag"]: c for c in _tab()["components"]}


def test_the_variants_tile_binds_the_fixture_columns():
    tile = _tiles()["viz-ranked-variants"]
    assert tile["viz_kind"] == "ranked_table"
    assert tile["data_collection_tag"] == "ranked_variants_demo"
    config = VIZ_CONFIG.validate_python(tile["config"])
    assert isinstance(config, RankedTableConfig)
    columns = set(_schema("ranked_variants_demo.tsv"))
    fields = [
        config.title_col,
        config.score_col,
        config.subtitle_col,
        config.selection_column,
        config.family_row_col,
        config.genotypes_row_col,
        *[c.column for c in config.columns],
        *config.popover_columns,
        *config.popover_grid_columns,
    ]
    for column in fields:
        assert column in columns, column
    assert config.selection_enabled is True
    assert validate_binding(config, _schema("ranked_variants_demo.tsv")) == []
    # The long-table family: ids and tags both, since the seed is built offline
    ids = _static_ids()["data_collections"]
    assert config.family_dc_id == ids["ranked_family_demo"]
    assert config.genotypes_dc_id == ids["ranked_genotypes_demo"]
    assert config.family_dc_tag == "ranked_family_demo"
    family = set(_schema("ranked_family_demo.tsv"))
    for column in (
        config.family_individual_col,
        config.family_father_col,
        config.family_mother_col,
        config.family_sex_col,
        config.family_status_col,
        config.family_proband_col,
        config.family_family_col,
    ):
        assert column in family, column
    genotypes = set(_schema("ranked_genotypes_demo.tsv"))
    for column in (
        config.genotypes_key_col,
        config.genotypes_individual_col,
        config.genotypes_genotype_col,
    ):
        assert column in genotypes, column


def test_the_outliers_tile_binds_the_fixture_columns():
    tile = _tiles()["viz-ranked-outliers"]
    config = VIZ_CONFIG.validate_python(tile["config"])
    assert isinstance(config, RankedTableConfig)
    columns = set(_schema("ranked_outliers_demo.tsv"))
    for column in (
        config.title_col,
        config.score_col,
        config.subtitle_col,
        config.selection_column,
        *[c.column for c in config.columns],
        *config.popover_columns,
        *config.popover_grid_columns,
    ):
        assert column in columns, column
    assert config.family_dc_tag is None


def test_the_tables_beside_the_tiles_read_the_same_collections():
    tiles = _tiles()
    assert tiles["table-ranked-variants"]["data_collection_tag"] == "ranked_variants_demo"
    assert tiles["table-ranked-outliers"]["data_collection_tag"] == "ranked_outliers_demo"


def test_the_dashboard_colours_the_badge_values_it_names():
    colours = _tab()["category_colors"]
    variants = {r["impact"] for r in _rows("ranked_variants_demo.tsv")}
    assert set(colours["impact"]) == variants
    statuses = {r["status"] for r in _rows("ranked_outliers_demo.tsv")}
    assert set(colours["status"]) == statuses


def _static_ids() -> dict:
    from depictio.api.v1.db_init_reference_datasets import STATIC_IDS

    return STATIC_IDS["advanced_viz_showcase"]


def test_the_tab_is_seeded_and_its_collections_are_registered():
    ids = _static_ids()
    tab = _tab()
    assert ids["dashboards"]["advanced_viz_ranked_table"] == tab["dashboard_id"]
    project = yaml.safe_load(PROJECT.read_text())
    declared = {
        dc["data_collection_tag"]: dc["id"] for dc in project["workflows"][0]["data_collections"]
    }
    for tag in (
        "ranked_variants_demo",
        "ranked_family_demo",
        "ranked_genotypes_demo",
        "ranked_outliers_demo",
    ):
        assert declared[tag] == ids["data_collections"][tag]
    assert SEED.exists()
    seed = json.loads(SEED.read_text())
    assert seed["dashboard_id"]["$oid"] == tab["dashboard_id"]
    kinds = [c.get("viz_kind") for c in seed["stored_metadata"]]
    assert kinds.count("ranked_table") == 2


def test_the_boot_seeding_list_names_the_tab():
    source = (REPO / "depictio" / "api" / "v1" / "db_init.py").read_text()
    assert '"ranked_table",' in source
