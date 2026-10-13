"""A child tab reads its main tab's `category_colors`, apart from its own.

Category colours are declared once, on the main tab, and must hold on every
tab: a filter bar fanned out to a sibling tab, or a figure drawn there, has to
give "Athens" the colour the main tab pinned. The GET endpoints send them as
`inherited_category_colors`, which the client lays the tab's own map over.
"""

from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints import core_functions
from depictio.models.models.dashboards import DashboardData

COLORS = {"locality": {"Athens": "#1c7ed6", "Naples": "#e8590c"}}


@pytest.fixture
def dashboards():
    db = mongomock.MongoClient()["depictio_test"]
    with patch.object(core_functions, "dashboards_collection", db["dashboards"]):
        yield db["dashboards"]


def _main(coll, category_colors=None):
    oid = ObjectId()
    doc = {"_id": oid, "dashboard_id": oid, "is_main_tab": True}
    if category_colors is not None:
        doc["category_colors"] = category_colors
    coll.insert_one(doc)
    return oid


def _child(parent_id, category_colors=None):
    doc = {"dashboard_id": ObjectId(), "is_main_tab": False, "parent_dashboard_id": parent_id}
    if category_colors is not None:
        doc["category_colors"] = category_colors
    return doc


class TestFamilyCategoryColors:
    def test_child_reads_the_main_tabs(self, dashboards):
        parent = _main(dashboards, COLORS)
        assert core_functions.family_category_colors(_child(parent)) == COLORS

    def test_child_with_its_own_still_gets_the_main_tabs(self, dashboards):
        """Unlike the brand, the two are merged client-side per value, so the
        main tab's map is sent even when the child pins some colours itself."""
        parent = _main(dashboards, COLORS)
        own = {"locality": {"Athens": "#000000"}}
        assert core_functions.family_category_colors(_child(parent, own)) == COLORS

    def test_main_tab_inherits_nothing(self, dashboards):
        parent = _main(dashboards, COLORS)
        assert core_functions.family_category_colors(dashboards.find_one({"_id": parent})) is None

    def test_parent_without_colours(self, dashboards):
        parent = _main(dashboards)
        assert core_functions.family_category_colors(_child(parent)) is None

    def test_parent_id_as_string(self, dashboards):
        parent = _main(dashboards, COLORS)
        assert core_functions.family_category_colors(_child(str(parent))) == COLORS

    def test_missing_parent(self, dashboards):
        assert core_functions.family_category_colors(_child(ObjectId())) is None


def test_inherited_colours_are_a_declared_runtime_field():
    """The editor saves back the document it loaded; an undeclared field would
    be rejected by the model, so the read-only field must be declared."""
    assert "inherited_category_colors" in DashboardData.model_fields
