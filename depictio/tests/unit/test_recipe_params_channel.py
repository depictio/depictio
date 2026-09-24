"""Template parameters reach recipes that declare a ``params`` keyword."""

from types import SimpleNamespace

from depictio.models.models.transforms import TransformConfig
from depictio.recipes import call_transform


def _module(fn):
    return SimpleNamespace(transform=fn)


def test_params_passed_when_recipe_accepts_them() -> None:
    seen = {}

    def transform(sources, params=None):
        seen.update(params or {})
        return "ok"

    assert call_transform(_module(transform), {}, {"marker_panel": "CD3D,LYZ"}) == "ok"
    assert seen == {"marker_panel": "CD3D,LYZ"}


def test_unresolved_placeholder_is_dropped() -> None:
    seen = {}

    def transform(sources, params=None):
        seen["params"] = params
        return "ok"

    call_transform(_module(transform), {}, {"marker_panel": "{MARKER_PANEL}", "k": "5"})
    assert seen["params"] == {"k": "5"}


def test_legacy_recipe_without_params_keyword() -> None:
    def transform(sources):
        return "legacy"

    assert call_transform(_module(transform), {}, {"x": "1"}) == "legacy"


def test_transform_config_accepts_params() -> None:
    cfg = TransformConfig(recipe="a/b.py", params={"marker_panel": "{MARKER_PANEL}"})
    assert cfg.params == {"marker_panel": "{MARKER_PANEL}"}


def test_gene_lane_accepts_genome_variable_values() -> None:
    from depictio.models.components.advanced_viz.configs import _coerce_gene_lane

    assert _coerce_gene_lane("GRCh38") == "hg38"
    assert _coerce_gene_lane("mm10") == "mm10"
    assert _coerce_gene_lane("{GENOME}") == "none"
    assert _coerce_gene_lane("TAIR10") == "none"
