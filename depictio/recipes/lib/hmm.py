"""HMMER3 profile HMMs: file parser, sequence logo heights and residue mapping.

nf-core/proteinfamilies publishes, per protein family, the HMMER3 profile that
``hmmbuild`` wrote (``<family>.hmm.gz``, plus a concatenated library
``<sample>.lib.gz``) and the family alignment ``hmmalign`` produced
(``<family>.sto.gz``, Stockholm). This module turns them into what an HMM logo
tile needs, with the standard library and Polars only (no HMMER, no Biopython):

* :func:`parse_hmm` / :func:`read_hmm` read a save file or a library of them
  (formats ``HMMER3/a`` .. ``HMMER3/f``) into :class:`HmmModel`;
* :func:`letter_heights`, :func:`occupancy`, :func:`insert_probability` and
  :func:`expected_insert_length` reproduce what ``hmmlogo`` prints;
* :func:`reference_positions_from_stockholm` / :func:`reference_positions_from_map`
  say which residue of a reference sequence each match state sits on;
  :func:`member_spans_from_stockholm` says which stretch of the model each row of
  an alignment covers;
* :func:`profile_frame` flattens it all into one long table, one row per
  (match state, letter);
* :func:`format_hmm` writes a ``HMMER3/f`` file back (test fixtures).

Sources checked (HMMER and Easel master, read line by line; outputs cross-checked against HMMER 3.4):

* file layout: https://github.com/EddyRivasLab/hmmer/blob/master/src/p7_hmmfile.c
  (``p7_hmmfile_WriteASCII`` and ``read_asc30hmm``);
* logo heights and indel values:
  https://github.com/EddyRivasLab/hmmer/blob/master/src/hmmlogo.c
  (``hmmlogo_RelativeEntropy_all``, ``hmmlogo_RelativeEntropy_above_bg``,
  ``hmmlogo_IndelValues``);
* occupancy: https://github.com/EddyRivasLab/hmmer/blob/master/src/p7_hmm.c
  (``p7_hmm_CalculateOccupancy``; ``p7_hmm_SetConsensus`` for legacy files);
* background: https://github.com/EddyRivasLab/hmmer/blob/master/src/hmmer.c
  (``p7_AminoFrequencies``, called by ``p7_bg_Create``), identical to
  https://github.com/EddyRivasLab/easel/blob/master/esl_composition.c
  (``esl_composition_SW50``).

Layout of a node, as HMMER writes it
------------------------------------
After the ``HMM`` line and the transition header, an optional ``COMPO`` line,
then node 0 (insert emissions, then the B-> transitions), then three lines per
node ``k = 1..M``: ``k`` + K match scores + annotation columns; K insert
scores; seven transition scores in the order ``m->m m->i m->d i->m i->i d->m
d->d``. Every score is ``-ln(p)`` and ``*`` means ``p = 0``. The annotation
columns after the K scores are ``MAP``, ``CONS`` (3/e and later), ``RF``,
``MM`` (3/f only), ``CS``; ``-`` stands for "none". The number of columns found
on the line (3, 4 or 5) decides the layout, which is what the format letter
dictates anyway. Files older than 3/e carry no consensus; HMMER computes it
from the emissions when reading them and so does :func:`parse_hmm`.

Indexing
--------
``match_emissions[k - 1]`` is match state ``k`` (``k = 1..M``, M rows).
``insert_emissions[k]`` and ``transitions[k]`` are indexed by node ``k = 0..M``
(M + 1 rows), exactly as ``hmm->ins[k]`` / ``hmm->t[k]`` in HMMER: row ``k`` of
``transitions`` leaves node ``k``.

Logo heights (modes of :func:`letter_heights`)
----------------------------------------------
With ``p_a`` the match emission of letter ``a``, ``b_a`` its background and
``lo_a = log2(p_a / b_a)`` (letters with ``p_a = 0`` are skipped)::

    RE_k = sum_a p_a * lo_a                    relative entropy, in bits

``relent_all`` (hmmlogo's default, ``hmmlogo_RelativeEntropy_all``)::

    height_a = RE_k * p_a

``relent_abovebg`` (``--height_relent_abovebg``, ``hmmlogo_RelativeEntropy_above_bg``)::

    A_k      = sum_{a : lo_a > 0} p_a          probability mass above background
    height_a = RE_k * p_a / A_k   if lo_a > 0, else 0

Note the column height stays the **full** ``RE_k`` (negative terms of letters
below background included), it is only *redistributed* over the letters above
background; a restricted sum would not be what ``hmmlogo`` reports.

``probability``: ``height_a = p_a`` (the column height is 1).

Indel values (``hmmlogo_IndelValues``)
--------------------------------------
``insert_P[k] = t_k(M->I)`` and ``insert_expL[k] = 1 / (1 - t_k(I->I))`` for
``k < M``; both are 0 after the last match state. ``occupancy`` is
``p7_hmm_CalculateOccupancy``::

    occ[1] = t_0(M->M) + t_0(M->I)                       (= 1 - B->D1)
    occ[k] = occ[k-1] * (t_{k-1}(M->M) + t_{k-1}(M->I))
             + (1 - occ[k-1]) * t_{k-1}(D->M)
"""

from __future__ import annotations

import gzip
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import polars as pl

#: Amino alphabet in the order HMMER (and Easel) writes the ``HMM`` header.
AMINO_LETTERS = "ACDEFGHIKLMNPQRSTVWY"

#: Swiss-Prot 50.8 residue frequencies, the null model of every HMMER3 amino
#: profile. Copied from ``p7_AminoFrequencies`` (hmmer.c) = ``esl_composition_SW50``.
BACKGROUND_AMINO: dict[str, float] = {
    "A": 0.0787945,
    "C": 0.0151600,
    "D": 0.0535222,
    "E": 0.0668298,
    "F": 0.0397062,
    "G": 0.0695071,
    "H": 0.0229198,
    "I": 0.0590092,
    "K": 0.0594422,
    "L": 0.0963728,
    "M": 0.0237718,
    "N": 0.0414386,
    "P": 0.0482904,
    "Q": 0.0395639,
    "R": 0.0540978,
    "S": 0.0683364,
    "T": 0.0540687,
    "V": 0.0673417,
    "W": 0.0114135,
    "Y": 0.0304133,
}

#: Order of the seven transition columns of a node.
TRANSITIONS = ("mm", "mi", "md", "im", "ii", "dm", "dd")
T_MM, T_MI, T_MD, T_IM, T_II, T_DM, T_DD = range(7)

LOGO_MODES = ("relent_all", "relent_abovebg", "probability")

#: Gap characters of Stockholm/aligned FASTA rows and of an RF line (Easel's set).
GAP_CHARS = "-.~_"

_AMINO_K = 20
_NUCLEIC_K = 4
_FORMAT_LETTERS = "abcdef"


@dataclass(kw_only=True)
class HmmModel:
    """One HMMER3 profile HMM (see the module docstring for the indexing)."""

    name: str
    length: int
    alphabet: tuple[str, ...]
    match_emissions: list[list[float]]
    insert_emissions: list[list[float]]
    transitions: list[list[float]]
    acc: str | None = None
    desc: str | None = None
    #: ``ALPH`` header: ``amino``, ``DNA`` or ``RNA``.
    alphabet_type: str = "amino"
    #: 1-based column of the seed alignment of each match state, ``None`` if unknown.
    map_columns: list[int | None] = field(default_factory=list)
    consensus: list[str | None] = field(default_factory=list)
    rf: list[str | None] = field(default_factory=list)
    mm: list[str | None] = field(default_factory=list)
    cs: list[str | None] = field(default_factory=list)
    nseq: int | None = None
    effn: float | None = None
    #: Mean emitted composition (``COMPO`` line), ``None`` when absent.
    compo: list[float] | None = None

    def __post_init__(self) -> None:
        self.alphabet = tuple(self.alphabet)
        k, m = len(self.alphabet), self.length
        if m < 1:
            raise ValueError(f"HMM {self.name!r}: model length must be >= 1, got {m}")
        if len(self.match_emissions) != m:
            raise ValueError(
                f"HMM {self.name!r}: {len(self.match_emissions)} match rows for LENG {m}"
            )
        for label, rows, n_rows, width in (
            ("match emission", self.match_emissions, m, k),
            ("insert emission", self.insert_emissions, m + 1, k),
            ("transition", self.transitions, m + 1, len(TRANSITIONS)),
        ):
            if len(rows) != n_rows or any(len(r) != width for r in rows):
                raise ValueError(f"HMM {self.name!r}: {label} table must be {n_rows} x {width}")
        for label in ("map_columns", "consensus", "rf", "mm", "cs"):
            values = getattr(self, label)
            if not values:
                setattr(self, label, [None] * m)
            elif len(values) != m:
                raise ValueError(
                    f"HMM {self.name!r}: {label} has {len(values)} entries for LENG {m}"
                )
        if self.compo is not None and len(self.compo) != k:
            raise ValueError(
                f"HMM {self.name!r}: COMPO has {len(self.compo)} entries, expected {k}"
            )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_hmm(path: str | Path) -> list[HmmModel]:
    """Read a ``.hmm`` / ``.hmm.gz`` / ``.lib.gz`` file (gzip is detected by magic bytes)."""
    raw = Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return parse_hmm(raw.decode("utf-8", errors="replace"))


def parse_hmm(text: str) -> list[HmmModel]:
    """Parse HMMER3 save files (formats ``HMMER3/a`` .. ``HMMER3/f``).

    A file holds one model or a library of them, each record closed by ``//``.
    Raises :class:`ValueError` on anything that is not a complete HMMER3 record.
    """
    models: list[HmmModel] = []
    record: list[str] = []
    version: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if version is None:
            if not line:
                continue
            if line.startswith("HMMER3/"):
                letter = line.split()[0][len("HMMER3/") :]
                if letter not in tuple(_FORMAT_LETTERS):
                    raise ValueError(
                        f"line {number}: unknown HMMER3 format tag {line.split()[0]!r}"
                    )
                version, record = letter, []
                continue
            if line.startswith("HMMER2"):
                raise ValueError(
                    f"line {number}: HMMER2 files are not supported, convert with hmmconvert"
                )
            raise ValueError(f"line {number}: expected a 'HMMER3/x' header, got {line[:40]!r}")
        if line == "//":
            models.append(_parse_record(record, version))
            version = None
            continue
        record.append(line)
    if version is not None:
        raise ValueError("truncated HMM record: no closing '//'")
    if not models:
        raise ValueError("no HMMER3 record found")
    return models


def _prob(token: str, where: str) -> float:
    if token == "*":
        return 0.0
    try:
        return math.exp(-float(token))
    except ValueError:
        raise ValueError(f"{where}: {token!r} is not a score") from None


def _scores(tokens: list[str], start: int, count: int, where: str) -> list[float]:
    if len(tokens) < start + count:
        raise ValueError(f"{where}: expected {count} scores, found {max(0, len(tokens) - start)}")
    return [_prob(t, where) for t in tokens[start : start + count]]


def _annotation(token: str) -> str | None:
    return None if token == "-" else token


def _consensus_from_emissions(row: list[float], alphabet: tuple[str, ...], alph: str) -> str:
    """``p7_hmm_SetConsensus``: most likely letter, upper-cased from 0.5 (0.9 for DNA/RNA)."""
    best = max(range(len(row)), key=lambda i: (row[i], -i))
    threshold = 0.9 if alph in ("DNA", "RNA") else 0.5
    letter = alphabet[best]
    return letter.upper() if row[best] >= threshold else letter.lower()


def _parse_record(lines: list[str], version: str) -> HmmModel:
    name: str | None = None
    acc = desc = None
    length = 0
    alph = "amino"
    nseq: int | None = None
    effn: float | None = None
    letters: list[str] | None = None
    body_start: int | None = None
    for i, line in enumerate(lines):
        if not line:
            continue
        head = line.split(None, 1)
        tag, rest = head[0], (head[1].strip() if len(head) > 1 else "")
        if tag == "NAME":
            name = rest.split()[0] if rest else None
        elif tag == "ACC":
            acc = rest.split()[0] if rest else None
        elif tag == "DESC":
            desc = rest or None
        elif tag == "LENG":
            try:
                length = int(rest.split()[0])
            except (ValueError, IndexError):
                raise ValueError(f"HMM {name!r}: invalid LENG {rest!r}") from None
        elif tag == "ALPH":
            low = rest.lower()
            alph = "amino" if low == "amino" else rest.upper() if low in ("dna", "rna") else rest
        elif tag == "NSEQ":
            nseq = int(rest.split()[0]) if rest.split() else None
        elif tag == "EFFN":
            effn = float(rest.split()[0]) if rest.split() else None
        elif tag == "HMM":
            letters = rest.split()
            body_start = i + 1
            break
        # RF/MM/CONS/CS/MAP flags, DATE, COM, MAXL, CKSUM, GA/TC/NC, STATS: not needed.
    if name is None:
        raise ValueError("HMM record without NAME")
    if letters is None or body_start is None:
        raise ValueError(f"HMM {name!r}: no 'HMM' section found")
    if length < 1:
        raise ValueError(f"HMM {name!r}: missing or invalid LENG")
    k = len(letters)
    expected_k = _AMINO_K if alph == "amino" else _NUCLEIC_K if alph in ("DNA", "RNA") else None
    if expected_k is not None and k != expected_k:
        raise ValueError(
            f"HMM {name!r}: ALPH {alph} needs {expected_k} letters, the HMM line has {k}"
        )

    body = [line.split() for line in lines[body_start:] if line]
    if not body:
        raise ValueError(f"HMM {name!r}: no model data after the HMM line")
    pos = 1  # body[0] is the m->m m->i ... header line
    compo: list[float] | None = None
    if pos < len(body) and body[pos][0] == "COMPO":
        compo = _scores(body[pos], 1, k, f"HMM {name!r}: COMPO line")
        pos += 1
    where0 = f"HMM {name!r}: node 0"
    if pos + 1 >= len(body):
        raise ValueError(f"{where0}: missing insert/transition lines")
    insert = [_scores(body[pos], 0, k, f"{where0} insert line")]
    trans = [_scores(body[pos + 1], 0, len(TRANSITIONS), f"{where0} transition line")]
    pos += 2

    match: list[list[float]] = []
    map_columns: list[int | None] = []
    consensus: list[str | None] = []
    rf: list[str | None] = []
    mm: list[str | None] = []
    cs: list[str | None] = []
    for node in range(1, length + 1):
        where = f"HMM {name!r}: node {node}"
        if pos + 2 >= len(body):
            raise ValueError(f"{where}: premature end of data (LENG {length})")
        first, second, third = body[pos], body[pos + 1], body[pos + 2]
        pos += 3
        if first[0] != str(node):
            raise ValueError(f"{where}: match line starts with {first[0]!r}")
        match.append(_scores(first, 1, k, f"{where} match line"))
        extras = first[1 + k :]
        if len(extras) == 5:
            map_tok, cons_tok, rf_tok, mm_tok, cs_tok = extras
        elif len(extras) == 4:
            map_tok, cons_tok, rf_tok, cs_tok = extras
            mm_tok = "-"
        elif len(extras) == 3:
            map_tok, rf_tok, cs_tok = extras
            cons_tok = mm_tok = "-"
        else:
            raise ValueError(
                f"{where}: {len(extras)} annotation columns after the {k} scores, expected 3 to 5"
            )
        try:
            map_columns.append(int(map_tok))
        except ValueError:
            map_columns.append(None)
        if len(extras) == 3:  # before 3/e: HMMER derives the consensus from the emissions
            consensus.append(_consensus_from_emissions(match[-1], tuple(letters), alph))
        else:
            consensus.append(_annotation(cons_tok))
        rf.append(_annotation(rf_tok))
        mm.append(_annotation(mm_tok))
        cs.append(_annotation(cs_tok))
        insert.append(_scores(second, 0, k, f"{where} insert line"))
        trans.append(_scores(third, 0, len(TRANSITIONS), f"{where} transition line"))
    if pos != len(body):
        raise ValueError(f"HMM {name!r}: unexpected data after node {length}")
    return HmmModel(
        name=name,
        acc=acc,
        desc=desc,
        length=length,
        alphabet=tuple(letters),
        alphabet_type=alph,
        match_emissions=match,
        insert_emissions=insert,
        transitions=trans,
        map_columns=map_columns,
        consensus=consensus,
        rf=rf,
        mm=mm,
        cs=cs,
        nseq=nseq,
        effn=effn,
        compo=compo,
    )


# ---------------------------------------------------------------------------
# Writing (test fixtures)
# ---------------------------------------------------------------------------


def _score_field(p: float) -> str:
    if p <= 0.0:
        text = "*"
    elif p >= 1.0:
        text = "0.00000"
    else:
        text = f"{-math.log(p):.5f}"
    return f"{text:>8}"


def format_hmm(model: HmmModel) -> str:
    """Write ``model`` as a ``HMMER3/f`` file that :func:`parse_hmm` reads back.

    Scores keep five decimals like HMMER, so a round trip is exact to ~1e-5.
    """

    def flag(values: Sequence[object | None]) -> str:
        return "yes" if any(v is not None for v in values) else "no"

    def tok(value: object | None) -> str:
        return "-" if value is None else str(value)

    out = ["HMMER3/f [depictio | format_hmm]", f"NAME  {model.name}"]
    if model.acc:
        out.append(f"ACC   {model.acc}")
    if model.desc:
        out.append(f"DESC  {model.desc}")
    out += [
        f"LENG  {model.length}",
        f"ALPH  {model.alphabet_type}",
        f"RF    {flag(model.rf)}",
        f"MM    {flag(model.mm)}",
        f"CONS  {flag(model.consensus)}",
        f"CS    {flag(model.cs)}",
        f"MAP   {flag(model.map_columns)}",
    ]
    if model.nseq is not None:
        out.append(f"NSEQ  {model.nseq}")
    if model.effn is not None:
        out.append(f"EFFN  {model.effn:f}")
    out.append("HMM     " + "".join(f"     {a}   " for a in model.alphabet))
    out.append(
        "        "
        + " ".join(f"{t:>8}" for t in ("m->m", "m->i", "m->d", "i->m", "i->i", "d->m", "d->d"))
    )
    if model.compo is not None:
        out.append("  COMPO " + "".join(" " + _score_field(p) for p in model.compo))
    out.append("        " + "".join(" " + _score_field(p) for p in model.insert_emissions[0]))
    out.append("        " + "".join(" " + _score_field(p) for p in model.transitions[0]))
    for node in range(1, model.length + 1):
        i = node - 1
        annotations = " ".join(
            (
                f"{tok(model.map_columns[i]):>6}",
                tok(model.consensus[i]),
                tok(model.rf[i]),
                tok(model.mm[i]),
                tok(model.cs[i]),
            )
        )
        scores = "".join(" " + _score_field(p) for p in model.match_emissions[i])
        out.append(f" {node:>6} {scores} {annotations}")
        out.append(
            "        " + "".join(" " + _score_field(p) for p in model.insert_emissions[node])
        )
        out.append("        " + "".join(" " + _score_field(p) for p in model.transitions[node]))
    out.append("//")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Background, occupancy, indel values, logo heights
# ---------------------------------------------------------------------------


def background_frequencies(model: HmmModel) -> list[float]:
    """Null-model frequencies in the model's own letter order (``p7_bg_Create``).

    Swiss-Prot 50.8 for amino acids, ``1/K`` for DNA/RNA (and anything else).
    """
    if model.alphabet_type != "amino":
        return [1.0 / len(model.alphabet)] * len(model.alphabet)
    try:
        return [BACKGROUND_AMINO[letter] for letter in model.alphabet]
    except KeyError as exc:
        raise ValueError(f"HMM {model.name!r}: no background frequency for letter {exc}") from None


def occupancy(model: HmmModel) -> list[float]:
    """Probability that each match state ``1..M`` is used (``p7_hmm_CalculateOccupancy``)."""
    t = model.transitions
    occ = [0.0] * (model.length + 1)  # occ[0] is unused, as in HMMER
    occ[1] = t[0][T_MI] + t[0][T_MM]
    for k in range(2, model.length + 1):
        prev = occ[k - 1]
        occ[k] = prev * (t[k - 1][T_MM] + t[k - 1][T_MI]) + (1.0 - prev) * t[k - 1][T_DM]
    return occ[1:]


def delete_probability(model: HmmModel) -> list[float]:
    """``1 - occupancy`` per match state (clamped at 0 against float round-off)."""
    return [max(0.0, 1.0 - o) for o in occupancy(model)]


def insert_probability(model: HmmModel) -> list[float]:
    """hmmlogo's "insert P": ``t_k(M->I)`` after each match state, 0 after the last."""
    t = model.transitions
    return [t[k][T_MI] if k < model.length else 0.0 for k in range(1, model.length + 1)]


def expected_insert_length(model: HmmModel) -> list[float]:
    """hmmlogo's "insert expected length": ``1 / (1 - t_k(I->I))``, 0 after the last state.

    ``inf`` for a degenerate model whose insert state never exits.
    """
    t = model.transitions
    out: list[float] = []
    for k in range(1, model.length + 1):
        if k >= model.length:
            out.append(0.0)
            continue
        stay = t[k][T_II]
        out.append(1.0 / (1.0 - stay) if stay < 1.0 else math.inf)
    return out


class LetterHeights(NamedTuple):
    """``heights[k - 1][a]`` in bits for match state ``k``; ``info_bits[k - 1]`` the column height."""

    heights: list[list[float]]
    info_bits: list[float]


def letter_heights(model: HmmModel, mode: str = "relent_all") -> LetterHeights:
    """Logo letter heights per match state, in one of :data:`LOGO_MODES`.

    The formulas are in the module docstring; they port ``hmmlogo.c``.
    ``info_bits`` is the stack height: ``RE_k`` for the two entropy modes and the
    probability mass (1) for ``probability``.
    """
    if mode not in LOGO_MODES:
        raise ValueError(f"unknown logo mode {mode!r}, expected one of {LOGO_MODES}")
    bg = background_frequencies(model)
    heights: list[list[float]] = []
    info: list[float] = []
    for row in model.match_emissions:
        if mode == "probability":
            heights.append(list(row))
            info.append(sum(row))
            continue
        logodds = [math.log2(p / b) if p > 0 else 0.0 for p, b in zip(row, bg, strict=True)]
        rel_ent = sum(p * lo for p, lo in zip(row, logodds, strict=True) if p > 0)
        if mode == "relent_all":
            heights.append([rel_ent * p for p in row])
        else:
            above = sum(p for p, lo in zip(row, logodds, strict=True) if p > 0 and lo > 0)
            heights.append(
                [
                    rel_ent * p / above if (p > 0 and lo > 0 and above > 0) else 0.0
                    for p, lo in zip(row, logodds, strict=True)
                ]
            )
        info.append(rel_ent)
    return LetterHeights(heights, info)


# ---------------------------------------------------------------------------
# Mapping match states onto a reference sequence
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"^(?P<base>.+)/(?P<start>\d+)-(?P<end>\d+)$")


def _split_range(name: str) -> tuple[str, int | None]:
    """``P12345/31-90`` -> (``P12345``, 31); a plain name -> (name, None)."""
    match = _RANGE_RE.match(name)
    return (match["base"], int(match["start"])) if match else (name, None)


def _find_reference(rows: Sequence[tuple[str, str]], reference_id: str) -> tuple[str, int]:
    """The aligned row of ``reference_id`` and the number of its first residue."""
    ref_base, ref_start = _split_range(reference_id)
    exact = [(n, s) for n, s in rows if n == reference_id]
    if len(exact) > 1:
        raise ValueError(f"reference {reference_id!r} appears {len(exact)} times in the alignment")
    candidates = exact
    if not candidates:
        for n, s in rows:
            base, start = _split_range(n)
            if base == ref_base and (start is None or ref_start is None):
                candidates.append((n, s))
    if not candidates:
        known = ", ".join(n for n, _ in rows[:5])
        raise ValueError(
            f"reference {reference_id!r} not found in the alignment (first rows: {known})"
        )
    if len(candidates) > 1:
        names = ", ".join(n for n, _ in candidates)
        raise ValueError(
            f"reference {reference_id!r} is ambiguous ({names}); give the /start-end suffix"
        )
    row_name, row = candidates[0]
    _, row_start = _split_range(row_name)
    start = row_start if row_start is not None else ref_start if ref_start is not None else 1
    return row, start


def _residue_numbers(row: str, start: int) -> list[int | None]:
    """Residue number at each alignment column of ``row`` (``None`` on a gap)."""
    numbers: list[int | None] = []
    count = start - 1
    for char in row:
        if char in GAP_CHARS:
            numbers.append(None)
        else:
            count += 1
            numbers.append(count)
    return numbers


def _parse_stockholm(text: str) -> tuple[list[tuple[str, str]], str | None]:
    """Sequence rows (blocks joined, file order) and the ``#=GC RF`` line, if any."""
    chunks: dict[str, list[str]] = {}
    rf_chunks: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("//"):
            break
        if line.startswith("#"):
            if line.startswith("#=GC"):
                parts = line.split(None, 2)
                if len(parts) == 3 and parts[1] == "RF":
                    rf_chunks.append("".join(parts[2].split()))
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ValueError(f"Stockholm sequence line without residues: {line[:40]!r}")
        chunks.setdefault(parts[0], []).append("".join(parts[1].split()))
    rows = [(name, "".join(parts)) for name, parts in chunks.items()]
    return rows, ("".join(rf_chunks) if rf_chunks else None)


def _stockholm_match_columns(
    text: str, model_length: int | None
) -> tuple[list[tuple[str, str]], list[bool]]:
    """Rows of a Stockholm alignment and which of their columns are match states.

    Match columns are the ``#=GC RF`` characters outside :data:`GAP_CHARS`; without
    an RF line, the columns where some row has an upper-case letter or ``-``
    (HMMER's convention: inserts are lower case with ``.`` padding).
    ``model_length`` (the HMM's ``LENG``), when given, is checked against them.
    """
    rows, rf = _parse_stockholm(text)
    if not rows:
        raise ValueError("no sequence found in the Stockholm text")
    width = len(rows[0][1])
    for name, seq in rows:
        if len(seq) != width:
            raise ValueError(f"row {name!r} has {len(seq)} columns, expected {width}")
    if rf is not None:
        if len(rf) != width:
            raise ValueError(f"#=GC RF has {len(rf)} columns, the rows have {width}")
        is_match = [c not in GAP_CHARS for c in rf]
    else:
        is_match = [
            any(row[col].isupper() or row[col] == "-" for _, row in rows) for col in range(width)
        ]
    n_match = sum(is_match)
    if model_length is not None and n_match != model_length:
        source = "#=GC RF" if rf is not None else "the upper-case/'-' columns (no #=GC RF)"
        raise ValueError(
            f"{n_match} match columns found from {source}, but the model has {model_length} states"
        )
    return rows, is_match


def reference_positions_from_stockholm(
    text: str,
    reference_id: str,
    model_length: int | None = None,
    *,
    first_residue: int | None = None,
) -> list[int | None]:
    """Residue number of ``reference_id`` at each match state, from a ``hmmalign`` Stockholm file.

    Returns one entry per match column (``M`` of them, in order): the number of the
    reference residue aligned there, ``None`` where the reference has a deletion.
    Insert columns are skipped but their residues still count, so numbering stays
    true to the reference sequence.

    * match columns are the ``#=GC RF`` characters outside ``.~-_``; without an RF
      line, the columns where some row has an upper-case letter or ``-`` (HMMER's
      convention: inserts are lower case with ``.`` padding);
    * sequence blocks (interleaved Stockholm) are joined;
    * a ``/start-end`` suffix on the row sets the first residue number; the
      ``reference_id`` may carry it or not;
    * ``first_residue`` overrides that: the number of the reference's first residue,
      whatever its row name says (``1`` numbers along the sequence itself, which is
      how a structure predicted from it numbers its residues);
    * ``model_length`` (the HMM's ``LENG``) is checked against the match columns.
    """
    rows, is_match = _stockholm_match_columns(text, model_length)
    row, start = _find_reference(rows, reference_id)
    numbers = _residue_numbers(row, first_residue if first_residue is not None else start)
    return [numbers[col] for col in range(len(row)) if is_match[col]]


class MemberSpan(NamedTuple):
    """Where one aligned row sits on the model: see :func:`member_spans_from_stockholm`."""

    name: str
    #: First and last match state the row has a residue at (1-based).
    hmm_from: int
    hmm_to: int
    #: Residue numbers of those two residues along the row's own sequence (1-based).
    ali_from: int
    ali_to: int
    #: Residues of the row (match and insert columns).
    length: int
    #: Match states of the model (``M``).
    n_states: int


def member_spans_from_stockholm(text: str, model_length: int | None = None) -> list[MemberSpan]:
    """How much of the model each row of a ``hmmalign`` Stockholm file covers.

    One :class:`MemberSpan` per row with a residue in at least one match column, in
    file order: the first and last match state it aligns to, and the numbers of
    the residues sitting there counted from 1 along the row's own ungapped sequence
    (a ``/start-end`` suffix of the name is ignored: the span is on the sequence
    as aligned). Deletions inside the span are not subtracted, and a row with no
    residue in any match state is left out. Match columns and ``model_length``
    follow :func:`reference_positions_from_stockholm`.
    """
    rows, is_match = _stockholm_match_columns(text, model_length)
    match_columns = [col for col, flag in enumerate(is_match) if flag]
    n_states = len(match_columns)
    spans: list[MemberSpan] = []
    for name, seq in rows:
        numbers = _residue_numbers(seq, 1)
        aligned = [
            (state, number)
            for state, col in enumerate(match_columns, 1)
            if (number := numbers[col]) is not None
        ]
        if not aligned:
            continue
        (first, ali_from), (last, ali_to) = aligned[0], aligned[-1]
        length = sum(1 for number in numbers if number is not None)
        spans.append(MemberSpan(name, first, last, ali_from, ali_to, length, n_states))
    return spans


def reference_positions_from_map(
    model: HmmModel,
    aligned: dict[str, str] | Sequence[tuple[str, str]],
    reference_id: str,
) -> list[int | None]:
    """Residue number of ``reference_id`` at each match state, from the model's ``MAP``.

    ``MAP`` gives, for every match state, the 1-based column of the alignment
    ``hmmbuild`` read; ``aligned`` is that same alignment (aligned FASTA rows, gaps
    ``-`` or ``.``). ``None`` where the reference has a gap in the mapped column or
    the model has no ``MAP`` entry for the state. Same ``/start-end`` rules as
    :func:`reference_positions_from_stockholm`.
    """
    if all(c is None for c in model.map_columns):
        raise ValueError(f"HMM {model.name!r} has no MAP annotation")
    rows = list(aligned.items()) if isinstance(aligned, dict) else [(n, s) for n, s in aligned]
    row, start = _find_reference(rows, reference_id)
    numbers = _residue_numbers(row, start)
    out: list[int | None] = []
    for state, column in enumerate(model.map_columns, start=1):
        if column is None:
            out.append(None)
        elif not 1 <= column <= len(numbers):
            raise ValueError(
                f"HMM {model.name!r}: state {state} maps to column {column}, "
                f"the reference row has {len(numbers)}"
            )
        else:
            out.append(numbers[column - 1])
    return out


# ---------------------------------------------------------------------------
# Long table
# ---------------------------------------------------------------------------

#: Columns of :func:`profile_frame`. Deliberately no ``residue`` column: that name
#: belongs to the residue tables these rows are linked to.
PROFILE_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "position": pl.Int64,
    "hmm_name": pl.Utf8,
    "hmm_acc": pl.Utf8,
    "hmm_position": pl.Int64,
    "hmm_letter": pl.Utf8,
    "emission": pl.Float64,
    "height_bits": pl.Float64,
    "info_bits": pl.Float64,
    "insert_prob": pl.Float64,
    "insert_length": pl.Float64,
    "occupancy": pl.Float64,
    "delete_prob": pl.Float64,
    "consensus": pl.Utf8,
    "rf": pl.Utf8,
    "cs": pl.Utf8,
    "map_column": pl.Int64,
}


def profile_frame(
    model: HmmModel,
    *,
    entity: str | None = None,
    positions: list[int | None] | None = None,
    mode: str = "relent_abovebg",
) -> pl.DataFrame:
    """One row per (match state, letter), sorted by ``hmm_position`` then ``hmm_letter``.

    ``entity`` is the reference sequence id (default: the model name); ``positions``
    its residue number per match state (see ``reference_positions_from_*``), ``None``
    entries and a missing list give a null ``position``. ``mode`` is a
    :data:`LOGO_MODES` entry for ``height_bits``. State-level values (``info_bits``,
    indel values, occupancy, annotations) repeat on every letter row of the state.
    A non-finite ``insert_length`` is stored as null.
    """
    m, k = model.length, len(model.alphabet)
    if positions is not None and len(positions) != m:
        raise ValueError(f"positions has {len(positions)} entries, the model has {m} states")
    pos = positions if positions is not None else [None] * m
    heights = letter_heights(model, mode)
    occ = occupancy(model)
    dele = delete_probability(model)
    ins_p = insert_probability(model)
    ins_len = [v if math.isfinite(v) else None for v in expected_insert_length(model)]
    label = entity if entity is not None else model.name

    data: dict[str, list] = {name: [] for name in PROFILE_SCHEMA}
    for i in range(m):
        for a in range(k):
            data["entity"].append(label)
            data["position"].append(pos[i])
            data["hmm_name"].append(model.name)
            data["hmm_acc"].append(model.acc)
            data["hmm_position"].append(i + 1)
            data["hmm_letter"].append(model.alphabet[a])
            data["emission"].append(model.match_emissions[i][a])
            data["height_bits"].append(heights.heights[i][a])
            data["info_bits"].append(heights.info_bits[i])
            data["insert_prob"].append(ins_p[i])
            data["insert_length"].append(ins_len[i])
            data["occupancy"].append(occ[i])
            data["delete_prob"].append(dele[i])
            data["consensus"].append(model.consensus[i])
            data["rf"].append(model.rf[i])
            data["cs"].append(model.cs[i])
            data["map_column"].append(model.map_columns[i])
    return pl.DataFrame(data, schema=PROFILE_SCHEMA).sort(["hmm_position", "hmm_letter"])
