"""Guard-rail tests for `depictio run` option combinations and its dry run.

The full run pipeline needs a live stack; these only prove the CLI rejects
inconsistent flag combinations before doing any work, accepts a remote
`--data-root`, and reports what that root would yield under `--dry-run`.
"""

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from depictio.cli.cli.commands import run as run_module
from depictio.cli.cli.utils import rich_utils
from depictio.cli.cli.utils.templates import RunPreview
from depictio.cli.depictio_cli import app

# The S3 listing stub is shared with the templates tests rather than rewritten:
# one fixture tree, one definition of what a megatest prefix looks like.
from depictio.tests.cli.utils.test_templates import (
    MEGATEST_TREE,
    S3_ROOT,
    install_s3_listing,
    s3_cli_config,
    write_tree,
)

runner = CliRunner()


def test_manifest_requires_template():
    result = runner.invoke(app, ["run", "--manifest", "https://example.org/m.json"])
    assert result.exit_code == 1
    assert "--manifest requires --template" in result.output


def test_manifest_and_data_root_are_exclusive(tmp_path):
    result = runner.invoke(
        app,
        [
            "run",
            "--template",
            "generic/manifest-tables/1",
            "--manifest",
            "https://example.org/m.json",
            "--data-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_template_requires_data_root_or_manifest():
    result = runner.invoke(app, ["run", "--template", "generic/manifest-tables/1"])
    assert result.exit_code == 1
    assert "--data-root (or --manifest, or --bind)" in result.output


def test_template_accepts_bind_instead_of_data_root():
    """--bind names each DC's location itself, so it satisfies the same
    requirement as --data-root / --manifest and must clear this guard."""
    result = runner.invoke(
        app,
        [
            "run",
            "--template",
            "generic/manifest-tables/1",
            "--bind",
            "samples=s3://bucket/run42/*.samples.csv",
        ],
    )
    assert "is required when using --template" not in result.output


def test_ingestion_summary_covers_url_and_manifest_scan_modes():
    """The monitoring summary must surface the source URL for url/manifest DCs,
    not fall through to a None pattern like unknown modes do."""
    from depictio.cli.cli.commands.run import _ingestion_data_collections
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
        Scan,
        ScanManifest,
        ScanURL,
    )
    from depictio.models.models.data_collections_types.table import DCTableConfig
    from depictio.models.models.projects import Project
    from depictio.models.models.users import Permission, UserBase
    from depictio.models.models.workflows import (
        Workflow,
        WorkflowConfig,
        WorkflowDataLocation,
        WorkflowEngine,
    )

    def _dc(tag: str, scan: Scan) -> DataCollection:
        return DataCollection(
            data_collection_tag=tag,
            config=DataCollectionConfig(
                type="table",
                metatype="metadata",
                scan=scan,
                dc_specific_properties=DCTableConfig(format="csv"),
            ),
        )

    project = Project(
        name="summary-test",
        permissions=Permission(owners=[UserBase(email="owner@example.com")]),
        workflows=[
            Workflow(
                name="wf",
                engine=WorkflowEngine(name="python"),
                config=WorkflowConfig(),
                data_location=WorkflowDataLocation(
                    structure="flat", locations=["https://data.example.org"]
                ),
                data_collections=[
                    _dc(
                        "by_url",
                        Scan(
                            mode="url",
                            scan_parameters=ScanURL(url="https://data.example.org/t.parquet"),
                        ),
                    ),
                    _dc(
                        "by_manifest",
                        Scan(
                            mode="manifest",
                            scan_parameters=ScanManifest(
                                manifest_url="https://data.example.org/manifest.json",
                                manifest_type="samples",
                            ),
                        ),
                    ),
                ],
            )
        ],
    )

    summary = {row["tag"]: row for row in _ingestion_data_collections(project)}
    assert summary["by_url"]["scan_mode"] == "url"
    assert summary["by_url"]["scan_pattern"] == "https://data.example.org/t.parquet"
    assert summary["by_manifest"]["scan_mode"] == "manifest"
    assert summary["by_manifest"]["scan_pattern"] == "https://data.example.org/manifest.json"


def test_local_manifest_must_exist():
    result = runner.invoke(
        app,
        [
            "run",
            "--template",
            "generic/manifest-tables/1",
            "--manifest",
            "/nonexistent/manifest.json",
            "--skip-server-check",
        ],
    )
    assert result.exit_code == 1
    assert "does not exist" in result.output


# ---------------------------------------------------------------------------
# Remote data roots and the dry-run preview
# ---------------------------------------------------------------------------
#
# A `--data-root` may be an `s3://` prefix, and `--dry-run` has to say what that
# root would actually yield instead of reporting success for steps it skipped.
# The S3 listing is the shared stub from the templates tests: no network, and
# the key list is the whole fixture.

TEMPLATE = "nf-core/ampliseq/2.16.0"


def _flat(text: str) -> str:
    """Text with all whitespace removed.

    Rich lays the preview out for the terminal it thinks it has, so an
    assertion on a cell's content must not depend on where it wrapped.
    """
    return "".join(text.split())


@pytest.fixture
def wide_console(monkeypatch):
    """Render the preview wide enough that no cell folds mid-path."""
    monkeypatch.setattr(rich_utils.console, "_width", 200)


@pytest.fixture
def stub_cli_config(monkeypatch):
    """The config `run` loads before step 0, without touching ~/.depictio."""
    config = s3_cli_config()
    monkeypatch.setattr(run_module, "load_depictio_config", lambda **_kwargs: config)
    return config


def _fake_resolve_template(**kwargs):
    """A minimal stand-in for the resolver: no template files, no data root."""
    return (
        {"name": "stub-project", "workflows": []},
        SimpleNamespace(template_id="stub/template/1"),
        SimpleNamespace(template_id="stub/template/1", template_version="1", data_root="x"),
        [],
        {},
    )


def test_remote_data_root_clears_the_preflight_guard(monkeypatch, stub_cli_config, wide_console):
    """An `s3://` root has nothing to stat: the directory check must not run."""
    install_s3_listing(monkeypatch, MEGATEST_TREE)
    result = runner.invoke(
        app, ["run", "--template", TEMPLATE, "--data-root", S3_ROOT, "--dry-run"]
    )
    assert "does not exist or is not a directory" not in result.output
    assert result.exit_code == 0, result.output
    assert S3_ROOT in _flat(result.output)


def test_local_data_root_that_does_not_exist_still_fails(stub_cli_config):
    """The typo'd local path keeps failing with the message it always had."""
    result = runner.invoke(
        app, ["run", "--template", TEMPLATE, "--data-root", "/nonexistent/data", "--dry-run"]
    )
    assert result.exit_code == 1
    assert _flat("--data-root does not exist or is not a directory: /nonexistent/data") in _flat(
        result.output
    )


def test_cli_config_reaches_the_resolver_and_the_preview(monkeypatch, tmp_path, stub_cli_config):
    """Without it a remote root can only read an allowlisted public bucket, so
    the config has to be loaded before step 0, not after it."""
    from depictio.cli.cli.utils import templates as templates_module

    seen: dict[str, object] = {}

    def fake_resolve(**kwargs):
        seen["resolve"] = kwargs.get("CLI_config")
        return _fake_resolve_template(**kwargs)

    def fake_preview(**kwargs):
        seen["preview"] = kwargs.get("CLI_config")
        return RunPreview(
            template_id="stub/template/1",
            data_root=str(tmp_path),
            project_name="stub-project",
            resolved_variables={},
            detected_runs=[],
            data_collections=[],
        )

    monkeypatch.setattr(templates_module, "resolve_template", fake_resolve)
    monkeypatch.setattr(templates_module, "preview_data_root", fake_preview)

    result = runner.invoke(
        app, ["run", "--template", "stub/template/1", "--data-root", str(tmp_path), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert seen["resolve"] is stub_cli_config
    assert seen["preview"] is stub_cli_config


def test_dry_run_names_the_sources_a_collection_could_not_find(
    monkeypatch, stub_cli_config, wide_console
):
    """A count of zero does not tell you your prefix is one level too high; the
    paths it looked for do."""
    install_s3_listing(monkeypatch, MEGATEST_TREE)
    result = runner.invoke(
        app, ["run", "--template", TEMPLATE, "--data-root", S3_ROOT, "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    flat = _flat(result.output)
    # Header: what would run, and the params-derived flag that gates the DCs.
    assert _flat(f"Template: {TEMPLATE}") in flat
    assert "SKIP_ANCOM" in flat
    assert "GROUP_COL" in flat
    # A row per data collection, and the sources the missing one wanted.
    assert "multiqc_data" in flat
    assert _flat("Sources not found under this data root") in flat
    assert _flat("alpha_rarefaction: qiime2/alpha-rarefaction/faith_pd.csv") in flat
    assert "missingsources" in flat  # the closing summary line


def test_preview_failure_surfaces_as_a_template_resolution_failure(
    monkeypatch, tmp_path, stub_cli_config
):
    """A missing required variable must not be swallowed by the preview."""
    from depictio.cli.cli.utils import templates as templates_module

    def boom(**_kwargs):
        raise ValueError("Missing required template variable: METADATA_FILE")

    monkeypatch.setattr(templates_module, "resolve_template", _fake_resolve_template)
    monkeypatch.setattr(templates_module, "preview_data_root", boom)

    result = runner.invoke(
        app, ["run", "--template", "stub/template/1", "--data-root", str(tmp_path), "--dry-run"]
    )
    assert result.exit_code == 1
    assert _flat(
        "Template resolution failed: Missing required template variable: METADATA_FILE"
    ) in _flat(result.output)


def test_a_local_dry_run_previews_the_same_way(tmp_path, stub_cli_config, wide_console):
    """Same code path, and just as useful when the data is on disk."""
    base = write_tree(tmp_path / "results", MEGATEST_TREE)
    result = runner.invoke(
        app, ["run", "--template", TEMPLATE, "--data-root", str(base), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    flat = _flat(result.output)
    assert _flat(f"Data root: {base}") in flat
    assert "multiqc_data" in flat
    assert _flat("alpha_rarefaction: qiime2/alpha-rarefaction/faith_pd.csv") in flat
