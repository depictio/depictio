"""Nextflow/nf-core run-provenance connector.

The fixtures reproduce, byte-for-byte where it matters, shapes observed in real
nf-core output on disk: the 4-space-indented ``Workflow:`` section some template
generations emit, the plain ``software_versions.yml`` filename, and the four
distinct version strings the same pipeline reports depending on how it was
checked out.
"""

from pathlib import Path

import pytest

from depictio.models.models.nextflow import NextflowRunInfoReader, normalize_pipeline_version

# Real shape: `Workflow:` indented 4 spaces, plain `software_versions.yml`.
# (~/Data/ampliseq/megatest-full/pipeline_info/software_versions.yml)
VERSIONS_YAML_4_SPACE = """\
BARRNAP:
  barrnap: 0.9
CUTADAPT_BASIC:
  cutadapt: 4.6
DADA2_DENOISING:
  R: 4.3.2
  dada2: 1.30.0
Workflow:
    nf-core/ampliseq: v2.13.0dev-ge7bcfda
    Nextflow: 24.04.2
"""

# Real shape: `Workflow:` indented 2 spaces, Nextflow listed first.
# (~/Data/ampliseq/testdata/nf-core-ampliseq-202411281303/pipeline_info/software_versions.yml)
VERSIONS_YAML_2_SPACE = """\
FASTQC:
  fastqc: 0.12.1
Workflow:
  Nextflow: 23.10.1
  nf-core/ampliseq: 2.8.0
"""

# Legacy shape: process sections only, no identity at all.
VERSIONS_YAML_NO_WORKFLOW = """\
FASTQC:
  fastqc: 0.12.1
MULTIQC:
  multiqc: 1.21
"""

NEXTFLOW_CONFIG = """\
manifest {
    name            = 'nf-core/ampliseq'
    author          = 'Someone'
    homePage        = 'https://github.com/nf-core/ampliseq'
    description     = 'Amplicon sequencing analysis workflow'
    mainScript      = 'main.nf'
    nextflowVersion = '!>=25.04.3'
    version         = '2.16.0'
}
"""


def _reader() -> NextflowRunInfoReader:
    return NextflowRunInfoReader()


def _pipeline_info(root: Path) -> Path:
    pipeline_info = root / "pipeline_info"
    pipeline_info.mkdir(parents=True, exist_ok=True)
    return pipeline_info


class TestNormalizePipelineVersion:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Every one of these was read off a real run directory.
            ("v2.16.0-g3d5c7e5", "2.16.0"),
            ("v2.13.0dev-ge7bcfda", "2.13.0"),
            ("v2.13.0dev", "2.13.0"),
            ("2.8.0", "2.8.0"),
            # Shapes the same rules must not mangle.
            ("v3.0.0", "3.0.0"),
            ("2.16.0", "2.16.0"),
            (None, None),
            ("", None),
        ],
    )
    def test_normalises_to_a_comparable_release(
        self, raw: str | None, expected: str | None
    ) -> None:
        assert normalize_pipeline_version(raw) == expected

    def test_non_hex_suffix_is_not_a_git_sha(self) -> None:
        """`-g<sha>` stripping must not eat a legitimate pre-release suffix."""
        assert normalize_pipeline_version("v3.0.0-gamma") == "3.0.0-gamma"


class TestFullPipelineInfoParse:
    def test_reads_identity_tools_and_artefact_paths(self, tmp_path: Path) -> None:
        run = tmp_path / "run_16s_pe"
        pipeline_info = _pipeline_info(run)
        (pipeline_info / "software_versions.yml").write_text(VERSIONS_YAML_4_SPACE)
        (pipeline_info / "params_2026-06-11_16-37-38.json").write_text('{"skip_qiime": false}')
        (pipeline_info / "params_2026-06-12_07-20-45.json").write_text(
            '{"skip_qiime": true, "run_name": "grave_curie"}'
        )
        (pipeline_info / "execution_report_2026-06-12_07-20-35.html").write_text("<html/>")
        (pipeline_info / "execution_trace_2026-06-12_07-20-35.txt").write_text("task_id\n")
        (pipeline_info / "pipeline_dag_2026-06-12_07-20-35.html").write_text("<html/>")

        info = _reader().read(run)
        assert info is not None
        assert info.engine == "nextflow"
        assert info.pipeline_name == "nf-core/ampliseq"
        assert info.short_name == "ampliseq"
        assert info.pipeline_version == "2.13.0"
        assert info.extra["pipeline_version_raw"] == "v2.13.0dev-ge7bcfda"
        assert info.engine_version == "24.04.2"
        assert info.tools_executed == {"barrnap", "cutadapt", "r", "dada2"}
        # Newest params file by name wins (nf-core writes one per resume).
        assert info.params["skip_qiime"] is True
        assert info.run_name == "grave_curie"
        assert info.params_json_path is not None
        assert info.params_json_path.endswith("params_2026-06-12_07-20-45.json")
        assert info.software_versions_path is not None
        assert info.execution_report_path is not None
        assert info.execution_trace_path is not None
        assert info.pipeline_dag_path is not None
        assert info.template_ids()[0] == "nf-core/ampliseq/2.13.0"


class TestVersionsFileNameShapes:
    @pytest.mark.parametrize(
        "filename",
        [
            "software_versions.yml",
            "nf_core_ampliseq_software_mqc_versions.yml",
            "ampliseq_software_mqc_versions.yml",
        ],
    )
    def test_identity_read_from_every_shipped_filename(self, tmp_path: Path, filename: str) -> None:
        run = tmp_path / "run"
        (_pipeline_info(run) / filename).write_text(VERSIONS_YAML_4_SPACE)
        info = _reader().read(run)
        assert info is not None
        assert info.pipeline_name == "nf-core/ampliseq"
        assert info.pipeline_version == "2.13.0"

    def test_plain_software_versions_with_four_space_indent(self, tmp_path: Path) -> None:
        """The exact real-world combination a regex-based parser would miss."""
        run = tmp_path / "megatest-full"
        (_pipeline_info(run) / "software_versions.yml").write_text(VERSIONS_YAML_4_SPACE)
        info = _reader().read(run)
        assert info is not None
        assert info.pipeline_name == "nf-core/ampliseq"
        assert info.engine_version == "24.04.2"

    def test_two_space_indent_with_nextflow_listed_first(self, tmp_path: Path) -> None:
        run = tmp_path / "testdata-run"
        (_pipeline_info(run) / "software_versions.yml").write_text(VERSIONS_YAML_2_SPACE)
        info = _reader().read(run)
        assert info is not None
        assert info.pipeline_name == "nf-core/ampliseq"
        assert info.pipeline_version == "2.8.0"
        assert info.engine_version == "23.10.1"


class TestParamsFileShapes:
    @pytest.mark.parametrize("filename", ["params.json", "nf-params.json", "nf_params.json"])
    def test_reads_every_params_filename(self, tmp_path: Path, filename: str) -> None:
        run = tmp_path / "run"
        pipeline_info = _pipeline_info(run)
        (pipeline_info / "software_versions.yml").write_text(VERSIONS_YAML_2_SPACE)
        (pipeline_info / filename).write_text('{"input": "samplesheet.csv"}')
        info = _reader().read(run)
        assert info is not None
        assert info.params == {"input": "samplesheet.csv"}

    def test_unparseable_params_do_not_abort_detection(self, tmp_path: Path) -> None:
        run = tmp_path / "run"
        pipeline_info = _pipeline_info(run)
        (pipeline_info / "software_versions.yml").write_text(VERSIONS_YAML_2_SPACE)
        (pipeline_info / "params.json").write_text("{not json")
        info = _reader().read(run)
        assert info is not None
        assert info.params == {}
        assert info.pipeline_name == "nf-core/ampliseq"


class TestTolerance:
    def test_empty_directory_returns_none(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        assert _reader().read(empty) is None

    def test_empty_pipeline_info_returns_none(self, tmp_path: Path) -> None:
        run = tmp_path / "run"
        _pipeline_info(run)
        assert _reader().read(run) is None

    def test_nonexistent_path_returns_none(self, tmp_path: Path) -> None:
        assert _reader().read(tmp_path / "does-not-exist") is None

    def test_legacy_versions_without_workflow_section_yields_tools_only(
        self, tmp_path: Path
    ) -> None:
        run = tmp_path / "legacy"
        (_pipeline_info(run) / "software_versions.yml").write_text(VERSIONS_YAML_NO_WORKFLOW)
        info = _reader().read(run)
        assert info is not None
        assert info.pipeline_name is None
        assert info.pipeline_version is None
        assert info.tools_executed == {"fastqc", "multiqc"}
        assert info.template_ids() == []

    def test_malformed_versions_yaml_does_not_raise(self, tmp_path: Path) -> None:
        run = tmp_path / "broken"
        pipeline_info = _pipeline_info(run)
        (pipeline_info / "software_versions.yml").write_text("::: not: [valid: yaml")
        (pipeline_info / "params.json").write_text("{}")
        info = _reader().read(run)
        assert info is not None
        assert info.pipeline_name is None


class TestNextflowConfigFallback:
    def test_manifest_supplies_identity_when_no_versions_file(self, tmp_path: Path) -> None:
        checkout = tmp_path / "ampliseq-checkout"
        checkout.mkdir()
        (checkout / "nextflow.config").write_text(NEXTFLOW_CONFIG)
        info = _reader().read(checkout)
        assert info is not None
        assert info.pipeline_name == "nf-core/ampliseq"
        assert info.pipeline_version == "2.16.0"
        assert info.homepage == "https://github.com/nf-core/ampliseq"
        # `nextflowVersion` is a constraint (`!>=25.04.3`), never a runtime version.
        assert info.engine_version is None

    def test_versions_file_wins_over_the_manifest(self, tmp_path: Path) -> None:
        run = tmp_path / "run"
        (_pipeline_info(run) / "software_versions.yml").write_text(VERSIONS_YAML_2_SPACE)
        (run / "nextflow.config").write_text(NEXTFLOW_CONFIG)
        info = _reader().read(run)
        assert info is not None
        assert info.pipeline_version == "2.8.0"

    def test_config_without_manifest_block_is_not_a_signal(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "nextflow.config").write_text("process {\n    cpus = 2\n}\n")
        assert _reader().read(plain) is None


# A sequencing-runs project points DATA_ROOT at the PARENT of several run_*/
# directories, each a complete pipeline output with its own pipeline_info. This
# is the viralrecon layout (~/Data/viralrecon/validation-runs-3.0.0 holds five).
# Two runs of the same pipeline that executed different tools, which is the
# normal case: a nanopore run and an illumina run share a project.
VIRALRECON_NANOPORE = """\
ARTIC_MINION:
  artic: 1.2.4
NANOPLOT:
  nanoplot: 1.41.6
Workflow:
    nf-core/viralrecon: 3.0.0
    Nextflow: 25.04.6
"""

VIRALRECON_ILLUMINA = """\
FASTP:
  fastp: 0.23.4
IVAR_VARIANTS:
  ivar: 1.4.2
Workflow:
    nf-core/viralrecon: 3.0.0
    Nextflow: 25.04.6
"""


class TestSequencingRunsLayout:
    """DATA_ROOT is the parent of the run directories, not a run itself.

    Reading only `<root>/pipeline_info` left every such project with no engine,
    no pipeline version, no Nextflow version and no tools, whatever chose the
    template. The failure was invisible: the ingestion succeeded and simply
    recorded nothing about what produced the data.
    """

    @staticmethod
    def _project(root: Path) -> Path:
        for name, versions in (
            ("run_nanopore", VIRALRECON_NANOPORE),
            ("run_illumina", VIRALRECON_ILLUMINA),
        ):
            (_pipeline_info(root / name) / "software_versions.yml").write_text(versions)
        return root

    def test_identity_is_found_one_level_down(self, tmp_path):
        info = _reader().read(self._project(tmp_path))
        assert info is not None
        assert info.pipeline_name == "nf-core/viralrecon"
        assert info.pipeline_version == "3.0.0"
        assert info.engine_version == "25.04.6"

    def test_tools_are_unioned_across_the_runs(self, tmp_path):
        """Neither run alone describes the project: report what all of them ran."""
        info = _reader().read(self._project(tmp_path))
        assert info is not None
        assert info.tools_executed == {"artic", "nanoplot", "fastp", "ivar"}

    def test_it_records_which_run_the_identity_came_from(self, tmp_path):
        """Otherwise a version silently describes one run out of several."""
        info = _reader().read(self._project(tmp_path))
        assert info is not None
        assert info.extra["run_subdirs_scanned"] == 2
        # Deterministic: sorted, so the first run carrying an identity wins.
        assert info.extra["identity_from_run"] == "run_illumina"

    def test_a_flat_run_is_unchanged(self, tmp_path):
        """The top level still wins outright, and gains no sequencing-runs keys."""
        (_pipeline_info(tmp_path) / "software_versions.yml").write_text(VIRALRECON_NANOPORE)
        (_pipeline_info(tmp_path / "ignored") / "software_versions.yml").write_text(
            VIRALRECON_ILLUMINA
        )

        info = _reader().read(tmp_path)

        assert info is not None
        assert info.tools_executed == {"artic", "nanoplot"}
        assert "run_subdirs_scanned" not in info.extra

    def test_artefact_paths_come_from_the_identifying_run(self, tmp_path):
        """Mixing one run's versions with another's params would be incoherent."""
        root = self._project(tmp_path)
        (root / "run_illumina" / "pipeline_info" / "params_2026-01-01_00-00-00.json").write_text(
            '{"platform": "illumina"}'
        )
        (root / "run_nanopore" / "pipeline_info" / "params_2026-01-01_00-00-00.json").write_text(
            '{"platform": "nanopore"}'
        )

        info = _reader().read(root)

        assert info is not None
        assert info.extra["identity_from_run"] == "run_illumina"
        assert info.params["platform"] == "illumina"
        assert "run_illumina" in str(info.software_versions_path)

    def test_a_directory_with_neither_is_still_unrecognised(self, tmp_path):
        """A curated project directory is not a pipeline output; say so."""
        (tmp_path / "multiqc").mkdir()
        (tmp_path / "small").mkdir()
        assert _reader().read(tmp_path) is None
