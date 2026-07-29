"""Tests for leaving an unchanged data collection alone, and for aligning a
partial batch against the table it is being written into.

A wrong skip is worse than a redundant rebuild: the Delta table silently stops
tracking its files and nothing reports it. Every condition below therefore has
to hold before anything is skipped, and each test names the failure it prevents.
"""

from types import SimpleNamespace

import polars as pl
import pytest

from depictio.cli.cli.utils.deltatables import (
    SchemaConflictError,
    align_lazy_schemas,
    skip_unchanged_reason,
)

DC_ID = "507f1f77bcf86cd799439011"


def dc(dc_id: str = DC_ID) -> SimpleNamespace:
    return SimpleNamespace(id=dc_id, data_collection_tag="dc")


def probe(version: int = 7) -> SimpleNamespace:
    return SimpleNamespace(version=version)


def params(**overrides) -> dict:
    """A cycle in which nothing changed and skipping is allowed."""
    signal = {
        "changed_dcs": {},
        "covered_dcs": [DC_ID],
        "removed_runs": [],
        "complete": True,
    }
    signal.update(overrides.pop("signal", {}))
    return {"skip_unchanged": True, "scan_signal": signal, **overrides}


class TestSkipUnchanged:
    def test_an_untouched_collection_is_skipped(self):
        reason = skip_unchanged_reason(dc(), probe(), params())
        assert reason is not None and "version 7" in reason

    def test_a_changed_collection_is_processed(self):
        reason = skip_unchanged_reason(
            dc(), probe(), params(signal={"changed_dcs": {DC_ID: ["run_A"]}})
        )
        assert reason is None

    def test_another_collection_changing_does_not_protect_this_one(self):
        # Only this collection's own entry matters.
        reason = skip_unchanged_reason(
            dc(), probe(), params(signal={"changed_dcs": {"other-id": ["run_A"]}})
        )
        assert reason is not None

    def test_nothing_is_skipped_unless_asked(self):
        reason = skip_unchanged_reason(dc(), probe(), params(skip_unchanged=False))
        assert reason is None

    def test_an_incomplete_signal_never_skips(self):
        # Without --rescan-folders, registered runs are skipped with no check at
        # all, so "nothing changed" is a guess.
        reason = skip_unchanged_reason(dc(), probe(), params(signal={"complete": False}))
        assert reason is None

    def test_an_uncovered_collection_never_skips(self):
        # Single-file, MultiQC, recipe and join collections are never walked by
        # the run-based scan, so it cannot report them as unchanged.
        reason = skip_unchanged_reason(dc(), probe(), params(signal={"covered_dcs": []}))
        assert reason is None

    def test_a_removed_run_never_skips(self):
        # The rows of a deleted run have to come out of the table.
        reason = skip_unchanged_reason(dc(), probe(), params(signal={"removed_runs": ["run_C"]}))
        assert reason is None

    def test_a_missing_table_never_skips(self):
        # A first ingestion, or one whose write died before the table existed.
        reason = skip_unchanged_reason(dc(), None, params())
        assert reason is None

    def test_no_signal_at_all_never_skips(self):
        reason = skip_unchanged_reason(dc(), probe(), {"skip_unchanged": True})
        assert reason is None

    def test_empty_parameters_never_skip(self):
        # `depictio data process` invoked on its own has no scan to lean on.
        reason = skip_unchanged_reason(dc(), probe(), {})
        assert reason is None


class TestRunRestrictedFetch:
    """Filtering the file list to the runs that changed."""

    @pytest.fixture
    def registry(self, tmp_path, monkeypatch):
        """Two runs' worth of registered files, all present on disk."""
        docs = []
        for tag in ("run_A", "run_B"):
            path = tmp_path / f"{tag}.tsv"
            path.write_text("a\tb\n1\t2\n")
            docs.append(
                {
                    "_id": f"id-{tag}",
                    "file_location": str(path),
                    "run_tag": tag,
                    "filename": path.name,
                    "creation_time": "2026-01-01 00:00:00",
                    "modification_time": "2026-01-01 00:00:00",
                    "run_id": "507f1f77bcf86cd799439011",
                    "file_hash": "abc",
                }
            )

        def fake_get(dc_id, cli_config):
            return SimpleNamespace(status_code=200, json=lambda: docs, text="")

        monkeypatch.setattr("depictio.cli.cli.utils.deltatables.api_get_files_by_dc_id", fake_get)
        return docs

    @pytest.fixture
    def as_file_objects(self, monkeypatch):
        """Skip File validation; only the filtering is under test here."""
        from depictio.cli.cli.utils import deltatables

        monkeypatch.setattr(
            deltatables,
            "convert_to_file_objects",
            lambda docs: [SimpleNamespace(**doc) for doc in docs],
        )

    def test_only_the_named_runs_come_back(self, registry, as_file_objects):
        from depictio.cli.cli.utils import deltatables

        files = deltatables.fetch_file_data.__wrapped__("dc1", object(), run_tags={"run_A"})
        assert [f.run_tag for f in files] == ["run_A"]

    def test_no_filter_returns_everything(self, registry, as_file_objects):
        from depictio.cli.cli.utils import deltatables

        files = deltatables.fetch_file_data.__wrapped__("dc1", object(), run_tags=None)
        assert len(files) == 2

    def test_a_run_with_nothing_left_asks_for_a_full_rebuild(self, registry):
        from depictio.cli.cli.utils import deltatables

        # A scoped write cannot express "these rows should no longer exist", so
        # the caller has to fall back rather than write an empty subset.
        with pytest.raises(deltatables.NoFilesForRunsError):
            deltatables.fetch_file_data.__wrapped__("dc1", object(), run_tags={"run_gone"})


class TestAlignAgainstExistingTable:
    def test_without_a_target_the_batch_decides_its_own_schema(self):
        frames = [
            pl.DataFrame({"a": [1]}).lazy(),
            pl.DataFrame({"b": ["x"]}).lazy(),
        ]
        aligned = align_lazy_schemas(frames)
        assert set(aligned[0].collect_schema().names()) == {"a", "b"}

    def test_conflicting_types_still_coerce_to_utf8_for_a_full_rebuild(self):
        # Unchanged behaviour: a full rewrite puts every row in one type.
        frames = [
            pl.DataFrame({"a": [1]}).lazy(),
            pl.DataFrame({"a": ["one"]}).lazy(),
        ]
        aligned = align_lazy_schemas(frames)
        assert aligned[0].collect_schema()["a"] == pl.Utf8

    def test_a_column_the_batch_lacks_is_kept_as_typed_nulls(self):
        # Dropping it would narrow a table whose other runs still have data in
        # it — on deltalake 1.6.1 that deletes the column for every run.
        frames = [pl.DataFrame({"a": [1]}).lazy()]
        aligned = align_lazy_schemas(frames, target_schema={"a": pl.Int64, "keep": pl.Utf8})
        schema = aligned[0].collect_schema()
        assert schema["keep"] == pl.Utf8
        assert aligned[0].collect()["keep"].to_list() == [None]

    def test_a_new_column_is_allowed_through(self):
        frames = [pl.DataFrame({"a": [1], "extra": ["new"]}).lazy()]
        aligned = align_lazy_schemas(frames, target_schema={"a": pl.Int64})
        assert set(aligned[0].collect_schema().names()) == {"a", "extra"}

    def test_a_type_conflict_with_the_table_raises_instead_of_coercing(self):
        # Coercing here would leave the runs that are *not* being rewritten in
        # the old type, under a schema claiming the new one.
        frames = [pl.DataFrame({"a": ["one"]}).lazy()]
        with pytest.raises(SchemaConflictError, match="a is String here but Int64 in the table"):
            align_lazy_schemas(frames, target_schema={"a": pl.Int64})

    def test_column_order_does_not_matter(self):
        # deltalake 0.24 and 1.6 disagree on where the partition column sits.
        frames = [pl.DataFrame({"b": ["x"], "a": [1]}).lazy()]
        aligned = align_lazy_schemas(frames, target_schema={"a": pl.Int64, "b": pl.Utf8})
        assert set(aligned[0].collect_schema().names()) == {"a", "b"}
