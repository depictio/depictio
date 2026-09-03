"""Registry/dispatch tests for the engine-agnostic run-provenance layer.

Covers the part that is engine-independent: which connectors are registered,
which one a given directory dispatches to, and that registration is idempotent.
Engine-specific parsing lives in ``test_nextflow_run_info.py`` /
``test_snakemake_run_info.py``.
"""

from pathlib import Path

import pytest

from depictio.models.models.run_info import (
    WorkflowRunInfo,
    read_run_info,
    register_run_info_reader,
    registered_readers,
)

# A minimal but realistic nf-core versions YAML: process sections plus the
# `Workflow:` identity section.
NEXTFLOW_VERSIONS_YAML = """\
FASTQC:
  fastqc: 0.12.1
Workflow:
    nf-core/ampliseq: v2.16.0-g3d5c7e5
    Nextflow: 25.10.0
"""


def _make_nextflow_run(root: Path) -> Path:
    pipeline_info = root / "pipeline_info"
    pipeline_info.mkdir(parents=True)
    (pipeline_info / "software_versions.yml").write_text(NEXTFLOW_VERSIONS_YAML)
    return root


def _make_snakemake_run(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Snakefile").write_text('rule all:\n    input: "done.txt"\n')
    (root / ".snakemake").mkdir()
    return root


class TestRegistry:
    def test_both_bundled_connectors_are_registered(self) -> None:
        names = [reader.name for reader in registered_readers()]
        assert "nextflow" in names
        assert "snakemake" in names

    def test_readers_are_ordered_by_descending_priority(self) -> None:
        priorities = [reader.priority for reader in registered_readers()]
        assert priorities == sorted(priorities, reverse=True)

    def test_registration_is_idempotent_by_name(self) -> None:
        before = len(registered_readers())

        class _Stub:
            name = "stub-engine"
            priority = 1

            def read(self, run_dir: Path) -> WorkflowRunInfo | None:
                return None

        register_run_info_reader(_Stub())
        register_run_info_reader(_Stub())
        names = [reader.name for reader in registered_readers()]
        assert names.count("stub-engine") == 1
        assert len(names) == before + 1


class TestDispatch:
    def test_dispatches_to_nextflow(self, tmp_path: Path) -> None:
        info = read_run_info(_make_nextflow_run(tmp_path / "run"))
        assert info is not None
        assert info.engine == "nextflow"
        assert info.pipeline_name == "nf-core/ampliseq"

    def test_dispatches_to_snakemake(self, tmp_path: Path) -> None:
        info = read_run_info(_make_snakemake_run(tmp_path / "my_pipeline"))
        assert info is not None
        assert info.engine == "snakemake"

    def test_nextflow_wins_when_both_footprints_present(self, tmp_path: Path) -> None:
        """Higher priority resolves a directory carrying two engines' footprints."""
        run = tmp_path / "mixed"
        _make_snakemake_run(run)
        _make_nextflow_run(run)
        info = read_run_info(run)
        assert info is not None
        assert info.engine == "nextflow"

    def test_unknown_directory_returns_none(self, tmp_path: Path) -> None:
        plain = tmp_path / "just-results"
        plain.mkdir()
        (plain / "results.csv").write_text("a,b\n1,2\n")
        assert read_run_info(plain) is None

    def test_failing_reader_does_not_break_the_others(self, tmp_path: Path) -> None:
        class _Exploding:
            name = "exploding-engine"
            priority = 1000  # ahead of every bundled connector

            def read(self, run_dir: Path) -> WorkflowRunInfo | None:
                raise RuntimeError("boom")

        register_run_info_reader(_Exploding())
        try:
            info = read_run_info(_make_nextflow_run(tmp_path / "run"))
            assert info is not None
            assert info.engine == "nextflow"
        finally:
            # Restore the registry for the rest of the session.
            class _Inert:
                name = "exploding-engine"
                priority = -1

                def read(self, run_dir: Path) -> WorkflowRunInfo | None:
                    return None

            register_run_info_reader(_Inert())


class TestWorkflowRunInfo:
    def test_short_name_strips_the_namespace(self) -> None:
        assert WorkflowRunInfo(pipeline_name="nf-core/ampliseq").short_name == "ampliseq"
        assert WorkflowRunInfo(pipeline_name="ampliseq").short_name == "ampliseq"
        assert WorkflowRunInfo().short_name is None

    def test_template_ids_normalised_then_raw(self) -> None:
        info = WorkflowRunInfo(
            pipeline_name="nf-core/ampliseq",
            pipeline_version="2.16.0",
            extra={"pipeline_version_raw": "v2.16.0-g3d5c7e5"},
        )
        assert info.template_ids() == [
            "nf-core/ampliseq/2.16.0",
            "nf-core/ampliseq/v2.16.0-g3d5c7e5",
        ]

    def test_template_ids_deduplicates_identical_raw(self) -> None:
        info = WorkflowRunInfo(
            pipeline_name="nf-core/ampliseq",
            pipeline_version="2.8.0",
            extra={"pipeline_version_raw": "2.8.0"},
        )
        assert info.template_ids() == ["nf-core/ampliseq/2.8.0"]

    def test_template_ids_empty_without_identity(self) -> None:
        assert WorkflowRunInfo().template_ids() == []
        # A pipeline with no version yields no id: the version-less id would
        # resolve to the latest template, which is never a safe default.
        assert WorkflowRunInfo(pipeline_name="nf-core/ampliseq").template_ids() == []

    def test_model_forbids_extra_fields(self) -> None:
        with pytest.raises(Exception):
            WorkflowRunInfo(unexpected_field="x")  # type: ignore[call-arg]
