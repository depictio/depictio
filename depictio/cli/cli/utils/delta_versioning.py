"""Delta Lake commit metadata, history and write strategies.

Delta already creates a new version on every write, so `s3://bucket/{dc_id}`
has had a v0, v1, v2… history all along that nothing ever read. Half of dataset
versioning is therefore surfacing what exists; this module does that, and adds
the write strategies that make re-ingestion incremental.

Two consequences of never reading that history are worth stating plainly:

* Nothing has ever called ``vacuum``, so every re-ingest leaves the previous
  version's files behind. The physical footprint under a data collection's
  prefix grows without bound, and a watcher accelerates that. Hence
  :func:`vacuum_delta_table`.
* ``mode="overwrite"`` rewrites the whole table even when one run changed. That
  is what :func:`write_delta_table_versioned` with ``replace-runs`` fixes, by
  partitioning on ``depictio_run_id`` and scoping the overwrite with a
  predicate so untouched runs keep their files.

**Version compatibility.** The CLI pins deltalake 1.6 but development
environments lag to 0.24, and the two disagree on ``operationMetrics`` key
spelling (``num_added_rows`` vs ``numOutputRows``). Everything read back from
``DeltaTable.history()`` is therefore parsed defensively — see
:func:`_metric`. Custom commit metadata is *flattened* into the history entry
at the top level rather than nested, which is why :func:`_custom_metadata`
filters by prefix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import polars as pl
from deltalake import DeltaTable
from deltalake.exceptions import TableNotFoundError

from depictio.cli.cli_logging import logger
from depictio.models.models.s3 import PolarsStorageOptions

WriteMode = Literal["overwrite", "replace-runs"]

#: Prefix for depictio's own commit metadata keys, so they cannot collide with
#: anything delta-rs or another writer puts in the same namespace.
METADATA_PREFIX = "depictio."

#: The column every aggregated frame carries, identifying its source run.
RUN_ID_COLUMN = "depictio_run_id"

#: Run tags become hive path segments when partitioning. Anything outside this
#: set gets percent-encoded into an unreadable directory name, and a "/" would
#: silently nest partitions.
SAFE_RUN_TAG = re.compile(r"^[A-Za-z0-9._-]+$")

#: Commit metadata is inlined into every _delta_log entry, forever. A project
#: with thousands of runs would otherwise write hundreds of KB of run tags into
#: each commit — and a watcher commits far more often than a human does.
MAX_RUN_TAGS_IN_METADATA = 50
MAX_METADATA_BYTES = 16 * 1024

#: Above this, hive partitioning produces more small files than it saves work.
MAX_PARTITIONS = 5000


@dataclass
class DeltaCommitInfo:
    """One entry of a Delta table's commit history."""

    version: int
    timestamp: datetime | None = None
    operation: str | None = None
    rows_added: int | None = None
    files_added: int | None = None
    files_removed: int | None = None
    custom_metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class DeltaWriteResult:
    """Outcome of a versioned write."""

    result: Literal["success", "error"]
    message: str
    write_mode: str
    rows_written: int = 0
    delta_version: int | None = None
    delta_timestamp: datetime | None = None
    partitioned: bool = False


def _metric(metrics: dict[str, Any], *names: str) -> int | None:
    """Read a metric under any of its known spellings.

    deltalake 0.24 emits snake_case (``num_added_rows``) and 1.x emits
    camelCase (``numOutputRows``); some versions also stringify the values.
    """
    for name in names:
        if name in metrics:
            value = metrics[name]
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _custom_metadata(entry: dict[str, Any]) -> dict[str, str]:
    """Depictio's own keys from a history entry.

    delta-rs flattens custom commit metadata into the entry rather than nesting
    it, so the keys sit alongside ``operation`` and ``timestamp``.
    """
    return {key: str(value) for key, value in entry.items() if key.startswith(METADATA_PREFIX)}


def _parse_commit(entry: dict[str, Any]) -> DeltaCommitInfo:
    raw_timestamp = entry.get("timestamp")
    timestamp = None
    if isinstance(raw_timestamp, (int, float)):
        # Epoch milliseconds, not seconds.
        timestamp = datetime.fromtimestamp(raw_timestamp / 1000)

    metrics = entry.get("operationMetrics") or {}
    return DeltaCommitInfo(
        version=int(entry.get("version", -1)),
        timestamp=timestamp,
        operation=entry.get("operation"),
        rows_added=_metric(metrics, "num_added_rows", "numOutputRows"),
        files_added=_metric(metrics, "num_added_files", "numAddedFiles", "numFiles"),
        files_removed=_metric(metrics, "num_removed_files", "numRemovedFiles"),
        custom_metadata=_custom_metadata(entry),
    )


def build_commit_metadata(
    *,
    data_collection_id: str,
    data_collection_tag: str,
    write_mode: str,
    run_tags: list[str] | None = None,
    file_count: int | None = None,
    row_count: int | None = None,
    ingestion_run_id: str | None = None,
    project_id: str | None = None,
    trigger: str | None = None,
    cli_version: str | None = None,
    user_email: str | None = None,
) -> dict[str, str]:
    """Assemble depictio's commit metadata, truncated to a sane size.

    Every value is coerced to ``str`` because delta-rs requires
    ``dict[str, str]``, and the run-tag list is capped: this blob is inlined
    into each ``_delta_log`` entry permanently.
    """
    metadata: dict[str, str] = {
        f"{METADATA_PREFIX}data_collection_id": str(data_collection_id),
        f"{METADATA_PREFIX}data_collection_tag": str(data_collection_tag),
        f"{METADATA_PREFIX}write_mode": str(write_mode),
    }

    optional = {
        "ingestion_run_id": ingestion_run_id,
        "project_id": project_id,
        "trigger": trigger,
        "cli_version": cli_version,
        "user_email": user_email,
        "file_count": file_count,
        "row_count": row_count,
    }
    for key, value in optional.items():
        if value is not None:
            metadata[f"{METADATA_PREFIX}{key}"] = str(value)

    if run_tags:
        metadata[f"{METADATA_PREFIX}run_count"] = str(len(run_tags))
        shown = sorted(run_tags)[:MAX_RUN_TAGS_IN_METADATA]
        joined = ",".join(shown)
        if len(run_tags) > MAX_RUN_TAGS_IN_METADATA:
            joined += f",+{len(run_tags) - MAX_RUN_TAGS_IN_METADATA} more"
        metadata[f"{METADATA_PREFIX}run_tags"] = joined

    # Hard cap regardless of how the pieces added up.
    total = sum(len(k) + len(v) for k, v in metadata.items())
    if total > MAX_METADATA_BYTES:
        metadata.pop(f"{METADATA_PREFIX}run_tags", None)
        logger.warning(
            f"Commit metadata exceeded {MAX_METADATA_BYTES} bytes; dropped the run-tag list."
        )
    return metadata


@dataclass
class DeltaTableProbe:
    """Everything knowable about an existing table without reading a row.

    All of it comes from the ``_delta_log``. This exists because the question
    "does this table already exist?" used to be answered with a full eager
    ``pl.read_delta`` whose result was logged and discarded — on a watched
    project, re-downloading the entire table every cycle to branch on a boolean.
    """

    version: int
    partition_columns: list[str]
    #: Column name -> polars dtype. ``None`` when the schema could not be read,
    #: which callers must treat as "unknown" rather than "empty".
    schema: dict[str, pl.DataType] | None
    #: Sum of the sizes of the files the current version references. Lets a
    #: partial write report the table's real size instead of the subset's.
    size_bytes: int | None

    @property
    def partitioned_by_run(self) -> bool:
        return self.partition_columns == [RUN_ID_COLUMN]


def probe_delta_table(
    destination: str, storage_options: PolarsStorageOptions, *, with_schema: bool = False
) -> DeltaTableProbe | None:
    """Metadata-only view of an existing table, or None when there is none.

    ``with_schema`` is opt-in because it is the one part that goes through
    polars rather than the delta-rs metadata API, and only scoped writes need
    it. A schema that cannot be read comes back as ``None`` rather than raising:
    the caller's correct response is to fall back to a full rebuild, not to
    fail the ingestion.

    One behaviour change worth stating: a table that exists but is *unreadable*
    used to look absent (the full read failed, so the caller carried on and
    overwrote it). It now reports as existing, so a ``process`` without
    ``--overwrite`` refuses rather than silently replacing a broken table.
    """
    options = storage_options.model_dump()
    try:
        table = DeltaTable(destination, storage_options=options)
        metadata = table.metadata()
    except TableNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001 - never let a probe abort a write
        logger.debug(f"Could not probe {destination}: {exc}")
        return None

    schema: dict[str, pl.DataType] | None = None
    if with_schema:
        try:
            schema = dict(pl.scan_delta(destination, storage_options=options).collect_schema())
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not read the schema of {destination}: {exc}")

    size_bytes: int | None = None
    try:
        actions = table.get_add_actions(flatten=True)
        size_bytes = int(sum(actions["size_bytes"].to_pylist()))
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Could not size {destination} from its add actions: {exc}")

    return DeltaTableProbe(
        version=table.version(),
        partition_columns=list(metadata.partition_columns),
        schema=schema,
        size_bytes=size_bytes,
    )


def plan_partitioning(
    frame: pl.DataFrame,
    destination: str,
    storage_options: PolarsStorageOptions,
    write_mode: WriteMode,
    repartition: bool = False,
    probe: DeltaTableProbe | None = None,
) -> tuple[bool, str | None]:
    """Decide whether to partition by run, and why not when we cannot.

    Returns ``(partition, reason_to_fall_back)``. The fall-back cases are all
    ones where partitioning would either fail outright or make things worse:

    * the frame has no run column (recipes, joins, single-file collections);
    * only one distinct run, so partitioning buys nothing;
    * a run tag that is not filesystem-safe, which would become an unreadable
      percent-encoded hive segment;
    * too many runs, where hive partitioning trades one big file for thousands
      of small ones;
    * an existing table with different partitioning — delta-rs rejects a
      partition-column change outright, so adopting one means rewriting every
      row. ``repartition=True`` is the caller saying they accept that cost;
      without it we fall back rather than silently rewrite the whole table.

    This is the *full-frame* planner: falling back to a full overwrite is safe
    here precisely because ``frame`` holds every row the table should end up
    with. A frame restricted to the runs that changed must go through
    :func:`plan_scoped_write` instead, where a fall-back means "rebuild
    everything", never "overwrite the table with a subset".
    """
    if write_mode != "replace-runs":
        return False, None

    if RUN_ID_COLUMN not in frame.columns:
        return False, f"no {RUN_ID_COLUMN} column (recipe, join or single-file collection)"

    run_tags = [str(tag) for tag in frame[RUN_ID_COLUMN].unique().to_list() if tag is not None]
    if len(run_tags) <= 1:
        return False, "only one run in this data collection"

    unsafe = [tag for tag in run_tags if not SAFE_RUN_TAG.match(tag)]
    if unsafe:
        return False, f"run tags are not path-safe (e.g. {unsafe[0]!r})"

    if len(run_tags) > MAX_PARTITIONS:
        return False, f"{len(run_tags)} runs exceeds the {MAX_PARTITIONS}-partition guard"

    if probe is None:
        probe = probe_delta_table(destination, storage_options)
    existing = probe.partition_columns if probe else None
    if existing is not None and existing != [RUN_ID_COLUMN] and not repartition:
        return False, (
            f"existing table is partitioned by {existing or 'nothing'}; "
            "adopting run partitioning rewrites every row — pass --repartition "
            "to allow it"
        )

    return True, None


@dataclass
class ScopedWritePlan:
    """Whether this write may cover only the runs that changed."""

    scoped: bool
    run_tags: list[str] = field(default_factory=list)
    #: Why a scoped write was refused. Never an error — it means "rebuild the
    #: whole table instead", which is always correct, only slower.
    declined: str | None = None


def plan_scoped_write(
    *,
    probe: DeltaTableProbe | None,
    changed_runs: list[str],
    removed_runs: list[str],
    write_mode: str,
    incremental_write: bool,
    signal_complete: bool,
    covered: bool,
) -> ScopedWritePlan:
    """Decide whether to rewrite only the runs that changed.

    Called *before* any file is fetched, and that ordering is the safety
    property. A frame restricted to a subset of runs must never reach the
    full-frame write path, where a declined partitioning falls back to
    ``mode="overwrite"`` — with a subset in hand that overwrite would delete
    every run not in it. Deciding first means a partial frame is only ever built
    once a partitioned, predicate-scoped write is guaranteed.

    Every refusal here means "rebuild the whole table", never "write less".

    Note what is deliberately *not* checked: the single-run case.
    :func:`plan_partitioning` declines it because partitioning a one-run table
    buys nothing, but one changed run out of forty is the nominal case for this
    function — and the one where scoping pays most.
    """
    if not incremental_write:
        return ScopedWritePlan(scoped=False)
    if write_mode != "replace-runs":
        return ScopedWritePlan(scoped=False, declined="--incremental-write needs replace-runs")
    if not signal_complete:
        return ScopedWritePlan(
            scoped=False, declined="the scan could not vouch for every run on disk"
        )
    if not covered:
        return ScopedWritePlan(
            scoped=False, declined="this collection was not covered by a run-based scan"
        )
    if removed_runs:
        return ScopedWritePlan(
            scoped=False,
            declined=(
                f"{len(removed_runs)} run(s) disappeared — a scoped write cannot express "
                "a removal, so the table is rebuilt"
            ),
        )
    if not changed_runs:
        return ScopedWritePlan(scoped=False, declined="no run changed")
    if probe is None:
        return ScopedWritePlan(scoped=False, declined="there is no table to write into yet")
    if not probe.partitioned_by_run:
        return ScopedWritePlan(
            scoped=False,
            declined=(
                f"the table is partitioned by {probe.partition_columns or 'nothing'}; "
                "adopting run partitioning rewrites every row (--repartition)"
            ),
        )
    if probe.schema is None:
        return ScopedWritePlan(
            scoped=False, declined="the table's schema could not be read to align against"
        )

    unsafe = [tag for tag in changed_runs if not SAFE_RUN_TAG.match(tag)]
    if unsafe:
        return ScopedWritePlan(scoped=False, declined=f"run tag {unsafe[0]!r} is not path-safe")
    if len(changed_runs) > MAX_PARTITIONS:
        return ScopedWritePlan(
            scoped=False,
            declined=f"{len(changed_runs)} runs exceeds the {MAX_PARTITIONS}-partition guard",
        )

    return ScopedWritePlan(scoped=True, run_tags=sorted(set(changed_runs)))


def write_delta_table_versioned(
    aggregated_df: pl.DataFrame,
    destination_file: str,
    storage_options: PolarsStorageOptions,
    *,
    write_mode: WriteMode = "overwrite",
    commit_metadata: dict[str, str] | None = None,
    partition: bool = False,
    replace_run_tags: list[str] | None = None,
    scoped: bool = False,
) -> DeltaWriteResult:
    """Write the aggregated frame, recording what the commit was.

    ``overwrite`` reproduces the historical behaviour exactly. ``replace-runs``
    scopes the overwrite to the runs present in ``aggregated_df`` so untouched
    runs keep their existing files — one atomic commit, and duplicates are
    structurally impossible.

    There is deliberately no append mode. A run's frame is rebuilt by re-parsing
    every file registered for it, so it always holds *all* of that run's rows,
    never just the new ones: appending it would duplicate a run whose file was
    edited, and could not remove the rows of a file that has since disappeared.
    Replacing the run's partition expresses "upsert this run" exactly, and for a
    run that is genuinely new the predicate matches nothing to remove, so it
    costs no more than an append would.

    ``scoped`` says ``aggregated_df`` holds only *some* of the table's runs. It
    changes two things, both required for correctness rather than performance:

    * the write must be partitioned and predicated, so an unpartitioned
      subset write is refused outright rather than silently overwriting the
      table with a fraction of its rows;
    * ``schema_mode`` becomes ``"merge"``. Measured against deltalake 0.24 and
      1.6.1: a subset written with ``schema_mode="overwrite"`` and one column
      missing drops that column for *every* run on 1.6.1 and leaves the table
      unreadable on 0.24. ``merge`` keeps the column, and turns a genuine type
      conflict into a loud failure instead of a corrupt table.
    """
    if scoped and not partition:
        # Invariant, deliberately an exception rather than a fall-back: with a
        # subset frame, "overwrite the whole table" is data loss.
        raise ValueError(
            "a scoped write must be partitioned and predicate-scoped; "
            "refusing to overwrite the whole table with a subset of its runs"
        )
    if replace_run_tags and not partition:
        raise ValueError("replace_run_tags is meaningless without partitioning")

    # Replacing the schema is only correct when the frame *is* the table; a
    # subset has to merge into the schema it finds. See the docstring.
    delta_write_options: dict[str, Any] = {"schema_mode": "merge" if scoped else "overwrite"}
    if commit_metadata:
        # Imported here so a deltalake without CommitProperties degrades to a
        # metadata-less write rather than failing at import time.
        try:
            from deltalake import CommitProperties

            delta_write_options["commit_properties"] = CommitProperties(
                custom_metadata=commit_metadata
            )
        except ImportError:
            logger.warning("deltalake has no CommitProperties; writing without commit metadata.")

    if partition:
        delta_write_options["partition_by"] = [RUN_ID_COLUMN]
        if write_mode == "replace-runs" and replace_run_tags:
            quoted = ", ".join(
                "'" + tag.replace("'", "''") + "'" for tag in sorted(replace_run_tags)
            )
            delta_write_options["predicate"] = f"{RUN_ID_COLUMN} IN ({quoted})"

    logger.debug(
        f"Writing Delta table to {destination_file} "
        f"(write_mode={write_mode}, partition={partition}, scoped={scoped})"
    )
    aggregated_df.write_delta(
        destination_file,
        storage_options=storage_options.model_dump(),
        delta_write_options=delta_write_options,
        mode="overwrite",
    )

    commit = read_delta_commit_info(destination_file, storage_options)
    logger.info(
        f"Delta table written to {destination_file} "
        f"(version {commit.version if commit else '?'}, mode {write_mode})"
    )
    return DeltaWriteResult(
        result="success",
        message=f"Aggregated Delta table written to {destination_file}.",
        write_mode=write_mode,
        rows_written=aggregated_df.height,
        delta_version=commit.version if commit else None,
        delta_timestamp=commit.timestamp if commit else None,
        partitioned=partition,
    )


def read_delta_commit_info(
    destination_file: str, storage_options: PolarsStorageOptions, version: int | None = None
) -> DeltaCommitInfo | None:
    """The most recent commit (or a specific version), or None if unreadable.

    Returns None rather than raising: commit info is metadata *about* a write
    that already succeeded, so failing to read it must not turn a good write
    into a reported failure.
    """
    try:
        table = DeltaTable(destination_file, storage_options=storage_options.model_dump())
        if version is not None:
            entries = [entry for entry in table.history(50) if entry.get("version") == version]
            return _parse_commit(entries[0]) if entries else None
        history = table.history(1)
        return _parse_commit(history[0]) if history else None
    except TableNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not read commit info for {destination_file}: {exc}")
        return None


def list_delta_versions(
    destination_file: str, storage_options: PolarsStorageOptions, limit: int = 20
) -> list[DeltaCommitInfo]:
    """Commit history, newest first. Empty when the table does not exist."""
    try:
        table = DeltaTable(destination_file, storage_options=storage_options.model_dump())
        return [_parse_commit(entry) for entry in table.history(limit)]
    except TableNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not read history for {destination_file}: {exc}")
        return []


def vacuum_delta_table(
    destination_file: str,
    storage_options: PolarsStorageOptions,
    *,
    retention_hours: int = 168,
    dry_run: bool = True,
) -> list[str]:
    """Remove files no longer referenced by any retained version.

    Dry-run by default, and never wired into an ingestion path. Vacuuming below
    the 168 h default breaks concurrent readers — an API worker part-way through
    a ``scan_delta`` loses the files under it — which is exactly what
    ``enforce_retention_duration`` exists to prevent.
    """
    table = DeltaTable(destination_file, storage_options=storage_options.model_dump())
    return table.vacuum(
        retention_hours=retention_hours,
        dry_run=dry_run,
        enforce_retention_duration=True,
    )
