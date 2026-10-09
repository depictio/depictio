"""The penguins_versioned story in one place: ids, batches, labels, expectations.

Every other script in this directory reads from here. The fixture is only useful
while four things agree with each other (the batch files, the dashboard YAMLs,
the order they are applied in, and what the verifier expects), so they are
described once rather than restated in each script.

Two datasets that move independently, and their persisted join, which moves
whenever either of them does:

    batch  physical_features    demographic_data     penguins_complete    dashboard version
    1      delta 0  109 rows    delta 0  109 rows    delta 0  109 rows    v1 First season
    2      delta 1  223 rows    delta 1  223 rows    delta 1  223 rows    v2 Second season
    3      delta 2  223 rows *  (not ingested)       delta 2  223 rows *  v3 Scale recalibrated
    4      delta 3  342 rows    delta 2  342 rows    delta 3  342 rows    v4 Three seasons
    5      (not ingested)       delta 3  342 rows *  delta 4  342 rows *  v5 Sex records completed

    * same row count as the step before, different values.

The dashboard reads the join from v2 on, so v1 stamps two collections and every
later version three.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
BATCHES_DIR = HERE / "batches"
DASHBOARDS_DIR = HERE / "dashboards"
DEFAULT_DATA_ROOT = HERE / "data"
PROJECT_YAML = HERE / "project.yaml"

# Fixed ids, chosen fresh for this fixture (no other file in the repository uses
# the 56284517418915ace150 prefix). Dashboards have none: the import endpoint
# always mints a new dashboard id, so the rebuild finds the dashboard by
# SOURCE_KEY instead.
PROJECT_ID = "56284517418915ace150a001"
WORKFLOW_ID = "56284517418915ace150a002"
PF_ID = "56284517418915ace150a003"
DD_ID = "56284517418915ace150a004"
JOIN_ID = "56284517418915ace150a005"

PROJECT_NAME = "Penguins Versioned Demo"
WORKFLOW_NAME = "penguins_versioned_workflow"
PF = "physical_features"
DD = "demographic_data"
JOIN_NAME = "penguins_complete"
#: The tag `persist_joined_table` gives the joined collection ("joined_<name>").
JOIN = f"joined_{JOIN_NAME}"
#: What the join reads. It is rebuilt at every ingest, so it gets a new commit
#: at every step that moves either of these, and none at a step that moves
#: neither (the rows come out the same, and nothing is written).
JOIN_INPUTS = (PF, DD)
DC_IDS = {PF: PF_ID, DD: DD_ID, JOIN: JOIN_ID}

#: Stored on the main dashboard by the import, so every later import of the
#: next version replaces the same dashboard even after its title changes.
#: Child tabs are keyed "<SOURCE_KEY>#<tab title>", which is why tab titles
#: never change between versions.
SOURCE_KEY = "penguins_versioned:dashboard"

SEASONS = (2007, 2008, 2009)

#: Batch 3: every 2007 body mass is scaled by this factor, plus a seeded jitter.
#: Synthetic. The real palmerpenguins data has no such correction.
RECALIBRATION_FACTOR = 1.05
RECALIBRATION_JITTER_G = 20.0
SEED = 20261009


@dataclass(frozen=True)
class Step:
    """One batch, ingested, then one dashboard version saved against it."""

    n: int
    batch: str
    #: The collections this batch writes. A collection left out keeps its
    #: previous Delta commit, which is what makes the two pins diverge.
    ingest: tuple[str, ...]
    #: The collections this dashboard version reads, so the ones it stamps.
    reads: tuple[str, ...]
    dashboard: str
    label: str
    summary: str
    #: Rows each collection holds once this batch is in.
    rows: dict[str, int] = field(default_factory=dict)
    #: The Delta version each collection is at once this batch is in, which is
    #: what the dashboard version saved right after it must stamp.
    stamps: dict[str, int] = field(default_factory=dict)
    tabs: int = 1
    components: int = 0
    pinned: bool = False

    @property
    def moves(self) -> tuple[str, ...]:
        """Every collection that gets a new Delta commit at this step: the ones
        it ingests, plus the join whenever one of its inputs is among them."""
        joined = (JOIN,) if set(self.ingest) & set(JOIN_INPUTS) else ()
        return (*self.ingest, *joined)


STEPS: tuple[Step, ...] = (
    Step(
        n=1,
        batch="batch_01_season_2007",
        ingest=(PF, DD),
        reads=(PF, DD),
        dashboard="v1_first_season.yaml",
        label="v1 First season",
        summary="2007 only: 109 birds",
        rows={PF: 109, DD: 109, JOIN: 109},
        stamps={PF: 0, DD: 0, JOIN: 0},
        tabs=1,
        components=6,
    ),
    Step(
        n=2,
        batch="batch_02_season_2008",
        ingest=(PF, DD),
        reads=(PF, DD, JOIN),
        dashboard="v2_second_season.yaml",
        label="v2 Second season",
        summary="+ 2008: 223 birds",
        rows={PF: 223, DD: 223, JOIN: 223},
        stamps={PF: 1, DD: 1, JOIN: 1},
        tabs=2,
        components=15,
    ),
    Step(
        n=3,
        batch="batch_03_scale_recalibrated",
        ingest=(PF,),
        reads=(PF, DD, JOIN),
        dashboard="v3_scale_recalibrated.yaml",
        label="v3 Scale recalibrated",
        summary="2007 body masses corrected (synthetic), physical_features only",
        rows={PF: 223, DD: 223, JOIN: 223},
        stamps={PF: 2, DD: 1, JOIN: 2},
        tabs=2,
        components=16,
        pinned=True,
    ),
    Step(
        n=4,
        batch="batch_04_season_2009",
        ingest=(PF, DD),
        reads=(PF, DD, JOIN),
        dashboard="v4_three_seasons.yaml",
        label="v4 Three seasons",
        summary="+ 2009: 342 birds, the complete survey",
        rows={PF: 342, DD: 342, JOIN: 342},
        stamps={PF: 3, DD: 2, JOIN: 3},
        tabs=2,
        components=19,
    ),
    Step(
        n=5,
        batch="batch_05_sex_completed",
        ingest=(DD,),
        reads=(PF, DD, JOIN),
        dashboard="v5_sex_completed.yaml",
        label="v5 Sex records completed",
        summary="9 missing sex values filled (synthetic), demographic_data only",
        rows={PF: 342, DD: 342, JOIN: 342},
        stamps={PF: 3, DD: 3, JOIN: 4},
        tabs=3,
        components=22,
    ),
)


def commit_rows(dc_tag: str, upto: int = len(STEPS)) -> list[int]:
    """Row count of each Delta commit of one collection, oldest first.

    One commit per step that moves the collection, so the list is shorter
    than the steps whenever the collection sat a step out.
    """
    return [step.rows[dc_tag] for step in STEPS[:upto] if dc_tag in step.moves]


def step(n: int) -> Step:
    return STEPS[n - 1]
