"""Data-collection config for phylogeny (Newick/Nexus tree) files.

A `phylogeny` DC is file-backed (the .nwk / .nex file lives on disk under
the project's data_location). The scanner registers the file's location;
the backend then serves the raw Newick string via the
/advanced_viz/phylogeny/{dc_id}/newick endpoint, and the React renderer
hands it to Phylocanvas 3 (via react-phylogeny-tree).

Metadata for tip annotations (group / habitat / etc.) lives in a *separate*
Table DC keyed by the taxon name — same pattern Microreact uses.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class DCPhylogenyConfig(BaseModel):
    """Config for a phylogeny (Newick / Nexus) data collection."""

    format: Literal["newick", "nexus"] = "newick"
    # If True the renderer ladderises the tree by default (clade sizes
    # ordered ascending); the user can toggle in the viz controls.
    ladderize: bool = True
    # Name of a separate Table DC supplying tip metadata (group / habitat
    # / clinical labels). Optional — the renderer falls back to "no
    # metadata" if absent.
    metadata_dc_tag: str | None = None
    # Column in the metadata DC that joins to tip labels in the tree.
    metadata_taxon_column: str | None = "taxon"
    # Convention for tip labels in the tree:
    #   - "taxon" → leaf name IS the taxon id (no transform)
    #   - "first_token" → take the first underscore-separated token
    tip_label_strategy: Literal["taxon", "first_token"] = "taxon"

    model_config = ConfigDict(extra="forbid")

    @field_validator("format")
    @classmethod
    def _normalise_format(cls, v: str) -> str:
        return v.lower()
