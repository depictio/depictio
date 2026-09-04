"""`Project.triggered_by`: an open vocabulary that must not fragment.

The field records what invoked an ingestion, as opposed to `engine_name`, which
records what produced the data and reads "nextflow" even for a hand-typed run.
It is a plain string so a new trigger needs no migration, which only works as
long as spelling variants collapse to one value.
"""

import pytest

from depictio.models.models.projects import Project

OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.org"}


def _project(**overrides) -> Project:
    payload = {
        "name": "Demo",
        "permissions": {"owners": [OWNER], "editors": [], "viewers": []},
        **overrides,
    }
    return Project.model_validate(payload)


def test_defaults_to_manual():
    assert _project().triggered_by == "manual"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("nextflow", "nextflow"),
        ("Nextflow", "nextflow"),
        ("  NEXTFLOW  ", "nextflow"),
        ("snakemake", "snakemake"),
        ("", "manual"),
        ("   ", "manual"),
        (None, "manual"),
    ],
)
def test_normalisation(raw, expected):
    assert _project(triggered_by=raw).triggered_by == expected


def test_an_unknown_trigger_is_accepted():
    """No enum, so a future trigger works without touching the model."""
    assert _project(triggered_by="directory-watcher").triggered_by == "directory-watcher"


def test_it_round_trips_through_a_dump():
    """The CLI sends the project as a dict; the value has to survive that."""
    dumped = _project(triggered_by="Nextflow").model_dump()
    assert dumped["triggered_by"] == "nextflow"
    assert Project.model_validate(dumped).triggered_by == "nextflow"
