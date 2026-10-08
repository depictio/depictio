"""Guard-rail tests for `depictio run` option combinations (manifest mode).

The full run pipeline needs a live stack; these only prove the CLI rejects
inconsistent flag combinations before doing any work.
"""

from typer.testing import CliRunner

from depictio.cli.depictio_cli import app

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
