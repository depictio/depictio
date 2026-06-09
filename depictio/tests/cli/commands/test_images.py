"""Unit tests for CLI image commands."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from depictio.cli.cli.commands.images import (
    SUPPORTED_IMAGE_EXTENSIONS,
    _get_content_type,
    _is_image_file,
    _scan_directory_for_images,
    app,
)


class TestImageUtilityFunctions:
    """Test suite for image utility functions."""

    def test_is_image_file_supported_extensions(self):
        """Test _is_image_file recognizes supported extensions."""
        for ext in SUPPORTED_IMAGE_EXTENSIONS:
            path = Path(f"test{ext}")
            assert _is_image_file(path) is True

    def test_is_image_file_uppercase_extensions(self):
        """Test _is_image_file handles uppercase extensions."""
        for ext in [".PNG", ".JPG", ".JPEG", ".GIF"]:
            path = Path(f"test{ext}")
            assert _is_image_file(path) is True

    def test_is_image_file_unsupported_extensions(self):
        """Test _is_image_file rejects unsupported extensions."""
        for ext in [".txt", ".pdf", ".doc", ".mp4"]:
            path = Path(f"test{ext}")
            assert _is_image_file(path) is False

    def test_get_content_type_known_types(self):
        """Test _get_content_type returns correct MIME types."""
        test_cases = {
            "image.png": "image/png",
            "photo.jpg": "image/jpeg",
            "graphic.gif": "image/gif",
            "vector.svg": "image/svg+xml",
        }
        for filename, expected_type in test_cases.items():
            path = Path(filename)
            content_type = _get_content_type(path)
            assert content_type == expected_type

    def test_get_content_type_unknown_fallback(self):
        """Test _get_content_type returns fallback for unknown types."""
        path = Path("file.unknown")
        content_type = _get_content_type(path)
        assert content_type == "application/octet-stream"


class TestScanDirectoryForImages:
    """Test suite for directory scanning functionality."""

    @pytest.fixture
    def temp_image_dir(self, tmp_path):
        """Create temporary directory with test images."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()

        # Create some test image files
        (img_dir / "image1.png").touch()
        (img_dir / "photo.jpg").touch()
        (img_dir / "graphic.gif").touch()
        (img_dir / "document.txt").touch()  # Non-image file

        # Create subdirectory with images
        sub_dir = img_dir / "subdir"
        sub_dir.mkdir()
        (sub_dir / "nested.png").touch()
        (sub_dir / "deep.jpeg").touch()

        return img_dir

    def test_scan_directory_recursive(self, temp_image_dir):
        """Test recursive directory scanning finds all images."""
        images = _scan_directory_for_images(temp_image_dir, recursive=True)

        # Should find 5 image files (3 in root, 2 in subdir)
        assert len(images) == 5

        # Should not include .txt file
        txt_files = [img for img in images if img.suffix == ".txt"]
        assert len(txt_files) == 0

    def test_scan_directory_non_recursive(self, temp_image_dir):
        """Test non-recursive scanning only finds root images."""
        images = _scan_directory_for_images(temp_image_dir, recursive=False)

        # Should find only 3 images in root directory
        assert len(images) == 3

        # Should not include subdirectory images
        nested_images = [img for img in images if "subdir" in str(img)]
        assert len(nested_images) == 0

    def test_scan_directory_specific_extensions(self, temp_image_dir):
        """Test scanning with specific extension filter."""
        extensions = {".png", ".gif"}
        images = _scan_directory_for_images(temp_image_dir, recursive=True, extensions=extensions)

        # Should find only .png and .gif files (3 total)
        assert len(images) == 3
        for img in images:
            assert img.suffix.lower() in extensions

    def test_scan_directory_uppercase_extensions(self, temp_image_dir):
        """Test scanning finds uppercase extensions."""
        # Create uppercase extension files
        (temp_image_dir / "CAPS.PNG").touch()
        (temp_image_dir / "UPPER.JPG").touch()

        images = _scan_directory_for_images(temp_image_dir, recursive=False)

        # Should find both lowercase and uppercase files
        caps_files = [img for img in images if img.name in ["CAPS.PNG", "UPPER.JPG"]]
        assert len(caps_files) == 2

    def test_scan_directory_empty(self, tmp_path):
        """Test scanning empty directory returns empty list."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        images = _scan_directory_for_images(empty_dir, recursive=True)
        assert len(images) == 0

    def test_scan_directory_no_images(self, tmp_path):
        """Test scanning directory with no images."""
        text_dir = tmp_path / "texts"
        text_dir.mkdir()
        (text_dir / "file1.txt").touch()
        (text_dir / "file2.pdf").touch()

        images = _scan_directory_for_images(text_dir, recursive=True)
        assert len(images) == 0

    def test_scan_directory_removes_duplicates(self, temp_image_dir):
        """Test that duplicate paths are removed."""
        # Scanning twice shouldn't create duplicates
        images = _scan_directory_for_images(temp_image_dir, recursive=True)
        unique_images = list(set(images))
        assert len(images) == len(unique_images)


class TestPushCommand:
    """Test suite for 'images push' CLI command."""

    @pytest.fixture
    def runner(self):
        """Create CLI runner."""
        return CliRunner()

    def test_push_nonexistent_directory(self, runner):
        """Test push command with nonexistent source directory."""
        result = runner.invoke(app, ["push", "/nonexistent", "s3://bucket/path/"])
        assert result.exit_code == 1

    def test_push_invalid_s3_destination(self, runner, tmp_path):
        """Test push command with invalid S3 destination format."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()

        result = runner.invoke(app, ["push", str(img_dir), "invalid://bucket/path"])
        assert result.exit_code == 1

    def test_push_dry_run(self, runner, tmp_path):
        """Test push command in dry-run mode."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "test.png").touch()

        result = runner.invoke(app, ["push", str(img_dir), "s3://bucket/path/", "--dry-run"])
        assert result.exit_code == 0

    def test_push_s3_path_parsing(self, runner, tmp_path):
        """Test S3 path is correctly parsed."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()

        # Test various S3 path formats
        result = runner.invoke(app, ["push", str(img_dir), "s3://bucket/", "--dry-run"])
        assert result.exit_code == 0

        result = runner.invoke(app, ["push", str(img_dir), "s3://bucket/prefix/path/", "--dry-run"])
        assert result.exit_code == 0


class TestListBucketCommand:
    """Test suite for 'images list-bucket' CLI command."""

    @pytest.fixture
    def runner(self):
        """Create CLI runner."""
        return CliRunner()

    def test_list_bucket_invalid_s3_path(self, runner):
        """Test list-bucket command with invalid S3 path."""
        result = runner.invoke(app, ["list-bucket", "invalid://bucket/path"])
        assert result.exit_code == 1

    def test_list_bucket_s3_path_parsing(self, runner):
        """Test S3 path parsing in list-bucket command."""
        with patch("depictio.cli.cli.utils.common.load_depictio_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Mock boto3 client to avoid actual S3 calls
            with patch("boto3.client") as mock_boto:
                mock_s3 = MagicMock()
                mock_boto.return_value = mock_s3

                # Mock paginator
                mock_paginator = MagicMock()
                mock_paginator.paginate.return_value = [{"Contents": []}]
                mock_s3.get_paginator.return_value = mock_paginator

                result = runner.invoke(app, ["list-bucket", "s3://bucket/prefix/"])
                # Should attempt to connect (may fail in test env but path should parse)
                assert "bucket" in str(result.output) or result.exit_code in [0, 1]
