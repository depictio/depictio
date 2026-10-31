"""The `pedigree` kind: config, roles, guards and the showcase tab that binds it.

A family tree from a PED-like table, drawn as plain SVG with every coordinate in
`pedigree/pedigreeLayout.ts` (unit-tested by vitest, which also covers the PED
encodings). Here: the model contract, the sampling and export classification,
the record-card link, and the showcase fixture and dashboard checked against the
real columns.

Pure-model + fixture reads: no DB, no network.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import get_args

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import PedigreeConfig, VizConfig
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
FIXTURE = SHOWCASE / "data" / "pedigree_demo.tsv"
DASHBOARD = SHOWCASE / "dashboards" / "pedigree.yaml"
PROJECT = SHOWCASE / "project.yaml"
SEED = SHOWCASE / ".db_seeds" / "dashboard_pedigree.json"

VIZ_CONFIG = TypeAdapter(VizConfig)

REQUIRED = {"individual", "father", "mother", "sex", "status"}
OPTIONAL = {"family", "label", "deceased", "proband"}


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
        if values and all(v.lstrip("-").isdigit() for v in values):
            schema[column] = "Int64"
        else:
            schema[column] = "String"
    return schema


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_the_kind_is_registered_everywhere():
    assert "pedigree" in get_args(AdvancedVizKind)
    assert set(CANONICAL_SCHEMAS["pedigree"]) == REQUIRED
    assert set(_OPTIONAL_ROLES["pedigree"]) == OPTIONAL
    assert KIND_METADATA["pedigree"]["label"] == "Pedigree"
    assert KIND_METADATA["pedigree"]["icon"] == "mdi:family-tree"
    descriptor = next(d for d in kind_descriptors() if d["viz_kind"] == "pedigree")
    assert descriptor["legacy"] is False
    assert descriptor["required_roles"] == ["individual", "father", "mother", "sex", "status"]
    specs = role_dtype_specs("pedigree")
    assert set(specs) == REQUIRED | OPTIONAL
    assert all(spec["description"] for spec in specs.values())
    assert all(specs[role]["required"] for role in REQUIRED)
    assert not any(specs[role]["required"] for role in OPTIONAL)


def test_every_role_has_aliases_naming_itself():
    for role in REQUIRED | OPTIONAL:
        assert role in ROLE_NAMES["pedigree"][role]
    # The PED header (FID IID PAT MAT SEX PHENOTYPE) binds without renaming.
    for role, name in {
        "individual": "iid",
        "father": "pat",
        "mother": "mat",
        "sex": "sex",
        "status": "phenotype",
        "family": "fid",
    }.items():
        assert name in ROLE_NAMES["pedigree"][role]


def test_it_is_reachable_without_the_incubating_escape():
    """The showcase tab binds it, so no INCUBATING entry is needed."""
    assert "pedigree" not in INCUBATING


def test_the_server_never_samples_a_family():
    """A sampled frame drops a parent, and its child is drawn as a founder."""
    assert KIND_SAMPLING_POLICY["pedigree"] == "none"
    assert policy_for_kind("pedigree") == "none"


def test_a_pick_reaches_a_record_card_on_the_individual_column():
    assert SELECTION_EMITTING_KINDS["pedigree"] == (
        "selection_column",
        "individual_col",
        "=individual",
    )


def test_it_is_drawn_in_the_browser():
    from depictio.api.v1.services.export.capabilities import AV_JSON_SOURCE

    assert AV_JSON_SOURCE["pedigree"] == "client_only"


# ---------------------------------------------------------------------------
# The config
# ---------------------------------------------------------------------------


def test_defaults_bind_the_canonical_columns_and_nothing_optional():
    config = PedigreeConfig()
    for role in REQUIRED:
        assert getattr(config, f"{role}_col") == role
    for role in OPTIONAL:
        assert getattr(config, f"{role}_col") is None


def test_display_defaults():
    config = PedigreeConfig()
    assert config.show_labels is True
    assert config.max_individuals == 300
    assert config.max_families == 12
    assert config.controls_placement == "popover"
    # Opt-in, like the other non-protein kinds
    assert config.selection_enabled is False
    assert config.selection_column is None


def test_guards_are_bounded_on_both_sides():
    """An unbounded guard would let a tile ask for a 100 000-symbol SVG."""
    for field, bad in (
        ("max_individuals", 0),
        ("max_individuals", 5001),
        ("max_families", 0),
        ("max_families", 101),
    ):
        with pytest.raises(ValidationError):
            PedigreeConfig(**{field: bad})


def test_unknown_keys_are_refused_and_the_union_discriminates():
    with pytest.raises(ValidationError):
        VIZ_CONFIG.validate_python({"viz_kind": "pedigree", "layout": "radial"})
    parsed = VIZ_CONFIG.validate_python(
        {
            "viz_kind": "pedigree",
            "individual_col": "iid",
            "father_col": "pat",
            "mother_col": "mat",
            "sex_col": "sex",
            "status_col": "phenotype",
            "family_col": "fid",
            "deceased_col": "dead",
            "selection_enabled": True,
        }
    )
    assert isinstance(parsed, PedigreeConfig)
    assert parsed.family_col == "fid"
    assert parsed.selection_enabled is True


def test_a_bare_viz_kind_validates_to_the_defaults():
    parsed = VIZ_CONFIG.validate_python({"viz_kind": "pedigree"})
    assert isinstance(parsed, PedigreeConfig)
    assert parsed.individual_col == "individual"


# ---------------------------------------------------------------------------
# Binding to a table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "schema",
    [
        # PED coding: ids may be numbers, sex and status are 1 / 2 / 0 codes
        {
            "individual": "Int64",
            "father": "Int64",
            "mother": "Int64",
            "sex": "Int64",
            "status": "Int64",
        },
        # Words: ids and codes as strings
        {
            "individual": "String",
            "father": "String",
            "mother": "String",
            "sex": "String",
            "status": "String",
        },
    ],
)
def test_both_ped_encodings_bind(schema: dict[str, str]):
    assert validate_binding(PedigreeConfig(), schema) == []


def test_a_float_identifier_is_refused():
    schema = {
        "individual": "Float64",
        "father": "String",
        "mother": "String",
        "sex": "Int64",
        "status": "Int64",
    }
    assert validate_binding(PedigreeConfig(), schema) != []


def test_a_missing_parent_column_is_reported():
    schema = {"individual": "String", "father": "String", "sex": "Int64", "status": "Int64"}
    assert validate_binding(PedigreeConfig(), schema) != []


# ---------------------------------------------------------------------------
# The showcase fixture and tab
# ---------------------------------------------------------------------------


def test_the_fixture_is_a_ped_like_table_of_three_families():
    rows = _rows(FIXTURE)
    assert {r["family"] for r in rows} == {"FAM001", "FAM002", "FAM003"}
    # One row per individual, the identifier unique across families (a click
    # filters on it)
    ids = [r["individual"] for r in rows]
    assert len(ids) == len(set(ids))
    # The PED vocabularies, and nothing outside them
    assert {r["sex"] for r in rows} <= {"0", "1", "2"}
    assert {r["status"] for r in rows} <= {"0", "1", "2"}
    assert {r["deceased"] for r in rows} <= {"0", "1"}
    # Every symbol the legend draws appears: all three sexes, all three statuses,
    # and a death
    assert {r["sex"] for r in rows} == {"0", "1", "2"}
    assert {r["status"] for r in rows} == {"0", "1", "2"}
    assert "1" in {r["deceased"] for r in rows}


def test_every_parent_is_in_the_table_or_a_founder_except_by_design():
    """FAM003's father is 0 by design; no row names a parent who is not listed."""
    rows = _rows(FIXTURE)
    known = {(r["family"], r["individual"]) for r in rows}
    for r in rows:
        for parent in (r["father"], r["mother"]):
            if parent != "0":
                assert (r["family"], parent) in known, (r["individual"], parent)


def test_the_fixture_has_the_shapes_the_layout_has_to_handle():
    rows = _rows(FIXTURE)
    by_family: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_family.setdefault(r["family"], []).append(r)
    founders = {
        f: sum(1 for r in rs if r["father"] == "0" and r["mother"] == "0")
        for f, rs in by_family.items()
    }
    # Married-in founders next to descendants: more than the one founding couple
    assert founders["FAM001"] == 4
    # Three generations in FAM001: someone's parent is someone's child
    parents = {r["father"] for r in by_family["FAM001"]} | {
        r["mother"] for r in by_family["FAM001"]
    }
    children = {r["individual"] for r in by_family["FAM001"] if r["father"] != "0"}
    assert parents & children
    # A lone parent: a child whose other parent is 0
    single = [r for r in by_family["FAM003"] if (r["father"] == "0") != (r["mother"] == "0")]
    assert single
    # Labels are unique within a family
    for rs in by_family.values():
        labels = Counter(r["label"] for r in rs)
        assert max(labels.values()) == 1


def test_the_fixture_binds_cleanly_and_is_suggested_by_name():
    schema = _schema(FIXTURE)
    config = PedigreeConfig(family_col="family", label_col="label", deceased_col="deceased")
    assert validate_binding(config, schema) == []
    assert any(s.viz_kind == "pedigree" for s in suggest_viz_kinds(schema))


def _tab() -> dict:
    return yaml.safe_load(DASHBOARD.read_text())


def test_the_tab_binds_the_fixture_columns():
    components = {c["tag"]: c for c in _tab()["components"]}
    tile = components["viz-pedigree"]
    assert tile["viz_kind"] == "pedigree"
    assert tile["data_collection_tag"] == "pedigree_demo"
    config = VIZ_CONFIG.validate_python(tile["config"])
    assert isinstance(config, PedigreeConfig)
    columns = set(_schema(FIXTURE))
    for field in (
        "individual_col",
        "father_col",
        "mother_col",
        "sex_col",
        "status_col",
        "family_col",
        "label_col",
        "deceased_col",
        "selection_column",
    ):
        assert getattr(config, field) in columns, field
    assert config.selection_enabled is True
    # The table on the same collection is what a pick narrows
    assert components["table-pedigree"]["data_collection_tag"] == "pedigree_demo"


def test_the_tab_is_seeded_and_its_collection_is_registered():
    from depictio.api.v1.db_init_reference_datasets import STATIC_IDS

    ids = STATIC_IDS["advanced_viz_showcase"]
    tab = _tab()
    assert ids["dashboards"]["advanced_viz_pedigree"] == tab["dashboard_id"]
    project = yaml.safe_load(PROJECT.read_text())
    declared = {
        dc["data_collection_tag"]: dc["id"] for dc in project["workflows"][0]["data_collections"]
    }
    assert declared["pedigree_demo"] == ids["data_collections"]["pedigree_demo"]
    assert SEED.exists()
    seed = json.loads(SEED.read_text())
    assert seed["dashboard_id"]["$oid"] == tab["dashboard_id"]
    kinds = {c.get("viz_kind") for c in seed["stored_metadata"]}
    assert "pedigree" in kinds


def test_the_boot_seeding_list_names_the_tab():
    source = (REPO / "depictio" / "api" / "v1" / "db_init.py").read_text()
    assert '"pedigree",' in source


def test_the_proband_flag_is_an_optional_binding():
    assert PedigreeConfig().proband_col is None
    schema = {**_schema(FIXTURE), "is_proband": "Int64"}
    assert (
        validate_binding(PedigreeConfig(family_col="family", proband_col="is_proband"), schema)
        == []
    )
    # A column of the wrong type is reported against the role, not silently drawn.
    errors = validate_binding(
        PedigreeConfig(family_col="family", proband_col="is_proband"),
        {**schema, "is_proband": "Float64"},
    )
    assert any("proband" in str(e) for e in errors)
    # The usual header names bind without renaming.
    for name in ("proband", "is_proband", "index_case"):
        assert name in ROLE_NAMES["pedigree"]["proband"]
