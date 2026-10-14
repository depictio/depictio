"""Registry and model checks for the protein kinds.

The first three (molecule_3d, msa, sequence_track) landed with the third nf-core
template lot; hmm_logo, secondary_structure, domain_architecture, pae_matrix and
ramachandran are the second wave. All eight share the `residue_selection` link.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import (
    VizConfig,
    _check_resolve_source,
)
from depictio.models.components.advanced_viz.record_link import (
    RESIDUE_EMITTING_KINDS,
    SELECTION_EMITTING_KINDS,
    SELECTION_ON_BY_DEFAULT,
    emitted_selection_column,
)
from depictio.models.components.advanced_viz.sampling import KIND_SAMPLING_POLICY
from depictio.models.components.advanced_viz.schemas import (
    _OPTIONAL_ROLES,
    CANONICAL_SCHEMAS,
    INCUBATING,
    KIND_METADATA,
    RECOMMENDED_SCORE,
    ROLE_NAMES,
    _roles_for,
    kind_descriptors,
    role_dtype_specs,
    suggest_viz_kinds,
    validate_binding,
)
from depictio.models.components.types import AdvancedVizKind
from depictio.recipes.lib.hmm import PROFILE_SCHEMA
from depictio.recipes.lib.msa import MSA_SCHEMA
from depictio.recipes.lib.secondary_structure import SS2_SCHEMA

VIZ = TypeAdapter(VizConfig)

#: Registered with the lot 3 template pass.
FIRST_WAVE = ("molecule_3d", "msa", "sequence_track")
#: Registered ahead of their renderer and showcase tab.
SECOND_WAVE = (
    "hmm_logo",
    "secondary_structure",
    "domain_architecture",
    "pae_matrix",
    "ramachandran",
)
PROTEIN_KINDS = (*FIRST_WAVE, *SECOND_WAVE)

#: What a kind needs besides `viz_kind` to validate at all.
MINIMAL: dict[str, dict[str, Any]] = {"pae_matrix": {"pae_dc_tag": "pae"}}


def _cfg(kind: str, **fields: Any) -> Any:
    """The kind's config, with the fields it cannot validate without."""
    return VIZ.validate_python({"viz_kind": kind, **MINIMAL.get(kind, {}), **fields})


def _schema(frame_schema: dict[str, Any]) -> dict[str, str]:
    """A polars schema as the ``{column: dtype name}`` map `validate_binding` takes."""
    return {name: str(dtype) for name, dtype in frame_schema.items()}


#: ``EXPECTED_SCHEMA`` of the hmmer ``hmmsearch_domtbl`` catalog recipe
#: (feat/nfcore-templates-lot3, ``depictio/catalog/hmmer/hmmsearch_domtbl.py``),
#: copied here as dtype names: the recipe is not in this tree.
DOMTBL_SCHEMA: dict[str, str] = {
    "entity": "String",
    "sample": "String",
    "source": "String",
    "label": "String",
    "accession": "String",
    "description": "String",
    "start": "Int64",
    "end": "Int64",
    "protein_length": "Int64",
    "hmm_length": "Int64",
    "domain_index": "Int64",
    "domain_count": "Int64",
    "seq_evalue": "Float64",
    "seq_score": "Float64",
    "c_evalue": "Float64",
    "i_evalue": "Float64",
    "dom_score": "Float64",
    "dom_bias": "Float64",
    "hmm_from": "Int64",
    "hmm_to": "Int64",
    "ali_from": "Int64",
    "ali_to": "Int64",
    "acc": "Float64",
    "hmm_coverage": "Float64",
    "neg_log10_evalue": "Float64",
}
#: The s4pred catalog recipe's schema, held equal to the parser's by
#: ``test_secondary_structure_lib.py::test_schema_is_the_recipes_schema``.
S4PRED_SCHEMA = _schema(SS2_SCHEMA)
PROFILE = _schema(PROFILE_SCHEMA)
MSA = _schema(MSA_SCHEMA)


# --- registration -----------------------------------------------------------


@pytest.mark.parametrize("kind", PROTEIN_KINDS)
def test_kind_is_registered_everywhere(kind: str):
    assert kind in get_args(AdvancedVizKind)
    assert kind in CANONICAL_SCHEMAS
    assert kind in ROLE_NAMES
    assert kind in KIND_METADATA
    assert KIND_SAMPLING_POLICY[kind] == "none"
    assert _cfg(kind).viz_kind == kind
    meta = KIND_METADATA[kind]
    assert meta["label"] and meta["description"] and str(meta["icon"]).startswith("tabler:")
    assert kind in {d["viz_kind"] for d in kind_descriptors()}
    # Every required role is a role the kind can bind to a config field.
    config = _cfg(kind)
    for role in (*CANONICAL_SCHEMAS[kind], *_OPTIONAL_ROLES.get(kind, {})):
        assert hasattr(config, f"{role}_col"), f"{kind}: role {role!r} has no {role}_col field"


@pytest.mark.parametrize("kind", PROTEIN_KINDS)
def test_every_role_has_a_tooltip_and_dtypes(kind: str):
    specs = role_dtype_specs(kind)
    assert set(specs) == {*CANONICAL_SCHEMAS[kind], *_OPTIONAL_ROLES.get(kind, {})}
    for role, spec in specs.items():
        assert spec["description"], f"{kind}.{role} has no tooltip"
        assert spec["dtypes"], f"{kind}.{role} accepts no dtype"


@pytest.mark.parametrize("kind", SECOND_WAVE)
def test_every_role_of_a_second_wave_kind_has_column_names(kind: str):
    """The suggester and Tool Studio's picker rank kinds by these aliases."""
    assert set(ROLE_NAMES[kind]) == set(role_dtype_specs(kind))


@pytest.mark.parametrize("kind", PROTEIN_KINDS)
def test_selection_is_on_and_follows_by_default(kind: str):
    config = _cfg(kind)
    assert config.selection_enabled is True
    assert config.follow_selection is True
    assert kind in SELECTION_ON_BY_DEFAULT
    assert kind in SELECTION_EMITTING_KINDS
    # An MSA row pick selects a sequence, not a residue range: a card linked to it
    # still has to agree on `id_col`.
    assert (kind in RESIDUE_EMITTING_KINDS) == (kind != "msa")


@pytest.mark.parametrize("kind", SECOND_WAVE)
def test_second_wave_is_incubating_until_its_renderer_lands(kind: str):
    assert kind in INCUBATING


@pytest.mark.parametrize("kind", PROTEIN_KINDS)
def test_extra_fields_are_forbidden(kind: str):
    with pytest.raises(ValidationError):
        _cfg(kind, no_such_field=1)


@pytest.mark.parametrize("kind", SECOND_WAVE)
def test_every_field_carries_a_description(kind: str):
    """The descriptions feed the catalog JSON Schema and Tool Studio's form."""
    model = type(_cfg(kind))
    missing = [
        name
        for name, field in model.model_fields.items()
        if name != "viz_kind" and not field.description
    ]
    assert missing == []


# --- validators ---------------------------------------------------------------


def test_resolve_mode_needs_an_identifier_column():
    with pytest.raises(ValidationError, match="uniprot_col, gene_col or sequence_col"):
        VIZ.validate_python({"viz_kind": "molecule_3d", "structure_source": "resolve"})
    cfg = VIZ.validate_python(
        {"viz_kind": "molecule_3d", "structure_source": "resolve", "uniprot_col": "uniprot"}
    )
    assert cfg.taxon == 9606


@pytest.mark.parametrize("kind", ["molecule_3d", "ramachandran"])
def test_resolve_source_check_is_shared_and_says_the_same_thing(kind: str):
    message = "structure_source 'resolve' needs one of uniprot_col, gene_col or sequence_col"
    with pytest.raises(ValidationError) as excinfo:
        _cfg(kind, structure_source="resolve")
    assert message in str(excinfo.value)
    for column in ("uniprot_col", "gene_col", "sequence_col"):
        assert _cfg(kind, structure_source="resolve", **{column: "x"}).structure_source == "resolve"
    # A file source never needs one.
    assert _cfg(kind).structure_source == "file"


def test_the_shared_resolve_check_is_a_plain_function():
    _check_resolve_source("file", None, None, None)
    _check_resolve_source("resolve", None, "gene", None)
    with pytest.raises(ValueError, match="needs one of uniprot_col, gene_col or sequence_col"):
        _check_resolve_source("resolve", None, None, None)


def test_structure_msa_layout_needs_an_msa_collection():
    with pytest.raises(ValidationError, match="msa_dc_id"):
        VIZ.validate_python({"viz_kind": "molecule_3d", "layout": "structure_msa"})
    # A template ships the tag; the import resolves it to the ids.
    VIZ.validate_python({"viz_kind": "molecule_3d", "layout": "structure_msa", "msa_dc_tag": "msa"})


def test_msa_max_rows_is_bounded():
    with pytest.raises(ValidationError):
        VIZ.validate_python({"viz_kind": "msa", "max_rows": 1001})


def test_a_reference_source_needs_the_column_naming_the_sources():
    with pytest.raises(ValidationError, match="reference_source needs source_col"):
        _cfg("secondary_structure", reference_source="DSSP")
    cfg = _cfg("secondary_structure", source_col="source", reference_source="DSSP")
    assert cfg.reference_source == "DSSP"
    # Several sources compared with each other need no reference.
    assert _cfg("secondary_structure", source_col="source").reference_source is None


def test_a_pae_matrix_needs_its_pae_collection():
    with pytest.raises(ValidationError, match="pae_dc_id"):
        VIZ.validate_python({"viz_kind": "pae_matrix"})
    # A template ships the tag; the import resolves it to the ids.
    assert VIZ.validate_python({"viz_kind": "pae_matrix", "pae_dc_tag": "pae"}).pae_dc_id is None
    assert VIZ.validate_python({"viz_kind": "pae_matrix", "pae_dc_id": "64f"}).pae_dc_tag is None


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        ("hmm_logo", {"max_hits": 0}),
        ("hmm_logo", {"max_hits": 2001}),
        ("hmm_logo", {"hits_evalue_max": 0}),
        ("hmm_logo", {"height_mode": "bits"}),
        ("hmm_logo", {"profile_source": "stockholm"}),
        ("hmm_logo", {"color_scheme": "rainbow"}),
        ("domain_architecture", {"max_architectures": 0}),
        ("domain_architecture", {"max_architectures": 101}),
        ("domain_architecture", {"max_proteins": 20001}),
        ("domain_architecture", {"evalue_threshold": 0}),
        ("domain_architecture", {"partial_coverage": 1.1}),
        ("domain_architecture", {"partial_coverage": -0.1}),
        ("domain_architecture", {"view": "tree"}),
        ("domain_architecture", {"scale": "log"}),
        ("domain_architecture", {"color_by": "evalue"}),
        ("pae_matrix", {"max_pae": 0}),
        ("pae_matrix", {"brush": "lasso"}),
        ("pae_matrix", {"colour_scale": "Rainbow"}),
        ("ramachandran", {"marker_size": 1}),
        ("ramachandran", {"marker_size": 21}),
        ("ramachandran", {"taxon": 0}),
        ("ramachandran", {"color_mode": "spectrum"}),
        ("ramachandran", {"residue_classes": ["general", "alanine"]}),
    ],
)
def test_bounds_and_choices_are_enforced(kind: str, fields: dict[str, Any]):
    with pytest.raises(ValidationError):
        _cfg(kind, **fields)


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        ("hmm_logo", {"hits_evalue_max": None, "max_hits": 2000}),
        ("hmm_logo", {"profile_source": "msa", "height_mode": "probability"}),
        ("domain_architecture", {"max_architectures": 100, "evalue_threshold": 1e-5}),
        ("domain_architecture", {"sources": ["Pfam", "SMART"], "view": "architectures"}),
        ("pae_matrix", {"max_pae": 31.75, "colour_scale": "Viridis", "brush": "rectangle"}),
        ("ramachandran", {"residue_classes": ["glycine", "pre_proline"], "marker_size": 20}),
        ("ramachandran", {"color_mode": "secondary_structure", "show_regions": False}),
    ],
)
def test_valid_choices_round_trip(kind: str, fields: dict[str, Any]):
    config = _cfg(kind, **fields)
    assert VIZ.validate_python(config.model_dump()) == config


# --- defaults (the contract) ----------------------------------------------------


def test_hmm_logo_defaults():
    c = _cfg("hmm_logo")
    assert (c.profile_source, c.height_mode, c.color_scheme) == ("hmm", "relent_abovebg", "clustal")
    assert (c.entity_col, c.position_col, c.model_col) == ("entity", "position", "hmm_name")
    assert (c.state_col, c.letter_col, c.emission_col) == ("hmm_position", "hmm_letter", "emission")
    assert (c.insert_prob_col, c.insert_length_col, c.occupancy_col) == (
        "insert_prob",
        "insert_length",
        "occupancy",
    )
    assert (c.consensus_col, c.rf_col, c.cs_col) == ("consensus", "rf", "cs")
    assert (c.msa_id_col, c.seq_id_col, c.sequence_col, c.rank_col) == (
        "msa_id",
        "seq_id",
        "aligned_sequence",
        "rank",
    )
    assert (c.show_indel_rows, c.show_consensus) == (True, True)
    assert (c.hits_wf_id, c.hits_dc_id, c.hits_dc_tag) == (None, None, None)
    assert (c.hits_model_col, c.hits_entity_col) == ("label", "entity")
    assert (c.hits_from_col, c.hits_to_col, c.hits_length_col) == (
        "hmm_from",
        "hmm_to",
        "hmm_length",
    )
    assert (c.hits_evalue_col, c.hits_score_col) == ("i_evalue", "dom_score")
    assert (c.hits_ali_from_col, c.hits_ali_to_col) == ("ali_from", "ali_to")
    assert (c.hits_evalue_max, c.max_hits) == (0.01, 200)
    assert c.controls_placement == "popover"


def test_hmm_logo_reuses_the_msa_colour_schemes():
    from depictio.models.components.advanced_viz.configs import HmmLogoConfig, MsaConfig

    def schemes(model: type) -> tuple[str, ...]:
        return get_args(model.model_fields["color_scheme"].annotation)

    assert schemes(HmmLogoConfig) == schemes(MsaConfig) != ()


def test_secondary_structure_defaults():
    c = _cfg("secondary_structure")
    assert (c.entity_col, c.position_col, c.residue_col, c.state_col) == (
        "entity",
        "position",
        "residue",
        "ss_code",
    )
    assert (c.source_col, c.reference_source, c.confidence_col) == (None, None, None)
    assert (c.p_helix_col, c.p_strand_col, c.p_coil_col) == ("p_helix", "p_strand", "p_coil")
    assert (c.show_probabilities, c.show_agreement) == (True, True)
    assert (c.show_segments, c.show_composition) == (True, True)


def test_domain_architecture_defaults():
    c = _cfg("domain_architecture")
    assert (c.entity_col, c.start_col, c.end_col, c.label_col) == (
        "entity",
        "start",
        "end",
        "label",
    )
    assert (c.protein_length_col, c.hmm_from_col, c.hmm_to_col, c.hmm_length_col) == (
        "protein_length",
        "hmm_from",
        "hmm_to",
        "hmm_length",
    )
    assert (c.hmm_coverage_col, c.evalue_col, c.source_col) == (
        "hmm_coverage",
        "i_evalue",
        "source",
    )
    assert (c.description_col, c.accession_col) == ("description", "accession")
    assert (c.view, c.scale, c.color_by) == ("proteins", "shared", "label")
    assert (c.max_architectures, c.max_proteins) == (15, 2000)
    assert (c.evalue_threshold, c.sources, c.partial_coverage) == (None, None, 0.9)
    assert (c.position_col_for_selection, c.label_selection) == ("position", True)


def test_pae_matrix_defaults():
    c = _cfg("pae_matrix")
    assert (c.entity_col, c.position_col, c.value_col, c.chain_col) == (
        "entity",
        "position",
        None,
        None,
    )
    assert (c.max_pae, c.colour_scale, c.brush, c.show_plddt) == (None, None, "diagonal", True)


def test_ramachandran_defaults():
    c = _cfg("ramachandran")
    assert (c.structure_source, c.structure_wf_id, c.structure_dc_id, c.structure_dc_tag) == (
        "file",
        None,
        None,
        None,
    )
    assert (c.uniprot_col, c.gene_col, c.sequence_col, c.taxon) == (None, None, None, 9606)
    assert (c.entity_col, c.position_col) == ("entity", "position")
    assert (c.chain_col, c.value_col, c.category_col) == (None, None, None)
    assert (c.color_mode, c.show_regions, c.residue_classes, c.marker_size) == (
        "plddt",
        True,
        None,
        6,
    )


# --- the first wave, unchanged ---------------------------------------------------


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


# --- selection -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("molecule_3d", "position"),
        ("sequence_track", "position"),
        ("msa", "seq_id"),
        ("hmm_logo", "position"),
        ("secondary_structure", "position"),
        ("pae_matrix", "position"),
        ("ramachandran", "position"),
        ("domain_architecture", "label"),
    ],
)
def test_protein_kinds_emit_a_selection_by_default(kind: str, expected: str):
    comp = {"component_type": "advanced_viz", "config": {"viz_kind": kind}}
    assert emitted_selection_column(comp) == expected
    off = {
        "component_type": "advanced_viz",
        "config": {"viz_kind": kind, "selection_enabled": False},
    }
    assert emitted_selection_column(off) is None


@pytest.mark.parametrize(
    ("kind", "config", "expected"),
    [
        ("hmm_logo", {"position_col": "ref_pos"}, "ref_pos"),
        ("secondary_structure", {"position_col": "resnum"}, "resnum"),
        ("pae_matrix", {"position_col": "resnum"}, "resnum"),
        ("ramachandran", {"position_col": "resnum"}, "resnum"),
        ("domain_architecture", {"label_col": "family"}, "family"),
    ],
)
def test_the_emitted_column_is_the_one_the_config_names(
    kind: str, config: dict[str, Any], expected: str
):
    comp = {"component_type": "advanced_viz", "config": {"viz_kind": kind, **config}}
    assert emitted_selection_column(comp) == expected


# --- binding -----------------------------------------------------------------------


def test_the_lot3_domtbl_schema_binds_a_domain_architecture():
    assert validate_binding(_cfg("domain_architecture"), DOMTBL_SCHEMA) == []


def test_a_plain_domain_table_binds_a_domain_architecture():
    schema = {"entity": "String", "start": "Int64", "end": "Int64", "label": "String"}
    config = _cfg(
        "domain_architecture",
        protein_length_col=None,
        hmm_from_col=None,
        hmm_to_col=None,
        hmm_length_col=None,
        hmm_coverage_col=None,
        evalue_col=None,
        source_col=None,
        description_col=None,
        accession_col=None,
    )
    assert validate_binding(config, schema) == []


def test_the_lot3_s4pred_schema_binds_a_secondary_structure():
    assert validate_binding(_cfg("secondary_structure"), S4PRED_SCHEMA) == []


def test_the_hmm_profile_schema_binds_an_hmm_logo():
    assert validate_binding(_cfg("hmm_logo"), PROFILE) == []


def test_the_msa_schema_binds_an_hmm_logo_in_msa_mode():
    config = _cfg("hmm_logo", profile_source="msa")
    assert validate_binding(config, MSA) == []


def test_hmm_logo_binds_other_roles_in_msa_mode():
    """The profile table is not an alignment table, whichever mode the config is in."""
    hmm = validate_binding(_cfg("hmm_logo"), MSA)
    assert {e.role for e in hmm} >= {"state", "letter", "emission"}
    msa = validate_binding(_cfg("hmm_logo", profile_source="msa"), PROFILE)
    assert {e.role for e in msa} == {"msa_id", "seq_id", "sequence", "rank"}
    # Required first: an alignment config is missing `sequence_col`'s column, not `state_col`'s.
    assert not {e.role for e in msa} & {"state", "letter", "emission"}


def test_msa_mode_checks_the_alignment_dtypes():
    config = _cfg("hmm_logo", profile_source="msa")
    errors = validate_binding(config, {**MSA, "aligned_sequence": "Int64"})
    assert [(e.role, e.severity) for e in errors] == [("sequence", "error")]
    # `rank` is optional: absent from the config means nothing to check.
    assert validate_binding(_cfg("hmm_logo", profile_source="msa", rank_col=None), MSA) == []


def test_roles_for_changes_nothing_for_a_kind_without_modes():
    for kind in get_args(AdvancedVizKind):
        required, optional = _roles_for(kind)
        assert required is CANONICAL_SCHEMAS[kind]
        assert optional == _OPTIONAL_ROLES.get(kind, {})
    # A config of a kind with no mode table is read the same way.
    config = VIZ.validate_python({"viz_kind": "embedding", "compute_method": "pca"})
    assert _roles_for("embedding", config) == (
        CANONICAL_SCHEMAS["embedding"],
        _OPTIONAL_ROLES.get("embedding", {}),
    )
    hmm, _ = _roles_for("hmm_logo", _cfg("hmm_logo"))
    assert hmm is CANONICAL_SCHEMAS["hmm_logo"]


def test_roles_for_hmm_logo_follows_the_profile_source():
    required, optional = _roles_for("hmm_logo", _cfg("hmm_logo", profile_source="msa"))
    assert list(required) == ["msa_id", "seq_id", "sequence"]
    assert list(optional) == ["rank"]
    # The descriptor and the catalog read the kind's default roles ...
    assert {"state", "letter", "emission"} <= set(role_dtype_specs("hmm_logo"))
    assert "msa_id" not in role_dtype_specs("hmm_logo")
    # ... a config in msa mode reads the alignment's.
    specs = role_dtype_specs("hmm_logo", _cfg("hmm_logo", profile_source="msa"))
    assert list(specs) == ["msa_id", "seq_id", "sequence", "rank"]
    assert [specs[r]["required"] for r in specs] == [True, True, True, False]
    assert all(specs[r]["description"] for r in specs)


# --- suggestions -----------------------------------------------------------------------


def _by_kind(schema: dict[str, str]) -> dict[str, Any]:
    return {s.viz_kind: s for s in suggest_viz_kinds(schema)}


def test_a_position_column_alone_does_not_recommend_a_protein_kind():
    genomic = {"chromosome": "String", "position": "Int64", "value": "Float64", "sample": "String"}
    protein = {"entity": "String", "position": "Int64", "residue": "String", "value": "Float64"}
    by_kind = _by_kind(genomic)
    assert by_kind["molecule_3d"].match == "weak"
    assert by_kind["sequence_track"].score < 0.8
    for kind in ("pae_matrix", "ramachandran", "secondary_structure"):
        assert by_kind[kind].match == "weak" and by_kind[kind].score < RECOMMENDED_SCORE, kind
    by_kind = _by_kind(protein)
    assert by_kind["molecule_3d"].match == "named"
    assert by_kind["sequence_track"].score >= 0.8
    for kind in ("pae_matrix", "ramachandran"):
        assert by_kind[kind].match == "named" and by_kind[kind].score >= RECOMMENDED_SCORE, kind


def test_a_domtbl_ranks_domain_architecture_as_a_named_candidate():
    best = _by_kind(DOMTBL_SCHEMA)["domain_architecture"]
    assert best.match == "named"
    assert best.score >= RECOMMENDED_SCORE
    assert not best.unmet_roles
    top = suggest_viz_kinds(DOMTBL_SCHEMA)
    assert "domain_architecture" in [s.viz_kind for s in top if s.score >= RECOMMENDED_SCORE]


@pytest.mark.parametrize(
    "schema",
    [
        {"chrom": "String", "start": "Int64", "end": "Int64", "name": "String"},
        {"gene": "String", "start": "Int64", "end": "Int64", "name": "String"},
        {"entity": "String", "start": "Int64", "end": "Int64", "label": "String"},
    ],
    ids=["gene-bed", "gene-bed-named-gene", "plain-intervals"],
)
def test_an_interval_table_without_hit_columns_never_claims_domain_architecture(
    schema: dict[str, str],
):
    suggestion = _by_kind(schema)["domain_architecture"]
    assert suggestion.match == "weak"
    assert suggestion.score < RECOMMENDED_SCORE
    assert "domain-hit column" in suggestion.reasons[0]


@pytest.mark.parametrize(
    "evidence", ["hmm_from", "protein_length", "i_evalue", "evalue", "accession"]
)
def test_any_one_hit_column_lets_an_interval_table_claim_domain_architecture(evidence: str):
    dtype = "String" if evidence == "accession" else "Float64" if "evalue" in evidence else "Int64"
    schema = {
        "entity": "String",
        "start": "Int64",
        "end": "Int64",
        "label": "String",
        evidence: dtype,
    }
    suggestion = _by_kind(schema)["domain_architecture"]
    assert suggestion.match == "named"
    assert suggestion.score >= RECOMMENDED_SCORE


def test_a_profile_table_ranks_hmm_logo_but_an_alignment_does_not():
    profile = _by_kind(PROFILE)["hmm_logo"]
    assert profile.match == "named" and profile.score >= RECOMMENDED_SCORE
    alignment = _by_kind(MSA)
    assert alignment["hmm_logo"].match == "weak"
    assert alignment["msa"].match == "named"
    # A state / letter / probability table with no HMM column is not a profile.
    generic = {"state": "Int64", "letter": "String", "probability": "Float64"}
    assert _by_kind(generic)["hmm_logo"].match == "weak"
    assert _by_kind({**generic, "emission": "Float64"})["hmm_logo"].match == "named"


def test_an_s4pred_table_ranks_secondary_structure():
    suggestion = _by_kind(S4PRED_SCHEMA)["secondary_structure"]
    assert suggestion.match == "named" and suggestion.score >= RECOMMENDED_SCORE
    # The call and its probabilities are protein evidence on their own.
    bare = {"position": "Int64", "ss_code": "String"}
    assert _by_kind(bare)["secondary_structure"].match == "named"
