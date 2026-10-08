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


def _copy_declared(original: Path, copy: Path) -> Path:
    """``copy`` holding only what the connectors declare: footprint files with their
    content, marker files empty, matched directories as directories."""
    copy.mkdir(parents=True)
    for reader in registered_readers():
        # The stubs registered above declare nothing.
        declared = (getattr(reader, "footprint", ()), True), (getattr(reader, "markers", ()), False)
        for patterns, with_content in declared:
            for pattern in patterns:
                for path in original.glob(pattern):
                    target = copy / path.relative_to(original)
                    if path.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif with_content or not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(path.read_bytes() if with_content else b"")
    return copy


def _relative(info: WorkflowRunInfo | None, root: Path) -> dict | None:
    if info is None:
        return None
    prefix = f"{root}/"

    def strip(value):
        return (
            value[len(prefix) :] if isinstance(value, str) and value.startswith(prefix) else value
        )

    dumped = {key: strip(value) for key, value in info.model_dump().items()}
    dumped["extra"] = {key: strip(value) for key, value in info.extra.items()}
    return dumped


def _make_full_nextflow_run(root: Path) -> Path:
    _make_nextflow_run(root)
    pipeline_info = root / "pipeline_info"
    (pipeline_info / "params_2026-01-01_10-00-00.json").write_text('{"run_name": "r1"}')
    (pipeline_info / "execution_report_2026-01-01.html").write_text("<html></html>")
    (pipeline_info / "execution_trace_2026-01-01.txt").write_text("task_id\n")
    (root / "multiqc").mkdir()
    (root / "multiqc" / "multiqc_report.html").write_text("<html></html>")
    return root


def _make_full_snakemake_run(root: Path) -> Path:
    _make_snakemake_run(root)
    (root / "config.yaml").write_text("name: my-pipeline\nversion: 2.0\n")
    (root / ".snakemake" / "conda").mkdir()
    (root / ".snakemake" / "conda" / "env.yaml").write_text("dependencies:\n  - samtools=1.19\n")
    return root


class TestFootprint:
    """What each connector declares it reads, so a run folder can be staged locally."""

    @pytest.mark.parametrize("name", ["nextflow", "snakemake"])
    def test_bundled_connectors_declare_root_relative_patterns(self, name: str) -> None:
        reader = next(r for r in registered_readers() if r.name == name)
        assert reader.footprint and reader.markers
        for pattern in (*reader.footprint, *reader.markers):
            assert not pattern.startswith("/") and ".." not in pattern.split("/")
        # A file is either opened or only looked for.
        assert not set(reader.footprint) & set(reader.markers)

    @pytest.mark.parametrize(
        "make",
        [_make_full_nextflow_run, _make_full_snakemake_run],
        ids=["nextflow", "snakemake"],
    )
    def test_a_copy_of_the_declared_entries_reads_like_the_original(
        self, tmp_path: Path, make
    ) -> None:
        original = make(tmp_path / "a" / "run")
        copy = _copy_declared(original, tmp_path / "b" / "run")

        expected = read_run_info(original)
        assert expected is not None
        assert _relative(read_run_info(copy), copy) == _relative(expected, original)
