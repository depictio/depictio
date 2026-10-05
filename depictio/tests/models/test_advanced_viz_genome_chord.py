"""The `genome_chord` kind: config, roles and the two frames it is bound to.

A chord diagram is the one advanced-viz kind with no library behind it (Plotly
has no chord trace and d3 is not a dependency), so its contract lives entirely in
the canonical schema and this config. Both shipped bindings are checked against
the real column dtypes here rather than by eye: the Arriba catalog output that
ships with the tool, and the showcase fixture the demo dashboard reads.

Pure-model + fixture reads: no DB, no network.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import GenomeChordConfig, VizConfig
from depictio.models.components.advanced_viz.schemas import (
    _OPTIONAL_ROLES,
    CANONICAL_SCHEMAS,
    KIND_METADATA,
    ROLE_NAMES,
    validate_binding,
)

REPO = Path(__file__).resolve().parents[3]
CATALOG_FIXTURE = REPO / "depictio" / "catalog" / "arriba" / "fusion_links.tsv"
SHOWCASE_FIXTURE = (
    REPO
    / "depictio"
    / "projects"
    / "init"
    / "advanced_viz_showcase"
    / "data"
    / "genome_chord_demo.tsv"
)

VIZ_CONFIG = TypeAdapter(VizConfig)


def _fixture_schema(path: Path) -> dict[str, str]:
    """Column -> polars dtype name, inferred the way a scanned DC would report it.

    Deliberately not polars: these tests run in the pure-model environment, and
    the only distinction the binding cares about is numeric against string.
    """
    with path.open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
    assert rows, f"{path} has a header but no data rows"
    schema: dict[str, str] = {}
    for column in reader.fieldnames or []:
        values = [row[column] for row in rows if row[column] not in (None, "")]
        if values and all(v.lstrip("-").isdigit() for v in values):
            schema[column] = "Int64"
        else:
            schema[column] = "String"
    return schema


# ---------------------------------------------------------------------------
# The row contract
# ---------------------------------------------------------------------------


def test_required_roles_are_the_two_loci():
    """Four columns and nothing else: a link is two places on a genome."""
    assert set(CANONICAL_SCHEMAS["genome_chord"]) == {"chrom_a", "pos_a", "chrom_b", "pos_b"}
    assert set(_OPTIONAL_ROLES["genome_chord"]) == {"label", "weight", "category", "sample"}


def test_every_role_is_reachable_from_its_config_field():
    """The `*_col` defaults name their own role, so a DC whose columns already
    match the canonical schema needs no explicit binding."""
    config = GenomeChordConfig()
    for role in CANONICAL_SCHEMAS["genome_chord"]:
        assert getattr(config, f"{role}_col") == role
    # The optional roles default to unbound, not to a guessed column name: a
    # weight nobody declared must not silently size the chords.
    for role in _OPTIONAL_ROLES["genome_chord"]:
        assert getattr(config, f"{role}_col") is None


def test_the_kind_is_listed_and_the_suggester_knows_its_aliases():
    assert KIND_METADATA["genome_chord"]["label"]
    for role in CANONICAL_SCHEMAS["genome_chord"]:
        aliases = ROLE_NAMES["genome_chord"][role]
        assert role in aliases
    # The names Arriba, Manta and STAR-Fusion actually write.
    assert "breakpoint1" in ROLE_NAMES["genome_chord"]["pos_a"]
    assert "chr2" in ROLE_NAMES["genome_chord"]["chrom_b"]


# ---------------------------------------------------------------------------
# Guards and settings
# ---------------------------------------------------------------------------


def test_guards_have_defensible_defaults():
    config = GenomeChordConfig()
    assert config.max_links == 500
    assert config.min_weight is None
    assert config.intra_chromosomal is True
    assert config.colour_by == "category"
    assert config.assembly is None  # derive the ring from the data


def test_max_links_is_bounded_on_both_sides():
    """An unbounded cap would let a dashboard ask for a ring of 200000 chords."""
    with pytest.raises(ValidationError):
        GenomeChordConfig(max_links=0)
    with pytest.raises(ValidationError):
        GenomeChordConfig(max_links=50_000)


def test_selection_is_off_by_default_and_round_trips_when_opted_in():
    assert GenomeChordConfig().selection_enabled is False
    assert GenomeChordConfig().selection_column is None
    parsed = VIZ_CONFIG.validate_python(
        {
            "viz_kind": "genome_chord",
            "label_col": "label",
            "selection_enabled": True,
            "selection_column": "label",
        }
    )
    assert parsed.selection_enabled is True  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# The two shipped bindings, against the real columns
# ---------------------------------------------------------------------------


def test_arriba_breakpoint_links_bind_cleanly():
    """The catalog's own fixture is the shape `arriba/fusion_links.py` emits."""
    schema = _fixture_schema(CATALOG_FIXTURE)
    assert schema["pos_a"] == "Int64" and schema["pos_b"] == "Int64"
    config = GenomeChordConfig(
        label_col="label",
        weight_col="weight",
        category_col="category",
    )
    assert validate_binding(config, schema) == []


def test_showcase_fixture_binds_cleanly():
    schema = _fixture_schema(SHOWCASE_FIXTURE)
    config = GenomeChordConfig(
        label_col="label",
        weight_col="weight",
        category_col="category",
    )
    assert validate_binding(config, schema) == []


def test_a_breakpoint_left_as_a_string_is_reported():
    """The failure this kind exists to prevent: binding `chr:pos` as a position.

    Arriba writes both breakpoints as one string, and a template that binds them
    straight through would render every chord at position 0 rather than fail, so
    the dtype check has to be the thing that catches it.
    """
    errors = validate_binding(
        GenomeChordConfig(pos_a_col="breakpoint1", pos_b_col="breakpoint2"),
        {
            "chrom_a": "String",
            "breakpoint1": "String",
            "chrom_b": "String",
            "breakpoint2": "String",
        },
    )
    assert {e.role for e in errors} == {"pos_a", "pos_b"}


def test_an_unbound_optional_role_is_not_an_error():
    """A caller with no confidence or read count still draws a ring."""
    schema = {"chrom_a": "String", "pos_a": "Int64", "chrom_b": "String", "pos_b": "Int64"}
    assert validate_binding(GenomeChordConfig(), schema) == []


def test_a_bound_optional_role_pointing_nowhere_is_an_error():
    schema = {"chrom_a": "String", "pos_a": "Int64", "chrom_b": "String", "pos_b": "Int64"}
    errors = validate_binding(GenomeChordConfig(weight_col="supporting_reads"), schema)
    assert [e.role for e in errors] == ["weight"]
