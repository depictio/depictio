"""Guard-rail tests for `depictio ingest` option combinations (manifest mode).

The full run pipeline needs a live stack; these only prove the CLI rejects
inconsistent flag combinations before doing any work.
"""

from typer.testing import CliRunner

from depictio.cli.depictio_cli import app

runner = CliRunner()


def test_manifest_requires_template():
    result = runner.invoke(app, ["ingest", "--manifest", "https://example.org/m.json"])
    assert result.exit_code == 1
    assert "--manifest needs --template" in result.output


def test_manifest_and_data_root_are_exclusive(tmp_path):
    result = runner.invoke(
        app,
        [
            "ingest",
            "--template",
            "generic/manifest-tables/1",
            "--manifest",
            "https://example.org/m.json",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert "Give DATA_DIR or --manifest, not both" in result.output


def test_template_requires_data_root_or_manifest():
    result = runner.invoke(app, ["ingest", "--template", "generic/manifest-tables/1"])
    assert result.exit_code == 1
    assert "(or --manifest, or --bind)" in result.output


def test_template_accepts_bind_instead_of_data_root():
    """--bind names each DC's location itself, so it satisfies the same
    requirement as DATA_DIR / --manifest and must clear this guard."""
    result = runner.invoke(
        app,
        [
            "ingest",
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
            "ingest",
            "--template",
            "generic/manifest-tables/1",
            "--manifest",
            "/nonexistent/manifest.json",
            "--skip-server-check",
        ],
    )
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_s3_manifest_refused_before_any_step():
    """It used to pass every check and fail at the scan, after the project sync."""
    result = runner.invoke(
        app,
        ["ingest", "--template", "generic/manifest-tables/1", "--manifest", "s3://b/m.json"],
    )
    assert result.exit_code == 1
    assert "serve the manifest over https" in result.output
    assert "Step 0" not in result.output


def test_http_manifest_names_the_setting_it_needs(monkeypatch):
    """Not "file does not exist": an http:// URL is not a local path."""
    monkeypatch.delenv("DEPICTIO_REMOTE_ALLOW_HTTP", raising=False)
    result = runner.invoke(
        app,
        ["ingest", "--template", "generic/manifest-tables/1", "--manifest", "http://h/m.json"],
    )
    assert result.exit_code == 1
    assert "administrator" in result.output
    assert "does not exist" not in result.output


def test_an_optional_dc_the_manifest_lists_nothing_for_is_left_out(tmp_path, monkeypatch):
    """generic/manifest-tables/1 declares `measurements` optional: a manifest
    without it must not fail its scan once the project is synced."""
    monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", str(tmp_path / "no-cli-config.yaml"))
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("id,type,url\nS1,samples,https://data.example.org/s1.csv\n")
    result = runner.invoke(
        app,
        [
            "ingest",
            "--template",
            "generic/manifest-tables/1",
            "--manifest",
            str(manifest),
            "--dry-run",
        ],
    )
    assert "Left out 1 optional data collection(s)" in result.output
    assert "measurements" in result.output
