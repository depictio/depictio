"""molecule_3d viz kind + structure DC type — model contracts.

The molecule_3d kind is file-backed (like phylogenetic): its payload is a
PDB/mmCIF file in a ``structure`` DC, not a table, so its canonical schema is
empty and ``validate_binding`` is a no-op. These tests pin the config's
discriminated-union round trip, the DC-type coercion, and the showcase seed
blob so the seeded dashboard can't drift from the Pydantic model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz import Molecule3DConfig, VizConfig
from depictio.models.components.advanced_viz.schemas import (
    CANONICAL_SCHEMAS,
    validate_binding,
)
from depictio.models.models.data_collections import DataCollectionConfig
from depictio.models.models.data_collections_types.structure import DCStructureConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_PATH = (
    REPO_ROOT
    / "depictio"
    / "projects"
    / "init"
    / "advanced_viz_showcase"
    / ".db_seeds"
    / "dashboard_molecule_3d.json"
)


# ---------------------------------------------------------------------------
# Molecule3DConfig
# ---------------------------------------------------------------------------


def test_config_defaults():
    cfg = Molecule3DConfig(structure_wf_id="wf", structure_dc_id="dc")
    assert cfg.viz_kind == "molecule_3d"
    assert cfg.representation == "cartoon"
    assert cfg.color_mode == "spectrum"


def test_structure_ids_are_required():
    with pytest.raises(ValidationError):
        Molecule3DConfig(structure_wf_id="wf")  # type: ignore[call-arg]


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        Molecule3DConfig(
            structure_wf_id="wf",
            structure_dc_id="dc",
            background="#000000",  # type: ignore[call-arg]
        )


def test_discriminated_union_round_trip():
    cfg = TypeAdapter(VizConfig).validate_python(
        {"viz_kind": "molecule_3d", "structure_wf_id": "wf", "structure_dc_id": "dc"}
    )
    assert isinstance(cfg, Molecule3DConfig)


def test_empty_canonical_schema_makes_binding_a_noop():
    assert CANONICAL_SCHEMAS["molecule_3d"] == {}
    cfg = Molecule3DConfig(structure_wf_id="wf", structure_dc_id="dc")
    assert validate_binding(cfg, {"any_column": "String"}) == []


def test_showcase_seed_config_blob_parses_through_the_union():
    seed = json.loads(SEED_PATH.read_text())
    (component,) = seed["stored_metadata"]
    assert component["viz_kind"] == "molecule_3d"
    cfg = TypeAdapter(VizConfig).validate_python(component["config"])
    assert isinstance(cfg, Molecule3DConfig)
    assert cfg.structure_dc_id == component["dc_id"]["$oid"]


# ---------------------------------------------------------------------------
# DCStructureConfig / DataCollectionConfig
# ---------------------------------------------------------------------------


def test_format_is_normalised_to_lowercase():
    assert DCStructureConfig(format="PDB").format == "pdb"
    assert DCStructureConfig(format="mmCIF").format == "mmcif"


def test_unknown_format_is_rejected():
    with pytest.raises(ValidationError):
        DCStructureConfig(format="xyz")


def test_dc_config_coerces_dict_to_structure_properties():
    dc = DataCollectionConfig(
        type="Structure",
        scan={"mode": "single", "scan_parameters": {"filename": "/app/data/demo.pdb"}},
        dc_specific_properties={"format": "pdb"},
    )
    assert dc.type == "structure"
    assert isinstance(dc.dc_specific_properties, DCStructureConfig)
    assert dc.dc_specific_properties.plddt_in_bfactor is False


def test_dc_type_allowed_values_error_mentions_structure():
    with pytest.raises(ValidationError, match="structure"):
        DataCollectionConfig(
            type="bogus",
            scan={"mode": "single", "scan_parameters": {"filename": "/x"}},
            dc_specific_properties={"format": "pdb"},
        )
