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
    # Realistic cross-filter topology: metadata / metrics / features joined on a
    # ``sample_id`` with hundreds of distinct values (benchmark.datagen_linked).
    LINKS = "links"
    # The symmetric dataset whose join key is unique per row. Kept because it
    # found real bugs (eager full-table read in link resolution, a timeout
    # degrading into unfiltered data, an empty resolution rendering every row) —
    # but it is an adversarial case, not what normal usage costs, so it is no
    # longer what ``links`` means.
    LINKS_ADVERSARIAL = "links-adversarial"

    @property
    def is_links(self) -> bool:
        """Either link topology (as opposed to joins/independent)."""
        return self in (ConnectMode.LINKS, ConnectMode.LINKS_ADVERSARIAL)


# The realistic link topology is a fixed three-collection shape, so ``n_dcs`` is
# not a free dimension for it.
LINKED_N_DCS = 3


class VisuType(str, Enum):
    """The component families the benchmark exercises."""

    FIGURE = "figure"  # Plotly figure (scatter/box/histogram) via /render_figure
    TABLE = "table"  # AG-Grid table via /render_table
    ADVANCED_VIZ = "advanced_viz"  # async compute job (always Celery)


# Concrete Plotly ``visu_type`` values rotated across figure components.
# ``bar`` is deliberately excluded: px.bar stacks one segment per row, so on the
# large benchmark frames it materialises millions of rectangles and stalls the
# browser — not a useful render-perf case to benchmark.
FIGURE_VISU_ROTATION: tuple[str, ...] = ("scatter", "box", "histogram")
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


class DCKind(str, Enum):
    """The data-collection ingestion families the benchmark exercises.

    Each has a *different* magnitude axis, which is why ingestion is a separate
    spec from the render :class:`MatrixSpec` (whose axes — components/connect/visu
    — are render concerns that don't apply to MultiQC/image ingestion):

    - ``TABLE``   : magnitude = on-disk CSV bytes (the ``SIZES`` ladder).
    - ``MULTIQC`` : magnitude = number of ``multiqc.parquet`` files (parse + the
      per-file HTTP round-trips dominate, not the byte size of one parquet).
    - ``IMAGES``  : magnitude = number of images (N HEAD + N PUT dominate).
    """

    TABLE = "table"
    MULTIQC = "multiqc"
    IMAGES = "images"


# Default magnitude ladders per ingestion kind (overridable from the CLI).
MULTIQC_FILE_COUNTS: tuple[int, ...] = (1, 5, 25)
IMAGE_COUNTS: tuple[int, ...] = (1_000, 10_000)


@dataclass(frozen=True)
class IngestCell:
    """One ingestion benchmark configuration (no render).

    ``magnitude`` is interpreted per :attr:`kind`: a ``SIZES`` key for TABLE, a
    file count for MULTIQC, an image count for IMAGES. ``n_dcs`` lets the table
    kind exercise the sequential/parallel multi-DC ingestion path.
    """

    kind: DCKind
    magnitude: str  # SIZES key (table) | file count (multiqc) | image count (images)
    n_dcs: int = 1

    @property
    def magnitude_int(self) -> int:
        return int(self.magnitude)

    @property
    def size_bytes(self) -> int:
        """Target bytes per DC — only meaningful for TABLE (else 0)."""
        return SIZES.get(self.magnitude, 0)

    @property
    def slug(self) -> str:
        return f"ingest_{self.kind.value}_{self.magnitude}_dc{self.n_dcs}"


@dataclass
class IngestSpec:
    """Selected ingestion cells; ``expand()`` -> one cell per (magnitude, n_dcs).

    Unlike the render matrix this is not a full cartesian product across kinds —
    each kind is expanded over its own magnitude ladder so table sizes never mix
    with MultiQC file counts.
    """

    kinds: list[DCKind] = field(default_factory=lambda: [DCKind.TABLE])
    table_sizes: list[str] = field(default_factory=lambda: ["10mb", "100mb", "1gb"])
    multiqc_counts: list[int] = field(default_factory=lambda: list(MULTIQC_FILE_COUNTS))
    image_counts: list[int] = field(default_factory=lambda: list(IMAGE_COUNTS))
    n_dcs: list[int] = field(default_factory=lambda: [1])

    def __post_init__(self) -> None:
        for s in self.table_sizes:
            if s not in SIZES:
                raise ValueError(f"Unknown size {s!r}; valid: {sorted(SIZES)}")

    def expand(self) -> list[IngestCell]:
        cells: list[IngestCell] = []
        for kind in self.kinds:
            if kind is DCKind.TABLE:
                magnitudes: list[str] = list(self.table_sizes)
            elif kind is DCKind.MULTIQC:
                magnitudes = [str(c) for c in self.multiqc_counts]
            else:  # IMAGES
                magnitudes = [str(c) for c in self.image_counts]
            for magnitude in magnitudes:
                for n_dc in self.n_dcs:
                    # Only TABLE meaningfully scales across DCs; others stay 1.
                    dcs = n_dc if kind is DCKind.TABLE else 1
                    cells.append(IngestCell(kind=kind, magnitude=magnitude, n_dcs=dcs))
        # De-dup (image/multiqc collapse n_dcs -> 1 may create repeats).
        seen: dict[str, IngestCell] = {c.slug: c for c in cells}
        return list(seen.values())


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

        ``joins`` and ``links-adversarial`` require >= 2 DCs (there must be
        something to link to); such degenerate combinations are skipped rather
        than erroring. ``links`` is a fixed three-collection topology, so its
        ``n_dcs`` is pinned to :data:`LINKED_N_DCS` and duplicate cells that
        would differ only by a ``--dcs`` value are collapsed.

        The ``visu`` list is applied whole to every cell (the component-count
        loop rotates through it), so it is not part of the product.
        """
        cells: dict[str, Cell] = {}
        for size, n_comp, n_dc, conn in itertools.product(
            self.sizes, self.n_components, self.n_dcs, self.connect
        ):
            if conn is ConnectMode.LINKS:
                n_dc = LINKED_N_DCS
            elif conn in (ConnectMode.JOINS, ConnectMode.LINKS_ADVERSARIAL) and n_dc < 2:
                continue
            cell = Cell(
                size=size,
                n_components=n_comp,
                n_dcs=n_dc,
                connect=conn,
                visu=tuple(self.visu),
            )
            cells.setdefault(cell.slug, cell)
        return list(cells.values())


# ── CLI parsing helpers ─────────────────────────────────────────────────────
def parse_sizes(raw: str) -> list[str]:
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def parse_ints(raw: str) -> list[int]:
    return [int(s.strip()) for s in raw.split(",") if s.strip()]


def parse_connect(raw: str) -> list[ConnectMode]:
    return [ConnectMode(s.strip().lower()) for s in raw.split(",") if s.strip()]


def parse_visu(raw: str) -> list[VisuType]:
    return [VisuType(s.strip().lower()) for s in raw.split(",") if s.strip()]


def parse_kinds(raw: str) -> list[DCKind]:
    return [DCKind(s.strip().lower()) for s in raw.split(",") if s.strip()]
