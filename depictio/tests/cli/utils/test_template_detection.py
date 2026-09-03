"""Auto-selecting a bundled template from a results directory.

Most tests point ``_projects_roots`` at a synthetic ``projects/`` tree so the
version-fallback policy is asserted against a fixed set of shipped versions
rather than whatever the repo happens to ship today. One test deliberately runs
against the real bundled reference directory.
"""

from pathlib import Path

import pytest

from depictio.cli.cli.utils import templates as templates_module
from depictio.cli.cli.utils.templates import detect_template_from_run_dir

# Versions the synthetic projects tree ships. 2.15.0 sits between two of them
# and 2.8.0 is older than all of them, which is what the fallback policy turns on.
SHIPPED_VERSIONS = ("2.14.0", "2.16.0", "2.18.0")

REPO_REFERENCE_DIR = (
    Path(__file__).resolve().parents[4] / "depictio" / "projects" / "nf-core" / "ampliseq"
)


def _versions_yaml(raw_version: str, pipeline: str = "nf-core/ampliseq") -> str:
    # 4-space `Workflow:` indent, as real nf-core output uses.
    return f"FASTQC:\n  fastqc: 0.12.1\nWorkflow:\n    {pipeline}: {raw_version}\n    Nextflow: 25.10.0\n"


@pytest.fixture
def shipped_templates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A synthetic ``projects/`` root shipping nf-core/ampliseq 2.14.0/2.16.0/2.18.0."""
    projects = tmp_path / "projects"
    for version in SHIPPED_VERSIONS:
        version_dir = projects / "nf-core" / "ampliseq" / version
        version_dir.mkdir(parents=True)
        (version_dir / "template.yaml").write_text(
            f"template:\n  template_id: nf-core/ampliseq/{version}\n  version: '{version}'\n"
        )
    monkeypatch.setattr(templates_module, "_projects_roots", lambda: [projects])
    return projects


def _nextflow_run(root: Path, raw_version: str, pipeline: str = "nf-core/ampliseq") -> Path:
    pipeline_info = root / "pipeline_info"
    pipeline_info.mkdir(parents=True)
    (pipeline_info / "software_versions.yml").write_text(_versions_yaml(raw_version, pipeline))
    (pipeline_info / "params.json").write_text('{"input": "samplesheet.csv"}')
    return root


class TestExactMatch:
    def test_exact_version_selects_that_template(
        self, tmp_path: Path, shipped_templates: Path
    ) -> None:
        run = _nextflow_run(tmp_path / "run", "v2.16.0-g3d5c7e5")
        template_id, info = detect_template_from_run_dir(run)
        assert template_id == "nf-core/ampliseq/2.16.0"
        assert info is not None
        assert info.pipeline_name == "nf-core/ampliseq"
        assert info.pipeline_version == "2.16.0"
        assert info.extra["pipeline_version_raw"] == "v2.16.0-g3d5c7e5"

    def test_plain_version_string_matches_too(
        self, tmp_path: Path, shipped_templates: Path
    ) -> None:
        run = _nextflow_run(tmp_path / "run", "2.18.0")
        template_id, _ = detect_template_from_run_dir(run)
        assert template_id == "nf-core/ampliseq/2.18.0"


class TestVersionFallback:
    def test_picks_highest_version_not_newer_than_the_run(
        self, tmp_path: Path, shipped_templates: Path
    ) -> None:
        """A 2.15.0 run falls back to 2.14.0, not to 2.16.0."""
        run = _nextflow_run(tmp_path / "run", "v2.15.0-gabc1234")
        template_id, info = detect_template_from_run_dir(run)
        assert template_id == "nf-core/ampliseq/2.14.0"
        assert info is not None
        assert info.pipeline_version == "2.15.0"

    def test_run_older_than_every_template_picks_the_lowest(
        self, tmp_path: Path, shipped_templates: Path
    ) -> None:
        """The #811 regression: an old run must NOT be handed the newest template.

        A newer template describes outputs the older run never produced, so the
        lowest shipped version is the only defensible substitute.
        """
        run = _nextflow_run(tmp_path / "run", "2.8.0")
        template_id, _ = detect_template_from_run_dir(run)
        assert template_id == "nf-core/ampliseq/2.14.0"
        assert template_id != "nf-core/ampliseq/2.18.0"

    def test_run_newer_than_every_template_picks_the_highest(
        self, tmp_path: Path, shipped_templates: Path
    ) -> None:
        run = _nextflow_run(tmp_path / "run", "v2.20.0-gdeadbee")
        template_id, _ = detect_template_from_run_dir(run)
        assert template_id == "nf-core/ampliseq/2.18.0"

    def test_dev_suffix_normalises_before_comparison(
        self, tmp_path: Path, shipped_templates: Path
    ) -> None:
        run = _nextflow_run(tmp_path / "run", "v2.13.0dev-ge7bcfda")
        template_id, info = detect_template_from_run_dir(run)
        assert info is not None
        assert info.pipeline_version == "2.13.0"
        assert template_id == "nf-core/ampliseq/2.14.0"  # lowest: run predates them all


class TestNoSelection:
    def test_unknown_pipeline_returns_none_with_info(
        self, tmp_path: Path, shipped_templates: Path
    ) -> None:
        run = _nextflow_run(tmp_path / "run", "1.2.3", pipeline="nf-core/nowhere")
        template_id, info = detect_template_from_run_dir(run)
        assert template_id is None
        assert info is not None
        assert info.pipeline_name == "nf-core/nowhere"
        assert info.engine == "nextflow"

    def test_empty_directory_returns_none_none(
        self, tmp_path: Path, shipped_templates: Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        assert detect_template_from_run_dir(empty) == (None, None)

    def test_recognised_run_without_pipeline_identity(
        self, tmp_path: Path, shipped_templates: Path
    ) -> None:
        run = tmp_path / "legacy"
        pipeline_info = run / "pipeline_info"
        pipeline_info.mkdir(parents=True)
        (pipeline_info / "software_versions.yml").write_text("FASTQC:\n  fastqc: 0.12.1\n")
        template_id, info = detect_template_from_run_dir(run)
        assert template_id is None
        assert info is not None
        assert info.pipeline_name is None
        assert info.tools_executed == {"fastqc"}


class TestBundledReferenceDirectory:
    """Against the real reference run shipped in the repo, not a fixture."""

    @staticmethod
    def _reference_run() -> Path:
        from depictio.cli.cli.utils.templates import latest_template_version

        version = latest_template_version(REPO_REFERENCE_DIR)
        if version is None:
            pytest.skip(f"No bundled ampliseq template under {REPO_REFERENCE_DIR}")
        run_dir = REPO_REFERENCE_DIR / version
        if not (run_dir / "pipeline_info").is_dir():
            pytest.skip(f"Bundled reference run has no pipeline_info/: {run_dir}")
        return run_dir

    def test_detection_on_the_bundled_reference_run(self) -> None:
        run_dir = self._reference_run()
        template_id, info = detect_template_from_run_dir(run_dir)

        # Whatever the reference ships, detection must never raise and must
        # never invent a template that is not on disk.
        assert info is not None
        assert info.engine == "nextflow"
        if info.pipeline_name is None:
            # Degrades cleanly when the bundled versions YAML carries no
            # `Workflow:` identity section.
            assert template_id is None
            return

        assert info.pipeline_name == "nf-core/ampliseq"
        assert template_id is not None
        from depictio.cli.cli.utils.templates import locate_template

        assert locate_template(template_id).is_file()

    def test_bundled_reference_run_reports_tools(self) -> None:
        run_dir = self._reference_run()
        _, info = detect_template_from_run_dir(run_dir)
        assert info is not None
        assert info.tools_executed, "reference software_versions.yml should list tools"
