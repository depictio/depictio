"""The bioimage_viewer advanced-viz kind: config model and kind registries."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz import (
    AdvancedVizLiteComponent,
    BioimageChannel,
    BioimageViewerConfig,
    VizConfig,
    validate_binding,
)
from depictio.models.components.advanced_viz.sampling import policy_for_kind
from depictio.models.components.advanced_viz.schemas import (
    _KIND_REQUIRES_DC_TYPE,
    _OPTIONAL_ROLES,
    CANONICAL_SCHEMAS,
    KIND_METADATA,
    ROLE_NAMES,
    kind_descriptors,
    suggest_viz_kinds,
)

VIZ_CONFIG = TypeAdapter(VizConfig)


def test_defaults():
    config = BioimageViewerConfig()
    assert config.viz_kind == "bioimage_viewer"
    assert config.channels == []
    assert config.show_scalebar is True
    assert config.selection_enabled is True
    assert config.points_scale == 1.0
    assert config.point_radius == 6.0


def test_full_config_round_trips_through_the_union():
    blob = {
        "viz_kind": "bioimage_viewer",
        "image_dc_tag": "bioimage_images",
        "store": "sample_A.zarr",
        "sample_dc_tag": "samples",
        "sample_column": "sample",
        "channels": [
            {"index": 0, "name": "DAPI", "color": "#0000ff", "contrast_limits": [0, 4000]},
            {"index": 1, "visible": False, "color": "#F0F"},
        ],
        "points_dc_tag": "cells",
        "cell_id_col": "cell_id",
        "x_col": "centroid_x",
        "y_col": "centroid_y",
        "color_col": "cluster",
        "points_scale": 0.5,
        "points_sample_col": "sample",
    }
    parsed = VIZ_CONFIG.validate_python(blob)
    assert isinstance(parsed, BioimageViewerConfig)
    assert parsed.channels[0].contrast_limits == (0.0, 4000.0)
    again = VIZ_CONFIG.validate_python(parsed.model_dump())
    assert again == parsed


def test_lite_component_accepts_the_kind():
    component = AdvancedVizLiteComponent.model_validate(
        {
            "tag": "ome-1",
            "workflow_tag": "wf",
            "data_collection_tag": "bioimage_images",
            "viz_kind": "bioimage_viewer",
            "config": {"viz_kind": "bioimage_viewer", "image_dc_tag": "bioimage_images"},
        }
    )
    assert isinstance(component.config, BioimageViewerConfig)


def test_unknown_key_is_rejected():
    with pytest.raises(ValidationError):
        BioimageViewerConfig.model_validate({"zoom": 3})
    with pytest.raises(ValidationError):
        BioimageChannel.model_validate({"index": 0, "gamma": 1.2})


@pytest.mark.parametrize("color", ["red", "#ff00f", "ff00ff", "#gg0000", "#ff00ff00"])
def test_channel_colour_must_be_hex(color):
    with pytest.raises(ValidationError, match="hex colour"):
        BioimageChannel(index=0, color=color)


@pytest.mark.parametrize("limits", [(10.0, 10.0), (20.0, 5.0)])
def test_contrast_limits_must_be_ordered(limits):
    with pytest.raises(ValidationError, match="min < max"):
        BioimageChannel(index=0, contrast_limits=limits)


def test_negative_channel_index_is_rejected():
    with pytest.raises(ValidationError):
        BioimageChannel(index=-1)


@pytest.mark.parametrize("column", ["cell_id_col", "x_col", "color_col", "points_sample_col"])
def test_points_columns_need_a_points_dc(column):
    with pytest.raises(ValidationError, match="no points DC is bound"):
        BioimageViewerConfig.model_validate({column: "c", "x_col": "x", "y_col": "y"})


def test_points_dc_needs_both_coordinates():
    with pytest.raises(ValidationError, match="x_col and y_col"):
        BioimageViewerConfig(points_dc_tag="cells", x_col="x")
    with pytest.raises(ValidationError, match="x_col and y_col"):
        BioimageViewerConfig(points_dc_id="6500000000000000000000aa")


def test_points_bound_by_tag_alone_is_valid():
    """An import that cannot resolve the tag clears the ids and keeps the tag."""
    config = BioimageViewerConfig(points_dc_tag="cells", points_dc_id=None, x_col="x", y_col="y")
    assert config.points_dc_tag == "cells"


def test_sample_column_needs_a_sample_dc():
    with pytest.raises(ValidationError, match="sample_column needs a sample DC"):
        BioimageViewerConfig(sample_column="sample")
    assert BioimageViewerConfig(sample_column="sample", sample_dc_id="x").sample_column == "sample"


def test_kind_is_in_every_dense_registry():
    kind = "bioimage_viewer"
    assert CANONICAL_SCHEMAS[kind] == {}
    assert ROLE_NAMES[kind] == {}
    assert _OPTIONAL_ROLES[kind] == {}
    assert _KIND_REQUIRES_DC_TYPE[kind] == "bioimage"
    assert KIND_METADATA[kind]["icon"] == "tabler:microscope"
    assert policy_for_kind(kind) == "none"
    descriptor = next(d for d in kind_descriptors() if d["viz_kind"] == kind)
    assert descriptor["required_roles"] == [] and descriptor["roles"] == {}


def test_binding_validation_is_a_no_op():
    assert validate_binding(BioimageViewerConfig(), {}) == []


def test_suggester_never_recommends_it_for_a_table():
    by_kind = {s.viz_kind: s for s in suggest_viz_kinds({"a": "Float64"}, dc_type="table")}
    assert by_kind["bioimage_viewer"].score == 0.0


class TestLabelsBinding:
    def test_defaults(self):
        config = BioimageViewerConfig()
        assert config.labels_dc_tag is None
        assert config.labels_opacity == 0.5
        assert config.labels_outline is True

    def test_labels_need_an_image_dc(self):
        with pytest.raises(ValidationError, match="drawn over an image"):
            BioimageViewerConfig(labels_dc_tag="masks")
        config = BioimageViewerConfig(image_dc_tag="img", labels_dc_tag="masks")
        assert config.labels_dc_tag == "masks"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"image_dc_tag": "img", "labels_dc_tag": "img"},
            {"image_dc_id": "abc", "labels_dc_id": "abc"},
        ],
    )
    def test_labels_are_a_separate_dc(self, kwargs):
        with pytest.raises(ValidationError, match="name the same DC"):
            BioimageViewerConfig(**kwargs)

    @pytest.mark.parametrize("opacity", [-0.1, 1.5])
    def test_opacity_is_bounded(self, opacity):
        with pytest.raises(ValidationError):
            BioimageViewerConfig(image_dc_tag="i", labels_dc_tag="m", labels_opacity=opacity)
