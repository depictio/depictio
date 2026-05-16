"""Schema-level tests for the cross-tab Global Filters & Journeys feature.

These exercise the new Pydantic models in isolation — they don't touch the
``user_dashboard_state`` MongoDB collection or the API routes. End-to-end
coverage of the endpoints lives in the existing
``tests/api/v1/endpoints/dashboards_endpoints`` tree (added separately) and
requires a mongomock fixture.
"""

from __future__ import annotations

import importlib.util

import pytest
from pydantic import ValidationError

from depictio.models.models.base import PyObjectId
from depictio.models.models.dashboards import (
    FunnelStep,
    GlobalFilterDef,
    GlobalFilterLink,
    Journey,
)
from depictio.models.models.user_dashboard_state import UserDashboardState

# Some classes below import from `depictio.api.v1.endpoints.*`, which pulls in
# fastapi. The CLI quality job installs only model + cli deps, so skip those
# class blocks when fastapi isn't importable.
requires_fastapi = pytest.mark.skipif(
    importlib.util.find_spec("fastapi") is None,
    reason="requires fastapi (API endpoint tests)",
)


def _make_filter(**overrides) -> GlobalFilterDef:
    base = dict(
        id="gf_abc",
        label="Sample ID",
        source_component_index="comp-uuid-1",
        source_tab_id=PyObjectId(),
        interactive_component_type="MultiSelect",
        column_type="object",
        default_state=None,
        links=[
            GlobalFilterLink(
                wf_id="wf-1",
                dc_id="dc-1",
                column_name="sample_id",
            )
        ],
    )
    base.update(overrides)
    return GlobalFilterDef(**base)


class TestGlobalFilterLink:
    def test_minimal_round_trip(self):
        link = GlobalFilterLink(wf_id="wf1", dc_id="dc1", column_name="x")
        dumped = link.model_dump()
        assert dumped == {"wf_id": "wf1", "dc_id": "dc1", "column_name": "x"}
        assert GlobalFilterLink(**dumped) == link

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            GlobalFilterLink(wf_id="wf1", dc_id="dc1", column_name="x", bogus="nope")


class TestGlobalFilterDef:
    def test_minimal_construction(self):
        f = _make_filter()
        assert f.id == "gf_abc"
        assert f.label == "Sample ID"
        assert len(f.links) == 1
        assert f.links[0].column_name == "sample_id"

    def test_source_tab_id_serialized_as_string(self):
        f = _make_filter()
        dumped = f.model_dump(mode="json")
        assert isinstance(dumped["source_tab_id"], str)
        assert len(dumped["source_tab_id"]) == 24

    def test_round_trip_through_model_dump(self):
        original = _make_filter(
            links=[
                GlobalFilterLink(wf_id="wf1", dc_id="dc1", column_name="sample"),
                GlobalFilterLink(wf_id="wf2", dc_id="dc2", column_name="sample_id"),
            ]
        )
        dumped = original.model_dump(mode="json")
        rebuilt = GlobalFilterDef(**dumped)
        assert rebuilt.id == original.id
        assert len(rebuilt.links) == 2
        assert {link.dc_id for link in rebuilt.links} == {"dc1", "dc2"}

    def test_multiple_links_for_cross_dc_propagation(self):
        f = _make_filter(
            links=[
                GlobalFilterLink(wf_id="wf1", dc_id="dc-genes", column_name="gene_id"),
                GlobalFilterLink(wf_id="wf1", dc_id="dc-locations", column_name="gene"),
            ]
        )
        assert len(f.links) == 2
        assert f.links[0].column_name != f.links[1].column_name

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            _make_filter(unrelated="value")


class TestFunnelStep:
    def test_construct_global_step(self):
        step = FunnelStep(
            id="step_1",
            scope="global",
            tab_id=PyObjectId(),
            global_filter_id="gf_habitat",
            order_within_tab=0,
        )
        assert step.scope == "global"
        assert step.global_filter_id == "gf_habitat"
        assert step.component_index is None
        assert step.label is None

    def test_construct_local_step(self):
        step = FunnelStep(
            id="step_2",
            scope="local",
            tab_id=PyObjectId(),
            component_index="comp-uuid-1",
            order_within_tab=3,
            label="Sample QC",
        )
        assert step.scope == "local"
        assert step.component_index == "comp-uuid-1"
        assert step.label == "Sample QC"

    def test_serialize_tab_id_as_str(self):
        step = FunnelStep(
            id="s",
            scope="global",
            tab_id=PyObjectId(),
            global_filter_id="gf_x",
        )
        dumped = step.model_dump(mode="json")
        assert isinstance(dumped["tab_id"], str)
        assert len(dumped["tab_id"]) == 24

    def test_global_step_requires_global_filter_id(self):
        with pytest.raises(ValidationError):
            FunnelStep(id="s", scope="global", tab_id=PyObjectId())

    def test_local_step_requires_component_index(self):
        with pytest.raises(ValidationError):
            FunnelStep(id="s", scope="local", tab_id=PyObjectId())

    def test_scope_must_be_global_or_local(self):
        with pytest.raises(ValidationError):
            FunnelStep(
                id="s",
                scope="cosmic",
                tab_id=PyObjectId(),
                global_filter_id="gf_x",
            )

    def test_round_trip(self):
        original = FunnelStep(
            id="s",
            scope="local",
            tab_id=PyObjectId(),
            component_index="c1",
            order_within_tab=5,
            label="Filter X",
        )
        dumped = original.model_dump(mode="json")
        rebuilt = FunnelStep(**dumped)
        assert rebuilt.id == original.id
        assert rebuilt.scope == original.scope
        assert rebuilt.component_index == "c1"
        assert rebuilt.order_within_tab == 5
        assert rebuilt.label == "Filter X"

    def test_source_dc_id_round_trips(self):
        original = FunnelStep(
            id="s",
            scope="local",
            tab_id=PyObjectId(),
            component_index="c1",
            source_dc_id="dc-abc123",
        )
        dumped = original.model_dump(mode="json")
        assert dumped["source_dc_id"] == "dc-abc123"
        rebuilt = FunnelStep(**dumped)
        assert rebuilt.source_dc_id == "dc-abc123"

    def test_source_dc_id_defaults_none_for_legacy_payloads(self):
        # A persisted step from before source_dc_id existed must still load.
        step = FunnelStep(
            id="s",
            scope="local",
            tab_id=PyObjectId(),
            component_index="c1",
        )
        assert step.source_dc_id is None


class TestJourney:
    def test_construct_and_serialize(self):
        tab_a = PyObjectId()
        tab_b = PyObjectId()
        journey = Journey(
            id="journey_1",
            name="Genes → Locations",
            description="From gene-level filter to spatial footprint.",
            icon="tabler:route",
            color="blue",
            steps=[
                FunnelStep(
                    id="s1",
                    scope="global",
                    tab_id=tab_a,
                    global_filter_id="gf_gene",
                    order_within_tab=0,
                ),
                FunnelStep(
                    id="s2",
                    scope="local",
                    tab_id=tab_b,
                    component_index="comp-1",
                    order_within_tab=0,
                ),
            ],
            pinned=True,
            is_default=True,
        )
        dumped = journey.model_dump(mode="json")
        assert dumped["name"] == "Genes → Locations"
        assert dumped["pinned"] is True
        assert dumped["is_default"] is True
        assert len(dumped["steps"]) == 2
        assert isinstance(dumped["steps"][0]["tab_id"], str)

    def test_defaults(self):
        journey = Journey(id="j", name="bare")
        assert journey.steps == []
        assert journey.pinned is False
        assert journey.is_default is False
        assert journey.icon is None
        assert journey.color is None

    def test_dedupes_steps_with_identical_global_ref(self):
        """Two steps targeting the same global filter id collapse to one
        — the funnel can't apply the same filter twice meaningfully."""
        tab = PyObjectId()
        journey = Journey(
            id="j",
            name="dup",
            steps=[
                FunnelStep(
                    id="s1",
                    scope="global",
                    tab_id=tab,
                    global_filter_id="gf_x",
                    order_within_tab=0,
                ),
                FunnelStep(
                    id="s2",
                    scope="global",
                    tab_id=tab,
                    global_filter_id="gf_x",
                    order_within_tab=1,
                ),
            ],
        )
        assert len(journey.steps) == 1
        assert journey.steps[0].id == "s1"

    def test_dedupes_steps_with_identical_local_ref(self):
        tab = PyObjectId()
        journey = Journey(
            id="j",
            name="dup",
            steps=[
                FunnelStep(
                    id="s1",
                    scope="local",
                    tab_id=tab,
                    component_index="c-1",
                    order_within_tab=0,
                ),
                FunnelStep(
                    id="s2",
                    scope="local",
                    tab_id=tab,
                    component_index="c-1",
                    order_within_tab=1,
                ),
            ],
        )
        assert len(journey.steps) == 1

    def test_dedupes_steps_with_duplicate_id(self):
        tab = PyObjectId()
        journey = Journey(
            id="j",
            name="dup",
            steps=[
                FunnelStep(
                    id="s1",
                    scope="global",
                    tab_id=tab,
                    global_filter_id="gf_a",
                ),
                FunnelStep(
                    id="s1",
                    scope="global",
                    tab_id=tab,
                    global_filter_id="gf_b",
                ),
            ],
        )
        assert len(journey.steps) == 1

    def test_global_plus_local_coexist(self):
        """Same tab can carry a global step + a local step pointing at
        different filters — no dedup."""
        tab = PyObjectId()
        journey = Journey(
            id="j",
            name="mix",
            steps=[
                FunnelStep(
                    id="s1",
                    scope="global",
                    tab_id=tab,
                    global_filter_id="gf_a",
                ),
                FunnelStep(
                    id="s2",
                    scope="local",
                    tab_id=tab,
                    component_index="c-1",
                ),
            ],
        )
        assert len(journey.steps) == 2


class TestUserDashboardState:
    def test_default_empty_values(self):
        state = UserDashboardState(
            user_id=PyObjectId(),
            parent_dashboard_id=PyObjectId(),
        )
        assert state.global_filter_values == {}
        assert state.last_active_journey_id is None
        assert state.last_active_tab_id is None
        # Snapshot bookkeeping fields are dropped — instances should not
        # surface them as attributes.
        assert not hasattr(state, "last_active_journey_stop_id")
        assert not hasattr(state, "journey_stops")

    def test_round_trip_values(self):
        state = UserDashboardState(
            user_id=PyObjectId(),
            parent_dashboard_id=PyObjectId(),
            global_filter_values={"gf_a": ["x", "y"], "gf_b": [0, 100]},
            last_active_journey_id="journey_1",
        )
        dumped = state.model_dump(mode="json")
        assert isinstance(dumped["user_id"], str)
        assert isinstance(dumped["parent_dashboard_id"], str)
        assert dumped["global_filter_values"] == {"gf_a": ["x", "y"], "gf_b": [0, 100]}
        assert dumped["last_active_journey_id"] == "journey_1"
        assert "last_active_journey_stop_id" not in dumped
        assert "journey_stops" not in dumped


class TestDashboardDataIntegration:
    """Make sure adding the new fields to DashboardData didn't break defaults
    or older-document loading."""

    def test_dashboard_data_defaults_new_fields_to_empty(self):
        from depictio.models.models.dashboards import DashboardData
        from depictio.models.models.users import Permission

        dash = DashboardData(
            dashboard_id=PyObjectId(),
            project_id=PyObjectId(),
            title="t",
            permissions=Permission(),
        )
        assert dash.global_filters == []
        assert dash.journeys == []

    def test_dashboard_data_round_trip(self):
        from depictio.models.models.dashboards import DashboardData
        from depictio.models.models.users import Permission

        tab = PyObjectId()
        dash = DashboardData(
            dashboard_id=PyObjectId(),
            project_id=PyObjectId(),
            title="t",
            permissions=Permission(),
            global_filters=[_make_filter()],
            journeys=[
                Journey(
                    id="j1",
                    name="journey 1",
                    steps=[
                        FunnelStep(
                            id="s1",
                            scope="global",
                            tab_id=tab,
                            global_filter_id="gf_abc",
                        )
                    ],
                )
            ],
        )
        dumped = dash.model_dump(mode="json")
        assert len(dumped["global_filters"]) == 1
        assert dumped["global_filters"][0]["id"] == "gf_abc"
        assert len(dumped["journeys"]) == 1
        assert dumped["journeys"][0]["name"] == "journey 1"
        assert len(dumped["journeys"][0]["steps"]) == 1
        assert dumped["journeys"][0]["steps"][0]["global_filter_id"] == "gf_abc"


@requires_fastapi
class TestGlobalFiltersEndpointNormalizers:
    """Regression tests for the `_id`→`id` rename helpers in
    ``depictio.api.v1.endpoints.dashboards_endpoints.global_filters``.

    These cover the case where ``MongoModel.mongo()`` recursively renamed
    journey/step/filter ``id`` keys to ``_id`` on persist, and our read
    paths need to flip them back so the Pydantic models (which expect
    ``id``) don't reject the payload.
    """

    def test_rename_id_key_flips_top_level(self):
        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import (
            _rename_id_key,
        )

        out = _rename_id_key({"_id": "gf_x", "label": "X"})
        assert out == {"id": "gf_x", "label": "X"}

    def test_rename_id_key_idempotent_when_id_present(self):
        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import (
            _rename_id_key,
        )

        original = {"id": "gf_x", "label": "X"}
        assert _rename_id_key(original) == original

    def test_normalize_journey_renames_steps(self):
        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import (
            _normalize_journey,
        )

        legacy = {
            "_id": "journey_a",
            "name": "Funnel A",
            "steps": [
                {"_id": "s1", "scope": "global", "global_filter_id": "gf_x"},
                {"_id": "s2", "scope": "local", "tab_id": "t1", "component_index": "c1"},
            ],
        }
        out = _normalize_journey(legacy)
        assert out["id"] == "journey_a"
        assert "_id" not in out
        assert [s["id"] for s in out["steps"]] == ["s1", "s2"]
        assert all("_id" not in s for s in out["steps"])


@requires_fastapi
class TestMeasureDf:
    """Unit tests for the ``_measure_df`` helper that powers the metric
    toggle in ``compute_funnel`` (``rows`` vs ``nunique``)."""

    @pytest.fixture
    def df(self):
        import polars as pl

        return pl.DataFrame(
            {
                "sample_id": ["s1", "s1", "s2", "s3"],
                "habitat": ["soil", "soil", "water", "soil"],
            }
        )

    def test_rows_returns_height(self, df):
        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import _measure_df

        assert _measure_df(df, "rows", None) == 4
        # metric_column is ignored when metric=rows
        assert _measure_df(df, "rows", "habitat") == 4

    def test_nunique_returns_distinct_count(self, df):
        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import _measure_df

        assert _measure_df(df, "nunique", "sample_id") == 3
        assert _measure_df(df, "nunique", "habitat") == 2

    def test_nunique_missing_column_returns_zero(self, df):
        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import _measure_df

        assert _measure_df(df, "nunique", "no_such_column") == 0

    def test_nunique_without_column_returns_zero(self, df):
        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import _measure_df

        assert _measure_df(df, "nunique", None) == 0


@requires_fastapi
class TestFunnelRequestEnvelope:
    """Validation of the ``FunnelRequest`` envelope — new ``metric`` and
    ``metric_column`` fields with safe defaults."""

    def test_defaults_to_rows_metric(self):
        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import FunnelRequest

        req = FunnelRequest()
        assert req.metric == "rows"
        assert req.metric_column is None
        assert req.steps == []
        assert req.target_dcs == []

    def test_accepts_nunique_with_column(self):
        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import FunnelRequest

        req = FunnelRequest(metric="nunique", metric_column="sample_id")
        assert req.metric == "nunique"
        assert req.metric_column == "sample_id"

    def test_rejects_unknown_metric(self):
        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import FunnelRequest

        with pytest.raises(ValidationError):
            FunnelRequest(metric="median")


@requires_fastapi
class TestComputeFunnelIntegration:
    """End-to-end test of ``compute_funnel`` with mocked DB + delta-table.

    Verifies the per-step ``applicable`` matrix marks no-op carry-forwards
    (step doesn't link to the target DC) as ``False``, and that the
    ``nunique`` metric is honored.
    """

    def _patch_environment(
        self,
        monkeypatch,
        df_by_dc: dict,
        parent_doc: dict,
        project_links: list | None = None,
    ):
        """Stub out everything ``compute_funnel`` reaches out for so we
        can exercise its branching logic in isolation."""

        from depictio.api.v1 import deltatables_utils
        from depictio.api.v1.endpoints.dashboards_endpoints import global_filters as gf_mod

        # Skip permission check; treat the caller as a viewer.
        monkeypatch.setattr(gf_mod, "_require_viewer", lambda parent, user: None)
        # Always return the supplied parent doc.
        monkeypatch.setattr(gf_mod, "_load_parent_or_404", lambda pid: parent_doc)
        # No child tabs — local-step coverage handled by global links here.
        monkeypatch.setattr(gf_mod, "_build_tab_dc_index", lambda pid: {})
        # Stub the project-links loader; default to no links so legacy tests
        # don't accidentally pick up cross-DC reach.
        monkeypatch.setattr(gf_mod, "_load_project_links", lambda parent: list(project_links or []))

        # Load returns the per-DC pre-built DataFrame.
        def fake_load(workflow_id, data_collection_id, metadata=None):
            return df_by_dc[str(data_collection_id)]

        monkeypatch.setattr(deltatables_utils, "load_deltatable_lite", fake_load)

        # apply_runtime_filters: minimal evaluator for `==` and `in` on
        # categorical columns — enough to cover the test cases below.
        def fake_apply(df, filters):
            import polars as pl

            out = df
            for f in filters:
                col = f["column_name"]
                if col not in out.columns:
                    continue
                value = f["value"]
                if isinstance(value, list):
                    out = out.filter(pl.col(col).is_in(value))
                else:
                    out = out.filter(pl.col(col) == value)
            return out

        monkeypatch.setattr(deltatables_utils, "apply_runtime_filters", fake_apply)

    @pytest.fixture
    def ids(self):
        """Stable hex ids — ``compute_funnel`` wraps wf/dc ids in ``ObjectId()``."""
        return {
            "wf": str(PyObjectId()),
            "dc_linked": str(PyObjectId()),
            "dc_unlinked": str(PyObjectId()),
            "dc1": str(PyObjectId()),
        }

    def test_applicable_matrix_marks_carry_forward_false(self, monkeypatch, ids):
        """A global step that doesn't link to a target DC should yield a
        carry-forward count AND ``applicable[i] == False``."""
        import asyncio

        import polars as pl

        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import (
            FunnelRequest,
            FunnelStepInput,
            FunnelTargetDC,
            compute_funnel,
        )

        # Two DCs, one filter linked only to dc_linked.
        parent_doc = {
            "dashboard_id": "parent_dash",
            "global_filters": [
                {
                    "id": "gf_habitat",
                    "interactive_component_type": "MultiSelect",
                    "links": [
                        {"wf_id": ids["wf"], "dc_id": ids["dc_linked"], "column_name": "habitat"},
                    ],
                }
            ],
        }
        df_by_dc = {
            ids["dc_linked"]: pl.DataFrame(
                {"habitat": ["soil", "soil", "water"], "sample_id": ["a", "b", "c"]}
            ),
            ids["dc_unlinked"]: pl.DataFrame(
                {"habitat": ["soil"] * 10, "sample_id": [f"s{i}" for i in range(10)]}
            ),
        }
        self._patch_environment(monkeypatch, df_by_dc, parent_doc)

        body = FunnelRequest(
            steps=[
                FunnelStepInput(
                    scope="global",
                    global_filter_id="gf_habitat",
                    value=["soil"],
                )
            ],
            target_dcs=[
                FunnelTargetDC(wf_id=ids["wf"], dc_id=ids["dc_linked"]),
                FunnelTargetDC(wf_id=ids["wf"], dc_id=ids["dc_unlinked"]),
            ],
        )
        result = asyncio.run(compute_funnel("parent_dash", body, current_user=None))

        # dc_linked narrows from 3 → 2 (soil rows); step is applicable.
        assert result["counts"][ids["dc_linked"]] == [3, 2]
        assert result["applicable"][ids["dc_linked"]] == [True, True]
        # dc_unlinked carries 10 forward; the step is a no-op for it.
        assert result["counts"][ids["dc_unlinked"]] == [10, 10]
        assert result["applicable"][ids["dc_unlinked"]] == [True, False]

    def test_local_step_with_source_dc_id_targets_that_dc_only(self, monkeypatch, ids):
        """Regression for the multi-DC-tab routing bug.

        When a local step carries ``source_dc_id``, the funnel must apply
        the filter to that DC directly — even if the tab→DC fallback
        index points at a different DC for the same ``tab_id`` (which is
        how the bug manifested on the ampliseq community tab, where the
        first stored_metadata entry was the metadata DC but the Phylum
        filter component lived on the taxonomy_rel_abundance DC).
        """
        import asyncio

        import polars as pl

        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import (
            FunnelRequest,
            FunnelStepInput,
            FunnelTargetDC,
            compute_funnel,
        )

        parent_doc = {"dashboard_id": "parent_dash", "global_filters": []}
        df_by_dc = {
            ids["dc_linked"]: pl.DataFrame(
                {"phylum": ["Acido", "Acido", "Other"], "sample": ["a", "b", "c"]}
            ),
            ids["dc_unlinked"]: pl.DataFrame(
                {"phylum": ["Other"] * 5, "sample": [f"s{i}" for i in range(5)]}
            ),
        }
        self._patch_environment(monkeypatch, df_by_dc, parent_doc)
        # Tab→DC index would route this step to the WRONG dc (dc_unlinked)
        # if source_dc_id weren't honored. The test passes only if the new
        # short-circuit overrides that fallback.
        from depictio.api.v1.endpoints.dashboards_endpoints import global_filters as gf_mod

        monkeypatch.setattr(
            gf_mod,
            "_build_tab_dc_index",
            lambda pid: {"tab_phylum": (ids["wf"], ids["dc_unlinked"])},
        )

        body = FunnelRequest(
            steps=[
                FunnelStepInput(
                    scope="local",
                    value=["Acido"],
                    tab_id="tab_phylum",
                    component_index="comp_phylum",
                    column_name="phylum",
                    interactive_component_type="MultiSelect",
                    source_dc_id=ids["dc_linked"],
                )
            ],
            target_dcs=[
                FunnelTargetDC(wf_id=ids["wf"], dc_id=ids["dc_linked"]),
                FunnelTargetDC(wf_id=ids["wf"], dc_id=ids["dc_unlinked"]),
            ],
        )
        result = asyncio.run(compute_funnel("parent_dash", body, current_user=None))

        # dc_linked is the source — Phylum narrows 3 → 2 rows.
        assert result["counts"][ids["dc_linked"]] == [3, 2]
        assert result["applicable"][ids["dc_linked"]] == [True, True]
        # dc_unlinked is NOT the source — even though tab_dc_index would
        # have routed there in the legacy fallback path, source_dc_id
        # overrides and the step is marked not-applicable.
        assert result["counts"][ids["dc_unlinked"]] == [5, 5]
        assert result["applicable"][ids["dc_unlinked"]] == [True, False]

    def test_local_step_without_source_dc_id_falls_back_to_tab_index(self, monkeypatch, ids):
        """Legacy journeys persisted before source_dc_id existed must still
        work — the backend falls back to the tab→DC index."""
        import asyncio

        import polars as pl

        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import (
            FunnelRequest,
            FunnelStepInput,
            FunnelTargetDC,
            compute_funnel,
        )

        parent_doc = {"dashboard_id": "parent_dash", "global_filters": []}
        df_by_dc = {
            ids["dc_linked"]: pl.DataFrame(
                {"phylum": ["Acido", "Acido", "Other"], "sample": ["a", "b", "c"]}
            ),
        }
        self._patch_environment(monkeypatch, df_by_dc, parent_doc)
        from depictio.api.v1.endpoints.dashboards_endpoints import global_filters as gf_mod

        monkeypatch.setattr(
            gf_mod,
            "_build_tab_dc_index",
            lambda pid: {"tab_phylum": (ids["wf"], ids["dc_linked"])},
        )

        body = FunnelRequest(
            steps=[
                FunnelStepInput(
                    scope="local",
                    value=["Acido"],
                    tab_id="tab_phylum",
                    component_index="comp_phylum",
                    column_name="phylum",
                    interactive_component_type="MultiSelect",
                    # source_dc_id omitted on purpose — legacy step.
                )
            ],
            target_dcs=[FunnelTargetDC(wf_id=ids["wf"], dc_id=ids["dc_linked"])],
        )
        result = asyncio.run(compute_funnel("parent_dash", body, current_user=None))

        assert result["counts"][ids["dc_linked"]] == [3, 2]
        assert result["applicable"][ids["dc_linked"]] == [True, True]

    def test_local_step_reaches_target_via_project_link(self, monkeypatch, ids):
        """Cross-DC funnel reach (Phase 2).

        Pinning Phylum on ``dc_taxa`` should narrow ``dc_meta`` as well,
        because the project defines a ``DCLink`` from ``dc_taxa`` →
        ``dc_meta`` keyed on ``sample`` (direct resolver).
        """
        import asyncio

        import polars as pl

        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import (
            FunnelRequest,
            FunnelStepInput,
            FunnelTargetDC,
            compute_funnel,
        )
        from depictio.models.models.links import DCLink, LinkConfig

        parent_doc = {"dashboard_id": "parent_dash", "global_filters": []}
        df_by_dc = {
            ids["dc_linked"]: pl.DataFrame(  # dc_taxa: row per (sample, phylum)
                {
                    "sample": ["s1", "s1", "s2", "s3", "s4"],
                    "phylum": ["Acido", "Other", "Acido", "Other", "Other"],
                }
            ),
            ids["dc_unlinked"]: pl.DataFrame(  # dc_meta: row per sample
                {"sample": ["s1", "s2", "s3", "s4"], "habitat": ["a", "b", "c", "d"]}
            ),
        }
        link = DCLink(
            source_dc_id=ids["dc_linked"],
            source_column="sample",
            target_dc_id=ids["dc_unlinked"],
            target_type="table",
            link_config=LinkConfig(resolver="direct", target_field="sample"),
        )
        self._patch_environment(monkeypatch, df_by_dc, parent_doc, project_links=[link])

        body = FunnelRequest(
            steps=[
                FunnelStepInput(
                    scope="local",
                    value=["Acido"],
                    tab_id="tab_phylum",
                    component_index="comp_phylum",
                    column_name="phylum",
                    interactive_component_type="MultiSelect",
                    source_dc_id=ids["dc_linked"],
                )
            ],
            target_dcs=[
                FunnelTargetDC(wf_id=ids["wf"], dc_id=ids["dc_linked"]),
                FunnelTargetDC(wf_id=ids["wf"], dc_id=ids["dc_unlinked"]),
            ],
        )
        result = asyncio.run(compute_funnel("parent_dash", body, current_user=None))

        # dc_taxa (source): 5 rows total, 2 match Acido → narrows to 2.
        assert result["counts"][ids["dc_linked"]] == [5, 2]
        assert result["applicable"][ids["dc_linked"]] == [True, True]
        # dc_meta (target): 4 rows total. Acido samples are s1+s2 → 2 rows
        # match after link resolution.
        assert result["counts"][ids["dc_unlinked"]] == [4, 2]
        assert result["applicable"][ids["dc_unlinked"]] == [True, True]

    def test_legacy_step_reaches_target_via_link_through_tab_index_fallback(self, monkeypatch, ids):
        """Phase 2 must still reach linked DCs for legacy pinned steps
        (no ``source_dc_id`` set). Otherwise existing journeys from before
        Phase 1 silently regress to flat funnels on every non-source DC.
        Uses the tab→DC index fallback to figure out the source DC.
        """
        import asyncio

        import polars as pl

        from depictio.api.v1.endpoints.dashboards_endpoints import global_filters as gf_mod
        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import (
            FunnelRequest,
            FunnelStepInput,
            FunnelTargetDC,
            compute_funnel,
        )
        from depictio.models.models.links import DCLink, LinkConfig

        parent_doc = {"dashboard_id": "parent_dash", "global_filters": []}
        df_by_dc = {
            ids["dc_linked"]: pl.DataFrame(
                {
                    "sample": ["s1", "s1", "s2", "s3"],
                    "phylum": ["Acido", "Other", "Acido", "Other"],
                }
            ),
            ids["dc_unlinked"]: pl.DataFrame(
                {"sample": ["s1", "s2", "s3"], "habitat": ["a", "b", "c"]}
            ),
        }
        link = DCLink(
            source_dc_id=ids["dc_linked"],
            source_column="sample",
            target_dc_id=ids["dc_unlinked"],
            target_type="table",
            link_config=LinkConfig(resolver="direct", target_field="sample"),
        )
        self._patch_environment(monkeypatch, df_by_dc, parent_doc, project_links=[link])
        # Legacy: step carries tab_id only; tab_dc_index maps that tab to
        # the source DC (mimicking the dashboard's stored_metadata lookup).
        monkeypatch.setattr(
            gf_mod,
            "_build_tab_dc_index",
            lambda pid: {"tab_phylum": (ids["wf"], ids["dc_linked"])},
        )

        body = FunnelRequest(
            steps=[
                FunnelStepInput(
                    scope="local",
                    value=["Acido"],
                    tab_id="tab_phylum",
                    component_index="comp_phylum",
                    column_name="phylum",
                    interactive_component_type="MultiSelect",
                    # source_dc_id deliberately omitted (legacy step)
                )
            ],
            target_dcs=[
                FunnelTargetDC(wf_id=ids["wf"], dc_id=ids["dc_linked"]),
                FunnelTargetDC(wf_id=ids["wf"], dc_id=ids["dc_unlinked"]),
            ],
        )
        result = asyncio.run(compute_funnel("parent_dash", body, current_user=None))

        # Native apply on dc_linked still works through the tab→DC fallback.
        assert result["counts"][ids["dc_linked"]] == [4, 2]
        # Phase 2 link reach: dc_unlinked narrows too, even though the
        # legacy step has no source_dc_id of its own.
        assert result["counts"][ids["dc_unlinked"]] == [3, 2]
        assert result["applicable"][ids["dc_unlinked"]] == [True, True]

    def test_local_step_without_link_still_skips_unlinked_target(self, monkeypatch, ids):
        """Sanity check: when there's no DCLink from source to target, the
        step is still marked not-applicable (no false-positive reach)."""
        import asyncio

        import polars as pl

        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import (
            FunnelRequest,
            FunnelStepInput,
            FunnelTargetDC,
            compute_funnel,
        )

        parent_doc = {"dashboard_id": "parent_dash", "global_filters": []}
        df_by_dc = {
            ids["dc_linked"]: pl.DataFrame({"sample": ["s1", "s2"], "phylum": ["Acido", "Other"]}),
            ids["dc_unlinked"]: pl.DataFrame(
                {"sample": ["s1", "s2", "s3"], "habitat": ["a", "b", "c"]}
            ),
        }
        self._patch_environment(monkeypatch, df_by_dc, parent_doc, project_links=[])

        body = FunnelRequest(
            steps=[
                FunnelStepInput(
                    scope="local",
                    value=["Acido"],
                    column_name="phylum",
                    interactive_component_type="MultiSelect",
                    source_dc_id=ids["dc_linked"],
                )
            ],
            target_dcs=[
                FunnelTargetDC(wf_id=ids["wf"], dc_id=ids["dc_linked"]),
                FunnelTargetDC(wf_id=ids["wf"], dc_id=ids["dc_unlinked"]),
            ],
        )
        result = asyncio.run(compute_funnel("parent_dash", body, current_user=None))

        assert result["counts"][ids["dc_linked"]] == [2, 1]
        assert result["applicable"][ids["dc_unlinked"]] == [True, False]

    def test_metric_nunique_returns_distinct_counts(self, monkeypatch, ids):
        import asyncio

        import polars as pl

        from depictio.api.v1.endpoints.dashboards_endpoints.global_filters import (
            FunnelRequest,
            FunnelStepInput,
            FunnelTargetDC,
            compute_funnel,
        )

        parent_doc = {
            "dashboard_id": "parent_dash",
            "global_filters": [
                {
                    "id": "gf_habitat",
                    "interactive_component_type": "MultiSelect",
                    "links": [
                        {"wf_id": ids["wf"], "dc_id": ids["dc1"], "column_name": "habitat"},
                    ],
                }
            ],
        }
        df = pl.DataFrame(
            {
                "habitat": ["soil", "soil", "water", "soil"],
                "sample_id": ["a", "a", "b", "c"],
            }
        )
        df_by_dc = {ids["dc1"]: df}
        self._patch_environment(monkeypatch, df_by_dc, parent_doc)

        body = FunnelRequest(
            steps=[
                FunnelStepInput(
                    scope="global",
                    global_filter_id="gf_habitat",
                    value=["soil"],
                )
            ],
            target_dcs=[FunnelTargetDC(wf_id=ids["wf"], dc_id=ids["dc1"])],
            metric="nunique",
            metric_column="sample_id",
        )
        result = asyncio.run(compute_funnel("parent_dash", body, current_user=None))

        # All rows: 3 unique sample_ids (a, b, c).
        # After habitat=soil: 2 unique (a, c).
        assert result["counts"][ids["dc1"]] == [3, 2]
        assert result["applicable"][ids["dc1"]] == [True, True]
