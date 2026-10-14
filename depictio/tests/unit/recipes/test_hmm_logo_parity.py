"""The HMM logo tile computes letter heights in the browser; they must be HMMER's.

``packages/depictio-react-core/src/components/advanced_viz/logo/heights.ts``
ports :func:`depictio.recipes.lib.hmm.letter_heights` (itself a port of HMMER's
``hmmlogo.c``) so the tile can switch height modes without a refetch. Two
checks keep the port honest, without running JavaScript here:

* the Swiss-Prot 50.8 background table is parsed out of ``heights.ts`` and
  compared with :data:`BACKGROUND_AMINO` (1e-6);
* a JSON fixture of toy columns (amino and DNA) and their heights in every
  mode is recomputed with the Python and compared (1e-9). ``heights.test.ts``
  asserts the same fixture on the TypeScript side, so both implementations
  are pinned to one set of numbers.

Regenerate the fixture after changing the toy columns below (or the Python
formulas, which should then be a deliberate change), from the repository root::

    python - <<'EOF'
    import json
    from depictio.tests.unit.recipes.test_hmm_logo_parity import FIXTURE, build_fixture
    FIXTURE.write_text(json.dumps(build_fixture(), indent=2) + "\\n")
    EOF
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from depictio.recipes.lib.hmm import (
    AMINO_LETTERS,
    BACKGROUND_AMINO,
    LOGO_MODES,
    HmmModel,
    letter_heights,
)

REPO = Path(__file__).resolve().parents[4]
LOGO_DIR = (
    REPO / "packages" / "depictio-react-core" / "src" / "components" / "advanced_viz" / "logo"
)
HEIGHTS_TS = LOGO_DIR / "heights.ts"
FIXTURE = LOGO_DIR / "__fixtures__" / "heights.json"

TOLERANCE = 1e-9

_REST_OF_W = 0.1 / 19

#: Toy amino columns, letters in HMMER order (ACDEFGHIKLMNPQRSTVWY).
AMINO_COLUMNS: list[list[float]] = [
    # one dominant letter
    [_REST_OF_W] * 18 + [0.9, _REST_OF_W],
    # uniform: every letter above or below its background, RE small
    [0.05] * 20,
    # the background itself: RE = 0, nothing drawn in the entropy modes
    [BACKGROUND_AMINO[a] for a in AMINO_LETTERS],
    # acidic / basic mix with zero-probability letters (C, W, Y)
    [
        0.02,
        0.0,
        0.3,
        0.25,
        0.01,
        0.03,
        0.01,
        0.01,
        0.15,
        0.035,
        0.005,
        0.02,
        0.015,
        0.02,
        0.1,
        0.01,
        0.01,
        0.005,
        0.0,
        0.0,
    ],  # fmt: skip
    # two letters only
    [0.0] * 5 + [0.6] + [0.0] * 6 + [0.4] + [0.0] * 7,
    # a row that sums to 0.998, as five-decimal scores read back can
    [0.0499] * 20,
]

#: Toy DNA columns (ACGT, uniform background 1/4).
DNA_COLUMNS: list[list[float]] = [
    [0.7, 0.1, 0.1, 0.1],
    [0.25, 0.25, 0.25, 0.25],
    [0.0, 0.5, 0.5, 0.0],
    [0.97, 0.01, 0.01, 0.01],
]


def _model(name: str, letters: str, alphabet_type: str, columns: list[list[float]]) -> HmmModel:
    """A model whose match emissions are ``columns`` (the rest is filler)."""
    k, m = len(letters), len(columns)
    return HmmModel(
        name=name,
        length=m,
        alphabet=tuple(letters),
        alphabet_type=alphabet_type,
        match_emissions=[list(c) for c in columns],
        insert_emissions=[[1.0 / k] * k for _ in range(m + 1)],
        transitions=[[0.9, 0.05, 0.05, 0.6, 0.4, 0.7, 0.3] for _ in range(m + 1)],
    )


CASES = [
    ("amino", AMINO_LETTERS, "amino", "amino", AMINO_COLUMNS),
    ("dna", "ACGT", "DNA", "nucleic", DNA_COLUMNS),
]


def build_fixture() -> dict:
    """The fixture ``heights.test.ts`` and this module both assert."""
    cases = []
    for name, letters, alph, ts_alphabet, columns in CASES:
        model = _model(name, letters, alph, columns)
        modes = {}
        for mode in LOGO_MODES:
            result = letter_heights(model, mode)
            modes[mode] = {"heights": result.heights, "info": result.info_bits}
        cases.append(
            {
                "name": name,
                "alphabet": ts_alphabet,
                "letters": letters,
                "emissions": columns,
                "modes": modes,
            }
        )
    return {
        "generator": "depictio/tests/unit/recipes/test_hmm_logo_parity.py::build_fixture",
        "tolerance": TOLERANCE,
        "cases": cases,
    }


def _ts_background() -> dict[str, float]:
    src = HEIGHTS_TS.read_text()
    block = re.search(r"BACKGROUND_AMINO[^=]*=\s*\{(.*?)\};", src, re.DOTALL)
    assert block, "BACKGROUND_AMINO table not found in heights.ts"
    pairs = re.findall(r"^\s*([A-Z]):\s*([0-9.eE+-]+),?\s*$", block.group(1), re.MULTILINE)
    return {letter: float(value) for letter, value in pairs}


def test_background_table_matches_the_python():
    ts = _ts_background()
    assert set(ts) == set(BACKGROUND_AMINO)
    for letter, value in BACKGROUND_AMINO.items():
        assert ts[letter] == pytest.approx(value, abs=1e-6), letter


def test_fixture_covers_every_mode_and_both_alphabets():
    fixture = json.loads(FIXTURE.read_text())
    assert {c["alphabet"] for c in fixture["cases"]} == {"amino", "nucleic"}
    for case in fixture["cases"]:
        assert set(case["modes"]) == set(LOGO_MODES)


@pytest.mark.parametrize("case", [c[0] for c in CASES])
def test_fixture_heights_are_the_python_heights(case: str):
    """The committed fixture is what ``letter_heights`` computes today."""
    fixture = {c["name"]: c for c in json.loads(FIXTURE.read_text())["cases"]}[case]
    expected = {c["name"]: c for c in build_fixture()["cases"]}[case]
    assert fixture["letters"] == expected["letters"]
    for row_got, row_want in zip(fixture["emissions"], expected["emissions"], strict=True):
        assert row_got == pytest.approx(row_want, abs=TOLERANCE)
    for mode in LOGO_MODES:
        got, want = fixture["modes"][mode], expected["modes"][mode]
        assert got["info"] == pytest.approx(want["info"], abs=TOLERANCE), mode
        for row_got, row_want in zip(got["heights"], want["heights"], strict=True):
            assert row_got == pytest.approx(row_want, abs=TOLERANCE), mode


def test_the_fixture_exercises_the_redistribution():
    """``relent_abovebg`` keeps the full RE but zeroes letters under background."""
    fixture = {c["name"]: c for c in json.loads(FIXTURE.read_text())["cases"]}["amino"]
    mixed = 3
    above = fixture["modes"]["relent_abovebg"]
    every = fixture["modes"]["relent_all"]
    assert above["info"][mixed] == pytest.approx(every["info"][mixed])
    assert any(h == 0.0 for h, p in zip(above["heights"][mixed], AMINO_COLUMNS[mixed]) if p > 0)
    assert sum(above["heights"][mixed]) == pytest.approx(above["info"][mixed])
