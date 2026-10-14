"""Unit tests for the prompt-side dashboard context."""

from depictio.api.v1.endpoints.ai_endpoints.context import DashboardContext, FilterSummary


def _ctx() -> DashboardContext:
    return DashboardContext(
        dashboard_id="d1",
        figures=[],
        filters=[
            FilterSummary(
                component_id="w-species",
                component_type="interactive",
                column="species",
                value=None,
                interactive_component_type="MultiSelect",
            ),
            FilterSummary(
                component_id="w-mass",
                component_type="interactive",
                column="body_mass_g",
                value=[2700, 6300],
                interactive_component_type="RangeSlider",
            ),
        ],
    )


class TestWithActiveFilters:
    def test_no_active_filters_is_identity(self):
        ctx = _ctx()
        assert ctx.with_active_filters(None) is ctx
        assert ctx.with_active_filters([]) is ctx

    def test_widget_value_overlays_stored_default(self):
        out = _ctx().with_active_filters(
            [{"index": "w-species", "value": ["Gentoo"], "column_name": "species"}]
        )
        by_id = {f.component_id: f for f in out.filters}
        assert by_id["w-species"].value == ["Gentoo"]
        # Untouched widgets keep their stored value.
        assert by_id["w-mass"].value == [2700, 6300]
        assert "w-species (interactive, col=species): ['Gentoo']" in out.filters_block()

    def test_cleared_widget_reads_as_unset(self):
        out = _ctx().with_active_filters(
            [{"index": "w-mass", "value": None, "column_name": "body_mass_g"}]
        )
        assert {f.component_id: f.value for f in out.filters}["w-mass"] is None

    def test_expression_only_filter_is_appended(self):
        out = _ctx().with_active_filters(
            [
                {
                    "index": "ai-abc-0",
                    "value": True,
                    "source": "ai_prompt",
                    "filter_expr": "pl.col('island') == 'Biscoe'",
                    "metadata": {"filter_expr": "pl.col('island') == 'Biscoe'"},
                }
            ]
        )
        assert len(out.filters) == 3
        extra = out.filters[-1]
        assert extra.component_type == "filter_expr"
        assert extra.value == "pl.col('island') == 'Biscoe'"
        assert "filter_expr" in out.filters_block()

    def test_original_context_is_not_mutated(self):
        ctx = _ctx()
        ctx.with_active_filters(
            [{"index": "w-species", "value": ["Adelie"], "column_name": "species"}]
        )
        assert ctx.filters[0].value is None


# ---------------------------------------------------------------------------
# Project inventory (hand-built, no Mongo)
# ---------------------------------------------------------------------------

from depictio.api.v1.endpoints.ai_endpoints.context import (  # noqa: E402
    MAX_INVENTORY_LINE_CHARS,
    InventoryEntry,
    ProjectInventory,
    dc_has_coordinates,
)


def _entry(
    tag: str,
    dc_type: str,
    columns: list[tuple[str, str]] | None = None,
    *,
    on_dashboard: bool = False,
    description: str | None = None,
    coordinate_columns: tuple[str, str] | None = None,
) -> InventoryEntry:
    return InventoryEntry(
        data_collection_id=f"id-{tag}",
        data_collection_tag=tag,
        workflow_id="wf-id",
        workflow_tag="wf",
        dc_type=dc_type,
        description=description,
        columns=columns or [],
        on_dashboard=on_dashboard,
        coordinate_columns=coordinate_columns,
    )


def _inventory() -> ProjectInventory:
    return ProjectInventory(
        dashboard_id="d1",
        project_id="p1",
        project_name="Sites",
        entries=[
            _entry(
                "sites",
                "table",
                [("site", "object"), ("latitude", "float64"), ("longitude", "float64")],
                on_dashboard=True,
                description="Sampling sites",
            ),
            _entry("counts", "table", [("site", "object"), ("reads", "int64")]),
            _entry("qc", "multiqc"),
            _entry("micrographs", "image", [("image_path", "object"), ("cell_id", "object")]),
            _entry("tree", "phylogeny"),
            _entry("genome", "jbrowse2"),
        ],
    )


class TestProjectInventoryCandidates:
    def test_tabular_types_take_table_like_collections_in_order(self):
        inv = _inventory()
        for component_type in ("figure", "card", "interactive", "table"):
            assert [e.data_collection_tag for e in inv.candidates_for(component_type)] == [
                "sites",
                "counts",
                "micrographs",
            ]

    def test_advanced_viz_adds_phylogeny(self):
        tags = [e.data_collection_tag for e in _inventory().candidates_for("advanced_viz")]
        assert tags == ["sites", "counts", "micrographs", "tree"]

    def test_multiqc_and_image_are_exact(self):
        inv = _inventory()
        assert [e.data_collection_tag for e in inv.candidates_for("multiqc")] == ["qc"]
        assert [e.data_collection_tag for e in inv.candidates_for("image")] == ["micrographs"]

    def test_map_needs_coordinates(self):
        assert [e.data_collection_tag for e in _inventory().candidates_for("map")] == ["sites"]

    def test_text_and_unknown_types_have_no_candidates(self):
        inv = _inventory()
        assert inv.candidates_for("text") == []
        assert inv.candidates_for("gizmo") == []

    def test_jbrowse_backs_nothing(self):
        inv = _inventory()
        for component_type in ("figure", "card", "table", "map", "image", "multiqc"):
            assert all(e.dc_type != "jbrowse2" for e in inv.candidates_for(component_type))


class TestDcHasCoordinates:
    def test_explicit_hints_win(self):
        assert dc_has_coordinates(_entry("x", "table", coordinate_columns=("a", "b")))

    def test_name_heuristic_needs_both_numeric_axes(self):
        assert dc_has_coordinates(_entry("x", "table", [("lat", "float64"), ("lon", "float64")]))
        assert dc_has_coordinates(
            _entry("x", "table", [("site_lat", "float64"), ("site_lng", "int64")])
        )
        assert not dc_has_coordinates(_entry("x", "table", [("latitude", "float64")]))
        assert not dc_has_coordinates(_entry("x", "table", [("lat", "object"), ("lon", "float64")]))

    def test_substrings_do_not_match(self):
        assert not dc_has_coordinates(
            _entry("x", "table", [("platform", "float64"), ("longevity", "float64")])
        )


class TestProjectInventoryTextBlock:
    def test_lines_carry_tag_type_marker_description_and_columns(self):
        block = _inventory().text_block()
        lines = block.splitlines()
        assert lines[0] == (
            "- sites [table, on dashboard]: Sampling sites. "
            "columns: site:object, latitude:float64, longitude:float64"
        )
        assert lines[1] == "- counts [table]. columns: site:object, reads:int64"
        assert lines[2] == "- qc [multiqc]"
        assert "(+" not in block

    def test_long_column_lists_are_truncated_with_a_count(self):
        columns = [(f"a_rather_long_measurement_name_{i:02d}", "float64") for i in range(40)]
        line = _entry("wide", "table", columns).to_prompt_line()
        assert len(line) <= MAX_INVENTORY_LINE_CHARS
        assert "a_rather_long_measurement_name_00:float64" in line
        assert line.endswith(" more)")
        shown = line.count(":float64")
        assert f"(+{40 - shown} more)" in line

    def test_long_descriptions_are_cut(self):
        line = _entry("x", "table", description="word " * 100).to_prompt_line()
        assert line.endswith("...")
        assert len(line) < 160

    def test_dropped_count_is_announced(self):
        inv = _inventory()
        inv.dropped = 4
        assert inv.text_block().splitlines()[-1] == "(+4 more collections not listed)"

    def test_empty_inventory(self):
        assert "no data collections" in ProjectInventory("d", "p", None).text_block()


class TestProjectInventoryLookup:
    def test_tag_lookup_is_exact_then_case_insensitive_then_id(self):
        inv = _inventory()
        assert inv.entry_for_tag("counts").data_collection_tag == "counts"
        assert inv.entry_for_tag("COUNTS").data_collection_tag == "counts"
        assert inv.entry_for_tag("id-qc").data_collection_tag == "qc"
        assert inv.entry_for_tag("nope") is None
        assert inv.entry_for_tag(None) is None
        assert inv.entry_for_id("id-tree").data_collection_tag == "tree"
