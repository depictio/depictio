"""Unit tests for the transient dict_kwargs override in figure rendering.

`merge_dict_kwargs_patch` is what `/dashboards/render_figure` applies when
the request carries an AI figure-mutation patch. The contract: shallow merge
over the stored kwargs, UI-mode figures only, malformed patches degrade to
the stored rendering, and the stored dict is never mutated in place.
"""

from depictio.api.v1.endpoints.dashboards_endpoints.routes import merge_dict_kwargs_patch


class TestMergeDictKwargsPatch:
    def test_patch_merges_over_stored_kwargs_in_ui_mode(self):
        merged = merge_dict_kwargs_patch(
            {"x": "depth", "y": "coverage", "color": "sample"},
            {"color": "variety", "log_y": True},
            "ui",
        )
        assert merged == {"x": "depth", "y": "coverage", "color": "variety", "log_y": True}

    def test_code_mode_ignores_the_patch(self):
        merged = merge_dict_kwargs_patch({"x": "depth"}, {"x": "coverage"}, "code")
        assert merged == {"x": "depth"}

    def test_non_dict_patch_is_ignored(self):
        for bad in ("color=variety", ["color", "variety"], 42, True):
            assert merge_dict_kwargs_patch({"x": "depth"}, bad, "ui") == {"x": "depth"}

    def test_empty_or_absent_patch_is_a_noop(self):
        assert merge_dict_kwargs_patch({"x": "depth"}, {}, "ui") == {"x": "depth"}
        assert merge_dict_kwargs_patch({"x": "depth"}, None, "ui") == {"x": "depth"}

    def test_stored_kwargs_absent(self):
        assert merge_dict_kwargs_patch(None, {"x": "depth"}, "ui") == {"x": "depth"}

    def test_stored_dict_is_not_mutated(self):
        stored = {"x": "depth"}
        merged = merge_dict_kwargs_patch(stored, {"x": "coverage"}, "ui")
        assert stored == {"x": "depth"}
        assert merged == {"x": "coverage"}
