"""Data-collection config for 3D molecular structure (PDB / mmCIF) files.

A `structure` DC is file-backed (the .pdb / .cif file lives on disk under
the project's data_location), following the same pattern as `phylogeny`.
The scanner registers the file's location; the backend then serves the raw
structure text via the /advanced_viz/structure/{dc_id}/file endpoint, and
the React renderer (viz_kind "molecule_3d") hands it to 3Dmol.js.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class DCStructureConfig(BaseModel):
    """Config for a 3D molecular structure (PDB / mmCIF) data collection."""

    format: Literal["pdb", "mmcif"] = "pdb"
    # True when the B-factor column carries per-residue pLDDT confidence
    # (the AlphaFold / ESMFold / ColabFold convention) — enables the
    # renderer's pLDDT colour mode.
    plddt_in_bfactor: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator("format", mode="before")
    @classmethod
    def _normalise_format(cls, v: str) -> str:
        return v.lower() if isinstance(v, str) else v
