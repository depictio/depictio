"""Unit tests for files endpoints with image serving functionality."""

import pytest

from depictio.api.v1.endpoints.files_endpoints.routes import (
    SUPPORTED_IMAGE_EXTENSIONS,
    _get_mime_type,
    _parse_s3_path,
    _validate_image_path,
)


class TestS3PathParsing:
    """Test suite for S3 path parsing utility."""

    def test_parse_s3_path_with_prefix(self):
        """Test parsing S3 path with s3:// prefix."""
        bucket, key = _parse_s3_path("s3://my-bucket/path/to/image.png")
        assert bucket == "my-bucket"
        assert key == "path/to/image.png"

    def test_parse_s3_path_without_prefix(self):
        """Test parsing S3 path without s3:// prefix."""
        bucket, key = _parse_s3_path("my-bucket/path/to/image.png")
        assert bucket == "my-bucket"
        assert key == "path/to/image.png"

    def test_parse_s3_path_nested_folders(self):
        """Test parsing S3 path with nested folders."""
        bucket, key = _parse_s3_path("s3://bucket/folder1/folder2/folder3/image.jpg")
        assert bucket == "bucket"
        assert key == "folder1/folder2/folder3/image.jpg"

    def test_parse_s3_path_root_level(self):
        """Test parsing S3 path at root level."""
        bucket, key = _parse_s3_path("s3://bucket/image.png")
        assert bucket == "bucket"
        assert key == "image.png"

    def test_parse_s3_path_invalid_no_key(self):
        """Test parsing invalid S3 path without key raises error."""
        with pytest.raises(ValueError, match="Invalid S3 path format"):
            _parse_s3_path("s3://bucket-only")

    def test_parse_s3_path_empty_string(self):
        """Test parsing empty string raises error."""
        with pytest.raises(ValueError, match="Invalid S3 path format"):
            _parse_s3_path("")


class TestMimeTypeDetection:
    """Test suite for MIME type detection utility."""

    def test_get_mime_type_png(self):
        """Test MIME type for PNG images."""
        assert _get_mime_type("image.png") == "image/png"

    def test_get_mime_type_jpeg(self):
        """Test MIME type for JPEG images."""
        assert _get_mime_type("photo.jpg") == "image/jpeg"
        assert _get_mime_type("photo.jpeg") == "image/jpeg"

    def test_get_mime_type_gif(self):
        """Test MIME type for GIF images."""
        assert _get_mime_type("animation.gif") == "image/gif"

    def test_get_mime_type_webp(self):
        """Test MIME type for WebP images."""
        assert _get_mime_type("modern.webp") == "image/webp"

    def test_get_mime_type_svg(self):
        """Test MIME type for SVG images."""
        assert _get_mime_type("vector.svg") == "image/svg+xml"

    def test_get_mime_type_unknown(self):
        """Test MIME type for unknown file returns fallback."""
        assert _get_mime_type("file.unknown") == "application/octet-stream"

    def test_get_mime_type_with_path(self):
        """Test MIME type detection works with full paths."""
        assert _get_mime_type("path/to/folder/image.png") == "image/png"


class TestImagePathValidation:
    """Test suite for image path validation utility."""

    def test_validate_image_path_valid_extensions(self):
        """Test validation accepts all supported image extensions."""
        for ext in SUPPORTED_IMAGE_EXTENSIONS:
            path = f"folder/image{ext}"
            assert _validate_image_path(path) is True

    def test_validate_image_path_uppercase_extensions(self):
        """Test validation handles uppercase extensions."""
        assert _validate_image_path("image.PNG") is True
        assert _validate_image_path("photo.JPG") is True

    def test_validate_image_path_mixed_case(self):
        """Test validation handles mixed case extensions."""
        assert _validate_image_path("image.PnG") is True
        assert _validate_image_path("photo.JpEg") is True

    def test_validate_image_path_nested_folders(self):
        """Test validation accepts nested folder paths."""
        assert _validate_image_path("folder1/folder2/folder3/image.png") is True

    def test_validate_image_path_rejects_parent_traversal(self):
        """Test validation rejects paths with parent directory traversal."""
        assert _validate_image_path("../image.png") is False
        assert _validate_image_path("folder/../image.png") is False
        assert _validate_image_path("folder/../../image.png") is False

    def test_validate_image_path_rejects_absolute_paths(self):
        """Test validation rejects absolute paths."""
        assert _validate_image_path("/image.png") is False
        assert _validate_image_path("/folder/image.png") is False

    def test_validate_image_path_rejects_unsupported_formats(self):
        """Test validation rejects unsupported file formats."""
        assert _validate_image_path("file.txt") is False
        assert _validate_image_path("document.pdf") is False
        assert _validate_image_path("video.mp4") is False

    def test_validate_image_path_empty_string(self):
        """Test validation rejects empty string."""
        assert _validate_image_path("") is False

    def test_validate_image_path_no_extension(self):
        """Test validation rejects paths without extensions."""
        assert _validate_image_path("folder/imagefile") is False


class TestSupportedImageExtensions:
    """Test suite for supported image extensions constant."""

    def test_supported_extensions_immutable(self):
        """Test SUPPORTED_IMAGE_EXTENSIONS is a frozenset (immutable)."""
        assert isinstance(SUPPORTED_IMAGE_EXTENSIONS, frozenset)

    def test_supported_extensions_content(self):
        """Test SUPPORTED_IMAGE_EXTENSIONS contains expected formats."""
        required_formats = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
        assert required_formats.issubset(SUPPORTED_IMAGE_EXTENSIONS)

    def test_supported_extensions_lowercase(self):
        """Test all extensions are lowercase."""
        for ext in SUPPORTED_IMAGE_EXTENSIONS:
            assert ext == ext.lower(), f"Extension {ext} should be lowercase"

    def test_supported_extensions_have_leading_dot(self):
        """Test all extensions start with a dot."""
        for ext in SUPPORTED_IMAGE_EXTENSIONS:
            assert ext.startswith("."), f"Extension {ext} should start with '.'"
