"""`Project.layout`: the owner's correction of what the viewer detected.

None means "detect" (the viewer reads the workflows and runs); a value is the
owner's word. The vocabulary is closed because the viewer branches on it.
"""

import pytest
from pydantic import ValidationError

from depictio.models.models.projects import Project

OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.org"}


def _project(**overrides) -> Project:
    payload = {
        "name": "Demo",
        "permissions": {"owners": [OWNER], "editors": [], "viewers": []},
        **overrides,
    }
    return Project.model_validate(payload)


def test_defaults_to_detect():
    assert _project().layout is None


@pytest.mark.parametrize("value", ["runs", "pipeline", "tables"])
def test_accepts_the_three_layouts(value):
    assert _project(layout=value).layout == value


def test_rejects_an_unknown_layout():
    with pytest.raises(ValidationError):
        _project(layout="basic")


def test_it_round_trips_through_a_dump():
    """The viewer PUTs the whole project back; the override must survive it."""
    dumped = _project(layout="runs").model_dump()
    assert Project.model_validate(dumped).layout == "runs"
