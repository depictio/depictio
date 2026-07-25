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

WriteMode = Literal["overwrite", "append", "replace-runs"]

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


def _existing_partition_columns(
    destination: str, storage_options: PolarsStorageOptions
) -> list[str] | None:
    """Partition columns of an existing table, or None when there is no table."""
    try:
        return list(
            DeltaTable(destination, storage_options=storage_options.model_dump())
            .metadata()
            .partition_columns
        )
    except TableNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001 - never let a probe abort a write
        logger.debug(f"Could not read partition columns for {destination}: {exc}")
        return None


def plan_partitioning(
    frame: pl.DataFrame,
    destination: str,
    storage_options: PolarsStorageOptions,
    write_mode: WriteMode,
    repartition: bool = False,
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

    existing = _existing_partition_columns(destination, storage_options)
    if existing is not None and existing != [RUN_ID_COLUMN] and not repartition:
        return False, (
            f"existing table is partitioned by {existing or 'nothing'}; "
            "adopting run partitioning rewrites every row — pass --repartition "
            "to allow it"
        )

    return True, None


def write_delta_table_versioned(
    aggregated_df: pl.DataFrame,
    destination_file: str,
    storage_options: PolarsStorageOptions,
    *,
    write_mode: WriteMode = "overwrite",
    commit_metadata: dict[str, str] | None = None,
    partition: bool = False,
    replace_run_tags: list[str] | None = None,
) -> DeltaWriteResult:
    """Write the aggregated frame, recording what the commit was.

    ``overwrite`` reproduces the historical behaviour exactly. ``replace-runs``
    scopes the overwrite to the runs present in ``aggregated_df`` so untouched
    runs keep their existing files — one atomic commit, and duplicates are
    structurally impossible. ``append`` is only meaningful alongside change
    detection and is guarded by the caller against re-appending a known run.
    """
    mode = "append" if write_mode == "append" else "overwrite"

    # delta-rs rejects schema_mode="overwrite" on an append — replacing the
    # schema is only meaningful when replacing the data. "merge" is the append
    # equivalent: it lets a new column appear without rewriting the table.
    delta_write_options: dict[str, Any] = {
        "schema_mode": "merge" if mode == "append" else "overwrite"
    }
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

    logger.debug(f"Writing Delta table to {destination_file} (mode={mode}, partition={partition})")
    aggregated_df.write_delta(
        destination_file,
        storage_options=storage_options.model_dump(),
        delta_write_options=delta_write_options,
        mode=mode,
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
