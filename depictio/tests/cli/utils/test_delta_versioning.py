"""Tests for Delta commit metadata, history parsing and write strategies.

deltalake writes to local file:// paths, so these run against a real table in
tmp_path with no MinIO. That matters: the parts most likely to break are the
ones that read delta-rs's own output back, and those cannot be mocked
usefully — the history entry shape differs between deltalake versions, which is
exactly the bug class these tests exist to catch.
"""

import polars as pl
import pytest

from depictio.cli.cli.utils.delta_versioning import (
    MAX_RUN_TAGS_IN_METADATA,
    METADATA_PREFIX,
    RUN_ID_COLUMN,
    DeltaCommitInfo,
    _metric,
    _parse_commit,
    build_commit_metadata,
    list_delta_versions,
    plan_partitioning,
    plan_scoped_write,
    probe_delta_table,
    read_delta_commit_info,
    write_delta_table_versioned,
)
from depictio.models.models.s3 import PolarsStorageOptions


@pytest.fixture
def storage() -> PolarsStorageOptions:
    # Local paths need no credentials, but the model requires them.
    return PolarsStorageOptions(
        endpoint_url="http://localhost:9000",
        aws_access_key_id="key",
        aws_secret_access_key="secret",
    )


@pytest.fixture
def destination(tmp_path) -> str:
    return str(tmp_path / "table")


def frame(run_ids: list[str], values: list[int] | None = None) -> pl.DataFrame:
    return pl.DataFrame(
        {RUN_ID_COLUMN: run_ids, "v": values if values is not None else list(range(len(run_ids)))}
    )


def rows(destination: str) -> list[tuple[str, int]]:
    table = pl.read_delta(destination)
    return sorted(zip(table[RUN_ID_COLUMN].to_list(), table["v"].to_list()))


class TestCommitMetadata:
    def test_required_keys_are_prefixed(self):
        metadata = build_commit_metadata(
            data_collection_id="dc1", data_collection_tag="tag", write_mode="overwrite"
        )
        assert all(key.startswith(METADATA_PREFIX) for key in metadata)
        assert metadata[f"{METADATA_PREFIX}write_mode"] == "overwrite"

    def test_every_value_is_a_string(self):
        # delta-rs requires dict[str, str]; an int would be rejected at write time.
        metadata = build_commit_metadata(
            data_collection_id="dc1",
            data_collection_tag="tag",
            write_mode="overwrite",
            file_count=12,
            row_count=3400,
        )
        assert all(isinstance(value, str) for value in metadata.values())
        assert metadata[f"{METADATA_PREFIX}file_count"] == "12"

    def test_optional_fields_are_omitted_when_absent(self):
        metadata = build_commit_metadata(
            data_collection_id="dc1", data_collection_tag="tag", write_mode="overwrite"
        )
        assert f"{METADATA_PREFIX}trigger" not in metadata
        assert f"{METADATA_PREFIX}run_tags" not in metadata

    def test_trigger_is_recorded(self):
        metadata = build_commit_metadata(
            data_collection_id="dc1",
            data_collection_tag="tag",
            write_mode="replace-runs",
            trigger="watch",
        )
        assert metadata[f"{METADATA_PREFIX}trigger"] == "watch"

    def test_run_tags_are_capped(self):
        tags = [f"run-{index:04d}" for index in range(500)]
        metadata = build_commit_metadata(
            data_collection_id="dc1",
            data_collection_tag="tag",
            write_mode="overwrite",
            run_tags=tags,
        )
        # The full count survives even though the list is truncated: this blob
        # is inlined into every _delta_log entry permanently.
        assert metadata[f"{METADATA_PREFIX}run_count"] == "500"
        joined = metadata[f"{METADATA_PREFIX}run_tags"]
        assert joined.count(",") <= MAX_RUN_TAGS_IN_METADATA
        assert "more" in joined

    def test_oversized_metadata_drops_the_tag_list(self):
        tags = [f"run-{'x' * 400}-{index}" for index in range(MAX_RUN_TAGS_IN_METADATA)]
        metadata = build_commit_metadata(
            data_collection_id="dc1",
            data_collection_tag="tag",
            write_mode="overwrite",
            run_tags=tags,
        )
        assert f"{METADATA_PREFIX}run_tags" not in metadata
        assert f"{METADATA_PREFIX}run_count" in metadata


class TestHistoryParsing:
    @pytest.mark.parametrize(
        "metrics,expected",
        [
            ({"num_added_rows": 5}, 5),
            ({"numOutputRows": 5}, 5),
            ({"numOutputRows": "5"}, 5),
            ({}, None),
            ({"num_added_rows": None}, None),
        ],
    )
    def test_metric_reads_both_spellings(self, metrics, expected):
        # deltalake 0.24 emits snake_case, 1.x emits camelCase. The CLI pins 1.6
        # but dev environments lag, so both have to parse.
        assert _metric(metrics, "num_added_rows", "numOutputRows") == expected

    def test_timestamp_is_parsed_from_epoch_milliseconds(self):
        commit = _parse_commit({"version": 3, "timestamp": 1784966848661})
        assert commit.timestamp is not None
        assert commit.timestamp.year == 2026

    def test_custom_metadata_is_read_from_the_flattened_entry(self):
        # delta-rs flattens custom metadata into the history entry rather than
        # nesting it under a key.
        commit = _parse_commit(
            {
                "version": 1,
                "operation": "WRITE",
                f"{METADATA_PREFIX}trigger": "watch",
                "clientVersion": "delta-rs.0.24",
            }
        )
        assert commit.custom_metadata == {f"{METADATA_PREFIX}trigger": "watch"}

    def test_missing_metrics_do_not_raise(self):
        commit = _parse_commit({"version": 0})
        assert commit.rows_added is None
        assert commit.files_added is None


class TestVersionedWrite:
    def test_overwrite_creates_a_version(self, destination, storage):
        result = write_delta_table_versioned(frame(["A", "B"]), destination, storage)
        assert result.result == "success"
        assert result.delta_version == 0
        assert result.rows_written == 2

    def test_versions_increment(self, destination, storage):
        write_delta_table_versioned(frame(["A"]), destination, storage)
        second = write_delta_table_versioned(frame(["A", "B"]), destination, storage)
        assert second.delta_version == 1

    def test_commit_metadata_round_trips(self, destination, storage):
        metadata = build_commit_metadata(
            data_collection_id="dc1",
            data_collection_tag="tag",
            write_mode="overwrite",
            trigger="watch",
        )
        write_delta_table_versioned(frame(["A"]), destination, storage, commit_metadata=metadata)

        commit = read_delta_commit_info(destination, storage)
        assert commit is not None
        assert commit.custom_metadata[f"{METADATA_PREFIX}trigger"] == "watch"
        assert commit.timestamp is not None

    def test_history_is_newest_first(self, destination, storage):
        write_delta_table_versioned(frame(["A"]), destination, storage)
        write_delta_table_versioned(frame(["A", "B"]), destination, storage)

        history = list_delta_versions(destination, storage)
        assert [entry.version for entry in history] == [1, 0]

    def test_missing_table_reads_as_absent_not_error(self, tmp_path, storage):
        absent = str(tmp_path / "never-written")
        assert read_delta_commit_info(absent, storage) is None
        assert list_delta_versions(absent, storage) == []


class TestReplaceRuns:
    def test_replaces_only_the_named_runs(self, destination, storage):
        write_delta_table_versioned(
            frame(["A", "A", "B", "C"], [1, 2, 3, 4]),
            destination,
            storage,
            write_mode="replace-runs",
            partition=True,
        )
        write_delta_table_versioned(
            frame(["A", "A", "A"], [10, 20, 30]),
            destination,
            storage,
            write_mode="replace-runs",
            partition=True,
            replace_run_tags=["A"],
        )
        # B and C keep their original rows; A is fully replaced, not appended to.
        assert rows(destination) == [("A", 10), ("A", 20), ("A", 30), ("B", 3), ("C", 4)]

    def test_re_ingesting_a_run_does_not_duplicate(self, destination, storage):
        write_delta_table_versioned(
            frame(["A", "B"], [1, 2]),
            destination,
            storage,
            write_mode="replace-runs",
            partition=True,
        )
        for _ in range(3):
            write_delta_table_versioned(
                frame(["A"], [1]),
                destination,
                storage,
                write_mode="replace-runs",
                partition=True,
                replace_run_tags=["A"],
            )
        assert rows(destination) == [("A", 1), ("B", 2)]

    def test_run_tags_with_quotes_are_escaped(self, destination, storage):
        # A tag containing a quote would otherwise break out of the predicate.
        write_delta_table_versioned(
            frame(["o'brien", "B"], [1, 2]), destination, storage, partition=True
        )
        write_delta_table_versioned(
            frame(["o'brien"], [9]),
            destination,
            storage,
            write_mode="replace-runs",
            partition=True,
            replace_run_tags=["o'brien"],
        )
        assert rows(destination) == [("B", 2), ("o'brien", 9)]

    def test_a_full_frame_replaces_rather_than_accumulates(self, destination, storage):
        # There is no append mode: a run's frame always holds every row of that
        # run, so adding it to what is already there would duplicate it.
        write_delta_table_versioned(frame(["A"], [1]), destination, storage)
        write_delta_table_versioned(frame(["B"], [2]), destination, storage)
        assert rows(destination) == [("B", 2)]


class TestPartitionPlanning:
    def test_not_planned_outside_replace_runs(self, destination, storage):
        partition, reason = plan_partitioning(frame(["A", "B"]), destination, storage, "overwrite")
        assert partition is False
        assert reason is None

    def test_planned_for_multiple_safe_runs(self, destination, storage):
        partition, reason = plan_partitioning(
            frame(["run-1", "run-2"]), destination, storage, "replace-runs"
        )
        assert partition is True
        assert reason is None

    def test_declined_without_a_run_column(self, destination, storage):
        # Recipes, joins and single-file collections have no run dimension.
        partition, reason = plan_partitioning(
            pl.DataFrame({"v": [1]}), destination, storage, "replace-runs"
        )
        assert partition is False
        assert reason is not None and RUN_ID_COLUMN in reason

    def test_declined_for_a_single_run(self, destination, storage):
        partition, reason = plan_partitioning(frame(["only"]), destination, storage, "replace-runs")
        assert partition is False
        assert reason is not None and "one run" in reason

    @pytest.mark.parametrize("tag", ["has/slash", "has space", "has=equals", "héllo"])
    def test_declined_for_unsafe_run_tags(self, destination, storage, tag):
        # These become percent-encoded hive segments; a slash would nest them.
        partition, reason = plan_partitioning(
            frame([tag, "safe"]), destination, storage, "replace-runs"
        )
        assert partition is False
        assert reason is not None and "path-safe" in reason

    def test_declined_above_the_partition_guard(self, destination, storage):
        partition, reason = plan_partitioning(
            frame([f"r{index}" for index in range(5001)]), destination, storage, "replace-runs"
        )
        assert partition is False
        assert reason is not None and "partition guard" in reason

    def test_declined_when_existing_table_is_unpartitioned(self, destination, storage):
        # delta-rs rejects a partition-column change outright, so this must be
        # detected before the write rather than surfacing as a DeltaError.
        write_delta_table_versioned(frame(["A", "B"]), destination, storage)
        partition, reason = plan_partitioning(
            frame(["A", "B"]), destination, storage, "replace-runs"
        )
        assert partition is False
        assert reason is not None and "repartition" in reason

    def test_allowed_when_existing_table_matches(self, destination, storage):
        write_delta_table_versioned(
            frame(["A", "B"]), destination, storage, write_mode="replace-runs", partition=True
        )
        partition, reason = plan_partitioning(
            frame(["A", "B"]), destination, storage, "replace-runs"
        )
        assert partition is True
        assert reason is None

    def test_repartition_opts_in_to_the_full_rewrite(self, destination, storage):
        # Adopting run partitioning on an existing unpartitioned table rewrites
        # every row. That is allowed, but only when explicitly asked for — the
        # watcher never passes this.
        write_delta_table_versioned(frame(["A", "B"]), destination, storage)
        partition, reason = plan_partitioning(
            frame(["A", "B"]), destination, storage, "replace-runs", repartition=True
        )
        assert partition is True
        assert reason is None

    def test_repartition_does_not_override_the_other_guards(self, destination, storage):
        # --repartition only waives the "existing table is partitioned
        # differently" objection. A path-unsafe tag is still a hard no, because
        # rewriting would not make it safe.
        write_delta_table_versioned(frame(["A", "B"]), destination, storage)
        partition, reason = plan_partitioning(
            frame(["A", "bad/tag"]), destination, storage, "replace-runs", repartition=True
        )
        assert partition is False
        assert reason is not None and "path-safe" in reason


class TestDeltaCommitInfoDefaults:
    def test_defaults_are_absent_not_zero(self):
        # A missing metric is unknown, not "none added" — the UI has to be able
        # to tell those apart.
        info = DeltaCommitInfo(version=0)
        assert info.rows_added is None
        assert info.custom_metadata == {}


def probe(destination, storage, **overrides):
    real = probe_delta_table(destination, storage, with_schema=True)
    for key, value in overrides.items():
        setattr(real, key, value)
    return real


def partitioned_table(destination, storage, run_ids=("A", "B", "C")):
    write_delta_table_versioned(
        frame(list(run_ids)), destination, storage, write_mode="replace-runs", partition=True
    )


class TestScopedWriteSafety:
    """The invariants that make a partial frame safe to write."""

    def test_a_subset_write_refuses_to_overwrite_the_whole_table(self, destination, storage):
        # Without partitioning, mode="overwrite" replaces every row — with a
        # subset in hand that deletes every run the subset does not contain.
        partitioned_table(destination, storage)
        with pytest.raises(ValueError, match="subset of its runs"):
            write_delta_table_versioned(
                frame(["A"], [99]),
                destination,
                storage,
                write_mode="replace-runs",
                partition=False,
                scoped=True,
            )
        assert rows(destination) == [("A", 0), ("B", 1), ("C", 2)]

    def test_replace_run_tags_without_partitioning_is_refused(self, destination, storage):
        partitioned_table(destination, storage)
        with pytest.raises(ValueError, match="meaningless without partitioning"):
            write_delta_table_versioned(
                frame(["A"], [99]),
                destination,
                storage,
                write_mode="replace-runs",
                partition=False,
                replace_run_tags=["A"],
            )

    def test_one_changed_run_leaves_the_others_alone(self, destination, storage):
        # The nominal case, and the one that would be catastrophic if the
        # single-run guard sent it down the full-overwrite path.
        partitioned_table(destination, storage)
        write_delta_table_versioned(
            frame(["A"], [99]),
            destination,
            storage,
            write_mode="replace-runs",
            partition=True,
            replace_run_tags=["A"],
            scoped=True,
        )
        assert rows(destination) == [("A", 99), ("B", 1), ("C", 2)]

    def test_a_scoped_write_does_not_drop_a_column_it_lacks(self, destination, storage):
        # Measured: with schema_mode="overwrite" this drops `keep` for every run
        # on deltalake 1.6.1 and leaves the table unreadable on 0.24.
        pl.DataFrame({RUN_ID_COLUMN: ["A", "B"], "v": [1, 2], "keep": ["x", "y"]}).write_delta(
            destination,
            mode="overwrite",
            delta_write_options={"schema_mode": "overwrite", "partition_by": [RUN_ID_COLUMN]},
        )
        write_delta_table_versioned(
            pl.DataFrame({RUN_ID_COLUMN: ["A"], "v": [99]}),
            destination,
            storage,
            write_mode="replace-runs",
            partition=True,
            replace_run_tags=["A"],
            scoped=True,
        )
        table = pl.read_delta(destination).sort(RUN_ID_COLUMN)
        assert "keep" in table.columns, "the untouched run's column must survive"
        assert table.filter(pl.col(RUN_ID_COLUMN) == "B")["keep"].to_list() == ["y"]

    def test_a_scoped_write_can_add_a_column(self, destination, storage):
        partitioned_table(destination, storage, run_ids=("A", "B"))
        write_delta_table_versioned(
            pl.DataFrame({RUN_ID_COLUMN: ["A"], "v": [99], "extra": ["new"]}),
            destination,
            storage,
            write_mode="replace-runs",
            partition=True,
            replace_run_tags=["A"],
            scoped=True,
        )
        table = pl.read_delta(destination).sort(RUN_ID_COLUMN)
        assert table.filter(pl.col(RUN_ID_COLUMN) == "A")["extra"].to_list() == ["new"]
        assert table.filter(pl.col(RUN_ID_COLUMN) == "B")["extra"].to_list() == [None]

    def test_a_type_conflict_fails_loudly_rather_than_corrupting(self, destination, storage):
        # schema_mode="merge" refuses; schema_mode="overwrite" would "succeed"
        # and leave a table whose schema disagrees with its retained files.
        partitioned_table(destination, storage, run_ids=("A", "B"))
        with pytest.raises(Exception):  # noqa: B017 - delta-rs error type varies by version
            write_delta_table_versioned(
                pl.DataFrame({RUN_ID_COLUMN: ["A"], "v": ["not-an-int"]}),
                destination,
                storage,
                write_mode="replace-runs",
                partition=True,
                replace_run_tags=["A"],
                scoped=True,
            )


class TestPlanScopedWrite:
    """Every path that must end in a full rebuild rather than a partial write."""

    def base(self, destination, storage, **overrides):
        partitioned_table(destination, storage)
        kwargs = {
            "probe": probe(destination, storage),
            "changed_runs": ["A"],
            "removed_runs": [],
            "write_mode": "replace-runs",
            "incremental_write": True,
            "signal_complete": True,
            "covered": True,
        }
        kwargs.update(overrides)
        return plan_scoped_write(**kwargs)

    def test_the_nominal_case_is_scoped(self, destination, storage):
        plan = self.base(destination, storage)
        assert plan.scoped is True
        assert plan.run_tags == ["A"]

    def test_a_single_changed_run_is_not_declined(self, destination, storage):
        # plan_partitioning declines a one-run frame because partitioning buys
        # nothing there. Here it is the whole point.
        plan = self.base(destination, storage, changed_runs=["B"])
        assert plan.scoped is True

    def test_off_by_default(self, destination, storage):
        plan = self.base(destination, storage, incremental_write=False)
        assert plan.scoped is False

    def test_needs_replace_runs(self, destination, storage):
        plan = self.base(destination, storage, write_mode="overwrite")
        assert plan.scoped is False
        assert plan.declined is not None and "replace-runs" in plan.declined

    def test_an_incomplete_signal_declines(self, destination, storage):
        plan = self.base(destination, storage, signal_complete=False)
        assert plan.scoped is False
        assert plan.declined is not None and "vouch" in plan.declined

    def test_an_uncovered_collection_declines(self, destination, storage):
        plan = self.base(destination, storage, covered=False)
        assert plan.scoped is False
        assert plan.declined is not None and "not covered" in plan.declined

    def test_a_removed_run_forces_a_rebuild(self, destination, storage):
        # A predicate can replace runs; it cannot express "this one is gone".
        plan = self.base(destination, storage, removed_runs=["C"])
        assert plan.scoped is False
        assert plan.declined is not None and "disappeared" in plan.declined

    def test_no_table_yet_declines(self, destination, storage):
        plan = self.base(destination, storage, probe=None)
        assert plan.scoped is False
        assert plan.declined is not None and "no table" in plan.declined

    def test_an_unpartitioned_table_declines(self, destination, storage):
        write_delta_table_versioned(frame(["A", "B"]), destination, storage)
        plan = plan_scoped_write(
            probe=probe_delta_table(destination, storage, with_schema=True),
            changed_runs=["A"],
            removed_runs=[],
            write_mode="replace-runs",
            incremental_write=True,
            signal_complete=True,
            covered=True,
        )
        assert plan.scoped is False
        assert plan.declined is not None and "partitioned by" in plan.declined

    def test_an_unreadable_schema_declines(self, destination, storage):
        # Without the table's schema there is nothing to align the partial frame
        # against, and an unaligned subset is what narrows a table.
        partitioned_table(destination, storage)
        plan = plan_scoped_write(
            probe=probe(destination, storage, schema=None),
            changed_runs=["A"],
            removed_runs=[],
            write_mode="replace-runs",
            incremental_write=True,
            signal_complete=True,
            covered=True,
        )
        assert plan.scoped is False
        assert plan.declined is not None and "schema" in plan.declined

    def test_an_unsafe_tag_declines(self, destination, storage):
        plan = self.base(destination, storage, changed_runs=["ok", "bad/tag"])
        assert plan.scoped is False
        assert plan.declined is not None and "path-safe" in plan.declined

    def test_too_many_runs_declines(self, destination, storage):
        plan = self.base(destination, storage, changed_runs=[f"r{i}" for i in range(5001)])
        assert plan.scoped is False
        assert plan.declined is not None and "partition guard" in plan.declined

    def test_no_changed_run_declines(self, destination, storage):
        plan = self.base(destination, storage, changed_runs=[])
        assert plan.scoped is False


class TestProbe:
    def test_absent_table_probes_as_none(self, tmp_path, storage):
        assert probe_delta_table(str(tmp_path / "nothing"), storage) is None

    def test_partition_columns_and_version_are_read(self, destination, storage):
        partitioned_table(destination, storage)
        found = probe_delta_table(destination, storage)
        assert found is not None
        assert found.partitioned_by_run is True
        assert found.version == 0
        assert found.size_bytes and found.size_bytes > 0

    def test_the_schema_is_only_read_when_asked(self, destination, storage):
        partitioned_table(destination, storage)
        assert probe_delta_table(destination, storage).schema is None
        schema = probe_delta_table(destination, storage, with_schema=True).schema
        assert schema is not None
        # Order differs between deltalake 0.24 and 1.6, so only names matter.
        assert set(schema) == {RUN_ID_COLUMN, "v"}

    def test_an_unpartitioned_table_is_not_partitioned_by_run(self, destination, storage):
        write_delta_table_versioned(frame(["A", "B"]), destination, storage)
        assert probe_delta_table(destination, storage).partitioned_by_run is False
