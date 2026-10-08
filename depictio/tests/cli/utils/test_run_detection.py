"""Run detection on any data root: a folder on disk, or an ``s3://`` prefix.

A remote run folder is recognised from a local copy of only what the run
readers declare (``footprint`` and ``markers``). The comparison tests below are
what proves those declarations complete: the same tree, served from a stubbed
S3 listing and written to disk, must read the same.

No network: the listing comes from ``depictio.tests.cli.s3_stubs``.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from depictio.cli.cli.commands import run as run_module
from depictio.cli.cli.utils import data_root as data_root_module
from depictio.cli.cli.utils import run_detection
from depictio.cli.cli.utils import templates as templates_module
from depictio.cli.cli.utils.data_root import LocalDataRoot, data_root_for
from depictio.cli.cli.utils.run_detection import detect_template_for_root, read_run_info_for_root
from depictio.cli.cli.utils.templates import detect_template_from_run_dir
from depictio.cli.depictio_cli import app
from depictio.models.models.run_info import WorkflowRunInfo, read_run_info
from depictio.models.s3_access import S3AccessFailed

from ..s3_stubs import (
    MEGATEST_TREE,
    S3_KEY_PREFIX,
    S3_ROOT,
    FailingS3Client,
    StubS3Client,
    install_megatest_listing,
    install_s3_client,
    s3_cli_config,
    s3_client_error,
    write_tree,
)

FOLDER = S3_ROOT.rsplit("/", 1)[-1]


def _versions(pipeline: str, version: str, tool: str = "fastqc") -> str:
    # 4-space `Workflow:` indent, as real nf-core output uses.
    return f"{tool.upper()}:\n  {tool}: 0.12.1\nWorkflow:\n    {pipeline}: {version}\n    Nextflow: 25.10.0\n"


FLAT_RUN = {
    "pipeline_info/software_versions.yml": _versions("nf-core/ampliseq", "v2.16.0-g3d5c7e5"),
    "pipeline_info/params_2026-01-01_10-00-00.json": json.dumps({"run_name": "first"}),
    "pipeline_info/params_2026-01-02_10-00-00.json": json.dumps({"run_name": "resumed"}),
    "pipeline_info/execution_report_2026-01-02.html": "<html>" + "x" * 4096,
    "pipeline_info/execution_trace_2026-01-02.txt": "task_id\tname\n",
    "pipeline_info/pipeline_dag_2026-01-02.html": "<html></html>",
    "multiqc/multiqc_data/multiqc.parquet": "PAR1",
    "qiime2/barplot/level-2.csv": "index,Bacteria\nS1,42\n",
}

# A sequencing-runs project: DATA_ROOT is the parent of one folder per run.
SEQUENCING_RUNS = {
    "run_a/pipeline_info/nf_core_viralrecon_software_mqc_versions.yml": _versions(
        "nf-core/viralrecon", "2.6.0", "fastqc"
    ),
    "run_a/pipeline_info/params_x.json": json.dumps({"run_name": "a"}),
    "run_a/pipeline_info/execution_trace_x.txt": "task_id\n",
    "run_b/pipeline_info/nf_core_viralrecon_software_mqc_versions.yml": _versions(
        "nf-core/viralrecon", "2.6.0", "nanoplot"
    ),
    "run_b/variants/summary.tsv": "sample\tvariants\n",
}

CHECKOUT = {
    "nextflow.config": (
        "manifest {\n    name            = 'nf-core/ampliseq'\n"
        "    homePage        = 'https://github.com/nf-core/ampliseq'\n"
        "    version         = '2.16.0'\n}\n"
    ),
    "main.nf": "workflow {}\n",
}

# No identity anywhere: recognised from the report's presence, tools from the
# legacy versions file searched for across the tree.
LEGACY_VERSIONS = {
    "pipeline_info/execution_report.html": "<html></html>",
    "results/fastqc/software_versions.yml": "FASTQC:\n  fastqc: 0.12.1\n",
}

# pipeline_info is there but holds nothing the reader knows, so the nested run is
# never looked at: the copy must hold the directory to read the same.
EMPTY_PIPELINE_INFO = {
    "pipeline_info/notes.txt": "nothing here",
    "run_a/pipeline_info/software_versions.yml": _versions("nf-core/ampliseq", "2.16.0"),
}

SNAKEMAKE = {
    "workflow/Snakefile": 'rule all:\n    input: "done.txt"\n',
    "config/config.yaml": "pipeline: my-lab/variant-calling\nversion: 1.2.0\n",
    ".snakemake/conda/abc123.yaml": "dependencies:\n  - bioconda::fastqc=0.12.1\n  - samtools=1.19\n",
    ".snakemake/log/2026-01-01.snakemake.log": "Building DAG of jobs...\n",
    "results/out.txt": "x\n",
}

# Named after its folder: nothing else names it.
SNAKEMAKE_UNNAMED = {
    ".snakemake/metadata/abc": "{}",
    "Snakefile": "rule all:\n",
}

PLAIN = {"results.csv": "a,b\n1,2\n"}


def _bytes(tree: dict[str, str]) -> dict[str, bytes]:
    return {rel: body.encode() for rel, body in tree.items()}


def _comparable(info: WorkflowRunInfo | None, location: str) -> dict | None:
    """``info`` with the paths under ``location`` made relative, local or remote alike."""
    if info is None:
        return None

    def relative(value):
        if isinstance(value, str) and value.startswith(f"{location}/"):
            return value[len(location) + 1 :]
        return value

    dumped = {key: relative(value) for key, value in info.model_dump().items()}
    dumped["extra"] = {key: relative(value) for key, value in info.extra.items()}
    return dumped


def _remote(monkeypatch, tree: dict[str, str], client_cls=StubS3Client):
    """An S3 root over ``tree`` and the client serving it."""
    client = client_cls({f"{S3_KEY_PREFIX}{rel}": body for rel, body in _bytes(tree).items()})
    install_s3_client(monkeypatch, client)
    return data_root_for(S3_ROOT, s3_cli_config()), client


def _fetched(client: StubS3Client) -> set[str]:
    return {key[len(S3_KEY_PREFIX) :] for key in client.get_object_calls}


@pytest.fixture
def shipped_templates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A synthetic ``projects/`` root shipping nf-core/ampliseq 2.14.0 and 2.16.0."""
    projects = tmp_path / "projects"
    for version in ("2.14.0", "2.16.0"):
        version_dir = projects / "nf-core" / "ampliseq" / version
        version_dir.mkdir(parents=True)
        (version_dir / "template.yaml").write_text(
            f"template:\n  template_id: nf-core/ampliseq/{version}\n  version: '{version}'\n"
        )
    monkeypatch.setattr(templates_module, "_projects_roots", lambda: [projects])
    return projects


class TestStagedCopyReadsLikeTheOriginal:
    @pytest.mark.parametrize(
        ("tree", "engine", "pipeline"),
        [
            (FLAT_RUN, "nextflow", "nf-core/ampliseq"),
            (SEQUENCING_RUNS, "nextflow", "nf-core/viralrecon"),
            (CHECKOUT, "nextflow", "nf-core/ampliseq"),
            (LEGACY_VERSIONS, "nextflow", None),
            (EMPTY_PIPELINE_INFO, None, None),
            (SNAKEMAKE, "snakemake", "my-lab/variant-calling"),
            (SNAKEMAKE_UNNAMED, "snakemake", FOLDER),
            (PLAIN, None, None),
        ],
        ids=[
            "flat",
            "sequencing-runs",
            "checkout",
            "legacy-versions",
            "empty-pipeline-info",
            "snakemake",
            "snakemake-unnamed",
            "plain",
        ],
    )
    def test_a_remote_run_folder_reads_like_the_same_tree_on_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tree, engine, pipeline
    ) -> None:
        local = write_tree(tmp_path / FOLDER, _bytes(tree))
        root, _client = _remote(monkeypatch, tree)

        expected = read_run_info(local)
        staged = read_run_info_for_root(root)

        assert _comparable(staged, S3_ROOT) == _comparable(expected, str(local))
        assert (staged.engine if staged else None) == engine
        assert (staged.pipeline_name if staged else None) == pipeline

    def test_paths_in_the_answer_are_locations_under_the_root(self, monkeypatch) -> None:
        root, _client = _remote(monkeypatch, FLAT_RUN)

        info = read_run_info_for_root(root)

        assert info is not None
        assert info.software_versions_path == f"{S3_ROOT}/pipeline_info/software_versions.yml"
        assert info.params_json_path == (f"{S3_ROOT}/pipeline_info/params_2026-01-02_10-00-00.json")
        assert info.execution_report_path == (
            f"{S3_ROOT}/pipeline_info/execution_report_2026-01-02.html"
        )
        assert info.run_name == "resumed"


class TestStagingIsBounded:
    def test_only_the_files_the_readers_open_are_fetched(self, monkeypatch) -> None:
        root, client = _remote(monkeypatch, FLAT_RUN)

        read_run_info_for_root(root)

        # Not the report, trace or DAG (markers), nor the data.
        assert _fetched(client) == {
            "pipeline_info/software_versions.yml",
            "pipeline_info/params_2026-01-01_10-00-00.json",
            "pipeline_info/params_2026-01-02_10-00-00.json",
        }

    def test_a_file_over_the_size_limit_is_not_fetched(self, monkeypatch) -> None:
        root, client = _remote(monkeypatch, FLAT_RUN)
        # Below the versions YAML, above each params file.
        monkeypatch.setattr(run_detection, "MAX_FILE_BYTES", 50)

        info = read_run_info_for_root(root)

        assert "pipeline_info/software_versions.yml" not in _fetched(client)
        assert info is not None and info.pipeline_name is None
        assert info.run_name == "resumed"

    def test_the_total_limit_stops_fetching(self, monkeypatch) -> None:
        root, client = _remote(monkeypatch, FLAT_RUN)
        monkeypatch.setattr(run_detection, "MAX_TOTAL_BYTES", 30)

        read_run_info_for_root(root)

        # Path order: the first params file (21 bytes) fits, the second does not.
        assert _fetched(client) == {"pipeline_info/params_2026-01-01_10-00-00.json"}

    def test_the_entry_limit_keeps_the_first_runs_whole(self, monkeypatch) -> None:
        root, client = _remote(monkeypatch, SEQUENCING_RUNS)
        # run_a's pipeline_info, trace, versions and params, in path order.
        monkeypatch.setattr(run_detection, "MAX_STAGED_ENTRIES", 4)

        info = read_run_info_for_root(root)

        assert info is not None and info.pipeline_name == "nf-core/viralrecon"
        assert info.run_name == "a"
        assert info.extra["run_subdirs_scanned"] == 1
        assert info.tools_executed == {"fastqc"}
        assert not any(rel.startswith("run_b/") for rel in _fetched(client))

    def test_a_key_that_climbs_out_of_the_root_is_never_fetched(self, monkeypatch) -> None:
        tree = {**FLAT_RUN, "../../escape/software_versions.yml": "FASTQC:\n  fastqc: 1\n"}
        root, client = _remote(monkeypatch, tree)

        info = read_run_info_for_root(root)

        assert "../../escape/software_versions.yml" not in _fetched(client)
        assert info is not None and info.pipeline_name == "nf-core/ampliseq"


class TestStoreErrors:
    def test_a_refused_read_propagates_unchanged(self, monkeypatch) -> None:
        class _Denied(StubS3Client):
            def get_object(self, Bucket, Key):  # noqa: N803
                raise s3_client_error("AccessDenied", 403, "GetObject")

        root, _client = _remote(monkeypatch, FLAT_RUN, _Denied)

        with pytest.raises(S3AccessFailed):
            detect_template_for_root(root)

    def test_a_file_gone_since_the_listing_is_simply_absent(self, monkeypatch) -> None:
        class _Vanished(StubS3Client):
            def get_object(self, Bucket, Key):  # noqa: N803
                raise s3_client_error("NoSuchKey", 404, "GetObject")

        tree = {
            "pipeline_info/software_versions.yml": FLAT_RUN["pipeline_info/software_versions.yml"]
        }
        root, _client = _remote(monkeypatch, tree, _Vanished)

        assert detect_template_for_root(root) == (None, None)


class TestTemplateSelection:
    def test_an_s3_run_folder_selects_its_template(self, monkeypatch, shipped_templates) -> None:
        install_megatest_listing(monkeypatch, _bytes(FLAT_RUN))
        root = data_root_for(S3_ROOT, s3_cli_config())

        template_id, info = detect_template_for_root(root)

        assert template_id == "nf-core/ampliseq/2.16.0"
        assert info is not None and info.pipeline_version == "2.16.0"

    def test_a_local_root_answers_like_the_run_dir_detection(
        self, tmp_path: Path, monkeypatch, shipped_templates
    ) -> None:
        run = write_tree(tmp_path / "run", _bytes(FLAT_RUN))

        def _no_staging(*_args):
            raise AssertionError("a local root is read in place")

        monkeypatch.setattr(run_detection, "_stage", _no_staging)

        assert detect_template_for_root(LocalDataRoot(str(run))) == (
            detect_template_from_run_dir(run)
        )

    def test_an_unrecognised_folder_selects_nothing(self, monkeypatch) -> None:
        root, _client = _remote(monkeypatch, PLAIN)

        assert detect_template_for_root(root) == (None, None)


class TestIngestDetectsAnS3RunFolder:
    """`depictio ingest s3://...` with no --template picks the template, as for a folder."""

    @pytest.fixture
    def cli_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """The CLI config `ingest` loads, from a file that exists, and every root built."""
        config = s3_cli_config()
        config_file = tmp_path / "CLI.yaml"
        config_file.write_text("stub: true\n")
        monkeypatch.setattr(run_module, "load_depictio_config", lambda **_kwargs: config)
        monkeypatch.setattr(run_module, "cli_config_file", lambda *_args: str(config_file))
        built = []
        real = data_root_module.as_data_root

        def as_data_root(value, CLI_config=None):  # noqa: N803 - the real spelling
            built.append(CLI_config)
            return real(value, CLI_config)

        monkeypatch.setattr(data_root_module, "as_data_root", as_data_root)
        return config, built

    def test_the_template_is_detected_from_the_prefix(self, monkeypatch, cli_config) -> None:
        config, built = cli_config
        tree = {
            **MEGATEST_TREE,
            "pipeline_info/software_versions.yml": _versions(
                "nf-core/ampliseq", "v2.16.0-g3d5c7e5"
            ).encode(),
        }
        install_megatest_listing(monkeypatch, tree)

        result = CliRunner().invoke(app, ["ingest", S3_ROOT, "--dry-run"])

        output = " ".join(result.output.split())
        assert result.exit_code == 0, result.output
        assert "Detected nf-core/ampliseq 2.16.0 (nextflow, 1 tool(s))" in output
        assert "Auto-selected template: nf-core/ampliseq/2.16.0" in output
        # Detection read the prefix with the config the rest of the command uses.
        assert built and built[0] is config

    def test_an_unreadable_prefix_without_a_template_says_so(self, monkeypatch, cli_config) -> None:
        install_s3_client(monkeypatch, FailingS3Client("AccessDenied", 403))

        result = CliRunner().invoke(app, ["ingest", S3_ROOT, "--dry-run"])

        output = " ".join(result.output.split())
        assert result.exit_code == 1, result.output
        assert "Could not read DATA_DIR:" in output
        assert "Say which project to ingest" not in output
