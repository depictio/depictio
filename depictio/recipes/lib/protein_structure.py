"""Per-residue tables read out of a PDB structure file.

Structure predictors (AlphaFold2, ColabFold, ESMFold, RoseTTAFold, Boltz)
write their per-residue confidence (pLDDT) into the B-factor column of the
PDB, so the residue table the ``molecule_3d`` and ``sequence_track`` kinds
read can be taken straight from the structure: one row per residue with its
chain, its residue number in the file's own numbering (the numbering the 3D
viewer picks residues by), its one-letter code and the B-factor of its CA atom.

Some predictors (RoseTTAFold All-Atom) store pLDDT as a 0-1 fraction; with
``rescale_unit_plddt`` a structure whose every B-factor lies in [0, 1] is put
on the usual 0-100 scale, so one colour scale fits every engine.

Shared here because every protein template reads structures, and recipes may
not import each other.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import polars as pl

#: Canonical residue table schema (see the protein module contract).
RESIDUE_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "chain": pl.Utf8,
    "position": pl.Int64,
    "residue": pl.Utf8,
    "value": pl.Float64,
}

#: Three-letter residue names to one-letter codes. Modified amino acids map to
#: their parent, nucleotides (RNA and DNA partners of a complex) to their base.
THREE_TO_ONE: dict[str, str] = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    "SEC": "U",
    "PYL": "O",
    "MSE": "M",
    "HSD": "H",
    "HSE": "H",
    "HSP": "H",
    "HID": "H",
    "HIE": "H",
    "HIP": "H",
    "UNK": "X",
    "A": "A",
    "C": "C",
    "G": "G",
    "U": "U",
    "T": "T",
    "DA": "A",
    "DC": "C",
    "DG": "G",
    "DT": "T",
    "DU": "U",
}

#: HETATM residues read as part of the chain (selenomethionine); everything
#: else in HETATM (ligands, waters, ions) is skipped.
_POLYMER_HETATM = frozenset({"MSE", "SEC", "PYL"})

#: Atom whose B-factor stands for the residue: CA for amino acids, C1' for
#: nucleotides, else the residue's first atom.
_REPRESENTATIVE_ATOMS = ("CA", "C1'")

#: AlphaFold's pLDDT confidence bands, lower bound inclusive, highest first.
PLDDT_BANDS: tuple[tuple[float, str], ...] = (
    (90.0, "very high"),
    (70.0, "confident"),
    (50.0, "low"),
    (0.0, "very low"),
)


def _read_text(text_or_path: str | Path | bytes) -> str:
    if isinstance(text_or_path, bytes):
        return text_or_path.decode("utf-8", errors="replace")
    if isinstance(text_or_path, Path) or "\n" not in text_or_path:
        path = Path(text_or_path)
        raw = path.read_bytes()
        if path.suffix == ".gz" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")
    return text_or_path


def _residue_atoms(text: str) -> list[tuple[str, int, str, str, str, float]]:
    """``(chain, resseq, icode, resname, atom, bfactor)`` of the first model."""
    atoms = []
    for line in text.splitlines():
        record = line[:6]
        if record.startswith("ENDMDL"):
            break
        if record not in ("ATOM  ", "HETATM") or len(line) < 54:
            continue
        resname = line[17:20].strip()
        if record == "HETATM" and resname not in _POLYMER_HETATM:
            continue
        try:
            resseq = int(line[22:26])
        except ValueError:
            continue
        try:
            bfactor = float(line[60:66])
        except (ValueError, IndexError):
            bfactor = float("nan")
        atoms.append(
            (
                line[21].strip() or "A",
                resseq,
                line[26].strip() if len(line) > 26 else "",
                resname,
                line[12:16].strip(),
                bfactor,
            )
        )
    return atoms


def _residues(text: str) -> list[tuple[str, int, str, float]]:
    """``(chain, position, one-letter, bfactor)`` per residue, file order."""
    order: list[tuple[str, int, str]] = []
    info: dict[tuple[str, int, str], dict[str, float | str]] = {}
    for chain, resseq, icode, resname, atom, bfactor in _residue_atoms(text):
        key = (chain, resseq, icode)
        if key not in info:
            order.append(key)
            info[key] = {"resname": resname, "first": bfactor}
        if atom in _REPRESENTATIVE_ATOMS and atom not in info[key]:
            info[key][atom] = bfactor
    residues = []
    for key in order:
        entry = info[key]
        rep = next((entry[a] for a in _REPRESENTATIVE_ATOMS if a in entry), entry["first"])
        residues.append(
            (key[0], key[1], THREE_TO_ONE.get(str(entry["resname"]).upper(), "X"), float(rep))
        )
    return residues


def residues_from_pdb(
    text_or_path: str | Path | bytes,
    entity: str,
    *,
    rescale_unit_plddt: bool = True,
) -> pl.DataFrame:
    """The residue table of one structure (first model only).

    Columns follow ``RESIDUE_SCHEMA``: ``entity`` as given, ``chain``,
    ``position`` (the file's residue number), ``residue`` (one-letter) and
    ``value`` (B-factor of the CA atom, pLDDT for predicted models). Insertion
    codes collapse onto their residue number's row order but keep one row each.
    """
    residues = _residues(_read_text(text_or_path))
    values = [r[3] for r in residues]
    finite = [v for v in values if v == v]
    if rescale_unit_plddt and finite and max(finite) <= 1.0 and min(finite) >= 0.0:
        values = [v * 100.0 for v in values]
    return pl.DataFrame(
        {
            "entity": [entity] * len(residues),
            "chain": [r[0] for r in residues],
            "position": [r[1] for r in residues],
            "residue": [r[2] for r in residues],
            "value": values,
        },
        schema=RESIDUE_SCHEMA,
    )


def sequences_from_pdb(text_or_path: str | Path | bytes) -> dict[str, str]:
    """One-letter sequence of every chain, in file order."""
    sequences: dict[str, list[str]] = {}
    for chain, _, letter, _ in _residues(_read_text(text_or_path)):
        sequences.setdefault(chain, []).append(letter)
    return {chain: "".join(letters) for chain, letters in sequences.items()}


def sequence_from_pdb(
    text_or_path: str | Path | bytes, chain: str | None = None, *, sep: str = ""
) -> str:
    """One-letter sequence of ``chain``, or of every chain joined by ``sep``."""
    sequences = sequences_from_pdb(text_or_path)
    if chain is not None:
        return sequences.get(chain, "")
    return sep.join(sequences.values())


def plddt_band(value: float | None) -> str | None:
    """AlphaFold confidence band of one pLDDT value (0-100)."""
    if value is None or value != value:
        return None
    for lower, label in PLDDT_BANDS:
        if value >= lower:
            return label
    return PLDDT_BANDS[-1][1]


def plddt_band_expr(column: str = "value", alias: str = "category") -> pl.Expr:
    """Polars expression mapping a pLDDT column onto its confidence band."""
    expr = pl.when(pl.col(column).is_null() | pl.col(column).is_nan()).then(pl.lit(None))
    for lower, label in PLDDT_BANDS:
        expr = expr.when(pl.col(column) >= lower).then(pl.lit(label))
    return expr.otherwise(pl.lit(PLDDT_BANDS[-1][1])).cast(pl.Utf8).alias(alias)
