"""Uploading an image data collection's local_images_path during `depictio ingest`.

S3 is a fake that keeps the keys it holds, so a test can say what is already in
storage and read back what was uploaded.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import polars as pl
import pytest
from rich.console import Console

from depictio.cli.cli.utils import image_upload
from depictio.cli.cli.utils.image_upload import (
    ImageUploadError,
    image_collections_to_upload,
    image_key,
    parse_s3_folder,
    resolve_local_images_path,
    upload_collection_images,
    upload_images,
    verify_s3_images,
)
from depictio.models.models.data_collections_types.image import DCImageConfig

BUCKET = "depictio-bucket"
FOLDER = f"s3://{BUCKET}/image_demo/"


class FakeS3:
    def __init__(self, keys=(), list_fails=False):
        self.keys = set(keys)
        self.uploads: list[tuple[str, str, dict]] = []
        self.list_fails = list_fails

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        if self.list_fails:
            raise RuntimeError("AccessDenied")
        return self

    def paginate(self, Bucket, Prefix):
        assert Bucket == BUCKET
        yield {"Contents": [{"Key": k} for k in sorted(self.keys) if k.startswith(Prefix)]}

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.uploads.append((filename, key, ExtraArgs))
        self.keys.add(key)


@pytest.fixture
def cli_config():
    return SimpleNamespace(s3_storage=SimpleNamespace(bucket=BUCKET))


@pytest.fixture
def images_dir(tmp_path):
    folder = tmp_path / "images"
    (folder / "sub").mkdir(parents=True)
    for name in ("sample_001.png", "sample_002.png", "sub/sample_003.png", "notes.txt"):
        (folder / name).write_bytes(b"x")
    return folder


def _collection(local_images_path, s3_base_folder=FOLDER, tag="sample_images", **props):
    return SimpleNamespace(
        data_collection_tag=tag,
        id="650a1b2c3d4e5f6a7b8c9d10",
        config=SimpleNamespace(
            type="image",
            dc_specific_properties=DCImageConfig(
                format="csv",
                image_column="image_path",
                s3_base_folder=s3_base_folder,
                local_images_path=str(local_images_path) if local_images_path else None,
                supported_formats=[".png"],
                **props,
            ),
        ),
    )


class TestLocalImagesPath:
    """Resolved like the project's other paths: from the current directory, with
    {VAR} from the environment as data_location.locations does."""

    def test_a_relative_path_is_read_from_the_current_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        assert resolve_local_images_path("../images") == (tmp_path.parent / "images").resolve()

    def test_an_environment_placeholder_is_expanded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEPICTIO_DATA_ROOT", str(tmp_path))

        assert (
            resolve_local_images_path("{DEPICTIO_DATA_ROOT}/images")
            == (tmp_path / "images").resolve()
        )

    def test_an_unset_placeholder_is_named(self, monkeypatch):
        monkeypatch.delenv("NOT_SET_ANYWHERE", raising=False)

        with pytest.raises(ImageUploadError, match="NOT_SET_ANYWHERE"):
            resolve_local_images_path("{NOT_SET_ANYWHERE}/images")

    def test_the_home_directory_is_expanded(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))

        assert resolve_local_images_path("~/images") == (tmp_path / "images").resolve()


class TestKeys:
    def test_the_folder_parses_to_a_bucket_and_a_prefix(self):
        assert parse_s3_folder("s3://bucket/a/b") == ("bucket", "a/b/")
        assert parse_s3_folder("s3://bucket/") == ("bucket", "")

    def test_anything_but_an_s3_path_is_refused(self):
        with pytest.raises(ValueError, match="s3://"):
            parse_s3_folder("/local/images")

    def test_an_image_path_goes_under_the_folder(self):
        assert image_key(FOLDER, "sample_001.png") == "image_demo/sample_001.png"

    def test_a_leading_copy_of_the_folder_name_is_dropped_as_the_viewer_does(self):
        assert image_key(FOLDER, "image_demo/sample_001.png") == "image_demo/sample_001.png"
        assert image_key(FOLDER, "/sub/a.png") == "image_demo/sub/a.png"

    def test_only_one_leading_copy_is_dropped(self):
        assert image_key(FOLDER, "image_demo/image_demo/a.png") == "image_demo/image_demo/a.png"

    def test_at_the_bucket_root_the_bucket_name_is_dropped_as_the_viewer_does(self):
        assert image_key(f"s3://{BUCKET}/", f"{BUCKET}/a.png") == "a.png"
        assert image_key(f"s3://{BUCKET}/", "sub/a.png") == "sub/a.png"

    def test_empty_segments_in_the_folder_are_dropped(self):
        assert parse_s3_folder("s3://bucket//a//b/") == ("bucket", "a/b/")
        assert image_key(f"s3://{BUCKET}//image_demo/", "a.png") == "image_demo/a.png"
        assert image_key("s3://b/x//images/", "images/a.png") == "x/images/a.png"


class TestUpload:
    def test_existing_keys_are_skipped(self, images_dir):
        s3 = FakeS3(keys={"image_demo/sample_001.png"})
        images = sorted(images_dir.rglob("*.png"))

        counts = upload_images(images, images_dir, s3, BUCKET, "image_demo/", label=FOLDER)

        assert counts == {"uploaded": 2, "replaced": 0, "skipped": 1, "error": 0}
        assert sorted(key for _, key, _ in s3.uploads) == [
            "image_demo/sample_002.png",
            "image_demo/sub/sample_003.png",
        ]
        assert all(extra == {"ContentType": "image/png"} for _, _, extra in s3.uploads)

    def test_overwrite_uploads_every_image_and_counts_the_replaced_ones(self, images_dir):
        s3 = FakeS3(keys={"image_demo/sample_001.png"})
        images = sorted(images_dir.rglob("*.png"))

        counts = upload_images(
            images, images_dir, s3, BUCKET, "image_demo/", overwrite=True, label=FOLDER
        )

        assert counts == {"uploaded": 2, "replaced": 1, "skipped": 0, "error": 0}
        assert len(s3.uploads) == 3

    def test_a_failed_upload_is_counted(self, images_dir):
        s3 = FakeS3()
        s3.upload_file = MagicMock(side_effect=RuntimeError("SlowDown"))

        counts = upload_images(
            [images_dir / "sample_001.png"], images_dir, s3, BUCKET, "x/", label="x"
        )

        assert counts == {"uploaded": 0, "replaced": 0, "skipped": 0, "error": 1}


class TestUploadAndVerifyAgree:
    """The upload puts each image where the check, and the dashboard, look for it."""

    def _round_trip(self, source, folder, referenced, cli_config):
        s3 = FakeS3()
        bucket, prefix = parse_s3_folder(folder)
        upload_images(sorted(source.rglob("*.png")), source, s3, bucket, prefix, label=folder)
        with patch.object(image_upload, "s3_client", return_value=s3):
            return s3, verify_s3_images(folder, cli_config, referenced)

    def test_paths_that_start_with_the_folder_name(self, images_dir, cli_config):
        # local_images_path holds images/, and the column says images/...: the folder
        # ends in images/ too, so neither side doubles it.
        s3, result = self._round_trip(
            images_dir.parent,
            f"s3://{BUCKET}/proj/images/",
            ["images/sample_001.png", "images/sub/sample_003.png", "sample_002.png"],
            cli_config,
        )

        assert "proj/images/sample_001.png" in s3.keys
        assert not any("images/images" in key for key in s3.keys)
        assert result["missing"] == []

    def test_a_folder_with_double_slashes(self, images_dir, cli_config):
        s3, result = self._round_trip(
            images_dir, f"s3://{BUCKET}//image_demo//", ["sample_001.png"], cli_config
        )

        assert "image_demo/sample_001.png" in s3.keys
        assert result["missing"] == []


class TestVerify:
    def test_it_counts_the_images_and_names_the_missing_ones(self, cli_config):
        s3 = FakeS3(keys={"image_demo/a.png", "image_demo/b.png", "image_demo/readme.txt"})

        with patch.object(image_upload, "s3_client", return_value=s3):
            result = verify_s3_images(FOLDER, cli_config, ["a.png", "image_demo/b.png", "c.png"])

        assert result["count"] == 2
        assert result["missing"] == ["c.png"]

    def test_it_counts_past_a_hundred_images(self, cli_config):
        s3 = FakeS3(keys={f"image_demo/{i}.png" for i in range(250)})

        with patch.object(image_upload, "s3_client", return_value=s3):
            assert verify_s3_images(FOLDER, cli_config)["count"] == 250

    def test_a_folder_that_cannot_be_listed_is_an_error(self, cli_config):
        with patch.object(image_upload, "s3_client", return_value=FakeS3(list_fails=True)):
            result = verify_s3_images(FOLDER, cli_config, ["a.png"])

        assert "AccessDenied" in result["error"]


class TestCollectionUpload:
    def _upload(self, dc, cli_config, s3, referenced, **kwargs):
        with (
            patch.object(image_upload, "s3_client", return_value=s3),
            patch.object(image_upload, "_referenced_images", return_value=referenced),
        ):
            return upload_collection_images(dc, cli_config, **kwargs)

    @pytest.fixture
    def printed(self, monkeypatch):
        """What the status lines print, through a real console: markup is rendered."""
        from depictio.cli.cli.utils import rich_utils

        out = Console(file=io.StringIO(), width=500, color_system=None)
        monkeypatch.setattr(rich_utils, "console", out)
        return lambda: " ".join(out.file.getvalue().split())

    def test_the_local_images_land_in_the_folder_and_are_verified(self, images_dir, cli_config):
        s3 = FakeS3(keys={"image_demo/sample_001.png"})

        result = self._upload(
            _collection(images_dir), cli_config, s3, ["sample_001.png", "sub/sample_003.png"]
        )

        assert (result["uploaded"], result["skipped"], result["count"]) == (2, 1, 3)
        # Only the supported formats: notes.txt stays behind.
        assert "image_demo/notes.txt" not in s3.keys

    def test_images_the_table_references_but_that_are_missing_fail(self, images_dir, cli_config):
        with pytest.raises(ImageUploadError, match=r"2 image\(s\).*absent_1.png, absent_2.png"):
            self._upload(
                _collection(images_dir),
                cli_config,
                FakeS3(),
                ["sample_001.png", "absent_1.png", "absent_2.png"],
            )

    def test_an_unreadable_table_still_uploads(self, images_dir, cli_config):
        result = self._upload(_collection(images_dir), cli_config, FakeS3(), None)

        assert result["uploaded"] == 3
        assert result["referenced"] is None

    def test_a_local_path_that_is_not_a_directory_fails_clearly(self, tmp_path, cli_config):
        with pytest.raises(ImageUploadError, match="not a directory"):
            self._upload(_collection(tmp_path / "nowhere"), cli_config, FakeS3(), [])

    def test_a_folder_in_another_bucket_fails_before_any_upload(self, images_dir, cli_config):
        s3 = FakeS3()

        with pytest.raises(ImageUploadError, match=f"serves images from its bucket '{BUCKET}'"):
            self._upload(_collection(images_dir, "s3://elsewhere/imgs/"), cli_config, s3, [])

        assert s3.uploads == []

    def test_a_folder_with_an_empty_segment_fails_before_any_upload(self, images_dir, cli_config):
        # The viewer would ask the server for '/image_demo/...', which it refuses.
        s3 = FakeS3()

        with pytest.raises(ImageUploadError, match=f"Write it as s3://{BUCKET}/image_demo/"):
            self._upload(_collection(images_dir, f"s3://{BUCKET}//image_demo/"), cli_config, s3, [])

        assert s3.uploads == []

    def test_a_changed_image_is_replaced_with_overwrite(self, images_dir, cli_config, printed):
        s3 = FakeS3(keys={"image_demo/sample_001.png", "image_demo/sample_002.png"})

        result = self._upload(
            _collection(images_dir), cli_config, s3, ["sample_001.png"], overwrite=True
        )

        assert (result["uploaded"], result["replaced"], result["skipped"]) == (1, 2, 0)
        assert "image_demo/sample_001.png" in [key for _, key, _ in s3.uploads]
        assert "'sample_images': 1 uploaded, 2 replaced;" in printed()

    def test_without_overwrite_the_summary_counts_what_was_already_there(
        self, images_dir, cli_config, printed
    ):
        s3 = FakeS3(keys={"image_demo/sample_001.png"})

        self._upload(_collection(images_dir), cli_config, s3, ["sample_001.png"])

        assert "'sample_images': 2 uploaded, 1 already in storage;" in printed()

    def test_brackets_in_paths_and_tags_are_printed_as_they_are(
        self, tmp_path, cli_config, printed
    ):
        source = tmp_path / "[/run]" / "[x]"
        source.mkdir(parents=True)
        (source / "a.png").write_bytes(b"x")
        dc = _collection(source, tag="[b]imgs")

        self._upload(dc, cli_config, FakeS3(), ["a.png"])

        assert f"'[b]imgs': uploading 1 image(s) from {source}" in printed()
        assert "'[b]imgs': 1 uploaded, 0 already in storage;" in printed()


class TestWhichCollections:
    def test_only_image_collections_with_a_local_path(self, images_dir):
        with_path = _collection(images_dir)
        without_path = _collection(None)
        table = SimpleNamespace(config=SimpleNamespace(type="table", dc_specific_properties=None))
        project = SimpleNamespace(
            workflows=[SimpleNamespace(data_collections=[with_path, without_path, table])]
        )

        assert image_collections_to_upload(project) == [with_path]

    def test_narrowed_by_workflow_and_tag_as_the_scan_is(self, images_dir):
        first, second = _collection(images_dir, tag="first"), _collection(images_dir, tag="second")
        other = _collection(images_dir, tag="first")
        table = SimpleNamespace(
            data_collection_tag="first",
            config=SimpleNamespace(type="table", dc_specific_properties=None),
        )
        project = SimpleNamespace(
            workflows=[
                SimpleNamespace(workflow_tag="wf", data_collections=[first, second, table]),
                SimpleNamespace(workflow_tag="other_wf", data_collections=[other]),
            ]
        )

        assert image_collections_to_upload(project, workflow_name="wf") == [first, second]
        assert image_collections_to_upload(project, data_collection_tag="first") == [first, other]
        assert image_collections_to_upload(project, "wf", "second") == [second]
        assert image_collections_to_upload(project, "missing_wf") == []


class TestReferencedImages:
    def test_the_processed_table_gives_its_image_paths(self, images_dir, cli_config):
        table = pl.DataFrame({"image_path": ["a.png", None, "a.png", "b.png", " "]})
        read = MagicMock(return_value={"result": "success", "data": table})

        with (
            patch("depictio.cli.cli.utils.deltatables.read_delta_table", read),
            patch("depictio.models.s3_utils.turn_S3_config_into_polars_storage_options"),
        ):
            paths = image_upload._referenced_images(_collection(images_dir), cli_config)

        assert sorted(paths) == ["a.png", "b.png"]
        assert read.call_args.args[0] == f"s3://{BUCKET}/650a1b2c3d4e5f6a7b8c9d10"

    def test_a_table_that_cannot_be_read_gives_none(self, images_dir, cli_config):
        read = MagicMock(return_value={"result": "error", "message": "no table"})

        with (
            patch("depictio.cli.cli.utils.deltatables.read_delta_table", read),
            patch("depictio.models.s3_utils.turn_S3_config_into_polars_storage_options"),
        ):
            assert image_upload._referenced_images(_collection(images_dir), cli_config) is None
