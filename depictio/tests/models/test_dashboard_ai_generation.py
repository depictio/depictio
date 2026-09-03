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
# review pass existed gains the two empty bookkeeping lists.
STAMP_STORED = {**STAMP, "reviewed": [], "dropped": []}


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
