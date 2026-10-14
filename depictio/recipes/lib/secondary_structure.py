"""S4PRED / PSIPRED secondary-structure predictions (``.ss2``) as a residue table.

nf-core/proteinannotator runs S4PRED and publishes one ``.ss2`` file per sequence
in PSIPRED's VFORMAT::

    # PSIPRED VFORMAT (S4PRED V1.2.1)

       1 M C   0.999  0.001  0.000
       2 K H   0.210  0.760  0.030

that is ``position residue state P(coil) P(helix) P(strand)`` with the state one
of ``C``, ``H``, ``E``.

:func:`parse_ss2` yields exactly the columns of the s4pred catalog recipe
(``depictio/catalog/s4pred/secondary_structure.py``: ``OUTPUT_SCHEMA``, the
``STATES`` names, the ``value`` rule and the sort order), so a recipe can call it
instead of repeating the split. :func:`segments` turns the per-residue states
into the runs a secondary-structure track draws.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

#: Columns of :func:`parse_ss2`; the s4pred recipe's ``OUTPUT_SCHEMA`` is built from them.
SS2_SCHEMA: dict[str, type[pl.DataType]] = {
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

#: Predicted state code -> its name in the ``category`` column.
STATES = {"H": "Helix", "E": "Strand", "C": "Coil"}


def _to_int(token: str | None) -> int | None:
    try:
        return int(token) if token is not None else None
    except ValueError:
        return None


def _to_float(token: str | None) -> float | None:
    try:
        return float(token) if token is not None else None
    except ValueError:
        return None


def parse_ss2(text: str, entity: str, sample: str | None = None) -> pl.DataFrame:
    """One row per residue line of an ``.ss2`` file.

    Comment (``#``) and blank lines are skipped, as is any line whose first field is
    not an integer. ``position`` is the one written in the file (1-based).
    ``category`` names the called state (Helix, Strand, Coil; null for any other
    code) and ``value`` is the probability of that state: ``p_helix`` for ``H``,
    ``p_strand`` for ``E`` and ``p_coil`` otherwise, like the recipe. ``sample``
    defaults to ``entity``. Rows are sorted by sample, entity, position.
    """
    columns: dict[str, list] = {name: [] for name in SS2_SCHEMA}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(None, 5)
        position = _to_int(fields[0])
        if position is None:
            continue
        fields += [None] * (6 - len(fields))
        residue, ss_code = fields[1], fields[2]
        p_coil, p_helix, p_strand = (_to_float(f) for f in fields[3:6])
        if ss_code == "H":
            value = p_helix
        elif ss_code == "E":
            value = p_strand
        else:
            value = p_coil
        columns["entity"].append(entity)
        columns["sample"].append(sample if sample is not None else entity)
        columns["position"].append(position)
        columns["residue"].append(residue)
        columns["ss_code"].append(ss_code)
        columns["category"].append(STATES.get(ss_code) if ss_code is not None else None)
        columns["value"].append(value)
        columns["p_coil"].append(p_coil)
        columns["p_helix"].append(p_helix)
        columns["p_strand"].append(p_strand)
    return pl.DataFrame(columns, schema=SS2_SCHEMA).sort(["sample", "entity", "position"])


def segments(states: Sequence[str]) -> list[tuple[str, int, int]]:
    """Runs of identical states as ``(state, start, end)``, 1-based and inclusive.

    ``segments("CCHHHE")`` -> ``[("C", 1, 2), ("H", 3, 5), ("E", 6, 6)]``.
    """
    runs: list[tuple[str, int, int]] = []
    for index, state in enumerate(states, start=1):
        if runs and runs[-1][0] == state:
            runs[-1] = (state, runs[-1][1], index)
        else:
            runs.append((state, index, index))
    return runs
