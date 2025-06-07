from unittest.mock import patch

import pytest
from pydantic import ValidationError

# Import the functions to test
from depictio.models.models.base import PyObjectId
from depictio.models.models.files import File
from depictio.models.models.users import Permission, UserBase


class TestFileModel:
    """Test suite for File model validation."""

    @pytest.fixture
    def sample_permissions(self):
        """Sample permissions for testing."""
        return Permission(
            owners=[
                UserBase(
                    id=PyObjectId(),
                    email="test@example.com",
                    is_admin=True,
                )
            ]
        )

    @pytest.fixture
    def valid_file_data(self, sample_permissions):
        """Valid file data for testing."""
        return {
            "filename": "test_file.txt",
            "file_location": "/path/to/test_file.txt",
            "creation_time": "2025-01-01 10:00:00",
            "modification_time": "2025-01-01 11:00:00",
            "run_id": PyObjectId(),
            "data_collection_id": PyObjectId(),
            "filesize": 1024,
            "file_hash": "a" * 64,
            "permissions": sample_permissions,
        }

    def test_valid_file_creation(self, valid_file_data):
        """Test creating a valid File instance."""
        file_instance = File(**valid_file_data)
        assert file_instance.filename == "test_file.txt"
        assert file_instance.filesize == 1024
        assert len(file_instance.file_hash) == 64

    def test_empty_filename_validation(self, valid_file_data):
        """Test filename validation with empty string."""
        valid_file_data["filename"] = ""
        with pytest.raises(ValidationError, match="Filename cannot be empty"):
            File(**valid_file_data)

    def test_negative_filesize_validation(self, valid_file_data):
        """Test filesize validation with negative value."""
        valid_file_data["filesize"] = -100
        with pytest.raises(ValidationError, match="File size cannot be negative"):
            File(**valid_file_data)

    def test_zero_filesize_validation(self, valid_file_data):
        """Test filesize validation with zero value."""
        valid_file_data["filesize"] = 0
        with pytest.raises(ValidationError, match="File size cannot be zero"):
            File(**valid_file_data)

    def test_empty_hash_validation(self, valid_file_data):
        """Test hash validation with empty string."""
        valid_file_data["file_hash"] = ""
        with pytest.raises(ValidationError, match="Hash cannot be empty"):
            File(**valid_file_data)

    def test_invalid_hash_length_validation(self, valid_file_data):
        """Test hash validation with invalid length."""
        valid_file_data["file_hash"] = "short_hash"
        with pytest.raises(ValidationError, match="Invalid hash value, must be 32 characters long"):
            File(**valid_file_data)

    def test_datetime_validation_iso_format(self, valid_file_data):
        """Test datetime validation with ISO format."""
        valid_file_data["creation_time"] = "2025-01-01T10:00:00"
        valid_file_data["modification_time"] = "2025-01-01T11:00:00"

        file_instance = File(**valid_file_data)
        assert file_instance.creation_time == "2025-01-01 10:00:00"
        assert file_instance.modification_time == "2025-01-01 11:00:00"

    def test_datetime_validation_invalid_format(self, valid_file_data):
        """Test datetime validation with invalid format."""
        valid_file_data["creation_time"] = "invalid-date-format"
        with pytest.raises(ValidationError, match="Invalid datetime format"):
            File(**valid_file_data)

    @patch("depictio.models.models.files.DEPICTIO_CONTEXT", "cli")
    @patch("os.path.exists")
    @patch("os.path.isfile")
    @patch("os.access")
    def test_file_location_validation_cli_context(
        self, mock_access, mock_isfile, mock_exists, valid_file_data
    ):
        """Test file location validation in CLI context."""
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_access.return_value = True

        file_instance = File(**valid_file_data)
        assert file_instance.file_location == "/path/to/test_file.txt"

    @patch("depictio.models.models.files.DEPICTIO_CONTEXT", "cli")
    @patch("os.path.exists")
    def test_file_location_validation_cli_nonexistent(self, mock_exists, valid_file_data):
        """Test file location validation with non-existent file in CLI context."""
        mock_exists.return_value = False

        with pytest.raises(ValidationError, match="does not exist"):
            File(**valid_file_data)

    @patch("depictio.models.config.DEPICTIO_CONTEXT", "server")
    def test_file_location_validation_server_context(self, valid_file_data):
        """Test file location validation in server context."""
        # In server context, file existence is not checked
        file_instance = File(**valid_file_data)
        assert file_instance.file_location == "/path/to/test_file.txt"

    def test_empty_file_location_validation(self, valid_file_data):
        """Test file location validation with empty string."""
        valid_file_data["file_location"] = ""
        with pytest.raises(ValidationError, match="File location cannot be empty"):
            File(**valid_file_data)
