"""Unit tests for the comment-thread and annotation models."""

from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.models.comments import (
    MAX_LABEL_CHARS,
    MAX_POINT_IDS,
    AgentInfo,
    Anchor,
    Annotation,
    AnnotationStyle,
    ArrowNote,
    Author,
    CommentCreate,
    CommentThread,
    Geometry,
    MarkedPoints,
    PublishedAnnotation,
    RefLine,
    Review,
    Staleness,
    ThreadCreate,
    ThreadOut,
    ThreadReview,
    ThreadUpdate,
    XRange,
    YRange,
    component_fingerprint,
)

GEOMETRY = TypeAdapter(Geometry)
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _anchor() -> Anchor:
    return Anchor(dashboard_id="dash-1", component_index="comp-1")


def _range_annotation(**overrides) -> Annotation:
    data = {"kind": "range", "geometry": {"kind": "x_range", "x0": 1, "x1": 2}, "label": "peak"}
    data.update(overrides)
    return Annotation.model_validate(data)


def _human() -> Author:
    return Author(user_id="u1")


def _agent() -> Author:
    return Author(kind="agent", user_id="u1", agent=AgentInfo(name="bot"))


def _thread(created_by: Author, review: Review | None = None, cls=CommentThread):
    return cls(
        id="t1",
        project_id="p1",
        parent_dashboard_id="dash-1",
        anchor=_anchor(),
        created_by=created_by,
        created_at=NOW,
        updated_at=NOW,
        review=review,
    )


class TestComponentFingerprint:
    BASE = {"index": "c1", "title": "Scatter", "dc_config": {"id": "dc1"}, "layout": {"x": 0}}

    @pytest.mark.parametrize("value", [None, {}])
    def test_empty_is_none(self, value):
        assert component_fingerprint(value) is None

    def test_stable_under_key_order(self):
        reordered = dict(reversed(list(self.BASE.items())))
        assert component_fingerprint(self.BASE) == component_fingerprint(reordered)

    def test_nested_key_order_stable(self):
        a = {"dc_config": {"a": 1, "b": 2}}
        b = {"dc_config": {"b": 2, "a": 1}}
        assert component_fingerprint(a) == component_fingerprint(b)

    def test_ignores_layout_and_bookkeeping(self):
        moved = {
            **self.BASE,
            "layout": {"x": 5, "y": 3, "w": 4},
            "last_updated": "2026-01-01",
            "parent_index": "p9",
        }
        assert component_fingerprint(self.BASE) == component_fingerprint(moved)

    @pytest.mark.parametrize(
        "change",
        [{"title": "Other"}, {"dc_config": {"id": "dc2"}}, {"extra": 1}],
    )
    def test_changes_with_definition(self, change):
        assert component_fingerprint(self.BASE) != component_fingerprint({**self.BASE, **change})

    def test_is_short_hex(self):
        fp = component_fingerprint(self.BASE)
        assert fp is not None and len(fp) == 16
        int(fp, 16)


class TestGeometry:
    @pytest.mark.parametrize(
        ("data", "cls"),
        [
            ({"kind": "x_range", "x0": "2024-01-01", "x1": "2024-02-01"}, XRange),
            ({"kind": "y_range", "y0": 0.1, "y1": 0.9}, YRange),
            ({"kind": "ref_line", "axis": "y", "value": 3.5}, RefLine),
            ({"kind": "points", "column": "sample", "ids": ["a", 2]}, MarkedPoints),
            ({"kind": "arrow_note", "x": "cat", "y": 4}, ArrowNote),
        ],
    )
    def test_parse_each_kind(self, data, cls):
        geom = GEOMETRY.validate_python(data)
        assert isinstance(geom, cls)
        assert geom.kind == data["kind"]

    def test_arrow_note_defaults(self):
        geom = GEOMETRY.validate_python({"kind": "arrow_note", "x": 1, "y": 2})
        assert (geom.ax, geom.ay) == (-40, -40)

    @pytest.mark.parametrize("kind", ["box", "region", "circle"])
    def test_unknown_kind_rejected(self, kind):
        with pytest.raises(ValidationError):
            GEOMETRY.validate_python({"kind": kind, "x0": 0, "x1": 1, "y0": 0, "y1": 1})

    def test_missing_kind_rejected(self):
        with pytest.raises(ValidationError):
            GEOMETRY.validate_python({"x0": 0, "x1": 1})

    def test_ref_line_axis_restricted(self):
        with pytest.raises(ValidationError):
            GEOMETRY.validate_python({"kind": "ref_line", "axis": "z", "value": 1})

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            GEOMETRY.validate_python({"kind": "x_range", "x0": 0, "x1": 1, "y0": 0})


class TestMarkedPoints:
    def test_needs_ids_or_coords(self):
        with pytest.raises(ValidationError, match="ids or coords"):
            MarkedPoints()

    def test_ids_need_column(self):
        with pytest.raises(ValidationError, match="column"):
            MarkedPoints(ids=["a"])

    def test_coords_without_column_ok(self):
        mp = MarkedPoints.model_validate({"coords": [{"x": "A", "y": 3, "trace": 1}]})
        assert mp.coords[0].trace == 1
        assert mp.column is None

    def test_ids_max_length(self):
        MarkedPoints(column="c", ids=list(range(MAX_POINT_IDS)))
        with pytest.raises(ValidationError):
            MarkedPoints(column="c", ids=list(range(MAX_POINT_IDS + 1)))

    def test_coords_max_length(self):
        coords = [{"x": i, "y": i} for i in range(MAX_POINT_IDS + 1)]
        with pytest.raises(ValidationError):
            MarkedPoints.model_validate({"coords": coords})


class TestAnnotation:
    @pytest.mark.parametrize(
        ("kind", "geometry"),
        [
            ("range", {"kind": "x_range", "x0": 0, "x1": 1}),
            ("range", {"kind": "y_range", "y0": 0, "y1": 1}),
            ("line", {"kind": "ref_line", "axis": "x", "value": 0}),
            ("points", {"kind": "points", "coords": [{"x": 0, "y": 0}]}),
            ("note", {"kind": "arrow_note", "x": 0, "y": 0}),
        ],
    )
    def test_matching_kinds_accepted(self, kind, geometry):
        ann = Annotation.model_validate({"kind": kind, "geometry": geometry, "label": "x"})
        assert ann.kind == kind

    @pytest.mark.parametrize(
        ("kind", "geometry"),
        [
            ("line", {"kind": "x_range", "x0": 0, "x1": 1}),
            ("range", {"kind": "ref_line", "axis": "x", "value": 0}),
            ("note", {"kind": "points", "coords": [{"x": 0, "y": 0}]}),
            ("points", {"kind": "arrow_note", "x": 0, "y": 0}),
        ],
    )
    def test_kind_geometry_mismatch_rejected(self, kind, geometry):
        with pytest.raises(ValidationError, match="cannot use"):
            Annotation.model_validate({"kind": kind, "geometry": geometry, "label": "x"})

    def test_region_kind_rejected(self):
        with pytest.raises(ValidationError):
            _range_annotation(kind="region")

    def test_defaults(self):
        ann = _range_annotation()
        assert ann.published is False
        assert ann.color == "yellow"
        assert ann.style == AnnotationStyle()

    def test_palette_color_accepted(self):
        assert _range_annotation(color="grape").color == "grape"

    @pytest.mark.parametrize("color", ["#ff0000", "rgb(0,0,0)", "purple", "Blue"])
    def test_non_palette_color_rejected(self, color):
        with pytest.raises(ValidationError):
            _range_annotation(color=color)

    def test_label_length(self):
        _range_annotation(label="x" * MAX_LABEL_CHARS)
        with pytest.raises(ValidationError):
            _range_annotation(label="x" * (MAX_LABEL_CHARS + 1))
        with pytest.raises(ValidationError):
            _range_annotation(label="")

    @pytest.mark.parametrize(
        "style",
        [{"opacity": -0.1}, {"opacity": 1.1}, {"width": 0}, {"width": 11}, {"dash": "dashdot"}],
    )
    def test_style_bounds_rejected(self, style):
        with pytest.raises(ValidationError):
            AnnotationStyle.model_validate(style)

    def test_style_bounds_accepted(self):
        style = AnnotationStyle(opacity=1, width=10, dash="dot")
        assert style.opacity == 1 and style.width == 10


class TestAuthor:
    def test_human_default(self):
        assert _human().kind == "human"

    def test_agent_requires_agent_info(self):
        with pytest.raises(ValidationError, match="agent details"):
            Author(kind="agent", user_id="u1")

    def test_human_forbids_agent_info(self):
        with pytest.raises(ValidationError, match="agent details"):
            Author(kind="human", user_id="u1", agent=AgentInfo(name="bot"))

    def test_agent_with_info_ok(self):
        assert _agent().agent.name == "bot"


class TestThreadCreate:
    def test_needs_body_or_annotation(self):
        with pytest.raises(ValidationError, match="comment or an annotation"):
            ThreadCreate(anchor=_anchor())

    def test_body_only(self):
        assert ThreadCreate(anchor=_anchor(), body="hi").body == "hi"

    def test_annotation_only(self):
        tc = ThreadCreate(anchor=_anchor(), annotation=_range_annotation())
        assert tc.body is None

    @pytest.mark.parametrize("body", ["", "   ", "\n\t"])
    def test_blank_body_rejected(self, body):
        with pytest.raises(ValidationError, match="blank"):
            ThreadCreate(anchor=_anchor(), body=body, annotation=_range_annotation())

    def test_agent_published_annotation_rejected(self):
        with pytest.raises(ValidationError, match="cannot be published"):
            ThreadCreate(
                anchor=_anchor(),
                annotation=_range_annotation(published=True),
                agent=AgentInfo(name="bot"),
            )

    def test_agent_unpublished_annotation_ok(self):
        tc = ThreadCreate(
            anchor=_anchor(), annotation=_range_annotation(), agent=AgentInfo(name="bot")
        )
        assert tc.agent is not None

    def test_human_published_annotation_ok(self):
        tc = ThreadCreate(anchor=_anchor(), annotation=_range_annotation(published=True))
        assert tc.annotation.published is True

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ThreadCreate.model_validate(
                {"anchor": {"dashboard_id": "d"}, "body": "hi", "status": "open"}
            )

    def test_anchor_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ThreadCreate.model_validate({"anchor": {"dashboard_id": "d", "bogus": 1}, "body": "hi"})


class TestSmallRequestBodies:
    @pytest.mark.parametrize("body", ["", "  ", "\n"])
    def test_comment_create_blank_rejected(self, body):
        with pytest.raises(ValidationError):
            CommentCreate(body=body)

    def test_comment_create_ok(self):
        assert CommentCreate(body="hello").body == "hello"

    @pytest.mark.parametrize("status", ["open", "resolved", None])
    def test_thread_update_status_allowed(self, status):
        assert ThreadUpdate(status=status).status == status

    @pytest.mark.parametrize("status", ["proposed", "rejected", "closed"])
    def test_thread_update_status_rejected(self, status):
        with pytest.raises(ValidationError):
            ThreadUpdate(status=status)

    @pytest.mark.parametrize("decision", ["accepted", "rejected"])
    def test_thread_review_decisions(self, decision):
        assert ThreadReview(decision=decision).decision == decision

    @pytest.mark.parametrize("decision", ["approved", "proposed", ""])
    def test_thread_review_bad_decision(self, decision):
        with pytest.raises(ValidationError):
            ThreadReview(decision=decision)


class TestCommentThread:
    def test_human_not_proposal(self):
        assert _thread(_human()).is_agent_proposal is False

    def test_agent_unreviewed_is_proposal(self):
        assert _thread(_agent()).is_agent_proposal is True

    def test_agent_accepted_not_proposal(self):
        review = Review(decision="accepted", by="u2", at=NOW)
        assert _thread(_agent(), review).is_agent_proposal is False

    def test_agent_rejected_is_proposal(self):
        review = Review(decision="rejected", by="u2", at=NOW)
        assert _thread(_agent(), review).is_agent_proposal is True

    def test_defaults(self):
        thread = _thread(_human())
        assert thread.status == "open"
        assert thread.comments == []


class TestAnchor:
    def test_defaults(self):
        anchor = Anchor(dashboard_id="d")
        assert anchor.version_id is None
        assert anchor.pins == {}
        assert anchor.data_hashes == {}
        assert anchor.component_index is None
        assert anchor.component_hash is None
        assert anchor.view_state is None

    def test_mutable_defaults_not_shared(self):
        a, b = Anchor(dashboard_id="d"), Anchor(dashboard_id="d")
        a.pins["dc"] = 1
        assert b.pins == {}


class TestResponses:
    def test_thread_out_default_staleness(self):
        out = _thread(_human(), cls=ThreadOut)
        assert out.staleness == Staleness()
        assert not out.staleness.component_missing
        assert not out.staleness.component_changed
        assert not out.staleness.data_changed

    def test_published_annotation_has_no_comments(self):
        assert "comments" not in PublishedAnnotation.model_fields

    def test_published_annotation_parses_geometry(self):
        pa = PublishedAnnotation.model_validate(
            {
                "thread_id": "t1",
                "dashboard_id": "d",
                "component_index": None,
                "number": 1,
                "kind": "line",
                "geometry": {"kind": "ref_line", "axis": "x", "value": 2},
                "label": "cut-off",
                "color": "red",
                "style": {},
            }
        )
        assert isinstance(pa.geometry, RefLine)
