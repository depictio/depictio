"""Fixtures shared by the `depictio-cli run` tests.

The CLI package's CI job installs only `depictio.cli` and `depictio.models`, so
one test module cannot import a helper from another through `depictio.tests`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from depictio.models.models.projects import Project

OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.org"}


def _project(locations: list[str]) -> Project:
    return Project.model_validate(
        {
            "name": "Ampliseq Microbial Community Analysis",
            "project_type": "advanced",
            "permissions": {"owners": [OWNER], "editors": [], "viewers": []},
            "workflows": [
                {
                    "name": "ampliseq",
                    "engine": {"name": "nextflow"},
                    "catalog": {"name": "nf-core", "url": "https://nf-co.re"},
                    "data_location": {"structure": "flat", "locations": list(locations)},
                    "data_collections": [
                        {
                            "data_collection_tag": "asv_table",
                            "config": {
                                "type": "Table",
                                "scan": {
                                    "mode": "recursive",
                                    "scan_parameters": {
                                        "regex_config": {"pattern": "asv_table.tsv$"}
                                    },
                                },
                                "dc_specific_properties": {
                                    "format": "TSV",
                                    "polars_kwargs": {"separator": "\t"},
                                },
                            },
                        }
                    ],
                }
            ],
        }
    )


class _Harness:
    """Every mock the run pipeline needs, plus the recorded call arguments."""

    def __init__(self, data_root, remote_locations: list[str], project_found: bool = True):
        self.project = _project([str(data_root)])
        self.remote_doc = {
            "name": self.project.name,
            "hash": None,
            "workflows": [
                {
                    "workflow_tag": self.project.workflows[0].workflow_tag,
                    "data_location": {"structure": "flat", "locations": remote_locations},
                    "data_collections": [],
                }
            ],
        }
        self.project_found = project_found
        self.sync = MagicMock(return_value={"action": "updated"})
        self.scan = MagicMock(return_value={"result": "success"})
        self.process = MagicMock(return_value={"total_failed": 0})
        self.import_dashboards = MagicMock(return_value=[])

    def _get_project(self, *args, **kwargs):
        response = MagicMock()
        response.status_code = 200 if self.project_found else 404
        response.json.return_value = self.remote_doc
        return response

    def patches(self):
        template_meta = MagicMock()
        template_meta.template_id = "nf-core/ampliseq/2.16.0"
        resolve = getattr(self, "resolve", None) or MagicMock(
            return_value=({"name": self.project.name, "workflows": []}, template_meta, {}, [], {})
        )
        validate = MagicMock(
            return_value=(MagicMock(), {"success": True, "project_config": self.project})
        )
        return [
            patch("depictio.cli.cli.utils.templates.resolve_template", resolve),
            patch("depictio.cli.cli.utils.config.validate_template_project_config", validate),
            patch("depictio.cli.cli.commands.run.api_get_project_from_name", self._get_project),
            patch("depictio.cli.cli.commands.run.api_sync_project_config_to_server", self.sync),
            patch("depictio.cli.cli.commands.run.scan_project_files", self.scan),
            patch("depictio.cli.cli.commands.run.process_project_helper", self.process),
            patch("depictio.cli.cli.commands.run.api_monitoring_ingestion_start", MagicMock()),
            patch("depictio.cli.cli.commands.run.api_monitoring_ingestion_finish", MagicMock()),
            patch("depictio.cli.cli.commands.run.generate_api_headers", MagicMock(return_value={})),
            patch(
                "depictio.cli.cli.utils.templates.import_dashboards_from_template",
                self.import_dashboards,
            ),
        ]


@pytest.fixture
def make_harness():
    """The run harness class: `make_harness(data_root, remote_locations=[...])`."""
    return _Harness
