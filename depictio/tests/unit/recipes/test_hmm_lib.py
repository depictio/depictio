"""HMMER3 profile parser, logo heights, occupancy and reference mapping.

Everything is inline: one literal ``HMMER3/f`` file written the way HMMER lays it
out (header tags, STATS lines, COMPO line, ``*`` scores), models built from known
probabilities and written back with ``format_hmm``, and hand-written Stockholm
alignments in the shape ``hmmalign`` produces.
"""

from __future__ import annotations

import gzip
import math
import re

import polars as pl
import pytest

from depictio.recipes.lib.hmm import (
    BACKGROUND_AMINO,
    LOGO_MODES,
    PROFILE_SCHEMA,
    T_DD,
    T_MD,
    T_MI,
    HmmModel,
    background_frequencies,
    delete_probability,
    expected_insert_length,
    format_hmm,
    insert_probability,
    letter_heights,
    occupancy,
    parse_hmm,
    profile_frame,
    read_hmm,
    reference_positions_from_map,
    reference_positions_from_stockholm,
)

LETTERS = tuple("ACDEFGHIKLMNPQRSTVWY")

HEADER = """\
HMMER3/f [3.1b2 | February 2015]
NAME  FAM001
ACC   PF99999.1
DESC  Toy family for the unit tests
LENG  3
MAXL  12
ALPH  amino
RF    no
MM    no
CONS  yes
CS    no
MAP   yes
DATE  Mon Jan  5 10:00:00 2026
COM   [1] hmmbuild --amino fam001.hmm fam001.fa
NSEQ  12
EFFN  3.500000
CKSUM 1234567890
STATS LOCAL MSV       -9.1234  0.70000
STATS LOCAL VITERBI   -9.4567  0.70000
STATS LOCAL FORWARD   -3.4321  0.70000
"""

#: Scores are -ln(p): node 1 is 80% A, node 2 45% L + 35% I, node 3 60% W;
#: node 0 begins with M 0.90, I 0.05, D 0.05 and the last node has no M->I / M->D.
BODY = """\
HMM          A        C        D        E        F        G        H        I        K        L        M        N        P        Q        R        S        T        V        W        Y
            m->m     m->i     m->d     i->m     i->i     d->m     d->d
  COMPO   2.30259  3.13883  3.13883  3.13883  3.13883  3.13883  3.13883  3.13883  3.13883  2.12026  3.13883  3.13883  3.13883  3.13883  3.13883  3.13883  3.13883  3.13883  3.13883  3.13883
          2.52573  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  2.30259  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882
          0.10536  2.99573  2.99573  0.51083  0.91629  0.00000        *
      1   0.22314  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388  4.55388      4 A - - -
          2.52573  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  2.30259  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882
          0.22314  2.30259  2.30259  0.35667  1.20397  0.51083  0.91629
      2   4.49981  4.49981  4.49981  4.49981  4.49981  4.49981  4.49981  1.04982  4.49981  0.79851  4.49981  4.49981  4.49981  4.49981  4.49981  4.49981  4.49981  4.49981  4.49981  4.49981      5 l - - -
          2.52573  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  2.30259  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882
          0.35667  1.60944  2.30259  0.69315  0.69315  0.69315  0.69315
      3   3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  3.86073  0.51083  3.86073      7 W - - -
          2.52573  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  2.30259  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882  3.08882
          0.00000        *        *  0.69315  0.69315  0.00000        *
//
"""

HMM_TEXT = HEADER + BODY

#: The transitions of the fixture, node 0..3, order mm mi md im ii dm dd.
TRANS = [
    [0.9, 0.05, 0.05, 0.6, 0.4, 1.0, 0.0],
    [0.8, 0.1, 0.1, 0.7, 0.3, 0.6, 0.4],
    [0.7, 0.2, 0.1, 0.5, 0.5, 0.5, 0.5],
    [1.0, 0.0, 0.0, 0.5, 0.5, 1.0, 0.0],
]


def _dist(top: dict[str, float]) -> list[float]:
    rest = (1.0 - sum(top.values())) / (len(LETTERS) - len(top))
    return [top.get(a, rest) for a in LETTERS]


def _toy_model(**overrides) -> HmmModel:
    """The fixture's model, built from exact probabilities and fully annotated."""
    fields = {
        "name": "TOY",
        "acc": "PF00001.1",
        "desc": "toy family",
        "length": 3,
        "alphabet": LETTERS,
        "match_emissions": [
            _dist({"A": 0.8}),
            _dist({"L": 0.45, "I": 0.35}),
            _dist({"W": 0.6}),
        ],
        "insert_emissions": [_dist({"A": 0.08, "L": 0.1})] * 4,
        "transitions": [list(row) for row in TRANS],
        "map_columns": [4, 5, 7],
        "consensus": ["A", "l", "W"],
        "rf": ["x", "x", "x"],
        "mm": [None, "m", None],
        "cs": ["H", "H", "E"],
        "nseq": 12,
        "effn": 3.5,
        "compo": _dist({"A": 0.1, "L": 0.12}),
    }
    fields.update(overrides)
    return HmmModel(**fields)


def _relent(row: list[float]) -> float:
    return sum(p * math.log2(p / BACKGROUND_AMINO[a]) for p, a in zip(row, LETTERS) if p > 0)


def _as_format(text: str, letter: str) -> str:
    """Rewrite the ``HMMER3/f`` fixture as an older format by dropping the columns it lacked."""
    out = []
    for line in text.splitlines():
        if line.startswith("HMMER3/"):
            line = f"HMMER3/{letter} [3.0 | March 2010; reverse compatibility mode]"
        elif line.startswith("MM ") and letter < "f":
            continue
        elif line.startswith("CONS") and letter < "e":
            continue
        else:
            tokens = line.split()
            if tokens and tokens[0].isdigit() and len(tokens) == 1 + 20 + 5:
                scores, (map_, cons, rf, mm, cs) = tokens[:21], tokens[21:]
                keep = [map_] + ([cons] if letter >= "e" else []) + [rf]
                keep += [mm] if letter >= "f" else []
                line = " ".join(scores + keep + [cs])
        out.append(line)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_literal_hmmer3f_file():
    (model,) = parse_hmm(HMM_TEXT)
    assert (model.name, model.acc, model.desc) == (
        "FAM001",
        "PF99999.1",
        "Toy family for the unit tests",
    )
    assert model.length == 3
    assert model.alphabet == LETTERS
    assert model.alphabet_type == "amino"
    assert (model.nseq, model.effn) == (12, 3.5)
    assert model.map_columns == [4, 5, 7]
    assert model.consensus == ["A", "l", "W"]
    assert model.rf == model.mm == model.cs == [None, None, None]
    assert model.compo is not None
    assert len(model.compo) == 20
    assert model.compo[0] == pytest.approx(0.1, abs=1e-4)
    assert model.compo[LETTERS.index("L")] == pytest.approx(0.12, abs=1e-4)

    m = model.match_emissions
    assert len(m) == 3 and all(len(row) == 20 for row in m)
    assert m[0][LETTERS.index("A")] == pytest.approx(0.8, abs=1e-4)
    assert m[1][LETTERS.index("L")] == pytest.approx(0.45, abs=1e-4)
    assert m[1][LETTERS.index("I")] == pytest.approx(0.35, abs=1e-4)
    assert m[2][LETTERS.index("W")] == pytest.approx(0.6, abs=1e-4)
    assert all(sum(row) == pytest.approx(1.0, abs=1e-3) for row in m)

    assert len(model.insert_emissions) == 4  # node 0..M
    assert len(model.transitions) == 4
    for parsed, expected in zip(model.transitions, TRANS):
        assert parsed == pytest.approx(expected, abs=1e-4)


def test_star_score_is_exactly_zero_probability():
    (model,) = parse_hmm(HMM_TEXT)
    assert model.transitions[0][T_DD] == 0.0  # node 0, d->d
    assert model.transitions[3][T_MI] == 0.0  # last node, m->i
    assert model.transitions[3][T_MD] == 0.0


def test_library_of_two_models():
    second = HMM_TEXT.replace("NAME  FAM001", "NAME  FAM002").replace("PF99999.1", "PF99998.1")
    models = parse_hmm(HMM_TEXT + "\n" + second)
    assert [m.name for m in models] == ["FAM001", "FAM002"]
    assert [m.acc for m in models] == ["PF99999.1", "PF99998.1"]
    assert models[0].match_emissions == models[1].match_emissions


def test_read_hmm_handles_gzip_by_content_and_plain_files(tmp_path):
    library = HMM_TEXT + HMM_TEXT.replace("NAME  FAM001", "NAME  FAM002")
    gz = tmp_path / "sample.lib.gz"
    gz.write_bytes(gzip.compress(library.encode()))
    assert [m.name for m in read_hmm(gz)] == ["FAM001", "FAM002"]
    # no .gz extension: the magic bytes decide
    disguised = tmp_path / "fam.hmm"
    disguised.write_bytes(gzip.compress(HMM_TEXT.encode()))
    assert [m.name for m in read_hmm(disguised)] == ["FAM001"]
    plain = tmp_path / "plain.hmm"
    plain.write_text(HMM_TEXT)
    assert [m.name for m in read_hmm(str(plain))] == ["FAM001"]


def test_hmmer3e_has_no_mm_column():
    text = _as_format(HMM_TEXT, "e")
    assert text.startswith("HMMER3/e") and "\nMM " not in text
    (model,) = parse_hmm(text)
    (reference,) = parse_hmm(HMM_TEXT)
    assert model.mm == [None, None, None]
    assert model.consensus == ["A", "l", "W"]
    assert model.map_columns == [4, 5, 7]
    assert model.match_emissions == reference.match_emissions
    assert model.transitions == reference.transitions


@pytest.mark.parametrize("letter", ["a", "b", "c", "d"])
def test_older_formats_have_no_consensus_column(letter):
    """Before 3/e HMMER computes the consensus from the emissions: upper case from 0.5."""
    text = _as_format(HMM_TEXT, letter)
    assert text.startswith(f"HMMER3/{letter}") and "\nCONS" not in text
    (model,) = parse_hmm(text)
    assert model.consensus == ["A", "l", "W"]  # node 2 tops out at 0.45: lower case
    assert model.map_columns == [4, 5, 7]
    assert model.rf == model.mm == model.cs == [None, None, None]


def test_annotation_columns_are_read_in_3f_order():
    text = HMM_TEXT.replace("RF    no", "RF    yes").replace("CS    no", "CS    yes")
    text = text.replace("MM    no", "MM    yes")
    text = text.replace("      4 A - - -", "      4 A x . H").replace(
        "      5 l - - -", "      5 l x m E"
    )
    (model,) = parse_hmm(text)
    assert model.rf == ["x", "x", None]
    assert model.mm == [".", "m", None]
    assert model.cs == ["H", "E", None]
    assert model.consensus == ["A", "l", "W"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda t: t.replace("HMMER3/f", "HMMER3/z", 1), "format tag"),
        (lambda t: t.replace("HMMER3/f", "HMMER2.0", 1), "HMMER2"),
        (lambda t: t.rsplit("//", 1)[0], "truncated"),
        (lambda t: "", "no HMMER3 record"),
        (lambda t: t.replace("NAME  FAM001\n", ""), "NAME"),
        (lambda t: t.replace("LENG  3", "LENG  4"), "premature end"),
        (lambda t: t.replace("      2   4.49981", "      9   4.49981"), "node 2"),
        (lambda t: t.replace("      7 W - - -", "      7 W - - - -"), "annotation columns"),
        (lambda t: t.replace("0.51083  3.86073", "oops  3.86073"), "not a score"),
        (lambda t: t.replace("ALPH  amino", "ALPH  DNA"), "needs 4 letters"),
    ],
)
def test_malformed_files_raise_value_error(mutate, message):
    with pytest.raises(ValueError, match=message):
        parse_hmm(mutate(HMM_TEXT))


def test_model_shape_is_validated():
    with pytest.raises(ValueError, match="transition table"):
        _toy_model(transitions=TRANS[:3])
    with pytest.raises(ValueError, match="rf has 2 entries"):
        _toy_model(rf=["x", "x"])


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_format_hmm_round_trips_an_annotated_model():
    model = _toy_model()
    text = format_hmm(model)
    assert text.startswith("HMMER3/f ") and text.rstrip().endswith("//")
    for line in ("ALPH  amino", "RF    yes", "MM    yes", "CONS  yes", "CS    yes", "MAP   yes"):
        assert line in text.splitlines()
    assert any(tok == "*" for tok in text.split())  # probability 0 -> '*'
    (back,) = parse_hmm(text)
    assert (back.name, back.acc, back.desc, back.length) == ("TOY", "PF00001.1", "toy family", 3)
    assert (back.map_columns, back.consensus) == (model.map_columns, model.consensus)
    assert (back.rf, back.mm, back.cs) == (model.rf, model.mm, model.cs)
    assert (back.nseq, back.effn) == (12, 3.5)
    for got, want in (
        (back.match_emissions, model.match_emissions),
        (back.insert_emissions, model.insert_emissions),
        (back.transitions, model.transitions),
    ):
        for got_row, want_row in zip(got, want):
            assert got_row == pytest.approx(want_row, abs=1e-5)
    assert back.compo == pytest.approx(model.compo, abs=1e-5)
    assert back.transitions[3][T_MI] == 0.0


def test_format_hmm_without_annotations_writes_no_flags():
    bare = _toy_model(
        acc=None,
        desc=None,
        map_columns=[],
        consensus=[],
        rf=[],
        mm=[],
        cs=[],
        nseq=None,
        effn=None,
        compo=None,
    )
    text = format_hmm(bare)
    lines = text.splitlines()
    for line in ("RF    no", "MM    no", "CONS  no", "CS    no", "MAP   no"):
        assert line in lines
    assert not any(line.startswith(("ACC", "DESC", "NSEQ", "EFFN", "  COMPO")) for line in lines)
    (back,) = parse_hmm(text)
    assert back.acc is None and back.desc is None and back.compo is None
    assert back.nseq is None and back.effn is None
    assert back.map_columns == back.consensus == back.rf == back.mm == back.cs == [None] * 3


def test_zero_emissions_survive_a_round_trip():
    first = _dist({"A": 0.7, "C": 0.3})  # the other 18 letters have probability 0
    model = _toy_model(match_emissions=[first, _dist({"L": 0.45, "I": 0.35}), _dist({"W": 0.6})])
    assert 0.0 in first
    (back,) = parse_hmm(format_hmm(model))
    assert back.match_emissions[0].count(0.0) == 18
    heights = letter_heights(back, "relent_all").heights[0]
    assert all(math.isfinite(h) for h in heights)
    assert heights.count(0.0) == 18


# ---------------------------------------------------------------------------
# Background, occupancy, indel values
# ---------------------------------------------------------------------------


def test_background_is_swissprot_50_8_in_alphabet_order():
    assert tuple(BACKGROUND_AMINO) == LETTERS
    assert BACKGROUND_AMINO["A"] == 0.0787945
    assert BACKGROUND_AMINO["L"] == 0.0963728
    assert BACKGROUND_AMINO["W"] == 0.0114135
    assert BACKGROUND_AMINO["Y"] == 0.0304133
    assert sum(BACKGROUND_AMINO.values()) == pytest.approx(1.0, abs=1e-4)
    assert background_frequencies(_toy_model()) == list(BACKGROUND_AMINO.values())


def test_nucleic_background_is_uniform():
    dna = HmmModel(
        name="dna",
        length=1,
        alphabet=("A", "C", "G", "T"),
        alphabet_type="DNA",
        match_emissions=[[0.7, 0.1, 0.1, 0.1]],
        insert_emissions=[[0.25] * 4] * 2,
        transitions=[[0.9, 0.05, 0.05, 0.6, 0.4, 1.0, 0.0], [1.0, 0.0, 0.0, 0.5, 0.5, 1.0, 0.0]],
    )
    assert background_frequencies(dna) == [0.25] * 4
    expected = 0.7 * math.log2(0.7 / 0.25) + 3 * 0.1 * math.log2(0.1 / 0.25)
    assert letter_heights(dna, "relent_all").info_bits == [pytest.approx(expected)]
    (back,) = parse_hmm(format_hmm(dna))
    assert back.alphabet_type == "DNA" and back.alphabet == ("A", "C", "G", "T")


def test_occupancy_by_hand():
    """occ1 = t0(MM)+t0(MI) = 0.95; occ2 = 0.95*(0.8+0.1) + 0.05*0.6 = 0.885;
    occ3 = 0.885*(0.7+0.2) + 0.115*0.5 = 0.854."""
    model = _toy_model()
    assert occupancy(model) == pytest.approx([0.95, 0.885, 0.854])
    assert delete_probability(model) == pytest.approx([0.05, 0.115, 0.146])
    (parsed,) = parse_hmm(HMM_TEXT)
    assert occupancy(parsed) == pytest.approx([0.95, 0.885, 0.854], abs=1e-4)


def test_occupancy_of_a_single_state_model():
    model = _toy_model(
        length=1,
        match_emissions=[_dist({"A": 0.8})],
        insert_emissions=[_dist({"A": 0.08})] * 2,
        transitions=[[0.7, 0.2, 0.1, 0.6, 0.4, 1.0, 0.0], [1.0, 0.0, 0.0, 0.5, 0.5, 1.0, 0.0]],
        map_columns=[1],
        consensus=["A"],
        rf=["x"],
        mm=[None],
        cs=["H"],
    )
    assert occupancy(model) == pytest.approx([0.9])  # 1 - B->D1
    assert delete_probability(model) == pytest.approx([0.1])


def test_indel_values_follow_hmmlogo():
    model = _toy_model()
    assert insert_probability(model) == pytest.approx([0.1, 0.2, 0.0])  # t_k(MI); 0 after the last
    assert expected_insert_length(model) == pytest.approx([1 / 0.7, 1 / 0.5, 0.0])


def test_expected_insert_length_guards_a_closed_insert_state():
    rows = [list(r) for r in TRANS]
    rows[1][4] = 1.0  # I->I = 1 at node 1
    model = _toy_model(transitions=rows)
    assert expected_insert_length(model)[0] == math.inf
    frame = profile_frame(model)
    assert frame.filter(pl.col("hmm_position") == 1)["insert_length"].null_count() == 20
    assert frame.filter(pl.col("hmm_position") == 2)["insert_length"].null_count() == 0


# ---------------------------------------------------------------------------
# Letter heights
# ---------------------------------------------------------------------------


def test_relent_all_heights_are_relative_entropy_times_probability():
    model = _toy_model()
    heights, info = letter_heights(model, "relent_all")
    for k, row in enumerate(model.match_emissions):
        re_k = _relent(row)
        assert info[k] == pytest.approx(re_k)
        assert heights[k] == pytest.approx([re_k * p for p in row])
        assert sum(heights[k]) == pytest.approx(re_k)
    # the default mode is hmmlogo's own default
    assert letter_heights(model) == letter_heights(model, "relent_all")
    # letters below background keep a (small) height in this mode
    assert heights[0][LETTERS.index("C")] > 0


def test_relent_abovebg_dominant_letter_takes_the_whole_column():
    model = _toy_model()
    heights, info = letter_heights(model, "relent_abovebg")
    a = LETTERS.index("A")
    # every other letter of node 1 (p = 0.2/19 = 0.0105) is below its background
    assert all(
        p < b for p, b in zip(model.match_emissions[0], BACKGROUND_AMINO.values()) if p != 0.8
    )
    assert heights[0][a] == pytest.approx(info[0])
    assert [h for i, h in enumerate(heights[0]) if i != a] == [0.0] * 19


def test_relent_abovebg_splits_the_full_relative_entropy_over_letters_above_background():
    model = _toy_model()
    heights, info = letter_heights(model, "relent_abovebg")
    row = model.match_emissions[1]  # L 0.45, I 0.35, 18 letters at 0.0111
    leu, ile = LETTERS.index("L"), LETTERS.index("I")
    full = _relent(row)
    # hmmlogo keeps the whole column's relative entropy (below-background letters
    # count negatively) and shares it among the letters above background.
    assert info[1] == pytest.approx(full)
    assert heights[1][leu] == pytest.approx(full * 0.45 / 0.80)
    assert heights[1][ile] == pytest.approx(full * 0.35 / 0.80)
    assert sum(h for k, h in enumerate(heights[1]) if k not in (leu, ile)) == 0.0
    # not the sum over the positive terms only
    positive_only = sum(
        p * math.log2(p / b) for p, b in zip(row, BACKGROUND_AMINO.values()) if p > b
    )
    assert info[1] < positive_only
    for k in range(3):
        assert sum(heights[k]) == pytest.approx(info[k])
        assert all(h >= 0 for h in heights[k])


def test_letters_below_background_have_zero_height_in_abovebg_mode():
    model = _toy_model()
    heights, _ = letter_heights(model, "relent_abovebg")
    for k, row in enumerate(model.match_emissions):
        for p, b, h in zip(row, BACKGROUND_AMINO.values(), heights[k]):
            if p <= b:
                assert h == 0.0


def test_probability_mode_heights_are_the_emissions():
    model = _toy_model()
    heights, info = letter_heights(model, "probability")
    assert heights == model.match_emissions
    assert info == [pytest.approx(1.0)] * 3
    assert all(sum(row) == pytest.approx(1.0) for row in heights)


def test_unknown_mode_raises():
    assert set(LOGO_MODES) == {"relent_all", "relent_abovebg", "probability"}
    with pytest.raises(ValueError, match="unknown logo mode"):
        letter_heights(_toy_model(), "bits")


# ---------------------------------------------------------------------------
# Reference residue numbers
# ---------------------------------------------------------------------------

#: 10 alignment columns, 7 of them match states (RF 'x'). The reference carries
#: lower-case inserts at columns 3, 7 and 8 and a deletion at column 5, and its
#: name has a /31-90 range; the alignment is split over two blocks.
STO = """\
# STOCKHOLM 1.0
#=GF ID fam1

#=GC RF       xx.xx
ref/31-90     ACgD-
other/1-40    AC.DF
third/5-9     AC.D-

#=GC RF       x..xx
ref/31-90     EklGH
other/1-40    E..GH
third/5-9     E..G-
//
"""
STO_NO_RF = "\n".join(line for line in STO.splitlines() if not line.startswith("#=GC RF")) + "\n"


@pytest.mark.parametrize("sto", [STO, STO_NO_RF], ids=["with-RF", "no-RF-uppercase-fallback"])
def test_reference_positions_count_inserts_and_mark_deletions(sto):
    # A31 C32 g33 D34 -  E35 k36 l37 G38 H39 -> inserts shift the numbering
    expected = [31, 32, 34, None, 35, 38, 39]
    assert reference_positions_from_stockholm(sto, "ref/31-90") == expected
    assert reference_positions_from_stockholm(sto, "ref") == expected  # suffix is optional
    assert reference_positions_from_stockholm(sto, "ref/31-90", model_length=7) == expected


def test_reference_positions_other_rows_and_ranges():
    assert reference_positions_from_stockholm(STO, "other") == [1, 2, 3, 4, 5, 6, 7]
    assert reference_positions_from_stockholm(STO, "third/5-9") == [5, 6, 7, None, 8, 9, None]


def test_reference_without_a_range_numbers_from_one_and_reference_id_may_bring_it():
    sto = "# STOCKHOLM 1.0\n#=GC RF xxx\nsolo ACD\nother AC-\n//\n"
    assert reference_positions_from_stockholm(sto, "solo") == [1, 2, 3]
    assert reference_positions_from_stockholm(sto, "solo/10-12") == [10, 11, 12]


def test_reference_positions_check_the_model_length():
    with pytest.raises(ValueError, match="7 match columns.*model has 6 states"):
        reference_positions_from_stockholm(STO, "ref", model_length=6)
    with pytest.raises(ValueError, match="7 match columns"):
        reference_positions_from_stockholm(STO_NO_RF, "ref", model_length=8)


def test_reference_positions_errors():
    with pytest.raises(ValueError, match="not found"):
        reference_positions_from_stockholm(STO, "missing")
    ambiguous = "# STOCKHOLM 1.0\n#=GC RF xx\ndup/1-2 AC\ndup/20-21 DE\n//\n"
    with pytest.raises(ValueError, match="ambiguous"):
        reference_positions_from_stockholm(ambiguous, "dup")
    assert reference_positions_from_stockholm(ambiguous, "dup/20-21") == [20, 21]
    with pytest.raises(ValueError, match="no sequence"):
        reference_positions_from_stockholm("# STOCKHOLM 1.0\n//\n", "x")
    with pytest.raises(ValueError, match="columns"):
        reference_positions_from_stockholm("# STOCKHOLM 1.0\na ACD\nb AC\n//\n", "a")
    with pytest.raises(ValueError, match="RF"):
        reference_positions_from_stockholm("# STOCKHOLM 1.0\n#=GC RF xx\na ACD\n//\n", "a")


def test_rf_gap_characters_other_than_x_mark_insert_columns():
    sto = "# STOCKHOLM 1.0\n#=GC RF x.~-_x\na AcdefG\n//\n"
    assert reference_positions_from_stockholm(sto, "a") == [1, 6]


#: Output of HMMER 3.4 ``hmmalign`` for a 22-state model, as written (PP lines included):
#: the query has an N-terminal extension, a 3-residue insert, a 2-residue deletion and a tail.
HMMALIGN_OUT = """\
# STOCKHOLM 1.0

query/101-140         ggMKVLAAGIVaaaGLLLAQPS--DWKtt
#=GR query/101-140 PP ***********8888*******..998**
other                 ..MKVLAAGIV...GLLLAQPSTEDWK..
#=GR other         PP ..*********...************9..
#=GC PP_cons          ..*********...9***********9..
#=GC RF               ..xxxxxxxxx...xxxxxxxxxxxxx..
//
"""


def test_reference_positions_from_real_hmmalign_output():
    got = reference_positions_from_stockholm(HMMALIGN_OUT, "query/101-140", model_length=22)
    # gg = 101, 102; MKVLAAGIV = 103..111; aaa = 112..114 (inserts still count); G = 115 ...
    assert got == [*range(103, 112), *range(115, 123), None, None, 123, 124, 125]
    assert reference_positions_from_stockholm(HMMALIGN_OUT, "other", model_length=22) == list(
        range(1, 23)
    )


MAP_ALIGNED = {"ref/10-20": "-AC-DE", "other": "XAC-DE"}


def test_reference_positions_from_map():
    model = _toy_model(map_columns=[2, 3, 5])
    # ref/10-20: A10 (col 2), C11 (col 3), gap (col 4), D12 (col 5), E13 (col 6)
    assert reference_positions_from_map(model, MAP_ALIGNED, "ref") == [10, 11, 12]
    assert reference_positions_from_map(model, list(MAP_ALIGNED.items()), "ref/10-20") == [
        10,
        11,
        12,
    ]
    # other: X1 A2 C3 gap D4 E5 -> the leading X shifts everything by one
    assert reference_positions_from_map(model, MAP_ALIGNED, "other") == [2, 3, 4]


def test_reference_positions_from_map_gaps_and_missing_entries():
    gap_hits = _toy_model(map_columns=[1, 3, 4])
    assert reference_positions_from_map(gap_hits, MAP_ALIGNED, "ref") == [None, 11, None]
    partial = _toy_model(map_columns=[2, None, 6])
    assert reference_positions_from_map(partial, MAP_ALIGNED, "ref") == [10, None, 13]
    dotted = {"s": "A.C..D"}
    assert reference_positions_from_map(_toy_model(map_columns=[1, 3, 6]), dotted, "s") == [1, 2, 3]


def test_reference_positions_from_map_with_a_parsed_model():
    (model,) = parse_hmm(HMM_TEXT)  # MAP 4 5 7
    assert reference_positions_from_map(model, {"s": "AC-DEFGH"}, "s") == [3, 4, 6]


def test_reference_positions_from_map_errors():
    with pytest.raises(ValueError, match="no MAP"):
        reference_positions_from_map(_toy_model(map_columns=[]), MAP_ALIGNED, "ref")
    with pytest.raises(ValueError, match="maps to column 9"):
        reference_positions_from_map(_toy_model(map_columns=[2, 3, 9]), MAP_ALIGNED, "ref")
    with pytest.raises(ValueError, match="not found"):
        reference_positions_from_map(_toy_model(), MAP_ALIGNED, "nope")


# ---------------------------------------------------------------------------
# Long table
# ---------------------------------------------------------------------------


def test_profile_frame_schema_and_shape():
    (model,) = parse_hmm(HMM_TEXT)
    frame = profile_frame(model)
    assert frame.shape == (3 * 20, 17)
    assert frame.columns == list(PROFILE_SCHEMA)
    assert dict(frame.schema) == PROFILE_SCHEMA
    assert frame.schema["position"] == pl.Int64
    assert frame.schema["hmm_position"] == pl.Int64
    assert frame.schema["map_column"] == pl.Int64
    assert frame.schema["height_bits"] == pl.Float64
    assert "residue" not in frame.columns
    # without an entity or positions: the model name and null residue numbers
    assert frame["entity"].unique().to_list() == ["FAM001"]
    assert frame["position"].null_count() == frame.height
    assert frame["hmm_name"].unique().to_list() == ["FAM001"]
    assert frame["hmm_acc"].unique().to_list() == ["PF99999.1"]


def test_profile_frame_is_sorted_and_fills_entity_and_position():
    model = _toy_model()
    frame = profile_frame(model, entity="P12345", positions=[31, None, 34], mode="relent_all")
    assert frame["entity"].unique().to_list() == ["P12345"]
    assert frame["hmm_position"].to_list() == sorted(frame["hmm_position"].to_list())
    assert frame.select(pl.col("hmm_letter").head(20)).to_series().to_list() == list(LETTERS)
    by_state = {k: g for (k,), g in frame.group_by("hmm_position", maintain_order=True)}
    assert by_state[1]["position"].unique().to_list() == [31]
    assert by_state[2]["position"].unique().to_list() == [None]
    assert by_state[3]["position"].unique().to_list() == [34]

    state2 = by_state[2]
    assert state2["emission"].to_list() == pytest.approx(model.match_emissions[1])
    assert state2["info_bits"].unique().to_list() == [
        pytest.approx(_relent(model.match_emissions[1]))
    ]
    assert state2["height_bits"].sum() == pytest.approx(state2["info_bits"][0])
    assert state2["insert_prob"].unique().to_list() == [pytest.approx(0.2)]
    assert state2["insert_length"].unique().to_list() == [pytest.approx(2.0)]
    assert state2["occupancy"].unique().to_list() == [pytest.approx(0.885)]
    assert state2["delete_prob"].unique().to_list() == [pytest.approx(0.115)]
    assert state2["consensus"].unique().to_list() == ["l"]
    assert state2["rf"].unique().to_list() == ["x"]
    assert state2["cs"].unique().to_list() == ["H"]
    assert state2["map_column"].unique().to_list() == [5]
    assert by_state[3]["insert_prob"].unique().to_list() == [0.0]


def test_profile_frame_default_mode_is_abovebg():
    model = _toy_model()
    frame = profile_frame(model)
    expected = letter_heights(model, "relent_abovebg").heights[0]
    assert frame.filter(pl.col("hmm_position") == 1)["height_bits"].to_list() == pytest.approx(
        expected
    )


def test_profile_frame_rejects_bad_positions_and_modes():
    model = _toy_model()
    with pytest.raises(ValueError, match="positions has 2 entries"):
        profile_frame(model, positions=[1, 2])
    with pytest.raises(ValueError, match="unknown logo mode"):
        profile_frame(model, mode="nope")


def test_profile_frame_from_reference_alignment_end_to_end():
    """The path the tile takes: HMM + hmmalign output -> one row per (state, letter)."""
    model = _toy_model(
        length=7,
        match_emissions=[_dist({LETTERS[i]: 0.5}) for i in range(7)],
        insert_emissions=[_dist({"A": 0.08})] * 8,
        transitions=[[0.9, 0.05, 0.05, 0.6, 0.4, 1.0, 0.0]]
        + [[0.8, 0.1, 0.1, 0.7, 0.3, 0.6, 0.4]] * 6
        + [[1.0, 0.0, 0.0, 0.5, 0.5, 1.0, 0.0]],
        map_columns=[],
        consensus=[],
        rf=[],
        mm=[],
        cs=[],
    )
    positions = reference_positions_from_stockholm(STO, "ref/31-90", model_length=model.length)
    frame = profile_frame(model, entity="ref/31-90", positions=positions)
    assert frame.shape == (7 * 20, 17)
    firsts = frame.filter(pl.col("hmm_letter") == "A").sort("hmm_position")["position"].to_list()
    assert firsts == [31, 32, 34, None, 35, 38, 39]


def test_fixture_match_lines_have_the_column_count_as_format_relies_on():
    """``_as_format`` rewrites the fixture by column position: guard the layout."""
    match_lines = [ln for ln in HMM_TEXT.splitlines() if re.match(r"^\s+[123]\s+\d", ln)]
    assert len(match_lines) == 3
    assert all(len(ln.split()) == 26 for ln in match_lines)
