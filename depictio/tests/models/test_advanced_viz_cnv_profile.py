"""The `cnv_profile` kind: row contract, config, and the catalog that binds it.

The kind carries two row types in one collection (bins and called segments,
told apart by the `segment` role), which is the part most likely to be broken
by a well-meaning edit: drop the optional role and the renderer silently draws
every call as a point. These tests pin the contract end to end, from the
canonical schema through the config model to the three catalog entries that
produce it (cnvkit, ascat, controlfreec).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import CnvProfileConfig, VizConfig
from depictio.models.components.advanced_viz.sampling import KIND_SAMPLING_POLICY
from depictio.models.components.advanced_viz.schemas import (
    CANONICAL_SCHEMAS,
    KIND_METADATA,
    ROLE_NAMES,
    suggest_viz_kinds,
    validate_binding,
)

CATALOG = Path(__file__).resolve().parents[2] / "catalog"

#: The catalog entries whose recipe produces the canonical contract.
CNV_CATALOG_OUTPUTS = [
    ("cnvkit", "cnv_profile"),
    ("ascat", "cnv_segments"),
    ("controlfreec", "cnv_ratio"),
]


def _default_binding(**overrides: str | None) -> CnvProfileConfig:
    base: dict[str, str | None] = {
        "sample_col": "sample",
        "chrom_col": "chrom",
        "start_col": "start",
        "end_col": "end",
        "log2_col": "log2",
        "baf_col": "baf",
        "copy_number_col": "copy_number",
        "segment_col": "segment",
        "label_col": "label",
    }
    base.update(overrides)
    return CnvProfileConfig(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Row contract
# ---------------------------------------------------------------------------


def test_required_roles_are_the_five_that_place_a_row_on_the_genome():
    assert set(CANONICAL_SCHEMAS["cnv_profile"]) == {"sample", "chrom", "start", "end", "log2"}


def test_every_required_role_has_name_aliases():
    """The dtype-aware suggester matches on names, so a role with no alias set
    can never contribute to a suggestion."""
    assert set(ROLE_NAMES["cnv_profile"]) == set(CANONICAL_SCHEMAS["cnv_profile"])


def test_the_kind_is_listed_for_the_builder_picker():
    meta = KIND_METADATA["cnv_profile"]
    assert meta["label"]
    assert meta["icon"].startswith("tabler:")


def test_the_server_never_samples_this_kind():
    """Dropping rows at random erases a focal amplification, or a whole call."""
    assert KIND_SAMPLING_POLICY["cnv_profile"] == "none"


def test_a_bin_only_collection_binds_without_the_optional_roles():
    schema = {
        "sample": "String",
        "chrom": "String",
        "start": "Int64",
        "end": "Int64",
        "log2": "Float64",
    }
    assert validate_binding(CnvProfileConfig(), schema) == []


def test_the_full_contract_binds():
    schema = {
        "sample": "String",
        "chrom": "String",
        "start": "Int64",
        "end": "Int64",
        "log2": "Float64",
        "baf": "Float64",
        "copy_number": "Int64",
        "segment": "String",
        "label": "String",
    }
    assert validate_binding(_default_binding(), schema) == []


def test_a_missing_required_column_is_an_error():
    schema = {"sample": "String", "chrom": "String", "start": "Int64", "end": "Int64"}
    errors = validate_binding(CnvProfileConfig(), schema)
    assert errors, "a collection with no log2 column cannot draw a copy-number profile"


def test_the_kind_is_suggested_for_a_cnv_shaped_collection():
    schema = {
        "sample": "String",
        "chrom": "String",
        "start": "Int64",
        "end": "Int64",
        "log2": "Float64",
        "baf": "Float64",
    }
    ranked = suggest_viz_kinds(schema)
    kinds = [s.viz_kind for s in ranked]
    assert "cnv_profile" in kinds[:5], kinds[:5]


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------


def test_defaults_match_the_canonical_role_names():
    cfg = CnvProfileConfig()
    assert (cfg.sample_col, cfg.chrom_col, cfg.start_col, cfg.end_col, cfg.log2_col) == (
        "sample",
        "chrom",
        "start",
        "end",
        "log2",
    )
    assert cfg.baf_col is None and cfg.copy_number_col is None and cfg.segment_col is None


def test_the_thresholds_default_either_side_of_neutral():
    cfg = CnvProfileConfig()
    assert cfg.loss_threshold < 0 < cfg.gain_threshold


def test_it_survives_the_viz_config_union():
    cfg = TypeAdapter(VizConfig).validate_python(
        {"viz_kind": "cnv_profile", "segment_col": "segment", "chrom": "chr7", "show_baf": False}
    )
    assert isinstance(cfg, CnvProfileConfig)
    assert cfg.chrom == "chr7"
    assert cfg.show_baf is False


def test_an_unknown_key_is_rejected():
    """`extra="forbid"`: a persisted key with no field makes the whole
    component unloadable, so it must fail at the moment it is written."""
    with pytest.raises(ValidationError):
        CnvProfileConfig(colour_by="copy_number")  # type: ignore[call-arg]


def test_the_axis_limit_and_bin_cap_are_bounded():
    with pytest.raises(ValidationError):
        CnvProfileConfig(y_range=0)
    with pytest.raises(ValidationError):
        CnvProfileConfig(max_bins=10)


# ---------------------------------------------------------------------------
# The catalog entries that produce the contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("tool", "output"), CNV_CATALOG_OUTPUTS)
def test_catalog_fixture_satisfies_the_binding_it_declares(tool: str, output: str):
    """The committed fixture is the shape the render binds, dtypes included."""
    spec = yaml.safe_load((CATALOG / tool / f"{output}.yaml").read_text())
    render = next(r for r in spec["renders_as"] if r.get("kind") == "cnv_profile")

    fixture = pl.read_csv(CATALOG / tool / spec["fixture"], separator="\t")
    schema = {name: str(dtype) for name, dtype in fixture.schema.items()}

    roles = render["roles"]
    cfg = _default_binding(**{f"{role}_col": col for role, col in roles.items()})
    assert validate_binding(cfg, schema) == [], f"{tool}/{output} does not bind its own fixture"


@pytest.mark.parametrize(("tool", "output"), CNV_CATALOG_OUTPUTS)
def test_catalog_fixture_uses_the_two_row_types(tool: str, output: str):
    spec = yaml.safe_load((CATALOG / tool / f"{output}.yaml").read_text())
    fixture = pl.read_csv(CATALOG / tool / spec["fixture"], separator="\t")
    assert set(fixture["segment"].unique().to_list()) <= {"bin", "segment"}
    # ASCAT publishes no bin-level track of its own; the other two carry both.
    assert "segment" in fixture["segment"].to_list()


@pytest.mark.parametrize(("tool", "output"), CNV_CATALOG_OUTPUTS)
def test_catalog_glob_matches_the_sarek_layout(tool: str, output: str):
    """nf-core/sarek publishes these under `variant_calling/<tool>/<sample>/`."""
    spec = yaml.safe_load((CATALOG / tool / f"{output}.yaml").read_text())
    assert spec["find"]["path_glob"].startswith(f"**/variant_calling/{tool}/*/")


def test_showcase_fixture_carries_bins_and_segments_for_two_samples():
    demo = (
        Path(__file__).resolve().parents[2]
        / "projects/init/advanced_viz_showcase/data/cnv_profile_demo.tsv"
    )
    frame = pl.read_csv(demo, separator="\t")
    counts = {
        (sample, kind): n for sample, kind, n in frame.group_by(["sample", "segment"]).len().rows()
    }
    assert counts[("TUMOUR_A", "bin")] == 10_000
    assert counts[("TUMOUR_B", "bin")] == 10_000
    # Six planted events in TUMOUR_A, plus the neutral stretches between them.
    assert counts[("TUMOUR_A", "segment")] >= 6

    schema = {name: str(dtype) for name, dtype in frame.schema.items()}
    assert validate_binding(_default_binding(), schema) == []

    # The copy-neutral LOH is the reason the BAF panel exists: a log2 that says
    # nothing and allele fractions that do.
    loh = frame.filter((pl.col("segment") == "segment") & pl.col("label").str.contains("LOH"))
    assert loh.height >= 1
    assert loh["copy_number"].unique().to_list() == [2]
    assert loh["log2"].abs().max() < 0.1
    assert loh["baf"].max() < 0.2
