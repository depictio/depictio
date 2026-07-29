"""What changed between two versions — and, mostly, what did not.

`content_hash` can say two versions differ; it cannot say how. This is the
"how". But a diff that reports everything as changed after a routine re-save is
worse than no diff at all, because a reader learns to ignore it — so most of
what is pinned here is *absence* of change.

Two mechanisms carry that weight, and each has a whole class below:
`_VOLATILE_COMPONENT_KEYS` drops fields that churn without anyone editing
anything, and the emptiness rule treats `None` / `""` / `[]` / `{}` / absent as
one value at every leaf.
"""

from __future__ import annotations

import pytest

from depictio.api.v1.endpoints.dashboards_endpoints.version_diff import (
    changed_fields,
    diff_tabs,
    strip_box_prefix,
)


def _component(index: str = "c1", **overrides):
    base = {
        "index": index,
        "component_type": "figure",
        "wf_id": "wf1",
        "dc_id": "dc1",
        "dict_kwargs": {"x": "a", "y": "b"},
        "last_updated": "2026-03-01T12:00:00",
    }
    base.update(overrides)
    return base


def _tab(tab_id="t1", components=None, left=None, right=None, **overrides):
    tab = {
        "dashboard_id": tab_id,
        "title": "Main",
        "tab_order": 0,
        "stored_metadata": components if components is not None else [],
        "left_panel_layout_data": left or [],
        "right_panel_layout_data": right or [],
    }
    tab.update(overrides)
    return tab


def _only(report, tab_index=0):
    return report["tabs"][tab_index]["components"]


class TestNoiseControl:
    """Every case here must produce *no* diff. These are the ones that decide
    whether anyone trusts the feature."""

    def test_an_identical_snapshot_reports_nothing(self):
        tabs = [_tab(components=[_component()])]

        report = diff_tabs(tabs, tabs)

        assert _only(report) == []
        assert report["totals"]["unchanged"] == 1

    def test_a_new_last_updated_stamp_is_not_a_change(self):
        """Stamped unconditionally on every rebuild, in four places."""
        before = [_tab(components=[_component(last_updated="2026-03-01T12:00:00")])]
        after = [_tab(components=[_component(last_updated="2026-06-01T09:30:00")])]

        assert _only(diff_tabs(before, after)) == []

    def test_a_re_scanned_dc_config_is_not_a_change(self):
        """That is data drift, and the compatibility report already owns it.
        Letting it in here marks every component on a re-ingested collection as
        reconfigured."""
        before = [_tab(components=[_component(dc_config={"type": "table", "size_bytes": 100})])]
        after = [_tab(components=[_component(dc_config={"type": "table", "size_bytes": 999})])]

        assert _only(diff_tabs(before, after)) == []

    def test_a_recomputed_card_value_is_not_a_change(self):
        before = [_tab(components=[_component(component_type="card", value=41)])]
        after = [_tab(components=[_component(component_type="card", value=42)])]

        assert _only(diff_tabs(before, after)) == []

    @pytest.mark.parametrize(
        "before_value,after_value",
        [(None, ""), ("", []), ([], {}), (None, {}), ("", None)],
    )
    def test_empty_is_empty_however_it_is_spelled(self, before_value, after_value):
        """`buildMetadata` writes `background_color: c.background_color || ''`
        and `breakdown_col: (c.breakdown_col ?? null)`, where an older save
        simply omitted the key — so a re-save through a newer builder would
        otherwise mark every card reconfigured."""
        before = [_tab(components=[_component(background_color=before_value)])]
        after = [_tab(components=[_component(background_color=after_value)])]

        assert _only(diff_tabs(before, after)) == []

    def test_a_key_appearing_with_an_empty_value_is_not_a_change(self):
        before = [_tab(components=[_component()])]
        after = [_tab(components=[_component(breakdown_col=None)])]

        assert _only(diff_tabs(before, after)) == []

    def test_the_emptiness_rule_reaches_nested_leaves(self):
        before = [_tab(components=[_component(dict_kwargs={"x": "a", "y": "b", "color": ""})])]
        after = [_tab(components=[_component(dict_kwargs={"x": "a", "y": "b"})])]

        assert _only(diff_tabs(before, after)) == []

    def test_a_cols_json_statistics_refresh_is_not_a_change(self):
        before = [_tab(components=[_component(cols_json={"a": {"min": 0, "max": 10}})])]
        after = [_tab(components=[_component(cols_json={"a": {"min": 0, "max": 99}})])]

        assert _only(diff_tabs(before, after)) == []


class TestRealChanges:
    def test_a_hidden_column_is_a_change(self):
        """`cols_json` is mostly a stats cache, but `hide` is user intent and
        `TableRenderer` reads it."""
        before = [_tab(components=[_component(cols_json={"a": {"hide": False, "min": 0}})])]
        after = [_tab(components=[_component(cols_json={"a": {"hide": True, "min": 0}})])]

        entry = _only(diff_tabs(before, after))[0]

        assert entry["change"] == "modified"
        assert entry["modified_config"] is True

    def test_repointing_a_component_at_another_collection_is_a_change(self):
        """The most consequential edit there is, so `dc_id` is deliberately not
        in the volatile set."""
        before = [_tab(components=[_component(dc_id="dc1")])]
        after = [_tab(components=[_component(dc_id="dc2")])]

        assert _only(diff_tabs(before, after))[0]["changed_fields"] == ["dc_id"]

    def test_it_names_the_field_that_changed(self):
        before = [_tab(components=[_component(dict_kwargs={"x": "a", "y": "b"})])]
        after = [_tab(components=[_component(dict_kwargs={"x": "a", "y": "z"})])]

        assert _only(diff_tabs(before, after))[0]["changed_fields"] == ["dict_kwargs.y"]

    def test_a_list_reorder_is_a_change(self):
        """`columns` order is user-visible."""
        before = [_tab(components=[_component(columns=["a", "b"])])]
        after = [_tab(components=[_component(columns=["b", "a"])])]

        assert _only(diff_tabs(before, after))[0]["modified_config"] is True

    def test_a_long_field_list_is_capped_with_a_count(self):
        """A code-mode figure's `code_content` change would otherwise ship a
        field list the length of the file."""
        before = [_tab(components=[_component(config={f"k{i}": i for i in range(40)})])]
        after = [_tab(components=[_component(config={f"k{i}": i + 1 for i in range(40)})])]

        entry = _only(diff_tabs(before, after))[0]

        assert len(entry["changed_fields"]) == 12
        assert entry["changed_fields_truncated"] == 28

    def test_added_and_removed_components(self):
        before = [_tab(components=[_component("c1")])]
        after = [_tab(components=[_component("c1"), _component("c2")])]

        report = diff_tabs(before, after)
        entries = {e["index"]: e["change"] for e in _only(report)}

        assert entries == {"c2": "added"}
        assert report["totals"]["added"] == 1

        back = diff_tabs(after, before)
        assert {e["index"]: e["change"] for e in _only(back)} == {"c2": "removed"}


class TestLayout:
    def test_a_move_is_reported_as_moved_not_resized(self):
        before = [
            _tab(components=[_component()], right=[{"i": "c1", "x": 0, "y": 0, "w": 4, "h": 4}])
        ]
        after = [
            _tab(components=[_component()], right=[{"i": "c1", "x": 4, "y": 0, "w": 4, "h": 4}])
        ]

        entry = _only(diff_tabs(before, after))[0]

        assert entry["moved"] is True
        assert entry["resized"] is False
        assert entry["modified_config"] is False

    def test_a_resize_is_reported_as_resized(self):
        before = [
            _tab(components=[_component()], right=[{"i": "c1", "x": 0, "y": 0, "w": 4, "h": 4}])
        ]
        after = [
            _tab(components=[_component()], right=[{"i": "c1", "x": 0, "y": 0, "w": 8, "h": 4}])
        ]

        entry = _only(diff_tabs(before, after))[0]

        assert entry["resized"] is True
        assert entry["moved"] is False

    def test_a_box_prefixed_id_matches_a_bare_one(self):
        """`upsertComponent` writes `box-{index}` while the editor's drag path
        writes bare indices. Without stripping, the first save after a component
        is added reports every component as removed-and-re-added."""
        before = [
            _tab(components=[_component()], right=[{"i": "c1", "x": 0, "y": 0, "w": 4, "h": 4}])
        ]
        after = [
            _tab(components=[_component()], right=[{"i": "box-c1", "x": 0, "y": 0, "w": 4, "h": 4}])
        ]

        entry = _only(diff_tabs(before, after, include_unchanged=True))[0]

        assert entry["moved"] is False
        assert entry["change"] == "unchanged"

    def test_strip_box_prefix_leaves_other_ids_alone(self):
        assert strip_box_prefix("box-abc") == "abc"
        assert strip_box_prefix("abc") == "abc"
        assert strip_box_prefix("boxed-abc") == "boxed-abc"

    def test_a_component_with_no_layout_entry_is_not_moved(self):
        """Cards routinely have none — `DashboardGrid` auto-places them."""
        before = [_tab(components=[_component(component_type="card")])]
        after = [_tab(components=[_component(component_type="card")])]

        entries = _only(diff_tabs(before, after, include_unchanged=True))

        assert entries[0]["moved"] is False
        assert entries[0]["layout_before"] is None

    def test_a_cross_panel_move_is_reported(self):
        before = [
            _tab(components=[_component()], left=[{"i": "c1", "x": 0, "y": 0, "w": 4, "h": 4}])
        ]
        after = [
            _tab(components=[_component()], right=[{"i": "c1", "x": 0, "y": 0, "w": 4, "h": 4}])
        ]

        entry = _only(diff_tabs(before, after))[0]

        assert entry["moved"] is True
        assert entry["layout_before"]["panel"] == "left"
        assert entry["layout_after"]["panel"] == "right"

    def test_static_and_resize_handles_are_ignored(self):
        """`normalizeLayout` overrides them at render time, so they carry no
        user intent — pure churn from older editor passes."""
        before = [
            _tab(
                components=[_component()],
                right=[{"i": "c1", "x": 0, "y": 0, "w": 4, "h": 4, "static": True}],
            )
        ]
        after = [
            _tab(
                components=[_component()],
                right=[
                    {
                        "i": "c1",
                        "x": 0,
                        "y": 0,
                        "w": 4,
                        "h": 4,
                        "static": False,
                        "resizeHandles": ["se"],
                    }
                ],
            )
        ]

        assert _only(diff_tabs(before, after)) == []


class TestTabs:
    def test_an_added_tab_marks_its_components_via_tab(self):
        """So the UI can say "Tab 'QC' added (2 components)" instead of two
        indistinguishable adds."""
        before = [_tab("t1", [_component()])]
        after = [_tab("t1", [_component()]), _tab("t2", [_component("c2"), _component("c3")])]

        report = diff_tabs(before, after)
        added_tab = next(t for t in report["tabs"] if t["tab_id"] == "t2")

        assert added_tab["change"] == "added"
        assert report["totals"]["tabs_added"] == 1
        assert all(c["via_tab"] for c in added_tab["components"])

    def test_a_removed_tab_is_reported(self):
        before = [_tab("t1", [_component()]), _tab("t2", [_component("c2")])]
        after = [_tab("t1", [_component()])]

        report = diff_tabs(before, after)

        assert report["totals"]["tabs_removed"] == 1

    def test_a_reorder_is_a_tab_order_delta(self):
        """No component-level list would ever surface this."""
        before = [_tab("t1", tab_order=0), _tab("t2", tab_order=1)]
        after = [_tab("t1", tab_order=1), _tab("t2", tab_order=0)]

        report = diff_tabs(before, after)

        assert all("tab_order" in t["changed_fields"] for t in report["tabs"])

    def test_a_rename_is_reported(self):
        before = [_tab("t1", title="Old")]
        after = [_tab("t1", title="New")]

        assert diff_tabs(before, after)["tabs"][0]["changed_fields"] == ["title"]

    def test_an_unchanged_tab_reports_no_fields(self):
        tabs = [_tab("t1", [_component()])]

        assert diff_tabs(tabs, tabs)["tabs"][0]["changed_fields"] == []


class TestChangedFieldsDirectly:
    def test_it_ignores_every_volatile_key(self):
        before = _component(last_updated="a", dc_config={"x": 1}, value=1)
        after = _component(last_updated="b", dc_config={"x": 2}, value=2)

        assert changed_fields(before, after) == []

    def test_a_length_change_is_reported_once(self):
        before = _component(columns=["a", "b", "c"])
        after = _component(columns=["a"])

        assert changed_fields(before, after) == ["columns.length"]
