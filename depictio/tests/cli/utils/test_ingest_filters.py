"""The scan and the processing refuse a data collection tag no workflow has, and a
template warns only about the --var values the user passed."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from depictio.cli.cli.utils.process import process_project_data_collections
from depictio.cli.cli.utils.scan import scan_project_files
from depictio.cli.cli.utils.templates import resolve_template
from depictio.models.models.projects import Project

OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.org"}


def _project(tmp_path) -> Project:
    return Project.model_validate(
        {
            "name": "Two Workflows",
            "permissions": {"owners": [OWNER], "editors": [], "viewers": []},
            "workflows": [
                {
                    "name": name,
                    "engine": {"name": "python"},
                    "data_location": {"structure": "flat", "locations": [str(tmp_path)]},
                    "data_collections": [
                        {
                            "data_collection_tag": tag,
                            "config": {
                                "type": "Table",
                                "scan": {
                                    "mode": "recursive",
                                    "scan_parameters": {"regex_config": {"pattern": "x.csv"}},
                                },
                                "dc_specific_properties": {"format": "CSV"},
                            },
                        }
                    ],
                }
                for name, tag in (("first", "samples"), ("second", "counts"))
            ],
        }
    )


@pytest.mark.parametrize(
    "run",
    [
        pytest.param(
            lambda project: scan_project_files(project, MagicMock(), data_collection_tag="nope"),
            id="scan",
        ),
        pytest.param(
            lambda project: process_project_data_collections(
                MagicMock(), project, data_collection_tag="nope"
            ),
            id="process",
        ),
    ],
)
def test_a_tag_no_workflow_has_is_an_error(tmp_path, run):
    with pytest.raises(
        Exception, match="Data collection 'nope' not found in project. Known: samples, counts"
    ):
        run(_project(tmp_path))


def test_a_workflow_without_the_tag_is_skipped_quietly(tmp_path):
    """The tag is in the second workflow: the first is not the one asked for."""
    project = _project(tmp_path)
    ingest = MagicMock(return_value=[])
    with patch("depictio.cli.cli.utils.process._ingest_data_collections", ingest):
        result = process_project_data_collections(
            MagicMock(), project, data_collection_tag="counts"
        )

    assert result["total_failed"] == 0
    (call,) = ingest.call_args_list
    assert [dc.data_collection_tag for dc in call.kwargs["data_collections"]] == ["counts"]


def test_only_the_vars_the_user_passed_are_warned_about(tmp_path):
    logger = MagicMock()
    with patch("depictio.cli.cli.utils.templates.logger", logger):
        try:
            # rnaseq declares none of the defaults filled in for it (GROUP_COL,
            # METADATA_ID_COL, SKIP_ANCOM), which all used to be warned about.
            resolve_template(
                "nf-core/rnaseq/latest",
                str(tmp_path),
                extra_vars={"NOT_DECLARED": "x"},
            )
        except Exception:
            # An empty data root may fail later on; the warnings come first.
            pass

    warned = [
        str(call.args[0])
        for call in logger.warning.call_args_list
        if "provided via --var" in str(call.args[0])
    ]
    assert warned == ["Variable 'NOT_DECLARED' provided via --var but not declared in template"]
