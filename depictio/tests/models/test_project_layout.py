"""Project.layout: the user override of the detected layout."""

import pytest
from bson import ObjectId
from pydantic import ValidationError

from depictio.models.models.projects import Project


def _project(**extra) -> Project:
    owner = {"_id": ObjectId(), "email": "owner@example.com"}
    return Project(
        name="layout_project",
        project_type="basic",
        permissions={"owners": [owner], "editors": [], "viewers": []},  # type: ignore[arg-type]
        **extra,
    )


def test_layout_defaults_to_none():
    assert _project().layout is None


@pytest.mark.parametrize("layout", ["runs", "pipeline", "tables"])
def test_layout_accepts_known_values(layout):
    assert _project(layout=layout).layout == layout


def test_layout_rejects_unknown_value():
    with pytest.raises(ValidationError):
        _project(layout="basic")


def test_layout_survives_dump_round_trip():
    project = _project(layout="pipeline")
    assert project.model_dump()["layout"] == "pipeline"
    assert project.mongo()["layout"] == "pipeline"
    assert Project(**project.model_dump()).layout == "pipeline"
