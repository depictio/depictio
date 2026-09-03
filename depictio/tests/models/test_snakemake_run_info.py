"""Snakemake run-provenance connector."""

from pathlib import Path

from depictio.models.models.snakemake import SnakemakeRunInfoReader

CONDA_ENV_YAML = """\
channels:
  - conda-forge
  - bioconda
dependencies:
  - bioconda::fastqc=0.12.1
  - samtools=1.19
  - python
  - pip:
      - some-python-package==1.0
"""


def _reader() -> SnakemakeRunInfoReader:
    return SnakemakeRunInfoReader()


def _snakemake_project(root: Path, *, snakefile: str = "Snakefile") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / snakefile
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('rule all:\n    input: "done.txt"\n')
    return root


class TestIdentity:
    def test_config_pipeline_key_names_the_workflow(self, tmp_path: Path) -> None:
        run = _snakemake_project(tmp_path / "results")
        (run / "config.yaml").write_text("pipeline: my-lab/rnaseq\nversion: 1.4.2\n")
        info = _reader().read(run)
        assert info is not None
        assert info.engine == "snakemake"
        assert info.pipeline_name == "my-lab/rnaseq"
        assert info.short_name == "rnaseq"
        assert info.pipeline_version == "1.4.2"
        assert info.template_ids() == ["my-lab/rnaseq/1.4.2"]
        assert info.extra["config_path"].endswith("config.yaml")

    def test_name_and_workflow_keys_are_accepted(self, tmp_path: Path) -> None:
        run = _snakemake_project(tmp_path / "by-name")
        (run / "config.yml").write_text("name: assembly\n")
        info = _reader().read(run)
        assert info is not None
        assert info.pipeline_name == "assembly"

        other = _snakemake_project(tmp_path / "by-workflow")
        (other / "config" / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
        (other / "config" / "config.yaml").write_text("workflow: variant-calling\n")
        info = _reader().read(other)
        assert info is not None
        assert info.pipeline_name == "variant-calling"

    def test_directory_name_is_the_fallback_identity(self, tmp_path: Path) -> None:
        run = _snakemake_project(tmp_path / "chipseq-analysis")
        info = _reader().read(run)
        assert info is not None
        assert info.pipeline_name == "chipseq-analysis"
        assert info.pipeline_version is None
        # Without a version there is no template id to offer.
        assert info.template_ids() == []


class TestRecognition:
    def test_snakefile_only_is_recognised(self, tmp_path: Path) -> None:
        run = _snakemake_project(tmp_path / "flat")
        assert _reader().read(run) is not None

    def test_workflow_snakefile_layout_is_recognised(self, tmp_path: Path) -> None:
        run = _snakemake_project(tmp_path / "nested", snakefile="workflow/Snakefile")
        info = _reader().read(run)
        assert info is not None
        assert info.extra["snakefile_path"].endswith("workflow/Snakefile")

    def test_metadata_dir_alone_is_recognised(self, tmp_path: Path) -> None:
        run = tmp_path / "results-only"
        (run / ".snakemake").mkdir(parents=True)
        assert _reader().read(run) is not None

    def test_non_snakemake_directory_returns_none(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "results.csv").write_text("a,b\n1,2\n")
        assert _reader().read(plain) is None

    def test_config_alone_is_not_enough(self, tmp_path: Path) -> None:
        """A bare config.yaml is far too common to identify an engine."""
        plain = tmp_path / "some-project"
        plain.mkdir()
        (plain / "config.yaml").write_text("pipeline: not-snakemake\n")
        assert _reader().read(plain) is None

    def test_nonexistent_path_returns_none(self, tmp_path: Path) -> None:
        assert _reader().read(tmp_path / "missing") is None


class TestCondaTools:
    def test_tools_extracted_from_materialised_conda_envs(self, tmp_path: Path) -> None:
        run = _snakemake_project(tmp_path / "with-conda")
        conda = run / ".snakemake" / "conda"
        conda.mkdir(parents=True)
        (conda / "a1b2c3.yaml").write_text(CONDA_ENV_YAML)
        (conda / "d4e5f6.yaml").write_text("dependencies:\n  - bioconda::MultiQC=1.21\n")
        info = _reader().read(run)
        assert info is not None
        # Channel prefixes and version pins stripped, names lowercased; the
        # nested `pip:` mapping is skipped.
        assert info.tools_executed == {"fastqc", "samtools", "python", "multiqc"}

    def test_no_conda_envs_yields_no_tools(self, tmp_path: Path) -> None:
        run = _snakemake_project(tmp_path / "no-conda")
        (run / ".snakemake").mkdir()
        info = _reader().read(run)
        assert info is not None
        assert info.tools_executed == set()

    def test_unparseable_conda_env_is_skipped(self, tmp_path: Path) -> None:
        run = _snakemake_project(tmp_path / "broken-conda")
        conda = run / ".snakemake" / "conda"
        conda.mkdir(parents=True)
        (conda / "broken.yaml").write_text("::: [not: yaml")
        (conda / "ok.yaml").write_text("dependencies:\n  - bwa=0.7.17\n")
        info = _reader().read(run)
        assert info is not None
        assert info.tools_executed == {"bwa"}

    def test_unparseable_config_does_not_abort(self, tmp_path: Path) -> None:
        run = _snakemake_project(tmp_path / "broken-config")
        (run / "config.yaml").write_text("::: [not: yaml")
        info = _reader().read(run)
        assert info is not None
        assert info.pipeline_name == "broken-config"
