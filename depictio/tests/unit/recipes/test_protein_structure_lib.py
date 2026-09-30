"""Shared structure helpers: residue table and sequences from a PDB."""

from __future__ import annotations

import gzip
from pathlib import Path

import polars as pl

from depictio.recipes.lib.protein_structure import (
    RESIDUE_SCHEMA,
    plddt_band,
    plddt_band_expr,
    residues_from_pdb,
    sequence_from_pdb,
    sequences_from_pdb,
)


def _atom(serial: int, name: str, resname: str, chain: str, resseq: int, bfactor: float) -> str:
    record = "HETATM" if resname in {"MSE", "HOH"} else "ATOM  "
    return (
        f"{record}{serial:5d} {name:<4} {resname:>3} {chain}{resseq:4d}    "
        f"{0.0:8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{bfactor:6.2f}           C  "
    )


PDB = "\n".join(
    [
        "PARENT N/A",
        "MODEL        1",
        _atom(1, "N", "MET", "A", 1, 40.0),
        _atom(2, "CA", "MET", "A", 1, 55.5),
        _atom(3, "CA", "LYS", "A", 2, 91.0),
        _atom(4, "N", "MSE", "A", 3, 20.0),
        _atom(5, "CA", "MSE", "A", 3, 70.0),
        "TER",
        _atom(6, "CA", "GLY", "B", 665, 49.9),
        _atom(7, "O", "HOH", "B", 900, 10.0),
        "ENDMDL",
        "MODEL        2",
        _atom(8, "CA", "ALA", "C", 1, 99.0),
        "ENDMDL",
        "END",
    ]
)


def test_residues_from_pdb_reads_ca_bfactor_per_residue() -> None:
    df = residues_from_pdb(PDB, "e1")
    assert df.schema == pl.Schema(RESIDUE_SCHEMA)
    assert df.to_dicts() == [
        {"entity": "e1", "chain": "A", "position": 1, "residue": "M", "value": 55.5},
        {"entity": "e1", "chain": "A", "position": 2, "residue": "K", "value": 91.0},
        {"entity": "e1", "chain": "A", "position": 3, "residue": "M", "value": 70.0},
        {"entity": "e1", "chain": "B", "position": 665, "residue": "G", "value": 49.9},
    ]


def test_residues_from_pdb_rescales_unit_plddt(tmp_path: Path) -> None:
    unit = "\n".join([_atom(1, "CA", "ALA", "A", 1, 0.5), _atom(2, "CA", "GLY", "A", 2, 0.83)])
    path = tmp_path / "model.pdb.gz"
    path.write_bytes(gzip.compress(unit.encode()))
    assert residues_from_pdb(path, "e")["value"].to_list() == [50.0, 83.0]
    raw = residues_from_pdb(unit + "\n", "e", rescale_unit_plddt=False)
    assert raw["value"].to_list() == [0.5, 0.83]


def test_sequences_from_pdb() -> None:
    assert sequences_from_pdb(PDB) == {"A": "MKM", "B": "G"}
    assert sequence_from_pdb(PDB) == "MKMG"
    assert sequence_from_pdb(PDB, sep=":") == "MKM:G"
    assert sequence_from_pdb(PDB, chain="B") == "G"


def test_plddt_band_and_expr_agree() -> None:
    values = [95.0, 90.0, 75.0, 50.0, 12.0, None]
    expected = ["very high", "very high", "confident", "low", "very low", None]
    assert [plddt_band(v) for v in values] == expected
    df = pl.DataFrame({"value": values}, schema={"value": pl.Float64})
    assert df.select(plddt_band_expr("value"))["category"].to_list() == expected
