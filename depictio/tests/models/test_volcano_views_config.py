"""A volcano's MA and QQ views: bound by config, refused when unbound."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import VizConfig, VolcanoConfig
from depictio.models.components.advanced_viz.schemas import role_dtype_specs

BASE = {"feature_id_col": "id", "effect_size_col": "lfc", "significance_col": "q_val"}


def test_views_are_optional() -> None:
    cfg = VolcanoConfig(**BASE)
    assert cfg.default_view == "volcano"
    assert cfg.p_value_col is None and cfg.ma_dc_tag is None


def test_bound_views_round_trip_through_the_union() -> None:
    raw = {
        "viz_kind": "volcano",
        **BASE,
        "p_value_col": "p_val",
        "ma_dc_tag": "ma_canonical",
        "default_view": "qq",
    }
    cfg = TypeAdapter(VizConfig).validate_python(raw)
    assert isinstance(cfg, VolcanoConfig)
    assert cfg.model_dump(exclude_none=True)["ma_dc_tag"] == "ma_canonical"


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"default_view": "qq"}, "p_value_col"),
        ({"default_view": "ma"}, "avg_log_intensity_col"),
    ],
)
def test_a_default_view_needs_its_columns(extra: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        VolcanoConfig(**BASE, **extra)


@pytest.mark.parametrize(
    "binding",
    [{"avg_log_intensity_col": "mean"}, {"ma_dc_tag": "ma_canonical"}, {"ma_dc_id": "x"}],
)
def test_ma_default_view_accepts_either_binding(binding: dict) -> None:
    assert VolcanoConfig(**BASE, default_view="ma", **binding).default_view == "ma"


def test_builder_offers_the_view_columns_as_optional_roles() -> None:
    specs = role_dtype_specs("volcano")
    assert specs["p_value"]["required"] is False
    assert specs["avg_log_intensity"]["required"] is False
    assert "QQ" in specs["p_value"]["description"]
