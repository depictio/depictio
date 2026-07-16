"""The benchmark matrix: the set of dimensions and how to expand them into cells.

A *cell* is a single, fully-specified benchmark configuration — one generated
project + dashboard. The runner ingests it, renders every component, and records
a result row per component.

Dimensions (all parameterizable from the CLI so a smoke run is cheap and a full
sweep is opt-in):

- ``size``        : bytes per data collection (10mb ... 10gb)
- ``n_components``: number of components in the tab
- ``n_dcs``       : number of data collections rendered in parallel
- ``connect``     : how the DCs relate — independent / joins / links
- ``visu``        : the visualization types mixed across the components

The Celery on/off dimension is *not* a cell attribute — it is a server-level
setting that cannot be flipped mid-process (see ``runner.py``). The same matrix
is run once per server config; each render is stamped with its actual path from
the ``X-Celery-Path`` response header.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum

# ── Size ladder ─────────────────────────────────────────────────────────────
# Human name -> target bytes per data collection (on-disk CSV, pre-Delta).
SIZES: dict[str, int] = {
    "10mb": 10 * 1024**2,
    "100mb": 100 * 1024**2,
    "1gb": 1 * 1024**3,
    "5gb": 5 * 1024**3,
    "10gb": 10 * 1024**3,
}


class ConnectMode(str, Enum):
    """How the data collections in a cell relate to each other."""

    INDEPENDENT = "independent"  # N unrelated DCs side by side (baseline)
    JOINS = "joins"  # materialized top-level joins: -> one wide Delta table
    LINKS = "links"  # virtual cross-filter links: -> DCs stay separate


class VisuType(str, Enum):
    """The component families the benchmark exercises."""

    FIGURE = "figure"  # Plotly figure (scatter/bar/box) via /render_figure
    TABLE = "table"  # AG-Grid table via /render_table
    ADVANCED_VIZ = "advanced_viz"  # async compute job (always Celery)


# Concrete Plotly ``visu_type`` values rotated across figure components.
FIGURE_VISU_ROTATION: tuple[str, ...] = ("scatter", "bar", "box", "histogram")
# ``viz_kind`` values rotated across advanced_viz components (kept to kinds that
# map cleanly onto the generic numeric columns the generator produces).
ADVANCED_VIZ_ROTATION: tuple[str, ...] = ("volcano", "ma")


@dataclass(frozen=True)
class Cell:
    """A single, fully-specified benchmark configuration."""

    size: str  # key into SIZES
    n_components: int
    n_dcs: int
    connect: ConnectMode
    visu: tuple[VisuType, ...]

    @property
    def size_bytes(self) -> int:
        return SIZES[self.size]

    @property
    def slug(self) -> str:
        """Filesystem/collection-safe unique identifier for this cell."""
        visu = "-".join(v.value for v in self.visu)
        return f"bench_{self.size}_c{self.n_components}_dc{self.n_dcs}_{self.connect.value}_{visu}"


@dataclass
class MatrixSpec:
    """Selected values per dimension; ``expand()`` -> the cartesian product."""

    sizes: list[str] = field(default_factory=lambda: ["10mb"])
    n_components: list[int] = field(default_factory=lambda: [5])
    n_dcs: list[int] = field(default_factory=lambda: [2])
    connect: list[ConnectMode] = field(default_factory=lambda: [ConnectMode.JOINS])
    visu: list[VisuType] = field(default_factory=lambda: [VisuType.FIGURE, VisuType.TABLE])

    def __post_init__(self) -> None:
        for s in self.sizes:
            if s not in SIZES:
                raise ValueError(f"Unknown size {s!r}; valid: {sorted(SIZES)}")
        for n in self.n_dcs:
            if n < 1:
                raise ValueError(f"n_dcs must be >= 1, got {n}")
        for n in self.n_components:
            if n < 1:
                raise ValueError(f"n_components must be >= 1, got {n}")

    def expand(self) -> list[Cell]:
        """Cartesian product over the scalar dimensions.

        ``connect = links`` requires >= 2 DCs (there must be something to link
        to); such degenerate combinations are skipped rather than erroring.
        The ``visu`` list is applied whole to every cell (the component-count
        loop rotates through it), so it is not part of the product.
        """
        cells: list[Cell] = []
        for size, n_comp, n_dc, conn in itertools.product(
            self.sizes, self.n_components, self.n_dcs, self.connect
        ):
            if conn in (ConnectMode.JOINS, ConnectMode.LINKS) and n_dc < 2:
                continue
            cells.append(
                Cell(
                    size=size,
                    n_components=n_comp,
                    n_dcs=n_dc,
                    connect=conn,
                    visu=tuple(self.visu),
                )
            )
        return cells


# ── CLI parsing helpers ─────────────────────────────────────────────────────
def parse_sizes(raw: str) -> list[str]:
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def parse_ints(raw: str) -> list[int]:
    return [int(s.strip()) for s in raw.split(",") if s.strip()]


def parse_connect(raw: str) -> list[ConnectMode]:
    return [ConnectMode(s.strip().lower()) for s in raw.split(",") if s.strip()]


def parse_visu(raw: str) -> list[VisuType]:
    return [VisuType(s.strip().lower()) for s in raw.split(",") if s.strip()]
