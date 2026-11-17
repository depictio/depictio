"""A run takes its group's colour only when the run is that group (epic #1399)."""

from __future__ import annotations

import pytest

from depictio.api.v1.services.changes import run_colors as rc

COLLECTIONS = {"dc-meta": {"workflow_id": "wf"}, "dc-taxa": {"workflow_id": "wf"}}
PINNED = {"locality": {"Athens": "#blue", "Barcelona": "#orange", "Naples": "#green"}}


@pytest.fixture
def tables(monkeypatch):
    """`locality` read from a small metadata table, by run."""
    state = {
        "values": {
            "run_athens": {"Athens"},
            "run_barcelona": {"Barcelona"},
        },
        "reads": [],
    }
    monkeypatch.setattr(
        rc,
        "_latest_columns",
        lambda _ids: [
            ("dc-taxa", 3, 90_000, {"Phylum", "depictio_run_id", "locality"}),
            ("dc-meta", 2, 71, {"locality", "depictio_run_id"}),
        ],
    )

    def values(wf_id, dc_id, version, column):
        state["reads"].append((dc_id, version, column))
        return tuple((run, frozenset(v)) for run, v in state["values"].items())

    monkeypatch.setattr(rc, "_values_by_run", values)
    return state


def test_each_run_that_is_one_group_takes_its_colour(tables):
    out = rc.group_run_colors(["run_athens", "run_barcelona"], PINNED, COLLECTIONS)
    assert out == {"run_athens": "#blue", "run_barcelona": "#orange"}
    # The smallest table holding the column is the one read.
    assert tables["reads"] == [("dc-meta", 2, "locality")]


def test_a_run_mixing_groups_gets_none(tables):
    tables["values"]["run_naples"] = {"Naples", "Athens"}
    out = rc.group_run_colors(["run_barcelona", "run_naples"], PINNED, COLLECTIONS)
    assert out == {"run_barcelona": "#orange"}


def test_a_group_held_by_two_runs_colours_neither(tables):
    tables["values"]["run_athens_bis"] = {"Athens"}
    out = rc.group_run_colors(["run_athens", "run_athens_bis"], PINNED, COLLECTIONS)
    assert out == {}


def test_a_value_without_a_pinned_colour_gets_none(tables):
    tables["values"]["run_rome"] = {"Rome"}
    assert rc.group_run_colors(["run_rome"], PINNED, COLLECTIONS) == {}


def test_no_pinned_colours_reads_nothing(tables):
    assert rc.group_run_colors(["run_athens"], {}, COLLECTIONS) == {}
    assert rc.group_run_colors(["run_athens"], None, COLLECTIONS) == {}
    assert tables["reads"] == []
