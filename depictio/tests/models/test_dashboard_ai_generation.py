"""``AIGenerationInfo`` and the ``DashboardData.ai_generation`` field.

The stamp is server-owned provenance for AI-drafted dashboards. It must
validate strictly (the model is ``extra="forbid"`` and ``status`` is a closed
set), round-trip through the Mongo serialisation, stay absent on documents
written before the field existed, and never leak into the YAML surface.
"""

from __future__ import annotations

import pytest
from bson import ObjectId
from pydantic import ValidationError

from depictio.models.models.dashboards import AIGenerationInfo, DashboardData
from depictio.models.models.users import Permission, UserBase

STAMP = {
    "status": "draft",
    "model": "claude-sonnet-4-5",
    "prompt": "An overview of the iris measurements",
    "generated_at": "2026-01-01T10:00:00+00:00",
    # Deliberately not 24 hex chars: `MongoModel.mongo()` turns any
    # ObjectId-looking string into an ObjectId on the way in.
    "run_id": "run-3f9c1a7e",
    "warnings": ["Dropped 1 component: budget"],
}

# The same stamp once the model has loaded it: a draft written before the
# review pass existed gains its two empty bookkeeping lists, one written
# before the planner explained itself an empty `sections` list, and one
# written before the gates were recorded an empty `checks` list.
STAMP_STORED = {**STAMP, "reviewed": [], "dropped": [], "sections": [], "checks": []}


def _dashboard(**extra) -> DashboardData:
    owner = UserBase(id=ObjectId(), email="owner@example.com")
    return DashboardData(
        dashboard_id=ObjectId(),
        title="Iris",
        project_id=ObjectId(),
        permissions=Permission(owners=[owner]),
        **extra,
    )


class TestAIGenerationInfo:
    def test_defaults(self):
        info = AIGenerationInfo(
            model="claude-sonnet-4-5", generated_at="2026-01-01T10:00:00+00:00", run_id="run-1"
        )
        assert info.status == "draft"
        assert info.prompt == ""
        assert info.warnings == []

    def test_accepts_promoted(self):
        info = AIGenerationInfo(**{**STAMP, "status": "promoted"})
        assert info.status == "promoted"

    def test_rejects_an_unknown_status(self):
        with pytest.raises(ValidationError):
            AIGenerationInfo(**{**STAMP, "status": "pending"})

    def test_rejects_unknown_keys(self):
        with pytest.raises(ValidationError):
            AIGenerationInfo(**{**STAMP, "cost_usd": 0.1})

    def test_keeps_the_planner_section_rationales(self):
        info = AIGenerationInfo(
            **{
                **STAMP,
                "sections": [
                    {"name": "Cohort", "kind": "filter", "rationale": "narrows every tile"},
                    {"name": "Overview", "rationale": "the headline numbers"},
                ],
            }
        )
        assert [s.kind for s in info.sections] == ["filter", "grid"]
        assert info.sections[1].rationale == "the headline numbers"

    def test_keeps_the_gates_each_tile_went_through(self):
        info = AIGenerationInfo(
            **STAMP,
            checks=[
                {
                    "tag": "sepal_scatter",
                    "attempts": 2,
                    "repair": "figure: dict_kwargs is empty",
                    "checks": [
                        {"layer": "model", "status": "passed"},
                        {"layer": "render", "status": "skipped", "detail": "no cheap probe"},
                    ],
                }
            ],
        )
        (row,) = info.checks
        assert row.tag == "sepal_scatter"
        assert row.attempts == 2
        assert row.repair == "figure: dict_kwargs is empty"
        assert [(c.layer, c.status) for c in row.checks] == [
            ("model", "passed"),
            ("render", "skipped"),
        ]
        assert row.checks[0].detail == ""
        assert row.checks[1].detail == "no cheap probe"

    def test_a_gate_this_build_does_not_know_still_loads(self):
        """Open strings on purpose: a newer server may record a gate this one
        has never heard of, and rejecting the whole dashboard over a label
        would lose the draft, not just the label."""
        info = AIGenerationInfo(
            **STAMP,
            checks=[{"tag": "t", "checks": [{"layer": "quantum", "status": "shrugged"}]}],
        )
        assert info.checks[0].checks[0].layer == "quantum"
        assert info.checks[0].attempts == 1

    def test_rejects_an_unknown_key_inside_a_check(self):
        with pytest.raises(ValidationError):
            AIGenerationInfo(
                **STAMP,
                checks=[{"tag": "t", "checks": [{"layer": "model", "status": "passed", "why": 1}]}],
            )

    def test_rejects_an_unknown_section_kind(self):
        with pytest.raises(ValidationError):
            AIGenerationInfo(**{**STAMP, "sections": [{"name": "Cohort", "kind": "panel"}]})

    def test_model_generated_at_and_run_id_are_required(self):
        with pytest.raises(ValidationError):
            AIGenerationInfo()


class TestDashboardDataField:
    def test_absent_by_default(self):
        assert _dashboard().ai_generation is None

    def test_accepts_a_dict_and_round_trips_through_mongo(self):
        dashboard = _dashboard(ai_generation=STAMP)
        assert isinstance(dashboard.ai_generation, AIGenerationInfo)

        doc = dashboard.mongo()
        assert doc["ai_generation"] == STAMP_STORED

        reloaded = DashboardData.from_mongo(doc)
        assert reloaded.ai_generation == dashboard.ai_generation

    def test_rejects_an_unknown_status_on_the_dashboard(self):
        with pytest.raises(ValidationError):
            _dashboard(ai_generation={**STAMP, "status": "pending"})

    def test_legacy_document_without_the_field_loads(self):
        doc = _dashboard().mongo()
        doc.pop("ai_generation", None)
        assert "ai_generation" not in doc
        assert DashboardData.from_mongo(doc).ai_generation is None

    def test_not_part_of_the_yaml_surface(self):
        """`to_lite()` extracts named fields only, so the stamp never reaches an export."""
        lite = _dashboard(ai_generation=STAMP).to_lite()
        assert "ai_generation" not in lite.model_dump()
        assert "ai_generation" not in type(lite).model_fields
