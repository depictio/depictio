"""Predicted aligned error (PAE) matrices from the formats structure predictors publish.

A residue-linked PAE heatmap needs one square ``N x N`` matrix of floats, rows
being the aligned residue and columns the scored residue. Where it comes from:

* nf-core/proteinfold: ``paes/<name>_<rank>_pae.tsv``, whitespace or tab separated;
* AlphaFold DB (v3/v4): ``[{"predicted_aligned_error": [[...]], "max_predicted_aligned_error": 31.75}]``;
* ColabFold: a bare ``{"predicted_aligned_error": [[...]]}`` (or ``{"pae": [[...]]}``);
* AlphaFold DB v1: ``[{"residue1": [...], "residue2": [...], "distance": [...]}]``, the
  matrix flattened into 1-based residue pairs.

:func:`read_pae` takes any of them (also gzipped) and :func:`write_pae_tsv` writes
the neutral tab-separated form back.
"""

from __future__ import annotations

import gzip
import json
import re
from typing import Any

#: Keys under which a JSON object may hold the matrix.
_MATRIX_KEYS = ("predicted_aligned_error", "pae")
_SPLIT_RE = re.compile(r"[,;\s]+")


def read_pae(data: str | bytes) -> list[list[float]]:
    """Parse a PAE matrix from text, JSON or gzipped bytes of either.

    Raises :class:`ValueError` when nothing readable or square is found.
    """
    if isinstance(data, bytes):
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        text = data.decode("utf-8-sig")
    else:
        text = data.lstrip("﻿")
    text = text.strip()
    if not text:
        raise ValueError("empty PAE input")
    matrix = _from_json(text) if text[0] in "[{" else _from_delimited(text)
    return _validated(matrix)


def max_pae(matrix: list[list[float]]) -> float:
    """Largest error in the matrix (the heatmap's colour-scale upper bound)."""
    if not matrix or not matrix[0]:
        raise ValueError("empty PAE matrix")
    return max(max(row) for row in matrix)


def write_pae_tsv(matrix: list[list[float]], decimals: int = 2) -> str:
    """Tab-separated matrix, no header, one newline-terminated line per row."""
    return "".join("\t".join(f"{v:.{decimals}f}" for v in row) + "\n" for row in matrix)


def _from_delimited(text: str) -> list[list[float]]:
    rows: list[list[float]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        tokens = [t for t in _SPLIT_RE.split(line.strip()) if t]
        if not tokens:
            continue
        try:
            rows.append([float(t) for t in tokens])
        except ValueError:
            if not rows and not _any_number(tokens):  # a header row of names
                continue
            raise ValueError(f"line {number}: non-numeric value in PAE row") from None
    return rows


def _any_number(tokens: list[str]) -> bool:
    for token in tokens:
        try:
            float(token)
        except ValueError:
            continue
        return True
    return False


def _from_json(text: str) -> list[list[float]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"PAE JSON is not valid: {exc}") from None
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        payload = payload[0]  # AlphaFold DB wraps the object in a one-item list
    if isinstance(payload, dict):
        for key in _MATRIX_KEYS:
            if key in payload:
                return _numeric_matrix(payload[key])
        if {"residue1", "residue2", "distance"} <= payload.keys():
            return _from_pairs(payload["residue1"], payload["residue2"], payload["distance"])
        raise ValueError(
            f"PAE JSON has none of {', '.join(_MATRIX_KEYS)} nor residue1/residue2/distance"
        )
    return _numeric_matrix(payload)


def _numeric_matrix(value: Any) -> list[list[float]]:
    if not isinstance(value, list) or not all(isinstance(row, list) for row in value):
        raise ValueError("PAE matrix must be a list of rows")
    try:
        return [[_number(v) for v in row] for row in value]
    except (TypeError, ValueError):
        raise ValueError("PAE matrix holds a non-numeric value") from None


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("not a number")
    return float(value)


def _from_pairs(residue1: Any, residue2: Any, distance: Any) -> list[list[float]]:
    """AlphaFold DB v1: flattened (residue1, residue2, error) triples, residues 1-based."""
    if not all(isinstance(v, list) for v in (residue1, residue2, distance)):
        raise ValueError("residue1, residue2 and distance must be lists")
    if not len(residue1) == len(residue2) == len(distance):
        raise ValueError("residue1, residue2 and distance differ in length")
    if not residue1:
        raise ValueError("empty PAE pair list")
    try:
        r1 = [int(v) for v in residue1]
        r2 = [int(v) for v in residue2]
        values = [_number(v) for v in distance]
    except (TypeError, ValueError):
        raise ValueError("PAE pair lists hold a non-numeric value") from None
    if min(r1) < 1 or min(r2) < 1:
        raise ValueError("residue indices are 1-based")
    size = max(max(r1), max(r2))
    matrix: list[list[float | None]] = [[None] * size for _ in range(size)]
    for a, b, v in zip(r1, r2, values, strict=True):
        matrix[a - 1][b - 1] = v
    if any(v is None for row in matrix for v in row):
        raise ValueError(f"PAE pairs do not cover the full {size} x {size} matrix")
    return [[float(v) for v in row if v is not None] for row in matrix]


def _validated(matrix: list[list[float]]) -> list[list[float]]:
    size = len(matrix)
    if size == 0:
        raise ValueError("no PAE rows found")
    widths = {len(row) for row in matrix}
    if widths != {size}:
        raise ValueError(f"PAE matrix must be square: {size} rows, row lengths {sorted(widths)}")
    return matrix
