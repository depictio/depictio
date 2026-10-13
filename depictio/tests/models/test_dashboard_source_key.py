"""`DashboardData.source_key`: stored on the full model, never in YAML."""

import yaml
from bson import ObjectId

from depictio.models.models.dashboards import DashboardData, DashboardDataLite

KEY = "nf-core/rnaseq:dashboards/base.yaml"


def _doc(**extra):
    return {
        "dashboard_id": ObjectId(),
        "project_id": ObjectId(),
        "title": "RNA-seq",
        "permissions": {"owners": [], "editors": [], "viewers": []},
        **extra,
    }


def test_documents_without_the_key_still_load():
    """Existing documents and `.db_seeds` JSON predate the field."""
    assert DashboardData.from_mongo(_doc()).source_key is None


def test_key_is_stored():
    dashboard = DashboardData.from_mongo(_doc(source_key=KEY))

    assert dashboard.source_key == KEY
    assert dashboard.mongo()["source_key"] == KEY


def test_export_does_not_carry_the_key():
    dashboard = DashboardData.from_mongo(_doc(source_key=KEY))

    assert "source_key" not in DashboardDataLite.model_fields
    assert "source_key" not in dashboard.to_yaml()


def test_yaml_cannot_set_the_key():
    """The lite model allows extras; `to_full` must not pass this one through."""
    lite = DashboardDataLite.from_yaml(yaml.safe_dump({"title": "RNA-seq", "source_key": KEY}))

    assert "source_key" not in lite.to_full()
