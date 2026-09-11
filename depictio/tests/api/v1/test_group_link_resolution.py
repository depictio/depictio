"""Selection groups reaching a second data collection (cross-DC link resolution).

A group is captured on one data collection — "the samples whose ATAC signal is
poor", lassoed off a plot of ``ataqv_metrics`` — and is then expected to colour
every component on the dashboard. Matching it by column NAME alone only works
where the other collection happens to spell the join column identically; where
the project declares a link under different names the group used to vanish with
no error and no signal.

These tests pin the two halves of the fix:

- ``resolve_values_via_links`` (``depictio/api/v1/filter_links.py``) — the
  single-translation entry point the group path shares with dashboard filters,
  including the rule that the translated values name the LINK's join column and
  never the column the user selected on;
- ``resolve_group_defs_for_dc`` (``depictio/api/v1/services/figure/groups.py``)
  — the per-group verdict: applied / linked / dropped-with-a-reason.

The trap being guarded (see ``test_filter_links.py`` for its filter-side twin):
resolving through the user's own column instead of the link's join column
produces a name the target collection does not have, and a predicate on an
unknown column either drops out entirely or matches every row — a group that
silently covers the whole frame is far worse than one that covers nothing.
"""

from unittest.mock import patch

import polars as pl

from depictio.api.v1.filter_links import resolve_values_via_links
from depictio.api.v1.services.card_groups import compute_group_compare
from depictio.api.v1.services.figure.groups import (
    GROUP_APPLIED,
    GROUP_COLUMN,
    GROUP_COLUMN_ABSENT,
    GROUP_LINK_FAILED,
    GROUP_LINK_NO_MATCH,
    GROUP_LINKED,
    GROUP_NO_LINK,
    GROUP_UNKNOWN,
    OTHER_LABEL,
    group_annotation_expr,
    group_source_columns,
    resolve_group_defs_for_dc,
    sanitize_group_defs,
)

# The collection the selection was captured on, and the one a component reads.
SOURCE_DC = "6a19541470f089f587c39c64"
TARGET_DC = "6a1954189fa2f2d1ffc39c76"
THIRD_DC = "6a1954189fa2f2d1ffc39c99"


def _project_metadata(*, target_field=None, source_column="sample_id"):
    """One enabled direct table→table link, mirroring a seeded ``sample_id`` join."""
    return {
        "project": {
            "_id": "fcf60afdea2241b493b9c473",
            "links": [
                {
                    "id": "6a19541e70f089f587c39c6a",
                    "enabled": True,
                    "source_dc_id": SOURCE_DC,
                    # The join column — the name that exists on the target.
                    "source_column": source_column,
                    "target_dc_id": TARGET_DC,
                    "target_type": "table",
                    "link_config": {"resolver": "direct", "target_field": target_field},
                }
            ],
        }
    }


def _groups(column="habitat", dc_id=SOURCE_DC, values=("Groundwater",)):
    """One sanitized group, captured on ``dc_id``'s ``column``."""
    raw = {
        "name": "Poor signal",
        "column_name": column,
        "values": list(values),
        "color": "#1f77b4",
    }
    if dc_id:
        raw["dc_id"] = dc_id
    return sanitize_group_defs([raw])


def _translator(project_metadata, target_dc_id=TARGET_DC):
    """The ``translate`` callable ``resolve_group_defs_for_dc`` expects."""

    def translate(origin_dc_id, origin_column, values):
        return resolve_values_via_links(
            project_metadata=project_metadata,
            origin_dc_id=origin_dc_id,
            origin_column=origin_column,
            values=values,
            target_dc_id=target_dc_id,
            access_token="fake-token",
            component_type="figure",
        )

    return translate


class TestSanitizeKeepsDcId:
    """``dc_id`` is what separates "missing here" from "lives elsewhere"."""

    def test_dc_id_is_carried_through(self):
        assert _groups()[0]["dc_id"] == SOURCE_DC

    def test_absent_when_the_client_sent_none(self):
        # Older clients send no dc_id at all; the key must simply not appear,
        # rather than becoming an empty string that reads as a real origin.
        assert "dc_id" not in _groups(dc_id=None)[0]

    def test_non_string_dc_id_is_dropped(self):
        raw = {"name": "A", "column_name": "c", "values": ["v"], "color": "#1f77b4", "dc_id": 42}
        assert "dc_id" not in sanitize_group_defs([raw])[0]


class TestSameColumnMatch:
    """(a) The column is right there — nothing changes, and no link is consulted."""

    def test_group_is_kept_untouched_and_reported_applied(self):
        groups = _groups(column="sample_id")
        resolved, statuses = resolve_group_defs_for_dc(
            groups,
            TARGET_DC,
            ["sample_id", "depth"],
            translate=_never_called,
        )
        assert resolved == groups
        assert statuses == [
            {
                "name": "Poor signal",
                "status": GROUP_APPLIED,
                "applied": True,
                "column_name": "sample_id",
                "source_dc_id": SOURCE_DC,
                "source_column": "sample_id",
                "matched_values": 1,
            }
        ]

    def test_same_name_on_the_component_s_own_collection(self):
        groups = _groups(column="sample_id", dc_id=TARGET_DC)
        resolved, statuses = resolve_group_defs_for_dc(
            groups, TARGET_DC, ["sample_id"], translate=_never_called
        )
        assert resolved == groups
        assert statuses[0]["status"] == GROUP_APPLIED

    def test_annotation_is_unchanged(self):
        df = pl.DataFrame({"sample_id": ["S1", "S2", "S3"]})
        resolved, _ = resolve_group_defs_for_dc(
            _groups(column="sample_id", values=("S1", "S3")),
            TARGET_DC,
            df.columns,
            translate=_never_called,
        )
        labels = df.with_columns(group_annotation_expr(resolved, df.columns, dict(df.schema)))[
            GROUP_COLUMN
        ].to_list()
        assert labels == ["Poor signal", OTHER_LABEL, "Poor signal"]


class TestCrossDcMatchThroughALink:
    """(b) The column is absent here, but the project declares a link."""

    def test_group_is_translated_onto_the_target_s_column(self):
        resolved_values = ["SRR10070141", "SRR10070133"]
        with patch(
            "depictio.api.v1.filter_links.resolve_link_values",
            return_value={"resolved_values": resolved_values, "resolver_used": "direct"},
        ) as mock_resolve:
            resolved, statuses = resolve_group_defs_for_dc(
                _groups(),
                TARGET_DC,
                ["sample_id", "depth"],
                translate=_translator(_project_metadata()),
            )

        mock_resolve.assert_called_once()
        # The resolver is asked about the ORIGIN's column — that is where the
        # user's values live — and answers with the target's rows.
        assert mock_resolve.call_args.kwargs["source_column"] == "habitat"
        assert mock_resolve.call_args.kwargs["source_dc_id"] == SOURCE_DC
        assert mock_resolve.call_args.kwargs["target_dc_id"] == TARGET_DC

        assert len(resolved) == 1
        assert resolved[0]["column_name"] == "sample_id"
        assert resolved[0]["values"] == resolved_values
        # Name and colour are identity across collections — the legend must
        # read the same on every component.
        assert resolved[0]["name"] == "Poor signal"
        assert resolved[0]["color"] == "#1f77b4"
        assert statuses[0] == {
            "name": "Poor signal",
            "status": GROUP_LINKED,
            "applied": True,
            "column_name": "sample_id",
            "source_dc_id": SOURCE_DC,
            "source_column": "habitat",
            "matched_values": 2,
        }

    def test_the_translated_column_is_what_gets_projected(self):
        # The loader projects `group_source_columns`; projecting the group's
        # original column would leave the annotation without its input.
        with patch(
            "depictio.api.v1.filter_links.resolve_link_values",
            return_value={"resolved_values": ["S1"], "resolver_used": "direct"},
        ):
            resolved, _ = resolve_group_defs_for_dc(
                _groups(), TARGET_DC, ["sample_id"], translate=_translator(_project_metadata())
            )
        assert group_source_columns(resolved) == {"sample_id"}

    def test_target_field_rename_wins_over_the_join_column(self):
        with patch(
            "depictio.api.v1.filter_links.resolve_link_values",
            return_value={"resolved_values": ["s1"], "resolver_used": "sample_mapping"},
        ):
            resolved, statuses = resolve_group_defs_for_dc(
                _groups(),
                TARGET_DC,
                ["sample_name"],
                translate=_translator(_project_metadata(target_field="sample_name")),
            )
        assert resolved[0]["column_name"] == "sample_name"
        assert statuses[0]["status"] == GROUP_LINKED

    def test_values_are_stringified_like_a_captured_selection(self):
        with patch(
            "depictio.api.v1.filter_links.resolve_link_values",
            return_value={"resolved_values": [1, 2], "resolver_used": "direct"},
        ):
            resolved, _ = resolve_group_defs_for_dc(
                _groups(), TARGET_DC, ["sample_id"], translate=_translator(_project_metadata())
            )
        # `_categorical_predicate` matches stringified values against numeric
        # columns, so the whole pipeline stays on one representation.
        assert resolved[0]["values"] == ["1", "2"]


class TestDroppedWithAReason:
    """(c) Nothing to translate through — dropped, as before, but reportably."""

    def test_absent_column_and_no_link_is_dropped_as_no_link(self):
        with patch(
            "depictio.api.v1.filter_links.resolve_link_values"
        ) as mock_resolve:  # unlinked DCs: the resolver is never reached
            resolved, statuses = resolve_group_defs_for_dc(
                _groups(),
                THIRD_DC,
                ["some_other_column"],
                translate=_translator(_project_metadata(), target_dc_id=THIRD_DC),
            )
        mock_resolve.assert_not_called()
        assert resolved == []
        assert statuses[0]["status"] == GROUP_NO_LINK
        assert statuses[0]["applied"] is False
        assert statuses[0]["matched_values"] == 0

    def test_absent_column_on_its_own_collection_is_column_absent(self):
        resolved, statuses = resolve_group_defs_for_dc(
            _groups(dc_id=TARGET_DC), TARGET_DC, ["depth"], translate=_never_called
        )
        assert resolved == []
        assert statuses[0]["status"] == GROUP_COLUMN_ABSENT

    def test_a_group_without_a_dc_id_cannot_be_translated(self):
        # Nothing names where these values came from, so there is no link to
        # look for — today's behaviour, now with a reason attached.
        resolved, statuses = resolve_group_defs_for_dc(
            _groups(dc_id=None), TARGET_DC, ["sample_id"], translate=_never_called
        )
        assert resolved == []
        assert statuses[0]["status"] == GROUP_COLUMN_ABSENT
        assert statuses[0]["source_dc_id"] == ""

    def test_a_dropped_group_renders_ungrouped_rather_than_crashing(self):
        df = pl.DataFrame({"sample_id": ["S1", "S2"]})
        resolved, _ = resolve_group_defs_for_dc(
            _groups(), THIRD_DC, df.columns, translate=lambda *_: None
        )
        # No groups left => no annotation => the render path reverts to the
        # ungrouped kwargs. Crucially not an expression that labels every row.
        assert group_annotation_expr(resolved, df.columns, dict(df.schema)) is None

    def test_a_link_that_matches_nothing_is_not_a_failure(self):
        with patch(
            "depictio.api.v1.filter_links.resolve_link_values",
            return_value={"resolved_values": [], "resolver_used": "direct"},
        ):
            resolved, statuses = resolve_group_defs_for_dc(
                _groups(), TARGET_DC, ["sample_id"], translate=_translator(_project_metadata())
            )
        assert resolved == []
        assert statuses[0]["status"] == GROUP_LINK_NO_MATCH
        # The column is reported even though the group was dropped: it is what
        # the group WOULD have annotated on.
        assert statuses[0]["column_name"] == "sample_id"

    def test_a_resolution_error_drops_the_group_without_failing_the_render(self):
        # Unlike a filter — where a dropped one renders every row — a dropped
        # group only costs colour, so the render proceeds and reports this.
        def boom(*_args):
            raise RuntimeError("link resolution timed out")

        resolved, statuses = resolve_group_defs_for_dc(
            _groups(), TARGET_DC, ["sample_id"], translate=boom
        )
        assert resolved == []
        assert statuses[0]["status"] == GROUP_LINK_FAILED

    def test_a_link_naming_a_column_this_collection_lacks(self):
        with patch(
            "depictio.api.v1.filter_links.resolve_link_values",
            return_value={"resolved_values": ["s1"], "resolver_used": "direct"},
        ):
            resolved, statuses = resolve_group_defs_for_dc(
                _groups(),
                TARGET_DC,
                ["depth"],  # no sample_id here
                translate=_translator(_project_metadata()),
            )
        assert resolved == []
        assert statuses[0]["status"] == GROUP_COLUMN_ABSENT
        assert statuses[0]["column_name"] == "sample_id"

    def test_an_unreadable_schema_decides_nothing(self):
        groups = _groups()
        resolved, statuses = resolve_group_defs_for_dc(
            groups, TARGET_DC, None, translate=_never_called
        )
        # "Don't know" must not collapse into "carries nothing": the group is
        # passed through and the frame has the last word, exactly as before.
        assert resolved == groups
        assert statuses[0]["status"] == GROUP_UNKNOWN
        assert statuses[0]["applied"] is True


class TestSourceColumnTrap:
    """(d) The translation must name the LINK's join column, never the user's."""

    def test_the_join_column_is_used_not_the_selected_column(self):
        with patch(
            "depictio.api.v1.filter_links.resolve_link_values",
            return_value={"resolved_values": ["S1", "S3"], "resolver_used": "direct"},
        ):
            resolved, statuses = resolve_group_defs_for_dc(
                _groups(column="habitat"),
                TARGET_DC,
                ["sample_id", "depth"],
                translate=_translator(_project_metadata(target_field=None)),
            )

        # The crux: 'habitat' is the column the user selected on and does not
        # exist on the target. Carrying it over would annotate on a name the
        # frame lacks; the link's join column is the only correct answer.
        assert resolved[0]["column_name"] == "sample_id"
        assert resolved[0]["column_name"] != "habitat"
        assert statuses[0]["source_column"] == "habitat"

    def test_the_translated_group_labels_only_its_own_rows(self):
        """The end state: the right rows, and only the right rows."""
        # The target carries the join column and nothing resembling 'habitat'
        # — the shape that used to make the group disappear.
        df = pl.DataFrame({"sample_id": ["S1", "S2", "S3", "S4"], "depth": [1.0, 2.0, 3.0, 4.0]})
        groups = _groups(column="habitat")

        # Before translation there is nothing to annotate with: the group's own
        # column is not in this frame, so the whole annotation collapses to
        # None and the figure renders ungrouped, silently.
        assert group_annotation_expr(groups, df.columns, dict(df.schema)) is None

        with patch(
            "depictio.api.v1.filter_links.resolve_link_values",
            return_value={"resolved_values": ["S1", "S3"], "resolver_used": "direct"},
        ):
            resolved, _ = resolve_group_defs_for_dc(
                groups, TARGET_DC, df.columns, translate=_translator(_project_metadata())
            )

        labels = df.with_columns(group_annotation_expr(resolved, df.columns, dict(df.schema)))[
            GROUP_COLUMN
        ].to_list()
        # Two of four rows. Not zero (the old silent drop), and not four — the
        # predicate names the link's resolved sample ids, so it can neither
        # miss the group's rows nor spread over the whole frame.
        assert labels == ["Poor signal", OTHER_LABEL, "Poor signal", OTHER_LABEL]
        assert labels.count("Poor signal") == 2

    def test_values_come_from_the_resolver_not_the_original_selection(self):
        with patch(
            "depictio.api.v1.filter_links.resolve_link_values",
            return_value={"resolved_values": ["S1", "S3"], "resolver_used": "direct"},
        ):
            resolved, _ = resolve_group_defs_for_dc(
                _groups(column="habitat", values=("Groundwater",)),
                TARGET_DC,
                ["sample_id"],
                translate=_translator(_project_metadata()),
            )
        assert resolved[0]["values"] == ["S1", "S3"]
        assert "Groundwater" not in resolved[0]["values"]

    def test_resolve_values_via_links_reports_the_join_column(self):
        """The shared entry point, checked on its own (filter-side twin lives in
        ``test_filter_links.py``)."""
        with patch(
            "depictio.api.v1.filter_links.resolve_link_values",
            return_value={"resolved_values": ["S1"], "resolver_used": "direct"},
        ):
            hop = resolve_values_via_links(
                project_metadata=_project_metadata(),
                origin_dc_id=SOURCE_DC,
                origin_column="habitat",
                values=["Groundwater"],
                target_dc_id=TARGET_DC,
                access_token="fake-token",
            )
        assert hop == ("sample_id", ["S1"])

    def test_no_route_is_not_the_same_as_an_empty_route(self):
        # None ("no link declared") must stay distinguishable from (col, [])
        # ("linked, matched nothing") — the two produce different statuses.
        with patch("depictio.api.v1.filter_links.resolve_link_values") as mock_resolve:
            hop = resolve_values_via_links(
                project_metadata=_project_metadata(),
                origin_dc_id=SOURCE_DC,
                origin_column="habitat",
                values=["Groundwater"],
                target_dc_id=THIRD_DC,
                access_token="fake-token",
            )
        mock_resolve.assert_not_called()
        assert hop is None

    def test_a_link_with_no_resolvable_column_yields_no_route(self):
        md = _project_metadata(source_column="")
        with patch(
            "depictio.api.v1.filter_links.resolve_link_values",
            return_value={"resolved_values": ["S1"], "resolver_used": "direct"},
        ):
            hop = resolve_values_via_links(
                project_metadata=md,
                origin_dc_id=SOURCE_DC,
                origin_column="habitat",
                values=["Groundwater"],
                target_dc_id=TARGET_DC,
                access_token="fake-token",
            )
        assert hop is None


class TestEndpointWiring:
    """``_resolve_group_defs`` — what the figure and card endpoints actually call."""

    @staticmethod
    def _patched(column_specs, project_doc, resolved_values=("S1", "S3")):
        """Patch the two Mongo reads and the link resolver the helper reaches for."""
        from unittest.mock import MagicMock

        deltatables = MagicMock()
        deltatables.find_one.return_value = {
            "aggregation": [
                {"aggregation_columns_specs": [{"name": c, "specs": {}} for c in column_specs]}
            ]
        }
        projects = MagicMock()
        projects.find_one.return_value = project_doc
        return (
            patch("depictio.api.v1.db.deltatables_collection", deltatables),
            patch(
                "depictio.api.v1.endpoints.dashboards_endpoints.routes.projects_collection",
                projects,
            ),
            patch(
                "depictio.api.v1.filter_links.resolve_link_values",
                return_value={"resolved_values": list(resolved_values), "resolver_used": "direct"},
            ),
        )

    def test_schema_is_read_from_the_deltatable_and_the_link_is_walked(self):
        from bson import ObjectId

        from depictio.api.v1.endpoints.dashboards_endpoints.routes import _resolve_group_defs

        # Straight out of Mongo, so the _id is a real ObjectId — the helper has
        # to normalise it before the link walker sees it.
        project_doc = {
            **_project_metadata()["project"],
            "_id": ObjectId("fcf60afdea2241b493b9c473"),
        }
        dt_patch, proj_patch, resolve_patch = self._patched(["sample_id", "depth"], project_doc)
        with dt_patch, proj_patch, resolve_patch:
            resolved, statuses = _resolve_group_defs(
                group_defs=_groups(),
                target_dc_id=TARGET_DC,
                project_id="fcf60afdea2241b493b9c473",
                access_token="fake-token",
                component_type="figure",
            )
        assert resolved[0]["column_name"] == "sample_id"
        assert resolved[0]["values"] == ["S1", "S3"]
        assert statuses[0]["status"] == GROUP_LINKED

    def test_no_project_lookup_when_every_column_is_already_there(self):
        from unittest.mock import MagicMock

        from depictio.api.v1.endpoints.dashboards_endpoints.routes import _resolve_group_defs

        projects = MagicMock()
        dt_patch, _, _ = self._patched(["sample_id"], None)
        with (
            dt_patch,
            patch(
                "depictio.api.v1.endpoints.dashboards_endpoints.routes.projects_collection",
                projects,
            ),
        ):
            resolved, statuses = _resolve_group_defs(
                group_defs=_groups(column="sample_id"),
                target_dc_id=TARGET_DC,
                project_id="fcf60afdea2241b493b9c473",
                access_token="fake-token",
                component_type="figure",
            )
        # The deferred lookup is the point: a dashboard whose components all
        # carry the group's column must not pay a project read per render.
        projects.find_one.assert_not_called()
        assert statuses[0]["status"] == GROUP_APPLIED
        assert len(resolved) == 1

    def test_an_unreadable_deltatable_leaves_the_groups_alone(self):
        from unittest.mock import MagicMock

        from depictio.api.v1.endpoints.dashboards_endpoints.routes import _resolve_group_defs

        deltatables = MagicMock()
        deltatables.find_one.return_value = None
        with patch("depictio.api.v1.db.deltatables_collection", deltatables):
            groups = _groups()
            resolved, statuses = _resolve_group_defs(
                group_defs=groups,
                target_dc_id=TARGET_DC,
                project_id="fcf60afdea2241b493b9c473",
                access_token="fake-token",
                component_type="figure",
            )
        assert resolved == groups
        assert statuses[0]["status"] == GROUP_UNKNOWN

    def test_no_groups_means_no_work(self):
        from depictio.api.v1.endpoints.dashboards_endpoints.routes import _resolve_group_defs

        assert _resolve_group_defs([], TARGET_DC, "pid", "tok", "figure") == ([], [])


class TestCardComparisonReportsOmissions:
    """The card path drops by frame schema; that drop is now named too."""

    def test_omitted_groups_are_listed(self):
        from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
            _agg_expr,
            _coerce_agg_result,
        )

        df = pl.DataFrame({"sample_id": ["S1", "S2"], "depth": [10.0, 20.0]})
        groups = sanitize_group_defs(
            [
                {
                    "name": "Here",
                    "column_name": "sample_id",
                    "values": ["S1"],
                    "color": "#1f77b4",
                },
                {
                    "name": "Elsewhere",
                    "column_name": "habitat",
                    "values": ["Groundwater"],
                    "color": "#ff7f0e",
                },
            ]
        )
        out = compute_group_compare(df, groups, "depth", "mean", _agg_expr, _coerce_agg_result)
        assert out is not None
        assert [g["name"] for g in out["groups"]] == ["Here"]
        assert out["omitted"] == [{"name": "Elsewhere", "status": GROUP_COLUMN_ABSENT}]

    def test_no_omitted_key_when_every_group_applies(self):
        from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
            _agg_expr,
            _coerce_agg_result,
        )

        df = pl.DataFrame({"sample_id": ["S1", "S2"], "depth": [10.0, 20.0]})
        groups = sanitize_group_defs(
            [
                {
                    "name": "Here",
                    "column_name": "sample_id",
                    "values": ["S1"],
                    "color": "#1f77b4",
                }
            ]
        )
        out = compute_group_compare(df, groups, "depth", "mean", _agg_expr, _coerce_agg_result)
        assert out is not None
        assert "omitted" not in out


def _never_called(*_args):
    raise AssertionError(
        "translate() must not be consulted when the column is already present "
        "(or when there is nothing to translate through)"
    )
