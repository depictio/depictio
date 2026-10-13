"""A child tab is drawn in its main tab's brand unless it has its own.

The brand is set once, on a dashboard's main tab; its child tabs carry none.
`family_brand_theme` is what the GET endpoints and the figure render read, so
a child tab and its figures follow the main tab's colours and palette.
"""

from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints import core_functions
from depictio.models.models.dashboards import DashboardData

TREC = {"primary": "#00a550", "secondary": "#1a4f8f"}


@pytest.fixture
def dashboards():
    db = mongomock.MongoClient()["depictio_test"]
    with patch.object(core_functions, "dashboards_collection", db["dashboards"]):
        yield db["dashboards"]


def _main(coll, brand_theme=None):
    oid = ObjectId()
    doc = {"_id": oid, "dashboard_id": oid, "is_main_tab": True}
    if brand_theme is not None:
        doc["brand_theme"] = brand_theme
    coll.insert_one(doc)
    return oid


def _child(parent_id, brand_theme=None):
    doc = {"dashboard_id": ObjectId(), "is_main_tab": False, "parent_dashboard_id": parent_id}
    if brand_theme is not None:
        doc["brand_theme"] = brand_theme
    return doc


class TestFamilyBrandTheme:
    def test_child_without_brand_takes_the_main_tabs(self, dashboards):
        parent = _main(dashboards, TREC)
        assert core_functions.family_brand_theme(_child(parent)) == TREC

    def test_child_override_wins(self, dashboards):
        parent = _main(dashboards, TREC)
        own = {"primary": "#ff0000"}
        assert core_functions.family_brand_theme(_child(parent, own)) == own

    def test_main_tab_keeps_its_own(self, dashboards):
        parent = _main(dashboards, TREC)
        assert core_functions.family_brand_theme(dashboards.find_one({"_id": parent})) == TREC

    def test_unbranded_family_inherits_nothing(self, dashboards):
        parent = _main(dashboards)
        assert core_functions.family_brand_theme(_child(parent)) is None

    def test_parent_id_as_string(self, dashboards):
        """GET passes a model dump, where the parent id may be a string."""
        parent = _main(dashboards, TREC)
        assert core_functions.family_brand_theme(_child(str(parent))) == TREC

    def test_missing_parent(self, dashboards):
        assert core_functions.family_brand_theme(_child(ObjectId())) is None


def test_inherited_brand_is_a_declared_runtime_field():
    """The editor saves back the document it loaded; an undeclared field would
    be rejected by the model, so the read-only field must be declared."""
    assert "inherited_brand_theme" in DashboardData.model_fields
