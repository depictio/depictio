"""The `transcript_structure` kind: roles, config, and the two frames it binds.

The renderer draws one gene at a time from a long frame of exon / CDS blocks.
What has to hold for that to work is checked here: the roles the kind declares,
the config the author writes (`extra="forbid"`, so a stray key is fatal at load
time, not at render time), and that both shipped frames (the synthetic
showcase fixture and the catalog fixture cut from a real StringTie run) bind
with no errors.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import TranscriptStructureConfig, VizConfig
from depictio.models.components.advanced_viz.sampling import KIND_SAMPLING_POLICY
from depictio.models.components.advanced_viz.schemas import (
    CANONICAL_SCHEMAS,
    KIND_METADATA,
    role_dtype_specs,
    validate_binding,
)

REPO = Path(__file__).resolve().parents[3]
SHOWCASE = REPO / "depictio" / "projects" / "init" / "advanced_viz_showcase"
SHOWCASE_FIXTURE = SHOWCASE / "data" / "transcript_structure_demo.tsv"
SHOWCASE_DASHBOARD = SHOWCASE / "dashboards" / "transcript_structure.yaml"
CATALOG_FIXTURE = REPO / "depictio" / "catalog" / "gtf" / "transcripts.tsv"

KIND = "transcript_structure"

#: The binding both shipped frames use: the recipe and the fixture generator
#: name the columns after the roles, so config and schema read the same.
FULL_BINDING = TranscriptStructureConfig(
    transcript_id_col="transcript_id",
    gene_id_col="gene_id",
    chrom_col="chrom",
    start_col="start",
    end_col="end",
    feature_col="feature",
    strand_col="strand",
    sample_col="sample",
    gene_name_col="gene_name",
    transcript_class_col="transcript_class",
    expression_col="expression",
)


def _schema(path: Path) -> dict[str, str]:
    frame = pl.read_csv(path, separator="\t")
    return {name: str(dtype) for name, dtype in frame.schema.items()}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_the_kind_declares_the_roles_a_block_frame_carries():
    required = CANONICAL_SCHEMAS[KIND]
    assert set(required) == {
        "transcript_id",
        "gene_id",
        "chrom",
        "start",
        "end",
        "feature",
        "strand",
    }
    # The four optional roles are what turns the track from a shape into a
    # readable panel: who it came from, what it is called, whether the caller
    # thought it was new, and how much of it there was.
    optional = set(role_dtype_specs(KIND)) - set(required)
    assert optional == {"sample", "gene_name", "transcript_class", "expression"}


def test_the_kind_is_never_sampled():
    # A uniformly sampled annotation is a transcript with holes in its exon
    # chain, which reads as a different isoform.
    assert KIND_SAMPLING_POLICY[KIND] == "none"


def test_the_kind_is_listed_for_the_picker():
    meta = KIND_METADATA[KIND]
    assert meta["label"] == "Transcript structure"
    assert meta["icon"]
    assert "<" not in meta["description"] and ">" not in meta["description"]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_config_defaults_name_the_canonical_columns():
    config = TranscriptStructureConfig()
    assert config.viz_kind == KIND
    assert (config.transcript_id_col, config.gene_id_col, config.feature_col) == (
        "transcript_id",
        "gene_id",
        "feature",
    )
    # Optional roles stay unbound until an author binds them.
    assert config.sample_col is None
    assert config.expression_col is None
    # Drawing settings: a gene picked by the renderer, a lane budget, the two
    # feature values it tells apart and how the lanes are coloured.
    assert config.gene is None
    assert config.max_transcripts == 30
    assert (config.exon_feature, config.cds_feature) == ("exon", "CDS")
    assert config.colour_by == "transcript_class"


def test_config_round_trips_through_the_viz_config_union():
    adapter = TypeAdapter(VizConfig)
    blob = FULL_BINDING.model_dump()
    assert adapter.validate_python(blob).model_dump() == blob


def test_an_unknown_setting_is_rejected_rather_than_ignored():
    # `extra="forbid"`: a persisted key with no field does not go unvalidated,
    # it makes the whole component unloadable, so it has to fail here.
    with pytest.raises(ValidationError):
        TranscriptStructureConfig(show_introns=True)


@pytest.mark.parametrize("bad", [0, 500])
def test_the_lane_budget_is_bounded(bad: int):
    with pytest.raises(ValidationError):
        TranscriptStructureConfig(max_transcripts=bad)


# ---------------------------------------------------------------------------
# The two shipped frames
# ---------------------------------------------------------------------------


def test_the_showcase_fixture_binds_with_no_errors():
    assert validate_binding(FULL_BINDING, _schema(SHOWCASE_FIXTURE)) == []


def test_the_showcase_fixture_holds_the_events_the_tab_claims():
    frame = pl.read_csv(SHOWCASE_FIXTURE, separator="\t")
    genes = frame["gene_name"].unique().to_list()
    assert sorted(genes) == ["DPX1", "DPX2"]
    dpx1 = frame.filter(pl.col("gene_name") == "DPX1")
    assert dpx1["transcript_id"].n_unique() == 6
    assert "novel" in dpx1["transcript_class"].unique().to_list()
    # Coding blocks are what the renderer draws taller; without them the
    # exon-versus-CDS distinction the tab describes would be invisible.
    assert sorted(frame["feature"].unique().to_list()) == ["CDS", "exon"]
    # Both strands, so the chevrons have something to point at in both ways.
    assert sorted(frame["strand"].unique().to_list()) == ["+", "-"]


def test_the_catalog_fixture_binds_with_no_errors():
    # Cut from a real nf-core/rnaseq StringTie run, so this is the check that
    # the recipe's output and the kind's roles agree on real data.
    assert validate_binding(FULL_BINDING, _schema(CATALOG_FIXTURE)) == []


def test_the_showcase_tab_binds_the_columns_the_fixture_has():
    dashboard = yaml.safe_load(SHOWCASE_DASHBOARD.read_text())
    component = next(
        c for c in dashboard["components"] if c.get("component_type") == "advanced_viz"
    )
    assert component["viz_kind"] == KIND
    config = TranscriptStructureConfig(**component["config"])
    assert validate_binding(config, _schema(SHOWCASE_FIXTURE)) == []


def test_the_catalog_render_binds_roles_the_config_actually_declares():
    """`use: gtf/transcript_structures` must expand into keys the model has.

    The expansion spells a role as `role_config_key` says, and a config key with
    no field does not merely go unvalidated: `extra="forbid"` makes the whole
    component unloadable. The tool folder is loaded on its own rather than
    through `load_catalog_entries`, so an unrelated module being edited in
    parallel cannot make this read as a failure of the gtf entry.
    """
    from depictio.models.components.advanced_viz.catalog import _load_tool_dir, role_config_key

    entry = _load_tool_dir(REPO / "depictio" / "catalog" / "gtf")
    output = next(o for o in entry.outputs if o.id == "gtf_transcripts")
    render = next(r for r in output.renders_as if r.kind == KIND)

    bindings = {role_config_key(KIND, role): column for role, column in render.roles.items()}
    unknown = sorted(set(bindings) - set(TranscriptStructureConfig.model_fields))
    assert not unknown, f"catalog roles map to fields the model has not got: {unknown}"
    assert validate_binding(TranscriptStructureConfig(**bindings), _schema(CATALOG_FIXTURE)) == []
