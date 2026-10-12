"""An image collection's ``local_images_path`` is uploaded after its table, on the server.

``depictio ingest`` uploads the folder of images an image collection names;
``POST /projects/from_run`` ingests on the server, so ``_run_dc_ingest`` does the
same once the table is processed (``manifest_ingest._upload_collection_images``).
The server reads that folder from its own disk, so only under ``depictio local``
and only inside the folders it may read: every image file is checked against the
local data policy, a symlink in the folder cannot pull in another.

No network, no S3: ``upload_collection_images`` is replaced where a test is not
about its own checks.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.projects_endpoints import manifest_ingest
from depictio.cli.cli.utils import image_upload
from depictio.cli.cli.utils.image_upload import ImageUploadError
from depictio.models.models.users import UserBase
from depictio.tests.cli.s3_stubs import write_tree

NO_POLICY = "This server does not read folders on its own disk, so it cannot upload images."
BUCKET = "depictio-bucket"
FOLDER = f"s3://{BUCKET}/images/photos"


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS", raising=False)
    monkeypatch.delenv("DEPICTIO_AUTH_SINGLE_USER_MODE", raising=False)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Local folders on, ``home/`` the one root, three images in ``home/run42/images``."""
    folder = tmp_path / "home"
    write_tree(
        folder / "run42" / "images",
        {"a.png": b"x", "b.PNG": b"x", "sub/c.jpg": b"x", "notes.txt": b"not an image"},
    )
    write_tree(tmp_path / "outside", {"secret.png": b"x", "inner/other.png": b"x"})
    (folder / "depictio-local").mkdir()
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(folder))
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(folder / "depictio-local"))
    return folder


@pytest.fixture
def cli_config():
    return SimpleNamespace(s3_storage=SimpleNamespace(bucket=BUCKET))


def _image_dc(local_images_path, s3_base_folder=FOLDER, tag="photos"):
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
        Scan,
        ScanSingle,
    )
    from depictio.models.models.data_collections_types.image import DCImageConfig

    return DataCollection(
        data_collection_tag=tag,
        config=DataCollectionConfig(
            type="image",
            metatype="metadata",
            scan=Scan(mode="single", scan_parameters=ScanSingle(filename="/data/images.csv")),
            dc_specific_properties=DCImageConfig(
                format="csv",
                image_column="img",
                s3_base_folder=s3_base_folder,
                local_images_path=str(local_images_path) if local_images_path else None,
            ),
        ),
    )


def _table_dc():
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
        Scan,
        ScanSingle,
    )
    from depictio.models.models.data_collections_types.table import DCTableConfig

    return DataCollection(
        data_collection_tag="sheet",
        config=DataCollectionConfig(
            type="table",
            metatype="metadata",
            scan=Scan(mode="single", scan_parameters=ScanSingle(filename="/data/sheet.csv")),
            dc_specific_properties=DCTableConfig(format="csv"),
        ),
    )


@pytest.fixture
def upload():
    """``upload_collection_images`` replaced: nothing is put in storage."""
    with patch.object(image_upload, "upload_collection_images", return_value={"uploaded": 3}) as p:
        yield p


# ── which collections it is for ──────────────────────────────────────────────


class TestWhichCollections:
    def test_a_table_collection_has_nothing_to_upload(self, upload, cli_config):
        assert manifest_ingest._upload_collection_images(_table_dc(), cli_config) is None
        upload.assert_not_called()

    def test_an_image_collection_with_no_local_folder_has_nothing_to_upload(
        self, home, upload, cli_config
    ):
        dc = _image_dc(None)
        assert manifest_ingest._upload_collection_images(dc, cli_config) is None
        upload.assert_not_called()

    def test_an_image_collection_with_no_folder_is_not_refused_for_want_of_a_policy(
        self, upload, cli_config
    ):
        assert manifest_ingest._upload_collection_images(_image_dc(None), cli_config) is None


# ── what the server may read ─────────────────────────────────────────────────


class TestPolicy:
    def test_without_local_folders_the_server_cannot_upload_from_its_disk(
        self, tmp_path, upload, cli_config
    ):
        write_tree(tmp_path / "images", {"a.png": b"x"})
        message = manifest_ingest._upload_collection_images(
            _image_dc(tmp_path / "images"), cli_config
        )
        assert message == NO_POLICY
        upload.assert_not_called()

    def test_local_folders_are_off_in_cli_context_too(self, home, monkeypatch, upload, cli_config):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
        message = manifest_ingest._upload_collection_images(
            _image_dc(home / "run42" / "images"), cli_config
        )
        assert message == NO_POLICY

    def test_images_inside_the_allowed_folders_are_uploaded(self, home, upload, cli_config):
        dc = _image_dc(home / "run42" / "images")
        assert manifest_ingest._upload_collection_images(dc, cli_config) is None
        upload.assert_called_once_with(dc, cli_config, overwrite=False)

    def test_an_image_that_is_a_symlink_out_of_the_allowed_folders_refuses_the_folder(
        self, home, tmp_path, upload, cli_config
    ):
        images = home / "run42" / "images"
        (images / "leak.png").symlink_to(tmp_path / "outside" / "secret.png")

        message = manifest_ingest._upload_collection_images(_image_dc(images), cli_config)

        assert message == "1 image file(s) are outside the folders this server may read."
        upload.assert_not_called()

    def test_every_refused_image_is_counted(self, home, tmp_path, upload, cli_config):
        images = home / "run42" / "images"
        (images / "leak1.png").symlink_to(tmp_path / "outside" / "secret.png")
        (images / "sub" / "leak2.png").symlink_to(tmp_path / "outside" / "inner" / "other.png")

        message = manifest_ingest._upload_collection_images(_image_dc(images), cli_config)

        assert message == "2 image file(s) are outside the folders this server may read."
        upload.assert_not_called()

    def test_an_image_in_a_hidden_folder_is_refused(self, home, upload, cli_config):
        images = home / "run42" / "images"
        write_tree(images / ".cache", {"thumb.png": b"x"})

        message = manifest_ingest._upload_collection_images(_image_dc(images), cli_config)

        assert message == "1 image file(s) are outside the folders this server may read."
        upload.assert_not_called()

    def test_a_folder_that_is_itself_a_link_out_is_refused_file_by_file(
        self, home, tmp_path, upload, cli_config
    ):
        (home / "run42" / "linked").symlink_to(tmp_path / "outside", target_is_directory=True)

        message = manifest_ingest._upload_collection_images(
            _image_dc(home / "run42" / "linked"), cli_config
        )

        assert message == "2 image file(s) are outside the folders this server may read."
        upload.assert_not_called()

    def test_a_folder_outside_the_allowed_roots_is_refused(
        self, home, tmp_path, upload, cli_config
    ):
        message = manifest_ingest._upload_collection_images(
            _image_dc(tmp_path / "outside"), cli_config
        )
        assert message == "2 image file(s) are outside the folders this server may read."
        upload.assert_not_called()

    def test_files_that_are_not_images_are_not_judged(self, home, tmp_path, upload, cli_config):
        images = home / "run42" / "images"
        (images / "notes.txt").unlink()
        (images / "link.txt").symlink_to(tmp_path / "outside" / "secret.png")
        assert manifest_ingest._upload_collection_images(_image_dc(images), cli_config) is None
        upload.assert_called_once()

    def test_an_empty_folder_is_left_to_the_upload_to_report(self, home, upload, cli_config):
        empty = home / "run42" / "empty"
        empty.mkdir()
        assert manifest_ingest._upload_collection_images(_image_dc(empty), cli_config) is None
        upload.assert_called_once()


# ── what the upload itself says ──────────────────────────────────────────────


class TestUploadOutcome:
    def test_a_failed_upload_is_the_collections_failure(self, home, cli_config):
        with patch.object(
            image_upload, "upload_collection_images", side_effect=ImageUploadError("2 failed")
        ):
            message = manifest_ingest._upload_collection_images(
                _image_dc(home / "run42" / "images"), cli_config
            )
        assert message == "Image upload failed: 2 failed"

    def test_an_error_that_is_not_an_upload_error_is_not_swallowed(self, home, cli_config):
        with patch.object(
            image_upload, "upload_collection_images", side_effect=RuntimeError("bug")
        ):
            with pytest.raises(RuntimeError):
                manifest_ingest._upload_collection_images(
                    _image_dc(home / "run42" / "images"), cli_config
                )

    def test_a_local_folder_that_is_not_a_directory_says_so(self, home, cli_config):
        """The real upload, which checks before it reaches for storage."""
        message = manifest_ingest._upload_collection_images(
            _image_dc(home / "run42" / "not-there"), cli_config
        )
        assert message.startswith(
            "Image upload failed: 'photos': local_images_path is not a directory"
        )

    def test_a_collection_with_no_bucket_folder_says_so(self, home, cli_config):
        message = manifest_ingest._upload_collection_images(
            _image_dc(home / "run42" / "images", s3_base_folder=None), cli_config
        )
        assert message.startswith("Image upload failed: 'photos': no s3_base_folder")
        assert f"s3://{BUCKET}/images/photos" in message

    def test_a_bucket_folder_in_another_bucket_says_so(self, home, cli_config):
        message = manifest_ingest._upload_collection_images(
            _image_dc(home / "run42" / "images", s3_base_folder="s3://elsewhere/imgs"), cli_config
        )
        assert "serves images from its bucket" in message


# ── where it sits in the ingestion ───────────────────────────────────────────


def _user() -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=True)


def _workflow_with(*collections) -> dict:
    from depictio.models.models.workflows import (
        Workflow,
        WorkflowConfig,
        WorkflowDataLocation,
        WorkflowEngine,
    )

    return Workflow(
        name="wf",
        workflow_tag="wf",
        engine=WorkflowEngine(name="python"),
        config=WorkflowConfig(),
        data_location=WorkflowDataLocation(structure="flat", locations=["/data/run42"]),
        data_collections=list(collections),
    ).mongo()


def _ingest(workflow: dict, dc_id: str, process_result=None):
    result = {"result": "success"} if process_result is None else process_result
    with (
        patch.object(dc_utils, "_build_cli_config_for_user", return_value="CLI-CONFIG"),
        patch(
            "depictio.cli.cli.utils.helpers.process_data_collection_helper", return_value=result
        ) as helper,
    ):
        return manifest_ingest._run_dc_ingest(workflow, dc_id, _user(), scan=False), helper


class TestInTheIngestion:
    def test_the_images_are_uploaded_once_the_table_is_processed(self):
        image = _image_dc("/data/run42/images")
        workflow = _workflow_with(image)
        calls = []
        with patch.object(
            manifest_ingest,
            "_upload_collection_images",
            side_effect=lambda dc, config: calls.append((dc.data_collection_tag, config)),
        ):
            (ok, message), helper = _ingest(workflow, str(workflow["data_collections"][0]["_id"]))
        assert (ok, message) == (True, None)
        assert calls == [("photos", "CLI-CONFIG")]
        assert [c.kwargs["mode"] for c in helper.call_args_list] == ["process"]

    def test_a_failed_upload_fails_the_collection_with_its_message(self):
        workflow = _workflow_with(_image_dc("/data/run42/images"))
        with patch.object(manifest_ingest, "_upload_collection_images", return_value="no images"):
            (ok, message), _helper = _ingest(workflow, str(workflow["data_collections"][0]["_id"]))
        assert (ok, message) == (False, "no images")

    def test_a_table_that_failed_to_process_uploads_nothing(self):
        workflow = _workflow_with(_image_dc("/data/run42/images"))
        with patch.object(manifest_ingest, "_upload_collection_images") as uploading:
            (ok, message), _helper = _ingest(
                workflow,
                str(workflow["data_collections"][0]["_id"]),
                process_result={"result": "error", "message": "bad csv"},
            )
        assert ok is False and message == "Processing failed: bad csv"
        uploading.assert_not_called()

    def test_a_table_collection_goes_through_the_same_step_and_gets_none(self):
        workflow = _workflow_with(_table_dc())
        with patch.object(
            manifest_ingest,
            "_upload_collection_images",
            wraps=manifest_ingest._upload_collection_images,
        ) as uploading:
            (ok, message), _helper = _ingest(workflow, str(workflow["data_collections"][0]["_id"]))
        assert (ok, message) == (True, None)
        uploading.assert_called_once()

    def test_an_unknown_collection_has_no_images_to_upload(self):
        workflow = _workflow_with(_image_dc("/data/run42/images"))
        with patch.object(manifest_ingest, "_upload_collection_images") as uploading:
            (ok, _message), _helper = _ingest(workflow, str(ObjectId()))
        assert ok is True
        uploading.assert_not_called()
