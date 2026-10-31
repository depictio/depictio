"""`DashboardData.template_origin`: stored on the full model, never in YAML or a version."""

import pytest
import yaml
from bson import ObjectId
from pydantic import ValidationError

from depictio.models.models.dashboards import DashboardData, DashboardDataLite
from depictio.models.models.templates import DashboardTemplateOrigin

ORIGIN = {
    "template_id": "nf-core/nascent/2.3.0",
    "template_version": "1.2.0",
    "imported_at": "2026-10-29 10:14:00",
}


def _doc(**extra):
    return {
        "dashboard_id": ObjectId(),
        "project_id": ObjectId(),
        "title": "Nascent",
        "permissions": {"owners": [], "editors": [], "viewers": []},
        **extra,
    }


class TestDashboardTemplateOrigin:
    def test_it_stamps_the_import_time_in_utc(self):
        origin = DashboardTemplateOrigin(
            template_id="nf-core/nascent/2.3.0", template_version="1.0.0"
        )

        # Naive UTC "%Y-%m-%d %H:%M:%S", like every other API timestamp.
        assert len(origin.imported_at) == 19
        assert origin.imported_at[10] == " "

    @pytest.mark.parametrize("field", ["template_id", "template_version"])
    def test_it_names_a_template_and_a_revision(self, field):
        values = {"template_id": "nf-core/nascent/2.3.0", "template_version": "1.0.0"}
        values[field] = "  "

        with pytest.raises(ValidationError):
            DashboardTemplateOrigin(**values)


class TestDashboardField:
    def test_documents_without_it_still_load(self):
        """Existing documents and `.db_seeds` JSON predate the field."""
        assert DashboardData.from_mongo(_doc()).template_origin is None

    def test_it_is_stored(self):
        dashboard = DashboardData.from_mongo(_doc(template_origin=ORIGIN))

        assert dashboard.template_origin is not None
        assert dashboard.template_origin.template_version == "1.2.0"
        assert dashboard.mongo()["template_origin"] == ORIGIN

    def test_it_round_trips_through_the_api_serialisation(self):
        dumped = DashboardData.from_mongo(_doc(template_origin=ORIGIN)).model_dump()

        assert dumped["template_origin"] == ORIGIN

    def test_export_does_not_carry_it(self):
        dashboard = DashboardData.from_mongo(_doc(template_origin=ORIGIN))

        assert "template_origin" not in DashboardDataLite.model_fields
        assert "template_origin" not in dashboard.to_yaml()

    def test_yaml_cannot_set_it(self):
        """The lite model allows extras; `to_full` must not pass this one through."""
        lite = DashboardDataLite.from_yaml(
            yaml.safe_dump({"title": "Nascent", "template_origin": ORIGIN})
        )

        assert "template_origin" not in lite.to_full()


class TestNotContent:
    @pytest.fixture(autouse=True)
    def _server_extra(self):
        # The versioning module reads the API config, which needs the server extra.
        pytest.importorskip("cryptography")

    def test_it_is_excluded_from_snapshots_on_purpose(self):
        from depictio.api.v1.endpoints.dashboards_endpoints.versioning import (
            SNAPSHOT_EXCLUDED_FIELDS,
            SNAPSHOT_PROVENANCE_FIELDS,
        )
        from depictio.models.models.dashboard_versions import TabSnapshot

        assert "template_origin" in SNAPSHOT_PROVENANCE_FIELDS
        assert "template_origin" in SNAPSHOT_EXCLUDED_FIELDS
        assert "template_origin" not in TabSnapshot.model_fields

    def test_a_snapshot_is_the_same_whatever_the_stamp(self):
        from depictio.api.v1.endpoints.dashboards_endpoints.versioning import (
            build_tab_snapshots,
            compute_content_hash,
        )

        plain = _doc()
        stamped = {**plain, "template_origin": ORIGIN}
        restamped = {**plain, "template_origin": {**ORIGIN, "template_version": "9.0.0"}}

        hashes = {
            compute_content_hash(build_tab_snapshots([doc])) for doc in (plain, stamped, restamped)
        }

        assert len(hashes) == 1

    def test_the_export_revision_ignores_it(self):
        from depictio.api.v1.services.export.revision import _definition_fallback

        plain = _doc()

        assert _definition_fallback(plain) == _definition_fallback(
            {**plain, "template_origin": ORIGIN}
        )
