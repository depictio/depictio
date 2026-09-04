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


# ---------------------------------------------------------------------------
# Project data context (whole-dashboard generation)
# ---------------------------------------------------------------------------

import pytest  # noqa: E402
from bson import ObjectId  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from depictio.api.v1.endpoints.ai_endpoints import context as context_module  # noqa: E402
from depictio.api.v1.endpoints.ai_endpoints.context import (  # noqa: E402
    MAX_VIZ_SUGGESTIONS_PER_DC,
    ColumnSummary,
    DataContext,
    ProjectDataContext,
    build_project_data_context,
    offer_line,
    offer_use_id,
    viz_suggestion_line,
    viz_suggestions_for,
)

DE_COLUMNS = {
    "gene_id": "String",
    "log2FoldChange": "Float64",
    "padj": "Float64",
    "symbol": "String",
}
IRIS_COLUMNS = {"sepal_length": "Float64", "variety": "String"}
# The penguins `physical_features` collection, the schema that produced a
# `rarefaction` advanced viz nobody could render (see `viz_suggestions_for`).
PENGUIN_COLUMNS = {
    "individual_id": "String",
    "bill_length_mm": "Float64",
    "bill_depth_mm": "Float64",
    "body_mass_g": "Float64",
}


def _columns(spec: dict[str, str]) -> list[ColumnSummary]:
    return [ColumnSummary(name=n, dtype=d, null_pct=0.0, nunique=5) for n, d in spec.items()]


def _dc(tag: str, spec: dict[str, str], *, rows: int = 100, description: str | None = None):
    return DataContext(
        data_collection_id=tag.ljust(24, "0"),
        workflow_id="7" * 24,
        project_name="P",
        project_description=None,
        dc_name=tag,
        dc_description=description,
        columns=_columns(spec),
        sample_rows=[{"a": 1}],
        row_count=rows,
        workflow_tag="wf",
        data_collection_tag=tag,
        dc_type="table",
    )


class TestVizSuggestionsFor:
    def test_recommends_bindable_kinds_with_role_candidates(self):
        out = viz_suggestions_for(_columns(DE_COLUMNS))
        assert 0 < len(out) <= MAX_VIZ_SUGGESTIONS_PER_DC
        by_kind = {s["viz_kind"]: s for s in out}
        assert "volcano" in by_kind
        volcano = by_kind["volcano"]
        assert volcano["score"] >= 0.8
        assert volcano["role_candidates"]["feature_id"][0] == "gene_id"
        assert volcano["role_candidates"]["effect_size"][0] == "log2FoldChange"
        assert volcano["role_candidates"]["significance"][0] == "padj"

    def test_nothing_recommended_means_empty(self):
        # Nothing reaches the recommended bar on iris (see the fallback test in
        # test_prompts.py), and the generator must not plan advanced_viz then.
        assert viz_suggestions_for(_columns(IRIS_COLUMNS)) == []
        assert viz_suggestions_for([]) == []

    def test_limit_is_honoured(self):
        assert len(viz_suggestions_for(_columns(DE_COLUMNS), limit=1)) == 1

    def test_refuses_a_kind_whose_required_role_is_a_dtype_match_only(self):
        # The ranker ranks rarefaction first on penguins and puts it over the
        # RECOMMENDED_SCORE bar, but only via the optional-role nudge: `metric`
        # has no name signal at all and lands on the same float column as
        # `depth`, which is what the generator would then have bound and saved.
        from depictio.models.components.advanced_viz.schemas import suggest_viz_kinds

        top = suggest_viz_kinds(PENGUIN_COLUMNS, dc_type="table")[0]
        assert top.viz_kind == "rarefaction"
        assert top.score >= 0.8
        assert top.unmet_roles == []
        assert top.weak_roles == ["metric"]

        assert viz_suggestions_for(_columns(PENGUIN_COLUMNS)) == []

    def test_a_fully_named_kind_survives_while_a_thin_one_does_not(self):
        kinds = {s["viz_kind"] for s in viz_suggestions_for(_columns(DE_COLUMNS))}
        # Every required role of volcano matches a column by name.
        assert "volcano" in kinds
        # `ma` scores 0.88 on the same schema, but `avg_log_intensity` is
        # satisfied by dtype alone, so it is no longer offered to the planner.
        assert "ma" not in kinds


class TestPromptLines:
    def test_viz_suggestion_line(self):
        line = viz_suggestion_line(
            {
                "viz_kind": "volcano",
                "score": 0.925,
                "role_candidates": {"feature_id": ["gene_id", "symbol"], "empty": []},
            }
        )
        assert line == "volcano (fit 0.93): feature_id -> gene_id, symbol"

    def test_offer_line_and_use_id(self):
        offer = {
            "tool": "nf-core-rnaseq",
            "render_id": "deseq2-0",
            "title": "Volcano plot",
            "component_type": "advanced_viz",
            "dc_tag": "deseq2",
            "description": "Effect  size vs\nadjusted p-value",
        }
        assert offer_use_id(offer) == "nf-core-rnaseq/deseq2-0"
        assert offer_line(offer) == (
            'use "nf-core-rnaseq/deseq2-0" (advanced_viz: Volcano plot). '
            "Effect size vs adjusted p-value"
        )

    def test_offer_line_truncates_long_descriptions(self):
        line = offer_line({"tool": "t", "render_id": "r", "description": "word " * 60})
        assert line.endswith("...")
        assert len(line) < 140


class TestProjectBlock:
    def _ctx(self) -> ProjectDataContext:
        deseq2 = _dc("deseq2", DE_COLUMNS, rows=900, description="DE results")
        deseq2.viz_suggestions = [
            {"viz_kind": "volcano", "score": 1.0, "role_candidates": {"feature_id": ["gene_id"]}}
        ]
        deseq2.catalog_offers = [
            {
                "tool": "nf-core-rnaseq",
                "render_id": "deseq2-0",
                "title": "Volcano plot",
                "component_type": "advanced_viz",
            }
        ]
        return ProjectDataContext(
            project_id="p" * 24,
            project_name="RNA project",
            project_description="Bulk  RNA-seq\nDE",
            collections=[deseq2, _dc("samples", IRIS_COLUMNS, rows=12)],
            joins=[
                context_module.JoinSummary(left_dc="deseq2", right_dc="samples", on_columns=["id"])
            ],
        )

    def test_lists_project_collections_candidates_and_offers(self):
        block = self._ctx().project_block()
        lines = block.splitlines()
        assert lines[0] == "PROJECT: RNA project"
        assert lines[1] == "PROJECT DESCRIPTION: Bulk RNA-seq DE"
        assert 'dc["deseq2"]: 900 rows. DE results' in lines
        assert 'dc["samples"]: 12 rows' in lines
        assert "- gene_id (String, null=0%, distinct=5)" in lines
        assert "  sample: 1. {'a': 1}" in lines
        assert "  advanced_viz candidate: volcano (fit 1.00): feature_id -> gene_id" in lines
        assert (
            '  catalog offer: use "nf-core-rnaseq/deseq2-0" (advanced_viz: Volcano plot)' in lines
        )
        assert block.index("DATA COLLECTIONS:") < block.index("DECLARED JOINS:")
        assert "- deseq2 inner join samples on [id]" in lines

    def test_empty_project(self):
        block = ProjectDataContext(project_id="p", project_name="", collections=[]).project_block()
        assert "PROJECT: (unnamed)" in block
        assert "(no data collections)" in block
        assert "(no declared joins)" in block
        assert "PROJECT DESCRIPTION" not in block

    def test_drops_samples_then_trailing_collections_under_the_budget(self, monkeypatch):
        ctx = self._ctx()
        full = ctx.project_block()
        without_samples = full.replace("  sample: 1. {'a': 1}\n", "")
        assert len(without_samples) < len(full)

        # Just under the full size: samples go, collections stay.
        monkeypatch.setattr(context_module.settings.ai, "max_context_chars", len(full) - 1)
        warnings: list[str] = []
        block = ctx.project_block(warnings)
        assert "sample:" not in block
        assert 'dc["samples"]' in block
        assert warnings == [
            "Sample rows were omitted from the context to stay within the size budget."
        ]

        # Far too small: the trailing collection goes too, the first one stays.
        monkeypatch.setattr(context_module.settings.ai, "max_context_chars", 50)
        warnings = []
        block = ctx.project_block(warnings)
        assert 'dc["deseq2"]' in block
        assert 'dc["samples"]' not in block
        assert len(warnings) == 2
        assert "'samples' was left out of the context" in warnings[1]

    def test_without_a_warnings_list_cuts_are_silent_but_applied(self, monkeypatch):
        monkeypatch.setattr(context_module.settings.ai, "max_context_chars", 50)
        assert 'dc["samples"]' not in self._ctx().project_block()


# ---------------------------------------------------------------------------
# build_project_data_context: project doc -> table collections (Mongo faked)
# ---------------------------------------------------------------------------

PROJECT_OID = ObjectId()
DC_SITES, DC_COUNTS, DC_DE, DC_QC = ObjectId(), ObjectId(), ObjectId(), ObjectId()
TAG_BY_ID = {str(DC_SITES): "sites", str(DC_COUNTS): "counts", str(DC_DE): "de"}
COLUMNS_BY_TAG = {
    "sites": {"site": "String", "latitude": "Float64", "longitude": "Float64"},
    "counts": {"site": "String", "reads": "Int64"},
    "de": DE_COLUMNS,
}


def _project_doc() -> dict:
    return {
        "_id": PROJECT_OID,
        "name": "Sites",
        "description": "Sampling sites and counts",
        "joins": [
            {"left_dc": "sites", "right_dc": "counts", "on_columns": ["site"], "how": "left"},
            {"left_dc": "sites", "right_dc": "elsewhere", "on_columns": ["site"]},
        ],
        "workflows": [
            {
                "_id": ObjectId(),
                "workflow_tag": "wf",
                "data_collections": [
                    {"_id": DC_SITES, "data_collection_tag": "sites", "config": {"type": "table"}},
                    {"_id": DC_QC, "data_collection_tag": "qc", "config": {"type": "multiqc"}},
                    {
                        "_id": DC_COUNTS,
                        "data_collection_tag": "counts",
                        "config": {"type": "Table"},
                    },
                    {"_id": DC_DE, "data_collection_tag": "de", "config": {"type": "table"}},
                    "not-a-dict",
                ],
            }
        ],
    }


class _FakeProjects:
    def __init__(self, doc: dict | None):
        self.doc = doc
        self.queries: list[dict] = []

    def find_one(self, query, projection=None):
        self.queries.append(query)
        if self.doc is not None and query.get("_id") == self.doc["_id"]:
            return self.doc
        return None


@pytest.fixture()
def fake_project(monkeypatch):
    """Patch the project lookup and the per-DC loader; returns the set of broken DC ids."""
    broken: set[str] = set()
    monkeypatch.setattr(context_module, "projects_collection", _FakeProjects(_project_doc()))

    async def fake_build_data_context(dc_id, user, **kwargs):
        if dc_id in broken:
            raise RuntimeError("delta table missing")
        tag = TAG_BY_ID[dc_id]
        ctx = _dc(tag, COLUMNS_BY_TAG[tag])
        ctx.data_collection_id = dc_id
        return ctx

    monkeypatch.setattr(context_module, "build_data_context", fake_build_data_context)
    return broken


class TestBuildProjectDataContext:
    @pytest.mark.asyncio
    async def test_table_collections_only_in_project_order(self, fake_project):
        ctx, warnings = await build_project_data_context(str(PROJECT_OID), None)
        assert warnings == []
        assert ctx.tags() == ["sites", "counts", "de"]
        assert ctx.project_id == str(PROJECT_OID)
        assert ctx.project_name == "Sites"
        assert ctx.project_description == "Sampling sites and counts"
        assert ctx.dashboard_id == ""
        # Only joins with both sides in scope survive.
        assert [(j.left_dc, j.right_dc, j.how) for j in ctx.joins] == [("sites", "counts", "left")]

    @pytest.mark.asyncio
    async def test_fills_viz_suggestions_per_collection(self, fake_project):
        ctx, _ = await build_project_data_context(str(PROJECT_OID), None)
        by_tag = {c.data_collection_tag: c for c in ctx.collections}
        assert "volcano" in {s["viz_kind"] for s in by_tag["de"].viz_suggestions}
        # Nothing reaches the recommended bar on a site/latitude/longitude table.
        assert by_tag["sites"].viz_suggestions == []
        # Catalog offers are the generator's job, not this loader's.
        assert all(c.catalog_offers == [] for c in ctx.collections)

    @pytest.mark.asyncio
    async def test_dc_ids_narrow_in_requested_order_and_report_the_rest(self, fake_project):
        ctx, warnings = await build_project_data_context(
            str(PROJECT_OID), None, [str(DC_DE), str(DC_QC), str(DC_SITES), str(DC_DE)]
        )
        assert ctx.tags() == ["de", "sites"]
        assert len(warnings) == 1
        assert "1 requested data collection(s) are not table collections" in warnings[0]

    @pytest.mark.asyncio
    async def test_caps_at_max_collections_with_a_warning(self, fake_project):
        ctx, warnings = await build_project_data_context(str(PROJECT_OID), None, max_collections=2)
        assert ctx.tags() == ["sites", "counts"]
        assert warnings == [
            "1 of 3 data collections were left out of the generation context (limit 2)."
        ]

    @pytest.mark.asyncio
    async def test_unreadable_collection_is_skipped_not_fatal(self, fake_project):
        fake_project.add(str(DC_COUNTS))
        ctx, warnings = await build_project_data_context(str(PROJECT_OID), None)
        assert ctx.tags() == ["sites", "de"]
        assert warnings == [f"Data collection {DC_COUNTS} could not be read and was skipped."]
        # The join needs both sides, and counts is gone.
        assert ctx.joins == []

    @pytest.mark.asyncio
    async def test_bad_project_id_is_400(self, fake_project):
        with pytest.raises(HTTPException) as exc:
            await build_project_data_context("not-an-oid", None)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_project_is_404(self, fake_project):
        with pytest.raises(HTTPException) as exc:
            await build_project_data_context(str(ObjectId()), None)
        assert exc.value.status_code == 404
