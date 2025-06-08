import hashlib
import re
from unittest.mock import patch

import pytest

# Import the functions to test
from depictio.cli.cli.utils.scan_utils import (
    check_run_differences,
    construct_full_regex,
    generate_file_hash,
    generate_run_hash,
    regex_match,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.data_collections import Regex, WildcardRegexBase
from depictio.models.models.files import File
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import WorkflowRun


class TestRegexMatch:
    """Test suite for regex_match function."""

    @pytest.fixture
    def sample_file(self):
        """Sample File object for testing."""
        permissions = Permission(
            owners=[
                UserBase(
                    id=PyObjectId(),
                    email="test@example.com",
                    is_admin=True,
                )
            ]
        )

        return File(
            filename="test_file.txt",
            file_location="/path/to/test_file.txt",
            creation_time="2025-01-01 10:00:00",
            modification_time="2025-01-01 11:00:00",
            run_id=PyObjectId(),
            data_collection_id=PyObjectId(),
            filesize=1024,
            file_hash="a" * 64,  # 64-character hash
            permissions=permissions,
        )

    @pytest.fixture(autouse=True)
    def set_depictio_context(self, monkeypatch):
        """Set DEPICTIO_CONTEXT for all tests."""
        monkeypatch.setattr("depictio.models.config.DEPICTIO_CONTEXT", "server")
        monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "server")

    def test_simple_match_success(self, sample_file):
        """Test successful regex match with simple pattern."""
        regex_pattern = r"test_file\.txt"
        success, match_obj = regex_match(sample_file.filename, regex_pattern)

        assert success is True
        assert match_obj is not None
        assert match_obj.group() == "test_file.txt"

    def test_simple_match_failure(self, sample_file):
        """Test failed regex match with non-matching pattern."""
        regex_pattern = r"different_file\.txt"
        success, match_obj = regex_match(sample_file.filename, regex_pattern)

        assert success is False
        assert match_obj is None

    def test_regex_normalization_with_paths(self):
        """Test regex normalization for path separators."""
        filename = "path/to/file.txt"
        regex_pattern = "path/to/file\\.txt"

        success, match_obj = regex_match(filename, regex_pattern)

        assert success is True
        assert match_obj is not None

    def test_complex_regex_pattern(self, sample_file):
        """Test with complex regex patterns."""
        regex_pattern = r"test_\w+\.txt"
        success, match_obj = regex_match(sample_file.filename, regex_pattern)

        assert success is True
        assert match_obj is not None

    def test_case_sensitive_match(self):
        """Test case-sensitive regex matching."""
        filename = "Test_File.TXT"
        regex_pattern = r"test_file\.txt"

        success, match_obj = regex_match(filename, regex_pattern)

        assert success is False
        assert match_obj is None

    def test_empty_filename(self):
        """Test regex match with empty filename."""
        filename = ""
        regex_pattern = r".*"

        success, match_obj = regex_match(filename, regex_pattern)

        assert success is True
        assert match_obj is not None

    def test_special_characters_in_filename(self):
        """Test regex match with special characters in filename."""
        filename = "file[1].txt"
        regex_pattern = r"file\[1\]\.txt"

        success, match_obj = regex_match(filename, regex_pattern)

        assert success is True
        assert match_obj is not None

    def test_invalid_regex_pattern(self):
        """Test behavior with invalid regex pattern."""
        filename = "test_file.txt"
        invalid_regex = r"[invalid"

        with pytest.raises(re.error):
            regex_match(filename, invalid_regex)


class TestConstructFullRegex:
    """Test suite for construct_full_regex function."""

    def test_single_wildcard_replacement(self):
        """Test regex construction with single wildcard."""
        wildcard = WildcardRegexBase(name="date", wildcard_regex=r"\d{4}-\d{2}-\d{2}")
        regex_config = Regex(pattern="file_{date}.txt", wildcards=[wildcard])

        result = construct_full_regex(regex_config)
        expected = "file_(\\d{4}-\\d{2}-\\d{2}).txt"

        assert result == expected

    def test_multiple_wildcards_replacement(self):
        """Test regex construction with multiple wildcards."""
        wildcards = [
            WildcardRegexBase(name="date", wildcard_regex=r"\d{4}-\d{2}-\d{2}"),
            WildcardRegexBase(name="sample", wildcard_regex=r"[A-Z]+\d+"),
        ]
        regex_config = Regex(pattern="data_{date}_{sample}.csv", wildcards=wildcards)

        result = construct_full_regex(regex_config)
        expected = "data_(\\d{4}-\\d{2}-\\d{2})_([A-Z]+\\d+).csv"

        assert result == expected

    def test_no_wildcards(self):
        """Test regex construction with no wildcards."""
        regex_config = Regex(pattern="static_file.txt", wildcards=[])

        result = construct_full_regex(regex_config)
        expected = "static_file.txt"

        assert result == expected

    def test_wildcard_not_in_pattern(self):
        """Test when wildcard name is not present in pattern."""
        wildcard = WildcardRegexBase(name="unused", wildcard_regex=r"\d+")
        regex_config = Regex(pattern="file.txt", wildcards=[wildcard])

        result = construct_full_regex(regex_config)
        expected = "file.txt"  # Should remain unchanged

        assert result == expected

    def test_complex_wildcard_patterns(self):
        """Test with complex wildcard regex patterns."""
        wildcards = [
            WildcardRegexBase(
                name="timestamp", wildcard_regex=r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
            ),
            WildcardRegexBase(name="extension", wildcard_regex=r"(txt|csv|json)"),
        ]
        regex_config = Regex(pattern="log_{timestamp}.{extension}", wildcards=wildcards)

        result = construct_full_regex(regex_config)
        expected = "log_(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}).((txt|csv|json))"

        assert result == expected

    def test_wildcard_with_simple_alternatives(self):
        """Test with wildcard that uses simple alternatives without grouping."""
        wildcards = [
            WildcardRegexBase(name="extension", wildcard_regex=r"txt|csv|json"),  # No parentheses
        ]
        regex_config = Regex(pattern="file.{extension}", wildcards=wildcards)

        result = construct_full_regex(regex_config)
        expected = "file.(txt|csv|json)"

        assert result == expected

    def test_duplicate_wildcard_names(self):
        """Test behavior with duplicate wildcard names. Should raise an error."""
        wildcards = [
            WildcardRegexBase(name="id", wildcard_regex=r"\d+"),
            WildcardRegexBase(name="id", wildcard_regex=r"[A-Z]+"),  # Same name, different pattern
        ]
        regex_config = Regex(pattern="file_{id}.txt", wildcards=wildcards)

        with pytest.raises(
            ValueError, match="Duplicate wildcard names found in regex configuration"
        ):
            construct_full_regex(regex_config)


class TestGenerateFileHash:
    """Test suite for generate_file_hash function."""

    def test_consistent_hash_generation(self):
        """Test that same inputs produce same hash."""
        filename = "test_file.txt"
        filesize = 1024
        creation_time = "2025-01-01 10:00:00"
        modification_time = "2025-01-01 11:00:00"

        hash1 = generate_file_hash(filename, filesize, creation_time, modification_time)
        hash2 = generate_file_hash(filename, filesize, creation_time, modification_time)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 produces 64-character hex string
        assert isinstance(hash1, str)

    def test_different_filenames_different_hashes(self):
        """Test that different filenames produce different hashes."""
        filesize = 1024
        creation_time = "2025-01-01 10:00:00"
        modification_time = "2025-01-01 11:00:00"

        hash1 = generate_file_hash("file1.txt", filesize, creation_time, modification_time)
        hash2 = generate_file_hash("file2.txt", filesize, creation_time, modification_time)

        assert hash1 != hash2

    def test_different_filesizes_different_hashes(self):
        """Test that different file sizes produce different hashes."""
        filename = "test_file.txt"
        creation_time = "2025-01-01 10:00:00"
        modification_time = "2025-01-01 11:00:00"

        hash1 = generate_file_hash(filename, 1024, creation_time, modification_time)
        hash2 = generate_file_hash(filename, 2048, creation_time, modification_time)

        assert hash1 != hash2

    def test_different_times_different_hashes(self):
        """Test that different times produce different hashes."""
        filename = "test_file.txt"
        filesize = 1024

        hash1 = generate_file_hash(filename, filesize, "2025-01-01 10:00:00", "2025-01-01 11:00:00")
        hash2 = generate_file_hash(filename, filesize, "2025-01-01 10:00:01", "2025-01-01 11:00:00")

        assert hash1 != hash2

    def test_empty_filename(self):
        """Test hash generation with empty filename."""
        hash_result = generate_file_hash("", 0, "2025-01-01 10:00:00", "2025-01-01 11:00:00")

        assert isinstance(hash_result, str)
        assert len(hash_result) == 64

    def test_special_characters_in_filename(self):
        """Test hash generation with special characters in filename."""
        filename = "file@#$%^&*()_+.txt"
        hash_result = generate_file_hash(
            filename, 1024, "2025-01-01 10:00:00", "2025-01-01 11:00:00"
        )

        assert isinstance(hash_result, str)
        assert len(hash_result) == 64

    def test_zero_filesize(self):
        """Test hash generation with zero file size."""
        hash_result = generate_file_hash(
            "empty_file.txt", 0, "2025-01-01 10:00:00", "2025-01-01 11:00:00"
        )

        assert isinstance(hash_result, str)
        assert len(hash_result) == 64

    def test_large_filesize(self):
        """Test hash generation with large file size."""
        large_size = 999999999999  # Very large file size
        hash_result = generate_file_hash(
            "huge_file.txt", large_size, "2025-01-01 10:00:00", "2025-01-01 11:00:00"
        )

        assert isinstance(hash_result, str)
        assert len(hash_result) == 64

    def test_manual_hash_verification(self):
        """Test hash generation against manually calculated hash."""
        filename = "test.txt"
        filesize = 100
        creation_time = "2025-01-01 10:00:00"
        modification_time = "2025-01-01 11:00:00"

        # Manually calculate expected hash
        hash_input = f"{filename}{filesize}{creation_time}{modification_time}".encode()
        expected_hash = hashlib.sha256(hash_input).hexdigest()

        result_hash = generate_file_hash(filename, filesize, creation_time, modification_time)

        assert result_hash == expected_hash


class TestGenerateRunHash:
    """Test suite for generate_run_hash function."""

    @pytest.fixture
    def sample_files(self):
        """Sample File objects for testing."""
        permissions = Permission(
            owners=[
                UserBase(
                    id=PyObjectId(),
                    email="test@example.com",
                    is_admin=True,
                )
            ]
        )

        return [
            File(
                filename="file1.txt",
                file_location="/path/to/file1.txt",
                creation_time="2025-01-01 10:00:00",
                modification_time="2025-01-01 11:00:00",
                run_id=PyObjectId(),
                data_collection_id=PyObjectId(),
                filesize=1024,
                file_hash="hash1" + "a" * 59,  # 64-character hash
                permissions=permissions,
            ),
            File(
                filename="file2.txt",
                file_location="/path/to/file2.txt",
                creation_time="2025-01-01 10:00:00",
                modification_time="2025-01-01 11:00:00",
                run_id=PyObjectId(),
                data_collection_id=PyObjectId(),
                filesize=2048,
                file_hash="hash2" + "b" * 59,  # 64-character hash
                permissions=permissions,
            ),
        ]

    def test_consistent_hash_generation(self, sample_files):
        """Test that same inputs produce same hash."""
        run_location = "/path/to/run"
        creation_time = "2025-01-01 09:00:00"
        last_modification_time = "2025-01-01 12:00:00"

        hash1 = generate_run_hash(run_location, creation_time, last_modification_time, sample_files)
        hash2 = generate_run_hash(run_location, creation_time, last_modification_time, sample_files)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 produces 64-character hex string

    def test_different_run_locations_different_hashes(self, sample_files):
        """Test that different run locations produce different hashes."""
        creation_time = "2025-01-01 09:00:00"
        last_modification_time = "2025-01-01 12:00:00"

        hash1 = generate_run_hash(
            "/path/to/run1", creation_time, last_modification_time, sample_files
        )
        hash2 = generate_run_hash(
            "/path/to/run2", creation_time, last_modification_time, sample_files
        )

        assert hash1 != hash2

    def test_different_times_different_hashes(self, sample_files):
        """Test that different times produce different hashes."""
        run_location = "/path/to/run"

        hash1 = generate_run_hash(
            run_location, "2025-01-01 09:00:00", "2025-01-01 12:00:00", sample_files
        )
        hash2 = generate_run_hash(
            run_location, "2025-01-01 09:00:01", "2025-01-01 12:00:00", sample_files
        )

        assert hash1 != hash2

    def test_different_files_different_hashes(self):
        """Test that different file lists produce different hashes."""
        run_location = "/path/to/run"
        creation_time = "2025-01-01 09:00:00"
        last_modification_time = "2025-01-01 12:00:00"

        permissions = Permission(
            owners=[
                UserBase(
                    id=PyObjectId(),
                    email="test@example.com",
                    is_admin=True,
                )
            ]
        )

        files1 = [
            File(
                filename="file1.txt",
                file_location="/path/to/file1.txt",
                creation_time="2025-01-01 10:00:00",
                modification_time="2025-01-01 11:00:00",
                run_id=PyObjectId(),
                data_collection_id=PyObjectId(),
                filesize=1024,
                file_hash="hash1" + "a" * 59,
                permissions=permissions,
            )
        ]

        files2 = [
            File(
                filename="file2.txt",
                file_location="/path/to/file2.txt",
                creation_time="2025-01-01 10:00:00",
                modification_time="2025-01-01 11:00:00",
                run_id=PyObjectId(),
                data_collection_id=PyObjectId(),
                filesize=2048,
                file_hash="hash2" + "b" * 59,
                permissions=permissions,
            )
        ]

        hash1 = generate_run_hash(run_location, creation_time, last_modification_time, files1)
        hash2 = generate_run_hash(run_location, creation_time, last_modification_time, files2)

        assert hash1 != hash2

    def test_file_order_independence(self):
        """Test that file order doesn't affect hash (files are sorted internally)."""
        run_location = "/path/to/run"
        creation_time = "2025-01-01 09:00:00"
        last_modification_time = "2025-01-01 12:00:00"

        permissions = Permission(
            owners=[
                UserBase(
                    id=PyObjectId(),
                    email="test@example.com",
                    is_admin=True,
                )
            ]
        )

        file1 = File(
            filename="file1.txt",
            file_location="/path/to/file1.txt",
            creation_time="2025-01-01 10:00:00",
            modification_time="2025-01-01 11:00:00",
            run_id=PyObjectId(),
            data_collection_id=PyObjectId(),
            filesize=1024,
            file_hash="aaaa" + "a" * 60,
            permissions=permissions,
        )

        file2 = File(
            filename="file2.txt",
            file_location="/path/to/file2.txt",
            creation_time="2025-01-01 10:00:00",
            modification_time="2025-01-01 11:00:00",
            run_id=PyObjectId(),
            data_collection_id=PyObjectId(),
            filesize=2048,
            file_hash="bbbb" + "b" * 60,
            permissions=permissions,
        )

        files_order1 = [file1, file2]
        files_order2 = [file2, file1]

        hash1 = generate_run_hash(run_location, creation_time, last_modification_time, files_order1)
        hash2 = generate_run_hash(run_location, creation_time, last_modification_time, files_order2)

        assert hash1 == hash2

    def test_empty_files_list(self):
        """Test hash generation with empty files list."""
        run_location = "/path/to/run"
        creation_time = "2025-01-01 09:00:00"
        last_modification_time = "2025-01-01 12:00:00"

        hash_result = generate_run_hash(run_location, creation_time, last_modification_time, [])

        assert isinstance(hash_result, str)
        assert len(hash_result) == 64

    def test_single_file(self):
        """Test hash generation with single file."""
        run_location = "/path/to/run"
        creation_time = "2025-01-01 09:00:00"
        last_modification_time = "2025-01-01 12:00:00"

        permissions = Permission(
            owners=[
                UserBase(
                    id=PyObjectId(),
                    email="test@example.com",
                    is_admin=True,
                )
            ]
        )

        single_file = [
            File(
                filename="single_file.txt",
                file_location="/path/to/single_file.txt",
                creation_time="2025-01-01 10:00:00",
                modification_time="2025-01-01 11:00:00",
                run_id=PyObjectId(),
                data_collection_id=PyObjectId(),
                filesize=1024,
                file_hash="single" + "a" * 58,  # 64-character hash
                permissions=permissions,
            )
        ]

        hash_result = generate_run_hash(
            run_location, creation_time, last_modification_time, single_file
        )

        assert isinstance(hash_result, str)
        assert len(hash_result) == 64


class TestCheckRunDifferences:
    """Test suite for check_run_differences function."""

    @pytest.fixture
    def sample_user(self):
        """Sample user for testing."""
        return UserBase(
            email="test@example.com",
            is_admin=False,
            id=PyObjectId(),
        )

    @pytest.fixture
    def sample_files(self):
        """Sample File objects for testing."""
        permissions = Permission(
            owners=[
                UserBase(
                    id=PyObjectId(),
                    email="test@example.com",
                    is_admin=True,
                )
            ]
        )

        return [
            File(
                filename="file1.txt",
                file_location="/path/to/file1.txt",
                creation_time="2025-01-01 10:00:00",
                modification_time="2025-01-01 11:00:00",
                run_id=PyObjectId(),
                data_collection_id=PyObjectId(),
                filesize=1024,
                file_hash="hash1" + "a" * 59,
                permissions=permissions,
            ),
            File(
                filename="file2.txt",
                file_location="/path/to/file2.txt",
                creation_time="2025-01-01 10:00:00",
                modification_time="2025-01-01 11:00:00",
                run_id=PyObjectId(),
                data_collection_id=PyObjectId(),
                filesize=2048,
                file_hash="hash2" + "b" * 59,
                permissions=permissions,
            ),
        ]

    @pytest.fixture
    def sample_workflow_run(self, sample_user, sample_files):
        """Sample WorkflowRun for testing."""
        run_location = "/path/to/run"
        creation_time = "2025-01-01 09:00:00"
        last_modification_time = "2025-01-01 12:00:00"

        # Generate the hash for the sample data
        run_hash = generate_run_hash(
            run_location, creation_time, last_modification_time, sample_files
        )

        return WorkflowRun(
            workflow_id=PyObjectId(),
            run_tag="test_run",
            workflow_config_id=PyObjectId(),
            run_location=run_location,
            creation_time=creation_time,
            last_modification_time=last_modification_time,
            run_hash=run_hash,
            files_id=[file.id for file in sample_files],
            permissions=Permission(owners=[sample_user], editors=[], viewers=[]),
        )

    def test_no_differences(self, sample_workflow_run, sample_files):
        """Test when there are no differences between runs."""
        differences = check_run_differences(
            sample_workflow_run,
            sample_workflow_run.run_location,
            sample_workflow_run.creation_time,
            sample_workflow_run.last_modification_time,
            sample_files,
        )

        assert differences == {}

    def test_run_location_difference(self, sample_workflow_run, sample_files):
        """Test detection of run location differences."""
        new_location = "/different/path/to/run"

        differences = check_run_differences(
            sample_workflow_run,
            new_location,
            sample_workflow_run.creation_time,
            sample_workflow_run.last_modification_time,
            sample_files,
        )

        assert "run_location" in differences
        assert differences["run_location"]["previous"] == sample_workflow_run.run_location
        assert differences["run_location"]["current"] == new_location

    def test_creation_time_difference(self, sample_workflow_run, sample_files):
        """Test detection of creation time differences."""
        new_creation_time = "2025-01-01 10:00:00"

        differences = check_run_differences(
            sample_workflow_run,
            sample_workflow_run.run_location,
            new_creation_time,
            sample_workflow_run.last_modification_time,
            sample_files,
        )

        assert "creation_time" in differences
        assert differences["creation_time"]["previous"] == sample_workflow_run.creation_time
        assert differences["creation_time"]["current"] == new_creation_time

    def test_modification_time_difference(self, sample_workflow_run, sample_files):
        """Test detection of last modification time differences."""
        new_modification_time = "2025-01-01 13:00:00"

        differences = check_run_differences(
            sample_workflow_run,
            sample_workflow_run.run_location,
            sample_workflow_run.creation_time,
            new_modification_time,
            sample_files,
        )

        assert "last_modification_time" in differences
        assert (
            differences["last_modification_time"]["previous"]
            == sample_workflow_run.last_modification_time
        )
        assert differences["last_modification_time"]["current"] == new_modification_time

    def test_files_difference(self, sample_workflow_run):
        """Test detection of files differences."""
        permissions = Permission(
            owners=[
                UserBase(
                    id=PyObjectId(),
                    email="test@example.com",
                    is_admin=True,
                )
            ]
        )

        new_files = [
            File(
                filename="file3.txt",
                file_location="/path/to/file3.txt",
                creation_time="2025-01-01 10:00:00",
                modification_time="2025-01-01 11:00:00",
                run_id=PyObjectId(),
                data_collection_id=PyObjectId(),
                filesize=3072,
                file_hash="hash3" + "c" * 59,
                permissions=permissions,
            )
        ]

        differences = check_run_differences(
            sample_workflow_run,
            sample_workflow_run.run_location,
            sample_workflow_run.creation_time,
            sample_workflow_run.last_modification_time,
            new_files,
        )

        assert "files" in differences
        assert differences["files"]["previous"] == sample_workflow_run.files_id
        assert differences["files"]["current"] == [file.id for file in new_files]

    def test_multiple_differences(self, sample_workflow_run):
        """Test detection of multiple differences."""
        new_location = "/different/path"
        new_creation_time = "2025-01-01 10:00:00"

        permissions = Permission(
            owners=[
                UserBase(
                    id=PyObjectId(),
                    email="test@example.com",
                    is_admin=True,
                )
            ]
        )

        new_files = [
            File(
                filename="file4.txt",
                file_location="/path/to/file4.txt",
                creation_time="2025-01-01 10:00:00",
                modification_time="2025-01-01 11:00:00",
                run_id=PyObjectId(),
                data_collection_id=PyObjectId(),
                filesize=4096,
                file_hash="hash4" + "d" * 59,
                permissions=permissions,
            )
        ]

        differences = check_run_differences(
            sample_workflow_run,
            new_location,
            new_creation_time,
            sample_workflow_run.last_modification_time,
            new_files,
        )

        assert "run_location" in differences
        assert "creation_time" in differences
        assert len(differences) == 2  # Should detect location and time changes first

    def test_hash_consistency_check(self, sample_workflow_run, sample_files):
        """Test that identical data produces no differences via hash check."""
        # Create identical conditions - need to ensure exact same IDs and properties
        identical_files = []
        for file in sample_files:
            identical_file = File(
                id=file.id,  # Use same ID
                filename=file.filename,
                file_location=file.file_location,
                creation_time=file.creation_time,
                modification_time=file.modification_time,
                run_id=file.run_id,
                data_collection_id=file.data_collection_id,
                filesize=file.filesize,
                file_hash=file.file_hash,
                permissions=file.permissions,
            )
            identical_files.append(identical_file)

        differences = check_run_differences(
            sample_workflow_run,
            sample_workflow_run.run_location,
            sample_workflow_run.creation_time,
            sample_workflow_run.last_modification_time,
            identical_files,
        )

        assert differences == {}

    @patch("depictio.cli.cli.utils.scan_utils.logger")
    def test_logging_behavior(self, mock_logger, sample_workflow_run, sample_files):
        """Test that appropriate warning logs are generated."""
        new_location = "/different/path/to/run"

        check_run_differences(
            sample_workflow_run,
            new_location,
            sample_workflow_run.creation_time,
            sample_workflow_run.last_modification_time,
            sample_files,
        )

        # Verify that warning logs were called
        mock_logger.warning.assert_called()
        warning_calls = [call.args[0] for call in mock_logger.warning.call_args_list]
        assert any("Hash mismatch" in call for call in warning_calls)
        assert any("Run location changed" in call for call in warning_calls)
