"""JBrowse wave-2 model fields: calls, mate, views, floating placement.

The component model, the dashboard conversion the importer and the exporter
share (a floating browser claims no grid slot, new fields round-trip), the
record-link lint (a jbrowse tile may drive a record card) and the cross-tab
endpoint's own floating test.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from depictio.models.components.advanced_viz.configs import RecordCardConfig
from depictio.models.components.advanced_viz.record_link import (
    emitted_selection_column,
    linked_component_problems,
)
from depictio.models.components.lite import (
    JBrowseDisplaySettings,
    JBrowseLiteComponent,
    JBrowseLocusSource,
    JBrowseMateSource,
)
from depictio.models.models.dashboards import DashboardDataLite

pytestmark = pytest.mark.no_db

_LOCUS_FROM: dict[str, Any] = {
    "data_collection_tag": "fusions",
    "chrom_column": "chrom_a",
    "start_column": "pos_a",
}
_MATE = {"chrom_column": "chrom_b", "start_column": "pos_b"}

_BROWSER: dict[str, Any] = {
    "tag": "genome",
    "component_type": "jbrowse",
    "workflow_tag": "wf/x",
    "data_collection_tag": "tracks",
}

_CARD: dict[str, Any] = {
    "tag": "n",
    "component_type": "card",
    "workflow_tag": "wf/x",
    "data_collection_tag": "fusions",
    "aggregation": "count",
    "column_name": "pos_a",
}


def _dashboard(*components: dict[str, Any]) -> DashboardDataLite:
    return DashboardDataLite(dashboard_id="d1", title="T", components=list(components))


def _stored(full: dict[str, Any]) -> dict[str, Any]:
    return next(c for c in full["stored_metadata"] if c.get("component_type") == "jbrowse")


def _exported(*components: dict[str, Any]) -> dict[str, Any]:
    """The first component as an export writes it: stored form, back to lite."""
    comp = DashboardDataLite.from_full(_dashboard(*components).to_full()).components[0]
    return comp if isinstance(comp, dict) else comp.model_dump(exclude_unset=True)


class TestLocusSource:
    def test_the_new_fields_default_to_the_old_behaviour(self):
        spec = JBrowseLocusSource.model_validate(_LOCUS_FROM)
        assert spec.sort_by is None and spec.descending is True
        assert spec.label_column is None and spec.mate is None

    def test_sort_label_and_mate(self):
        spec = JBrowseLocusSource.model_validate(
            {**_LOCUS_FROM, "sort_by": "reads", "descending": False, "label_column": "fusion"}
            | {"mate": {**_MATE, "end_column": "end_b"}}
        )
        assert (spec.sort_by, spec.descending, spec.label_column) == ("reads", False, "fusion")
        assert spec.mate == JBrowseMateSource(**_MATE, end_column="end_b")

    def test_unknown_keys_are_refused_on_both_models(self):
        with pytest.raises(ValidationError):
            JBrowseLocusSource.model_validate({**_LOCUS_FROM, "order_by": "reads"})
        with pytest.raises(ValidationError):
            JBrowseMateSource.model_validate({**_MATE, "padding": 1})

    def test_a_mate_needs_its_chromosome_and_start(self):
        with pytest.raises(ValidationError):
            JBrowseMateSource.model_validate({"chrom_column": "chrom_b"})


class TestComponent:
    def test_defaults(self):
        comp = JBrowseLiteComponent.model_validate(_BROWSER)
        assert comp.placement == "grid" and comp.floating_initial_state == "compact"
        assert comp.color_by is None and comp.show_junctions is False
        assert comp.call_stepper is True and comp.follow_window is True
        assert comp.views == [] and comp.circular_categories == ["sv"]
        assert comp.read_pairs_display == "pileup"

    def test_the_circular_view_needs_nothing_more(self):
        comp = JBrowseLiteComponent.model_validate({**_BROWSER, "views": ["circular"]})
        assert comp.views == ["circular"]

    def test_the_breakpoint_view_needs_a_mate(self):
        with pytest.raises(ValidationError, match="requires locus_from.mate"):
            JBrowseLiteComponent.model_validate({**_BROWSER, "views": ["breakpoint"]})
        with pytest.raises(ValidationError, match="requires locus_from.mate"):
            JBrowseLiteComponent.model_validate(
                {**_BROWSER, "views": ["breakpoint"], "locus_from": _LOCUS_FROM}
            )
        comp = JBrowseLiteComponent.model_validate(
            {
                **_BROWSER,
                "views": ["breakpoint", "circular"],
                "locus_from": {**_LOCUS_FROM, "mate": _MATE},
            }
        )
        assert comp.views == ["breakpoint", "circular"]

    def test_unknown_views_and_read_pair_displays_are_refused(self):
        with pytest.raises(ValidationError):
            JBrowseLiteComponent.model_validate({**_BROWSER, "views": ["linear"]})
        with pytest.raises(ValidationError):
            JBrowseLiteComponent.model_validate({**_BROWSER, "read_pairs_display": "stack"})

    @pytest.mark.parametrize("display", ["pileup", "arcs", "cloud"])
    def test_every_read_pair_display_is_accepted(self, display: str):
        comp = JBrowseLiteComponent.model_validate({**_BROWSER, "read_pairs_display": display})
        assert comp.read_pairs_display == display

    def test_a_browser_may_float_in_any_opening_state(self):
        for state in ("compact", "expanded", "docked", "hidden"):
            comp = JBrowseLiteComponent.model_validate(
                {**_BROWSER, "placement": "floating", "floating_initial_state": state}
            )
            assert (comp.placement, comp.floating_initial_state) == ("floating", state)

    def test_rejects_unknown_placement_and_state(self):
        with pytest.raises(ValidationError, match="Invalid placement 'top'"):
            JBrowseLiteComponent.model_validate({**_BROWSER, "placement": "top"})
        with pytest.raises(ValidationError, match="Invalid floating_initial_state 'huge'"):
            JBrowseLiteComponent.model_validate(
                {**_BROWSER, "placement": "floating", "floating_initial_state": "huge"}
            )

    def test_a_bad_value_is_reported_by_the_dashboard_too(self):
        """A component failing a check falls through the union to a dict."""
        with pytest.raises(ValidationError, match="Invalid placement 'top'"):
            _dashboard({**_BROWSER, "placement": "top"})
        with pytest.raises(ValidationError, match="requires locus_from.mate"):
            _dashboard({**_BROWSER, "views": ["breakpoint"]})


class TestLiteToFull:
    def test_a_floating_browser_claims_no_grid_slot(self):
        full = _dashboard({**_BROWSER, "placement": "floating"}, _CARD).to_full()
        stored = _stored(full)
        assert stored["placement"] == "floating"
        assert stored["floating_initial_state"] == "compact"
        indices = {item["i"] for item in full["right_panel_layout_data"]}
        assert f"box-{stored['index']}" not in indices
        assert len(indices) == 1

    def test_the_opening_state_travels(self):
        full = _dashboard(
            {**_BROWSER, "placement": "floating", "floating_initial_state": "docked"}
        ).to_full()
        assert _stored(full)["floating_initial_state"] == "docked"

    def test_a_grid_browser_stores_neither_placement_key(self):
        stored = _stored(_dashboard(_BROWSER).to_full())
        assert "placement" not in stored and "floating_initial_state" not in stored

    def test_the_new_fields_are_stored_for_the_viewer(self):
        stored = _stored(
            _dashboard(
                {
                    **_BROWSER,
                    "locus_from": {**_LOCUS_FROM, "sort_by": "reads", "mate": _MATE},
                    "color_by": "condition",
                    "show_junctions": True,
                    "views": ["breakpoint"],
                    "read_pairs_display": "arcs",
                }
            ).to_full()
        )
        assert stored["color_by"] == "condition"
        assert stored["show_junctions"] is True
        assert stored["call_stepper"] is True and stored["follow_window"] is True
        assert stored["views"] == ["breakpoint"] and stored["circular_categories"] == ["sv"]
        assert stored["read_pairs_display"] == "arcs"
        assert stored["locus_from"]["sort_by"] == "reads"
        assert stored["locus_from"]["mate"]["chrom_column"] == "chrom_b"


class TestRoundTrip:
    def _back(self, **extra: Any) -> dict[str, Any]:
        lite = _dashboard({**_BROWSER, **extra})
        comp = DashboardDataLite.from_full(lite.to_full()).components[0]
        return comp if isinstance(comp, dict) else comp.model_dump()

    def test_everything_survives_an_export_and_a_re_import(self):
        comp = self._back(
            locus_from={
                **_LOCUS_FROM,
                "sort_by": "reads",
                "descending": False,
                "label_column": "fusion",
                "mate": _MATE,
            },
            color_by="condition",
            show_junctions=True,
            call_stepper=False,
            follow_window=False,
            views=["breakpoint", "circular"],
            circular_categories=["sv", "fusion"],
            read_pairs_display="cloud",
            placement="floating",
            floating_initial_state="hidden",
        )
        assert comp["locus_from"]["sort_by"] == "reads"
        assert comp["locus_from"]["descending"] is False
        assert comp["locus_from"]["mate"]["start_column"] == "pos_b"
        assert comp["color_by"] == "condition" and comp["show_junctions"] is True
        assert comp["call_stepper"] is False and comp["follow_window"] is False
        assert comp["views"] == ["breakpoint", "circular"]
        assert comp["circular_categories"] == ["sv", "fusion"]
        assert comp["read_pairs_display"] == "cloud"
        assert (comp["placement"], comp["floating_initial_state"]) == ("floating", "hidden")

    def test_the_export_is_the_minimal_diff_from_the_defaults(self):
        exported = _exported(_BROWSER)
        for key in (
            "show_junctions",
            "call_stepper",
            "follow_window",
            "read_pairs_display",
            "circular_categories",
            "placement",
            "floating_initial_state",
        ):
            assert key not in exported

    def test_a_default_opening_state_is_not_exported(self):
        exported = _exported({**_BROWSER, "placement": "floating"})
        assert exported["placement"] == "floating"
        assert "floating_initial_state" not in exported

    def test_what_differs_from_the_defaults_is_exported(self):
        exported = _exported(
            {**_BROWSER, "show_junctions": True, "call_stepper": False, "views": ["circular"]}
        )
        assert exported["show_junctions"] is True
        assert exported["call_stepper"] is False
        assert exported["views"] == ["circular"]


class TestRecordLink:
    def _browser(self, **extra: Any) -> dict[str, Any]:
        return {
            **_BROWSER,
            "selection_enabled": True,
            "selection_column": "sample",
            "layout": {"x": 0, "y": 0, "w": 6, "h": 6},
            **extra,
        }

    def _card(self, **config: Any) -> dict[str, Any]:
        return {
            "tag": "sample-card",
            "component_type": "advanced_viz",
            "workflow_tag": "wf/x",
            "data_collection_tag": "samples",
            "viz_kind": "record_card",
            "config": {"viz_kind": "record_card", "id_col": "sample", **config},
            "layout": {"x": 6, "y": 0, "w": 3, "h": 6},
        }

    def test_a_selecting_browser_emits_its_selection_column(self):
        assert emitted_selection_column(self._browser()) == "sample"

    def test_a_browser_that_does_not_select_emits_nothing(self):
        assert emitted_selection_column(self._browser(selection_enabled=False)) is None
        assert emitted_selection_column(self._browser(selection_column=None)) is None

    def test_a_card_may_link_to_a_selecting_browser(self):
        comps = [self._browser(), self._card(linked_component="genome")]
        assert linked_component_problems(comps) == []

    def test_a_card_linked_to_a_silent_browser_is_told_why(self):
        comps = [self._browser(selection_enabled=False), self._card(linked_component="genome")]
        (problem,) = linked_component_problems(comps)
        assert "emits no selection" in problem and "jbrowse" in problem

    def test_the_card_matches_on_its_id_column_when_it_shares_the_collection(self):
        browser = self._browser(data_collection_tag="samples", selection_column="cell")
        (problem,) = linked_component_problems([browser, self._card(linked_component="genome")])
        assert "selects on 'cell'" in problem

    def test_a_dashboard_with_a_linked_card_imports(self):
        _dashboard(self._browser(), self._card(linked_component="genome"))

    def test_the_card_follows_a_jbrowse_selection(self):
        assert RecordCardConfig(selection_source="jbrowse_selection").selection_source == (
            "jbrowse_selection"
        )
        assert RecordCardConfig().selection_source == "any"
        with pytest.raises(ValidationError):
            RecordCardConfig(selection_source="genome_selection")  # type: ignore[arg-type]


class TestDisplaySettings:
    def _component(self, **fields: Any) -> JBrowseLiteComponent:
        return JBrowseLiteComponent.model_validate({**_BROWSER, **fields})

    def test_unset_by_default(self):
        assert self._component().display is None
        assert all(v is None for v in JBrowseDisplaySettings().model_dump().values())

    def test_a_valid_block(self):
        comp = self._component(
            display={
                "center_line": True,
                "track_labels": "hidden",
                "color_scheme": "tag",
                "color_tag": "HP",
                "read_height": "compact",
                "lower_panel": "arcs",
                "coverage_height": 120,
                "min_arc_score": 3,
                "scale": "log",
                "autoscale": "globalsd",
                "renderer": "density",
                "fill": "emphasis",
                "summary": "whiskers",
                "feature_mode": "reducedRepresentation",
                "gene_glyph": "longestCoding",
                "variant_row_height": 12,
                "phased": True,
            }
        )
        assert comp.display is not None
        assert comp.display.scale == "log" and comp.display.coverage_height == 120
        assert comp.display.cytobands is None

    def test_unknown_keys_are_refused(self):
        with pytest.raises(ValidationError):
            self._component(display={"coverage_scale": "log"})

    def test_values_outside_the_enums_are_refused(self):
        with pytest.raises(ValidationError):
            self._component(display={"scale": "sqrt"})
        with pytest.raises(ValidationError):
            self._component(display={"read_height": "tall"})

    def test_the_tag_scheme_needs_a_tag_and_only_it_takes_one(self):
        with pytest.raises(ValidationError, match="requires display.color_tag"):
            self._component(display={"color_scheme": "tag"})
        with pytest.raises(ValidationError, match="only used with"):
            self._component(display={"color_scheme": "strand", "color_tag": "HP"})
        with pytest.raises(ValidationError, match="only used with"):
            self._component(display={"color_tag": "HP"})

    @pytest.mark.parametrize(
        ("field", "ok", "bad"),
        [
            ("coverage_height", (20, 2000), (19, 2001)),
            ("variant_row_height", (1, 50), (0, 51)),
            ("min_arc_score", (0, 10), (-1,)),
        ],
    )
    def test_numeric_bounds(self, field: str, ok: tuple[int, ...], bad: tuple[int, ...]):
        for value in ok:
            self._component(display={field: value})
        for value in bad:
            with pytest.raises(ValidationError):
                self._component(display={field: value})

    @pytest.mark.parametrize(
        ("display", "legacy"),
        [
            ({"track_labels": "hidden"}, {"track_labels": "overlapping"}),
            ({"sashimi_arcs": False}, {"show_junctions": True}),
            ({"lower_panel": "cloud"}, {"read_pairs_display": "arcs"}),
        ],
    )
    def test_a_contradiction_with_the_legacy_field_is_refused(
        self, display: dict[str, Any], legacy: dict[str, Any]
    ):
        with pytest.raises(ValidationError, match="contradicts"):
            self._component(display=display, **legacy)

    @pytest.mark.parametrize(
        ("display", "legacy"),
        [
            ({"track_labels": "hidden"}, {"track_labels": "hidden"}),
            ({"track_labels": "overlapping"}, {}),
            ({"sashimi_arcs": True}, {"show_junctions": True}),
            ({"sashimi_arcs": True}, {}),
            ({"lower_panel": "arcs"}, {"read_pairs_display": "arcs"}),
            ({"lower_panel": "cloud"}, {}),
        ],
    )
    def test_the_same_value_or_an_unset_legacy_field_is_accepted(
        self, display: dict[str, Any], legacy: dict[str, Any]
    ):
        assert self._component(display=display, **legacy).display is not None

    def test_the_block_round_trips_through_the_stored_form(self):
        stored = _stored(
            _dashboard(
                {**_BROWSER, "display": {"scale": "log", "read_height": "compact"}}
            ).to_full()
        )
        assert stored["display"] == {"scale": "log", "read_height": "compact"}
        assert _exported({**_BROWSER, "display": {"scale": "log"}})["display"] == {"scale": "log"}

    def test_the_block_is_not_spread_over_the_top_level_fields(self):
        stored = _stored(
            _dashboard(
                {
                    **_BROWSER,
                    "track_labels": "overlapping",
                    "display": {"track_labels": "overlapping"},
                }
            ).to_full()
        )
        assert stored["display"] == {"track_labels": "overlapping"}
        assert stored["track_labels"] == "overlapping"

    def test_an_unset_block_is_not_exported(self):
        assert _stored(_dashboard(_BROWSER).to_full())["display"] is None
        assert "display" not in _exported(_BROWSER)


_PEAKS: dict[str, Any] = {
    "name": "peaks",
    "data_collection_tag": "peaks",
    "chrom_column": "chr",
    "start_column": "start",
    "end_column": "end",
    "sort_by": "score",
    "sample_column": "library",
    "run_column": "run",
    "columns": ["fold", "padj"],
    "search_columns": ["gene"],
    "color": "teal",
}
_GENES: dict[str, Any] = {
    "data_collection_tag": "de_genes",
    "workflow_tag": "rnaseq",
    "chrom_column": "chromosome",
    "start_column": "pos",
}


class TestSeveralSources:
    def test_the_new_source_fields_default_to_unset(self):
        spec = JBrowseLocusSource.model_validate(_LOCUS_FROM)
        assert spec.name is None and spec.color is None and spec.workflow_tag is None
        assert spec.sample_column is None and spec.run_column is None
        assert spec.columns is None and spec.search_columns is None
        assert spec.source_name == "fusions"

    def test_a_source_carries_its_name_colour_workflow_and_picker_columns(self):
        spec = JBrowseLocusSource.model_validate({**_PEAKS, "workflow_tag": "atacseq"})
        assert (spec.name, spec.color, spec.workflow_tag) == ("peaks", "teal", "atacseq")
        assert (spec.sample_column, spec.run_column) == ("library", "run")
        assert spec.columns == ["fold", "padj"] and spec.search_columns == ["gene"]

    def test_locus_from_is_one_source_or_a_list(self):
        one = JBrowseLiteComponent.model_validate({**_BROWSER, "locus_from": _LOCUS_FROM})
        assert isinstance(one.locus_from, JBrowseLocusSource)
        many = JBrowseLiteComponent.model_validate({**_BROWSER, "locus_from": [_PEAKS, _GENES]})
        assert isinstance(many.locus_from, list) and len(many.locus_from) == 2
        assert many.primary_locus is many.locus_from[0]
        assert one.primary_locus is one.locus_from
        assert JBrowseLiteComponent.model_validate(_BROWSER).primary_locus is None

    def test_an_empty_list_is_refused(self):
        with pytest.raises(ValidationError, match="at least one source"):
            JBrowseLiteComponent.model_validate({**_BROWSER, "locus_from": []})

    def test_source_names_are_unique_by_name_or_collection_tag(self):
        with pytest.raises(ValidationError, match="unique"):
            JBrowseLiteComponent.model_validate(
                {**_BROWSER, "locus_from": [_GENES, {**_GENES, "workflow_tag": "other"}]}
            )
        with pytest.raises(ValidationError, match="peaks"):
            JBrowseLiteComponent.model_validate(
                {**_BROWSER, "locus_from": [_PEAKS, {**_GENES, "name": "peaks"}]}
            )

    def test_two_sources_of_one_collection_need_different_names(self):
        sources = [{**_GENES, "name": "up"}, {**_GENES, "name": "down"}]
        comp = JBrowseLiteComponent.model_validate({**_BROWSER, "locus_from": sources})
        assert [s.source_name for s in comp.locus_from] == ["up", "down"]

    def test_unknown_keys_are_still_refused_inside_a_list(self):
        with pytest.raises(ValidationError):
            JBrowseLiteComponent.model_validate(
                {**_BROWSER, "locus_from": [{**_PEAKS, "order_by": "x"}]}
            )

    def test_the_breakpoint_view_needs_a_mate_on_the_primary_source(self):
        with pytest.raises(ValidationError, match="requires locus_from.mate"):
            JBrowseLiteComponent.model_validate(
                {
                    **_BROWSER,
                    "views": ["breakpoint"],
                    "locus_from": [_PEAKS, {**_GENES, "mate": _MATE}],
                }
            )
        comp = JBrowseLiteComponent.model_validate(
            {
                **_BROWSER,
                "views": ["breakpoint"],
                "locus_from": [{**_PEAKS, "mate": _MATE}, _GENES],
            }
        )
        assert comp.primary_locus.mate is not None

    def test_show_density_is_offered_hidden_by_default(self):
        # Unset: offered in the view menu, hidden; true shows it, false removes it.
        assert JBrowseLiteComponent.model_validate(_BROWSER).show_density is None
        for value in (True, False):
            comp = JBrowseLiteComponent.model_validate({**_BROWSER, "show_density": value})
            assert comp.show_density is value

    def test_a_list_and_show_density_are_stored_for_the_viewer(self):
        stored = _stored(
            _dashboard(
                {**_BROWSER, "locus_from": [_PEAKS, _GENES], "show_density": False}
            ).to_full()
        )
        assert stored["show_density"] is False
        assert [s["data_collection_tag"] for s in stored["locus_from"]] == ["peaks", "de_genes"]
        assert stored["locus_from"][0]["columns"] == ["fold", "padj"]
        assert stored["locus_from"][1]["workflow_tag"] == "rnaseq"
        assert _stored(_dashboard(_BROWSER).to_full()).get("show_density") is None

    def test_a_list_and_show_density_survive_an_export_and_a_re_import(self):
        lite = _dashboard({**_BROWSER, "locus_from": [_PEAKS, _GENES], "show_density": False})
        back = DashboardDataLite.from_full(lite.to_full())
        comp = back.components[0]
        comp = comp if isinstance(comp, dict) else comp.model_dump(exclude_unset=True)
        assert comp["show_density"] is False
        assert [s.get("name") for s in comp["locus_from"]] == ["peaks", None]
        assert comp["locus_from"][0]["search_columns"] == ["gene"]
        # unset keys are not written out
        assert "mate" not in comp["locus_from"][1] and "color" not in comp["locus_from"][1]
        again = DashboardDataLite.model_validate(back.model_dump())
        assert isinstance(again.components[0], JBrowseLiteComponent)
        assert len(again.components[0].locus_from) == 2

    def test_the_default_density_is_not_exported(self):
        assert "show_density" not in _exported(_BROWSER)
        assert "show_density" not in _exported({**_BROWSER, "locus_from": _LOCUS_FROM})
