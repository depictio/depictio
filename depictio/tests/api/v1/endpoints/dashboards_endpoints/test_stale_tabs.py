"""A re-imported multi-tab dashboard keeps only the tabs its YAML still has."""

from __future__ import annotations

import mongomock
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints.routes import _drop_stale_tabs


def test_a_renamed_tab_does_not_stay_next_to_its_successor():
    dashboards = mongomock.MongoClient().db.dashboards
    project, main, other_main = ObjectId(), ObjectId(), ObjectId()
    kept, renamed, failed_update = ObjectId(), ObjectId(), ObjectId()
    dashboards.insert_many(
        [
            {"_id": main, "project_id": project, "is_main_tab": True},
            {
                "_id": kept,
                "project_id": project,
                "parent_dashboard_id": main,
                "title": "MultiQC (test_aws)",
            },
            # Its old title: the composed dashboard renamed it.
            {
                "_id": renamed,
                "project_id": project,
                "parent_dashboard_id": main,
                "title": "MultiQC (test_aws/multiqc/multiqc_data/multiqc.parquet)",
            },
            # Named by the YAML, but its update failed: not stale.
            {
                "_id": failed_update,
                "project_id": project,
                "parent_dashboard_id": main,
                "title": "QC",
            },
            # Another family's tab.
            {
                "_id": ObjectId(),
                "project_id": project,
                "parent_dashboard_id": other_main,
                "title": "X",
            },
        ]
    )

    deleted = _drop_stale_tabs(dashboards, main, str(project), keep={kept, failed_update})

    assert deleted == 1
    assert dashboards.find_one({"_id": renamed}) is None
    assert {d["_id"] for d in dashboards.find()} == {
        main,
        kept,
        failed_update,
        *[d["_id"] for d in dashboards.find({"parent_dashboard_id": other_main})],
    }
