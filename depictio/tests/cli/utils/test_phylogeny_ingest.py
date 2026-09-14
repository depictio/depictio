"""Phylogeny data collections at ingest: where the tree comes from, where it goes.

The scan registers a tree under the path the CLI saw, which a containerised or
remote backend cannot read, so ingest copies it to S3 under a fixed key the
Newick endpoint reads first. That key sits outside the ObjectId-shaped prefixes
orphan cleanup deletes, so the tests pin its shape as well as the upload.

One class reads the shipped ampliseq 2.18.0 template, because the precedence
between its tree-repointing rules is the rule order in that file.

No S3/MinIO or API is needed: the file listing and boto3 are mocked.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from depictio.cli.cli.utils import deltatables
from depictio.cli.cli.utils.deltatables import (
    client_aggregate_data,
    process_phylogeny_data_collection,
)
from depictio.cli.cli.utils.templates import _apply_conditionals, _load_yaml
from depictio.models.models.cli import CLIConfig
from depictio.models.models.data_collections_types.phylogeny import phylogeny_s3_key
from depictio.models.models.templates import TemplateMetadata
from depictio.recipes import PROJECTS_DIR

DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"
BUCKET = "depictio-bucket"


@pytest.fixture
def cli_config() -> CLIConfig:
    return CLIConfig(  # type: ignore[call-arg]
        user={
            "email": "test@example.com",
            "is_admin": False,
            "id": "507f1f77bcf86cd799439011",
            "token": {
                "user_id": "507f1f77bcf86cd799439011",
                "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test",
                "refresh_token": "refresh-token-example",
                "token_type": "bearer",
                "token_lifetime": "short-lived",
                "expire_datetime": "2025-12-31T23:59:59",
                "refresh_expire_datetime": "2025-12-31T23:59:59",
                "name": "test_token",
                "created_at": "2025-06-30T18:00:00",
                "logged_in": False,
            },
        },
        api_base_url="https://api.depictio.dev",
        s3_storage={
            "service_name": "minio",
            "service_port": 9000,
            "external_host": "localhost",
            "external_port": 9000,
            "external_protocol": "http",
            "root_user": "minio",
            "root_password": "minio123",
            "bucket": BUCKET,
        },
    )


@pytest.fixture
def s3_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock()
    monkeypatch.setattr("boto3.client", MagicMock(return_value=client))
    return client


def _dc(dc_type: str = "phylogeny") -> SimpleNamespace:
    return SimpleNamespace(
        id=DC_ID,
        data_collection_tag="phylogenetic_tree_canonical",
        config=SimpleNamespace(type=dc_type),
    )


def _registered(monkeypatch: pytest.MonkeyPatch, location: str) -> None:
    monkeypatch.setattr(
        deltatables,
        "fetch_file_data",
        lambda dc_id, CLI_config: [SimpleNamespace(file_location=location)],
    )


class TestUpload:
    def test_local_tree_is_uploaded_under_the_phylogeny_prefix(
        self, tmp_path, monkeypatch, cli_config, s3_client
    ):
        tree = tmp_path / "tree.nwk"
        tree.write_text("(a,b);")
        _registered(monkeypatch, str(tree))

        result = process_phylogeny_data_collection(_dc(), cli_config)

        assert result["result"] == "success"
        s3_client.upload_file.assert_called_once_with(
            str(tree), BUCKET, f"phylogeny/{DC_ID}/tree.nwk"
        )

    def test_key_is_not_an_objectid_prefix(self):
        """Orphan cleanup deletes 24-hex top-level prefixes with no deltatable document."""
        assert phylogeny_s3_key(DC_ID).split("/")[0] == "phylogeny"

    def test_tree_already_on_s3_is_not_uploaded(self, monkeypatch, cli_config, s3_client):
        _registered(monkeypatch, f"s3://{BUCKET}/elsewhere/tree.nwk")

        result = process_phylogeny_data_collection(_dc(), cli_config)

        assert result["result"] == "success"
        s3_client.upload_file.assert_not_called()

    def test_upload_failure_is_an_error_result(self, tmp_path, monkeypatch, cli_config, s3_client):
        tree = tmp_path / "tree.nwk"
        tree.write_text("(a,b);")
        _registered(monkeypatch, str(tree))
        s3_client.upload_file.side_effect = RuntimeError("AccessDenied")

        result = process_phylogeny_data_collection(_dc(), cli_config)

        assert result["result"] == "error"
        assert "AccessDenied" in result["message"]

    def test_no_registered_file_is_an_error_result(self, monkeypatch, cli_config, s3_client):
        def _no_files(dc_id, CLI_config):
            raise Exception(f"No files found for Data Collection {dc_id}.")

        monkeypatch.setattr(deltatables, "fetch_file_data", _no_files)

        result = process_phylogeny_data_collection(_dc(), cli_config)

        assert result["result"] == "error"
        s3_client.upload_file.assert_not_called()


class TestAmpliseqTreeRoutes:
    """The shipped ampliseq template decides which Newick the tree DC scans.

    Overrides are last-write-wins per tag, so the rule order in the template is
    the precedence: the pplace graft replaces the QIIME2 default, and a user's
    explicit TREE_FILE replaces both.
    """

    TEMPLATE = PROJECTS_DIR / "nf-core" / "ampliseq" / "2.18.0" / "template.yaml"
    DEFAULT = "/run/qiime2/phylogenetic_tree/tree.nwk"

    def _tree_filename(self, variables: dict[str, str]) -> str:
        metadata = TemplateMetadata(**_load_yaml(str(self.TEMPLATE))["template"])
        config = {
            "workflows": [
                {
                    "name": "ampliseq",
                    "data_collections": [
                        {
                            "data_collection_tag": "phylogenetic_tree_canonical",
                            "config": {"scan": {"scan_parameters": {"filename": self.DEFAULT}}},
                        }
                    ],
                }
            ],
            "links": [],
        }
        result, _, _ = _apply_conditionals(
            config, metadata.conditional, set(variables), self.TEMPLATE.parent, variables
        )
        (dc,) = result["workflows"][0]["data_collections"]
        return dc["config"]["scan"]["scan_parameters"]["filename"]

    def test_default_is_the_qiime2_tree(self):
        assert self._tree_filename({"DATA_ROOT": "/run"}) == self.DEFAULT

    def test_pplace_graft_repoints_the_tree(self):
        graft = "/run/pplace/run.graft.run.epa_result.newick"

        assert self._tree_filename({"DATA_ROOT": "/run", "PPLACE_TREE_FILE": graft}) == graft

    def test_explicit_tree_file_wins_over_the_graft(self):
        variables = {
            "DATA_ROOT": "/run",
            "PPLACE_TREE_FILE": "/run/pplace/run.graft.run.epa_result.newick",
            "TREE_FILE": "/pruned/tree.nwk",
        }

        assert self._tree_filename(variables) == "/pruned/tree.nwk"


class TestAggregateRouting:
    def test_phylogeny_dc_goes_through_the_upload(self, monkeypatch, cli_config):
        """Previously a short-circuit returned success without touching the tree."""
        calls = []
        monkeypatch.setattr(
            deltatables,
            "process_phylogeny_data_collection",
            lambda dc, cfg, overwrite: calls.append(overwrite) or {"result": "success"},
        )

        client_aggregate_data(_dc(), cli_config, {"overwrite": True})  # type: ignore[arg-type]

        assert calls == [True]
