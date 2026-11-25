"""Phylogeny data collections at ingest: where the tree comes from, where it goes.

The scan registers a tree under the path the CLI saw, which a containerised or
remote backend cannot read, so ingest copies it to S3 under a fixed key the
Newick endpoint reads first. That key sits outside the ObjectId-shaped prefixes
orphan cleanup deletes, so the tests pin its shape as well as the upload.

One class reads the shipped ampliseq 2.18.0 template, because the precedence
between its tree-repointing rules is the rule order in that file.

No S3/MinIO or API is needed: the file listing and boto3 are mocked.
"""

import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import polars as pl
import pytest

from depictio.cli.cli.utils import deltatables
from depictio.cli.cli.utils.deltatables import (
    client_aggregate_data,
    process_phylogeny_data_collection,
)
from depictio.cli.cli.utils.newick import parse_newick
from depictio.cli.cli.utils.templates import _apply_conditionals, _load_yaml
from depictio.models.models.cli import CLIConfig
from depictio.models.models.data_collections_types.phylogeny import (
    DCPhylogenyConfig,
    phylogeny_s3_key,
)
from depictio.models.models.templates import TemplateMetadata
from depictio.models.s3_access import S3AccessRefused
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


def _dc(dc_type: str = "phylogeny", **properties) -> SimpleNamespace:
    config = SimpleNamespace(type=dc_type)
    if properties:
        config.dc_specific_properties = DCPhylogenyConfig(**properties)
    return SimpleNamespace(
        id=DC_ID,
        data_collection_tag="phylogenetic_tree_canonical",
        config=config,
    )


def _registered(monkeypatch: pytest.MonkeyPatch, location: str) -> None:
    monkeypatch.setattr(
        deltatables,
        "fetch_file_data",
        lambda dc_id, CLI_config: [SimpleNamespace(file_location=location)],
    )


@pytest.fixture
def cli_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI reads the user's own files; the suite otherwise runs as the server."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "cli")


def _source_on(monkeypatch: pytest.MonkeyPatch, body: bytes = b"(a,b);") -> MagicMock:
    """Stand in for the remote-data resolution of an external ``s3://`` tree."""
    source = SimpleNamespace(bucket="runs", key="run42/tree.nwk", client=MagicMock())
    source.client.return_value.get_object.return_value = {"Body": io.BytesIO(body)}
    resolve = MagicMock(return_value=source)
    monkeypatch.setattr(deltatables, "s3_read_target_in_region", resolve)
    return source.client.return_value


@pytest.mark.usefixtures("cli_context")
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

    def test_tree_on_another_bucket_is_copied_under_the_phylogeny_prefix(
        self, monkeypatch, cli_config, s3_client
    ):
        """Stored as is, the external URL was later read with the instance credentials (#1170)."""
        _registered(monkeypatch, "s3://runs/run42/tree.nwk")
        source = _source_on(monkeypatch)

        result = process_phylogeny_data_collection(_dc(), cli_config)

        assert result["result"] == "success"
        deltatables.s3_read_target_in_region.assert_called_once_with(
            "s3://runs/run42/tree.nwk", cli_config
        )
        source.get_object.assert_called_once_with(Bucket="runs", Key="run42/tree.nwk")
        s3_client.put_object.assert_called_once_with(
            Bucket=BUCKET, Key=f"phylogeny/{DC_ID}/tree.nwk", Body=b"(a,b);"
        )

    def test_refused_s3_source_is_an_error_result(self, monkeypatch, cli_config, s3_client):
        _registered(monkeypatch, "s3://runs/run42/tree.nwk")
        monkeypatch.setattr(
            deltatables,
            "s3_read_target_in_region",
            MagicMock(side_effect=S3AccessRefused("s3://runs/run42/tree.nwk cannot be read.")),
        )

        result = process_phylogeny_data_collection(_dc(), cli_config)

        assert result["result"] == "error"
        s3_client.put_object.assert_not_called()

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


class TestServerContext:
    """The ingest worker reads a path a project's configuration names: confined (#1170)."""

    def test_a_path_outside_the_readable_folders_is_refused(
        self, tmp_path, monkeypatch, cli_config, s3_client
    ):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
        # The server's own temp dir is readable by design (uploads land there);
        # pytest's tmp_path sits inside it, so the server gets its own to keep
        # the tree below genuinely outside every readable folder.
        server_tmp = tmp_path / "server-tmp"
        server_tmp.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(server_tmp))
        tree = tmp_path / "tree.nwk"
        tree.write_text("(a,b);")
        _registered(monkeypatch, str(tree))

        result = process_phylogeny_data_collection(_dc(), cli_config)

        assert result["result"] == "error"
        assert str(tree) not in result["message"]
        s3_client.upload_file.assert_not_called()

    def test_a_bundled_reference_tree_is_uploaded(self, monkeypatch, cli_config, s3_client):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
        tree = PROJECTS_DIR / "init" / "advanced_viz_showcase" / "data" / "bacterial_tree.nwk"
        _registered(monkeypatch, str(tree))

        result = process_phylogeny_data_collection(_dc(), cli_config)

        assert result["result"] == "success"
        s3_client.upload_file.assert_called_once_with(
            str(tree), BUCKET, f"phylogeny/{DC_ID}/tree.nwk"
        )


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

    def test_tree_dc_prunes_to_its_metadata_dc_declared_before_it(self):
        """The prune reads the metadata DC's table: it must be ingested first."""
        config = _load_yaml(str(self.TEMPLATE))
        (workflow,) = config["workflows"]
        tags = [dc["data_collection_tag"] for dc in workflow["data_collections"]]
        tree = workflow["data_collections"][tags.index("phylogenetic_tree_canonical")]
        props = DCPhylogenyConfig(**tree["config"]["dc_specific_properties"])

        assert props.max_tips == 3000
        assert tags.index(props.metadata_dc_tag) < tags.index("phylogenetic_tree_canonical")

    def test_explicit_tree_file_wins_over_the_graft(self):
        variables = {
            "DATA_ROOT": "/run",
            "PPLACE_TREE_FILE": "/run/pplace/run.graft.run.epa_result.newick",
            "TREE_FILE": "/pruned/tree.nwk",
        }

        assert self._tree_filename(variables) == "/pruned/tree.nwk"


META_ID = "646b0f3c1e4a2d7f8e5b8caa"
BIG_TREE = "((a:1,b:1):1,(c:1,(d:1,e:1):1):1);"


def _workflow() -> SimpleNamespace:
    meta = SimpleNamespace(id=META_ID, data_collection_tag="tree_metadata")
    return SimpleNamespace(data_collections=[meta])


def _metadata_table(monkeypatch: pytest.MonkeyPatch, taxa: list[str] | None) -> list[str]:
    """Stand in for the metadata DC's Delta table; returns the paths read."""
    read: list[str] = []

    def fake_read(path, storage_options):
        read.append(path)
        if taxa is None:
            return {"result": "error", "message": "no table"}
        return {"result": "success", "data": pl.DataFrame({"taxon": taxa})}

    monkeypatch.setattr(deltatables, "read_delta_table", fake_read)
    return read


def _stored_tips(s3_client: MagicMock) -> set[str]:
    body = s3_client.put_object.call_args.kwargs["Body"]
    return set(parse_newick(body.decode())[0].tips())


@pytest.mark.usefixtures("cli_context")
class TestPruneAtIngest:
    """A tree over ``max_tips`` is stored pruned to the taxa of its metadata DC."""

    def _tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str = BIG_TREE) -> Path:
        tree = tmp_path / "tree.nwk"
        tree.write_text(text)
        _registered(monkeypatch, str(tree))
        return tree

    def test_large_tree_is_pruned_to_the_metadata_taxa(
        self, tmp_path, monkeypatch, cli_config, s3_client
    ):
        self._tree(tmp_path, monkeypatch)
        read = _metadata_table(monkeypatch, ["a", "d", "e"])
        dc = _dc(max_tips=3, metadata_dc_tag="tree_metadata")

        result = process_phylogeny_data_collection(dc, cli_config, workflow=_workflow())

        assert result["result"] == "success"
        assert read == [f"s3://{BUCKET}/{META_ID}"]
        s3_client.upload_file.assert_not_called()
        assert s3_client.put_object.call_args.kwargs["Key"] == f"phylogeny/{DC_ID}/tree.nwk"
        assert _stored_tips(s3_client) == {"a", "d", "e"}

    def test_tree_at_the_threshold_is_stored_as_written(
        self, tmp_path, monkeypatch, cli_config, s3_client
    ):
        tree = self._tree(tmp_path, monkeypatch)
        read = _metadata_table(monkeypatch, ["a"])
        dc = _dc(max_tips=5, metadata_dc_tag="tree_metadata")

        process_phylogeny_data_collection(dc, cli_config, workflow=_workflow())

        assert read == []  # the metadata is not even read
        s3_client.upload_file.assert_called_once_with(
            str(tree), BUCKET, f"phylogeny/{DC_ID}/tree.nwk"
        )

    def test_no_max_tips_never_prunes(self, tmp_path, monkeypatch, cli_config, s3_client):
        tree = self._tree(tmp_path, monkeypatch)
        read = _metadata_table(monkeypatch, ["a"])

        process_phylogeny_data_collection(
            _dc(metadata_dc_tag="tree_metadata"), cli_config, workflow=_workflow()
        )

        assert read == []
        s3_client.upload_file.assert_called_once_with(
            str(tree), BUCKET, f"phylogeny/{DC_ID}/tree.nwk"
        )

    @pytest.mark.parametrize(
        ("taxa", "props"),
        [
            (None, {"metadata_dc_tag": "tree_metadata"}),  # metadata table unreadable
            (["zzz"], {"metadata_dc_tag": "tree_metadata"}),  # no label matches
            (["a"], {"metadata_dc_tag": "not_in_workflow"}),
            (["a"], {"metadata_dc_tag": None}),
        ],
    )
    def test_without_usable_metadata_the_tree_is_stored_unpruned(
        self, tmp_path, monkeypatch, cli_config, s3_client, taxa, props
    ):
        """The old behaviour, with a warning, rather than a failed ingest."""
        tree = self._tree(tmp_path, monkeypatch)
        _metadata_table(monkeypatch, taxa)

        result = process_phylogeny_data_collection(
            _dc(max_tips=2, **props), cli_config, workflow=_workflow()
        )

        assert result["result"] == "success"
        s3_client.upload_file.assert_called_once_with(
            str(tree), BUCKET, f"phylogeny/{DC_ID}/tree.nwk"
        )

    def test_first_token_labels_match_on_their_first_token(
        self, tmp_path, monkeypatch, cli_config, s3_client
    ):
        self._tree(tmp_path, monkeypatch, "((a_x:1,b_y:1):1,(c_z:1,d_w:1):1);")
        _metadata_table(monkeypatch, ["a", "c"])
        dc = _dc(max_tips=2, metadata_dc_tag="tree_metadata", tip_label_strategy="first_token")

        process_phylogeny_data_collection(dc, cli_config, workflow=_workflow())

        assert _stored_tips(s3_client) == {"a_x", "c_z"}

    def test_tree_on_another_bucket_is_pruned_too(self, monkeypatch, cli_config, s3_client):
        _registered(monkeypatch, "s3://runs/run42/tree.nwk")
        _source_on(monkeypatch, BIG_TREE.encode())
        _metadata_table(monkeypatch, ["b", "c"])
        dc = _dc(max_tips=2, metadata_dc_tag="tree_metadata")

        result = process_phylogeny_data_collection(dc, cli_config, workflow=_workflow())

        assert result["result"] == "success"
        assert _stored_tips(s3_client) == {"b", "c"}


class TestAggregateRouting:
    def test_phylogeny_dc_goes_through_the_upload(self, monkeypatch, cli_config):
        """Previously a short-circuit returned success without touching the tree."""
        calls = []
        monkeypatch.setattr(
            deltatables,
            "process_phylogeny_data_collection",
            lambda dc, cfg, overwrite, workflow=None: (
                calls.append(overwrite) or {"result": "success"}
            ),
        )

        client_aggregate_data(_dc(), cli_config, {"overwrite": True})  # type: ignore[arg-type]

        assert calls == [True]

    @pytest.mark.parametrize(
        ("kind", "processor"),
        [
            ("multiqc", "process_multiqc_data_collection"),
            ("geojson", "process_geojson_data_collection"),
            ("phylogeny", "process_phylogeny_data_collection"),
            ("indexed_file", "process_indexed_file_data_collection"),
        ],
    )
    def test_a_dry_run_dispatches_nothing_that_writes(
        self, monkeypatch, cli_config, kind, processor
    ):
        """These processors write to S3 and the server as soon as they run."""
        process = MagicMock()
        monkeypatch.setattr(deltatables, processor, process)

        result = client_aggregate_data(_dc(kind), cli_config, {"dry_run": True})  # type: ignore[arg-type]

        process.assert_not_called()
        assert result["result"] == "success"
        assert f"would process this {kind} collection" in result["message"]

    def test_a_dry_run_runs_no_recipe(self, monkeypatch, cli_config):
        process = MagicMock()
        monkeypatch.setattr(deltatables, "process_recipe_data_collection", process)
        recipe = SimpleNamespace(
            id=DC_ID,
            data_collection_tag="recipe_dc",
            config=SimpleNamespace(
                type="table",
                source="transformed",
                transform=SimpleNamespace(materialized=False),
            ),
        )

        result = client_aggregate_data(recipe, cli_config, {"dry_run": True})  # type: ignore[arg-type]

        process.assert_not_called()
        assert "would process this recipe collection" in result["message"]
