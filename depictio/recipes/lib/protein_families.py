"""Shared parsing for protein-family outputs (nf-core/proteinfamilies layout).

The family recipes read their inputs through the one-column text scan idiom
(one file line per row in ``raw``, the file in ``source_path``), because the
formats involved (aligned FASTA, HMMER3 models, Newick trees) are not tables.
This module turns such a scan back into whole files and holds the per-family
computations more than one recipe needs:

- ``texts_by_file``: ``{source_path: text}`` in scan order;
- ``family_id`` / ``sample_from_path`` / ``origin_from_path``: the keys the
  pipeline writes into its paths (``<step>/<sample>/<family>.<ext>``, with
  the families an update run extends under ``update_families/``);
- ``column_conservation``: per-residue conservation of an alignment in the
  numbering of its first (reference) row;
- ``parse_hmm``: the header fields of a HMMER3 profile.

Kept free of pipeline-specific sample names: every key comes from the file
layout the pipeline documents, never from the content of a sample id.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

import polars as pl

#: Suffixes stripped, longest first, to turn a file name into its family id.
FAMILY_SUFFIXES: tuple[str, ...] = (
    ".treefile",
    ".hmm.gz",
    ".hmm",
    ".sto.gz",
    ".sto",
    ".fas.gz",
    ".fas",
    ".fasta.gz",
    ".fasta",
    ".aln",
    ".clipkit",
    ".faa",
)

#: Residue classes a conservation score falls into (score thresholds, high first).
CONSERVATION_CLASSES: tuple[tuple[float, str], ...] = (
    (0.7, "conserved"),
    (0.4, "intermediate"),
    (0.0, "variable"),
)

_AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
_GAPS = frozenset("-.")


def _posix(path: str) -> str:
    return path.replace("\\", "/")


def family_id(path: str) -> str:
    """The family a per-family file belongs to: its name without the format suffix."""
    name = _posix(path).rsplit("/", 1)[-1]
    for suffix in FAMILY_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name.rsplit(".", 1)[0] if "." in name else name


def sample_from_path(path: str) -> str:
    """The sample of a per-family file: the directory it sits in (``<step>/<sample>/<file>``)."""
    parts = _posix(path).rstrip("/").split("/")
    return parts[-2] if len(parts) >= 2 else ""


def origin_from_path(path: str) -> str:
    """``updated`` for an existing family an update run extended, else ``new``."""
    return "updated" if "update_families/" in _posix(path) else "new"


def texts_by_file(
    raw: pl.DataFrame, text_col: str = "raw", path_col: str = "source_path"
) -> dict[str, str]:
    """Reassemble a one-line-per-row text scan into ``{file: text}``, keeping line order.

    Blank lines come back from the scan as nulls; they are restored as empty
    lines so a parser sees the file as written.
    """
    if raw is None or raw.height == 0 or text_col not in raw.columns:
        return {}
    texts: dict[str, list[str]] = {}
    paths = raw[path_col].to_list() if path_col in raw.columns else [""] * raw.height
    for path, line in zip(paths, raw[text_col].to_list(), strict=True):
        texts.setdefault(path or "", []).append(line or "")
    return {path: "\n".join(lines) for path, lines in texts.items()}


def ungapped(sequence: str) -> str:
    """The residues of an aligned row, gaps removed."""
    return "".join(c for c in sequence if c not in _GAPS)


def conservation_class(score: float | None) -> str | None:
    """The class of ``CONSERVATION_CLASSES`` a score falls into."""
    if score is None:
        return None
    for threshold, label in CONSERVATION_CLASSES:
        if score >= threshold:
            return label
    return CONSERVATION_CLASSES[-1][1]


def column_conservation(records: Sequence[tuple[str, str]]) -> list[dict]:
    """Per-residue conservation of an alignment, in its first row's numbering.

    One dict per residue of the reference row (``records[0]``), with
    ``position`` (1-based, gaps of the reference skipped), ``residue``,
    ``consensus`` (most frequent residue of the column), ``consensus_share``
    (its share of the column's residues), ``occupancy`` (share of rows with a
    residue in the column) and ``value``: ``(1 - H / log2(20)) * occupancy``,
    the Shannon entropy of the column's residues normalised to the 20 amino
    acids and discounted by its gaps, so 1 is an invariant, gap-free column.
    """
    if not records:
        return []
    reference = records[0][1]
    width = len(reference)
    rows = [seq for _, seq in records if len(seq) == width]
    n_rows = len(rows)
    max_entropy = math.log2(len(_AMINO_ACIDS))
    out: list[dict] = []
    position = 0
    for col in range(width):
        ref_residue = reference[col]
        if ref_residue in _GAPS:
            continue
        position += 1
        residues = [row[col].upper() for row in rows if row[col] not in _GAPS]
        occupancy = len(residues) / n_rows if n_rows else 0.0
        counts = Counter(residues)
        if residues:
            entropy = -sum(
                (n / len(residues)) * math.log2(n / len(residues)) for n in counts.values()
            )
            consensus, top = counts.most_common(1)[0]
            share = top / len(residues)
        else:
            entropy, consensus, share = max_entropy, None, 0.0
        score = max(0.0, 1.0 - entropy / max_entropy) * occupancy
        out.append(
            {
                "position": position,
                "residue": ref_residue.upper(),
                "consensus": consensus,
                "consensus_share": share,
                "occupancy": occupancy,
                "value": score,
            }
        )
    return out


_HMM_HEADER = re.compile(r"^(NAME|LENG|NSEQ|EFFN)\s+(.+?)\s*$")


def parse_hmm(text: str) -> dict:
    """Header fields of a HMMER3 profile: ``{"name", "length", "nseq", "effn"}``.

    ``length`` is the number of match states (``LENG``), ``nseq`` the
    sequences the model was built from (``NSEQ``) and ``effn`` HMMER's
    effective sequence number after entropy weighting (``EFFN``). Only the
    header of the first model of the file is read. The per-state information
    content is not reported: hmmbuild's entropy weighting pins its mean to a
    target (0.59 bits per state for proteins), so it does not tell families apart.
    """
    header: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("HMM ") or line.startswith("//"):
            break
        match = _HMM_HEADER.match(line)
        if match:
            header.setdefault(match.group(1), match.group(2))

    def _num(key: str, cast):
        try:
            return cast(header[key])
        except (KeyError, ValueError):
            return None

    return {
        "name": header.get("NAME"),
        "length": _num("LENG", int),
        "nseq": _num("NSEQ", int),
        "effn": _num("EFFN", float),
    }
