"""Registry and model checks for the protein kinds (molecule_3d, msa, sequence_track)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import VizConfig
from depictio.models.components.advanced_viz.record_link import emitted_selection_column
from depictio.models.components.advanced_viz.sampling import KIND_SAMPLING_POLICY
from depictio.models.components.advanced_viz.schemas import (
    CANONICAL_SCHEMAS,
    KIND_METADATA,
    suggest_viz_kinds,
    validate_binding,
)

VIZ = TypeAdapter(VizConfig)
PROTEIN_KINDS = ("molecule_3d", "msa", "sequence_track")


@pytest.mark.parametrize("kind", PROTEIN_KINDS)
def test_kind_is_registered_everywhere(kind: str):
    assert kind in CANONICAL_SCHEMAS
    assert kind in KIND_METADATA
    assert KIND_SAMPLING_POLICY[kind] == "none"
    assert VIZ.validate_python({"viz_kind": kind}).viz_kind == kind


def test_resolve_mode_needs_an_identifier_column():
    with pytest.raises(ValidationError, match="uniprot_col, gene_col or sequence_col"):
        VIZ.validate_python({"viz_kind": "molecule_3d", "structure_source": "resolve"})
    cfg = VIZ.validate_python(
        {"viz_kind": "molecule_3d", "structure_source": "resolve", "uniprot_col": "uniprot"}
    )
    assert cfg.taxon == 9606


def test_structure_msa_layout_needs_an_msa_collection():
    with pytest.raises(ValidationError, match="msa_dc_id"):
        VIZ.validate_python({"viz_kind": "molecule_3d", "layout": "structure_msa"})
    # A template ships the tag; the import resolves it to the ids.
    VIZ.validate_python({"viz_kind": "molecule_3d", "layout": "structure_msa", "msa_dc_tag": "msa"})


def test_msa_max_rows_is_bounded():
    with pytest.raises(ValidationError):
        VIZ.validate_python({"viz_kind": "msa", "max_rows": 1001})


def test_msa_binds_the_aligned_sequence_through_the_sequence_role():
    cfg = VIZ.validate_python({"viz_kind": "msa"})
    schema = {
        "msa_id": "String",
        "seq_id": "String",
        "rank": "Int64",
        "aligned_sequence": "String",
        "identity": "Float64",
    }
    assert validate_binding(cfg, schema) == []


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("molecule_3d", "position"), ("sequence_track", "position"), ("msa", "seq_id")],
)
def test_protein_kinds_emit_a_selection_by_default(kind: str, expected: str):
    comp = {"component_type": "advanced_viz", "config": {"viz_kind": kind}}
    assert emitted_selection_column(comp) == expected
    off = {
        "component_type": "advanced_viz",
        "config": {"viz_kind": kind, "selection_enabled": False},
    }
    assert emitted_selection_column(off) is None


def test_a_position_column_alone_does_not_recommend_a_protein_kind():
    genomic = {"chromosome": "String", "position": "Int64", "value": "Float64", "sample": "String"}
    protein = {"entity": "String", "position": "Int64", "residue": "String", "value": "Float64"}
    by_kind = {s.viz_kind: s for s in suggest_viz_kinds(genomic)}
    assert by_kind["molecule_3d"].match == "weak"
    assert by_kind["sequence_track"].score < 0.8
    by_kind = {s.viz_kind: s for s in suggest_viz_kinds(protein)}
    assert by_kind["molecule_3d"].match == "named"
    assert by_kind["sequence_track"].score >= 0.8
