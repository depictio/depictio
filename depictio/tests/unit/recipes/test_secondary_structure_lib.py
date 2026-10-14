"""S4PRED ss2 parsing and secondary-structure runs."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes.lib.secondary_structure import SS2_SCHEMA, STATES, parse_ss2, segments

#: ``EXPECTED_SCHEMA`` of the s4pred catalog recipe (feat/nfcore-templates-lot3), copied
#: here so the shared parser is held to it: the recipe can only call it if they agree.
RECIPE_SCHEMA = {
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    "position": pl.Int64,
    "residue": pl.Utf8,
    "ss_code": pl.Utf8,
    "category": pl.Utf8,
    "value": pl.Float64,
    "p_coil": pl.Float64,
    "p_helix": pl.Float64,
    "p_strand": pl.Float64,
}

SS2 = """\
# PSIPRED VFORMAT (S4PRED V1.2.1)

   1 M C   0.900  0.050  0.050
   2 K H   0.100  0.800  0.100
   3 L H   0.330  0.340  0.330
   4 V E   0.100  0.200  0.700
   5 T E   0.200  0.100  0.700
   6 G C   0.400  0.350  0.250
"""


def test_schema_is_the_recipes_schema():
    assert list(SS2_SCHEMA) == list(RECIPE_SCHEMA)
    assert SS2_SCHEMA == RECIPE_SCHEMA
    assert STATES == {"H": "Helix", "E": "Strand", "C": "Coil"}
    frame = parse_ss2(SS2, "P12345")
    assert frame.columns == list(RECIPE_SCHEMA)
    assert dict(frame.schema) == RECIPE_SCHEMA


def test_parse_ss2_rows():
    frame = parse_ss2(SS2, "P12345")
    assert frame.height == 6  # header comment and blank line skipped
    assert frame["position"].to_list() == [1, 2, 3, 4, 5, 6]
    assert frame["residue"].to_list() == list("MKLVTG")
    assert frame["ss_code"].to_list() == list("CHHEEC")
    assert frame["category"].to_list() == ["Coil", "Helix", "Helix", "Strand", "Strand", "Coil"]
    assert frame["p_coil"].to_list() == [0.9, 0.1, 0.33, 0.1, 0.2, 0.4]
    assert frame["p_helix"].to_list() == [0.05, 0.8, 0.34, 0.2, 0.1, 0.35]
    assert frame["p_strand"].to_list() == [0.05, 0.1, 0.33, 0.7, 0.7, 0.25]


def test_value_is_the_probability_of_the_called_state():
    frame = parse_ss2(SS2, "P12345")
    assert frame["value"].to_list() == [0.9, 0.8, 0.34, 0.7, 0.7, 0.4]
    # residue 3 is called H although coil and strand are within 0.01: still p_helix
    assert frame.filter(pl.col("position") == 3)["value"].item() == 0.34


def test_entity_and_sample():
    frame = parse_ss2(SS2, "P12345")
    assert frame["entity"].unique().to_list() == ["P12345"]
    assert frame["sample"].unique().to_list() == ["P12345"]  # sample defaults to the entity
    named = parse_ss2(SS2, "P12345", sample="batch1")
    assert named["entity"].unique().to_list() == ["P12345"]
    assert named["sample"].unique().to_list() == ["batch1"]


def test_rows_are_sorted_by_position_and_malformed_lines_skipped():
    messy = "\n".join(
        [
            "# PSIPRED VFORMAT",
            "   3 L H 0.1 0.8 0.1",
            "   1 M C 0.9 0.05 0.05",
            "not a data line",
            "   2 K E 0.1 0.1 0.8",
            "",
        ]
    )
    frame = parse_ss2(messy, "s")
    assert frame["position"].to_list() == [1, 2, 3]
    assert frame["value"].to_list() == [0.9, 0.8, 0.8]


def test_unknown_state_and_short_lines_follow_the_recipe():
    frame = parse_ss2("1 M X 0.5 0.3 0.2\n2 K H 0.1\n", "s")
    first, second = frame.to_dicts()
    assert first["category"] is None and first["value"] == 0.5  # other states read p_coil
    assert second["p_coil"] == 0.1 and second["p_helix"] is None and second["value"] is None


def test_empty_input_gives_an_empty_frame_with_the_schema():
    frame = parse_ss2("# PSIPRED VFORMAT\n\n", "s")
    assert frame.height == 0
    assert dict(frame.schema) == RECIPE_SCHEMA


def test_segments_are_runs_of_identical_states():
    assert segments("CCHHHEEC") == [("C", 1, 2), ("H", 3, 5), ("E", 6, 7), ("C", 8, 8)]
    assert segments(["H", "H", "H"]) == [("H", 1, 3)]
    assert segments([]) == []
    assert segments("E") == [("E", 1, 1)]


def test_segments_from_a_parsed_frame():
    frame = parse_ss2(SS2, "P12345")
    assert segments(frame["ss_code"].to_list()) == [
        ("C", 1, 1),
        ("H", 2, 3),
        ("E", 4, 5),
        ("C", 6, 6),
    ]
    assert segments(frame["category"].to_list())[1] == ("Helix", 2, 3)


@pytest.mark.parametrize("states", ["", "H", "HE", "HHEECC"])
def test_segments_cover_every_residue_exactly_once(states):
    runs = segments(states)
    assert sum(end - start + 1 for _, start, end in runs) == len(states)
    assert all(a[2] + 1 == b[1] for a, b in zip(runs, runs[1:]))
    assert all(a[0] != b[0] for a, b in zip(runs, runs[1:]))
