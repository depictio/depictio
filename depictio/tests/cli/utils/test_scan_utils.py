import hashlib
import re
from unittest.mock import patch

import pytest

# Import the functions to test
from depictio.cli.cli.utils import scan_utils
from depictio.cli.cli.utils.scan_utils import (
    check_run_differences,
    collect_run_candidates,
    construct_full_regex,
    count_data_collection_matches,
    describe_empty_scan_outcome,
    describe_unmatched_run_scan,
    file_matches_data_collection,
    generate_file_hash,
    generate_run_hash,
    regex_match,
    resolve_run_locations,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.data_collections import DataCollection, Regex, WildcardRegexBase
from depictio.models.models.files import File
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import Workflow, WorkflowRun


@pytest.fixture(autouse=True)
def set_depictio_context(monkeypatch):
    """Set DEPICTIO_CONTEXT for all tests in the module."""
    monkeypatch.setattr("depictio.models.config.DEPICTIO_CONTEXT", "server")
    monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "server")


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

    # @pytest.fixture(autouse=True)
    # def set_depictio_context(self, monkeypatch):
    #     """Set DEPICTIO_CONTEXT for all tests."""
    #     monkeypatch.setattr("depictio.models.config.DEPICTIO_CONTEXT", "server")
    #     monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "server")

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


class TestDescribeUnmatchedRunScan:
    """A `sequencing-runs` scan that matches nothing must say why."""

    def test_names_the_location_the_pattern_and_what_was_there(self):
        message = describe_unmatched_run_scan(
            "/data/results", r"^run_\d+$", ["multiqc", "qiime2", "pipeline_info"]
        )

        assert "/data/results" in message
        assert r"^run_\d+$" in message
        # The listing is the part that turns "0 runs" into "wrong level".
        assert "multiqc" in message and "qiime2" in message
        assert "--data-root" in message

    def test_an_empty_directory_says_so_rather_than_listing_nothing(self):
        message = describe_unmatched_run_scan("/data/results", r"^run_\d+$", [])

        assert "no subdirectories at all" in message
        assert "--data-root" not in message, "there is no level to move to; say the simpler thing"

    def test_a_long_listing_is_truncated_but_counted(self):
        subdirs = [f"sample_{i}" for i in range(25)]

        message = describe_unmatched_run_scan("/data", "^run", subdirs)

        assert "25 subdirectories" in message
        assert "and 15 more" in message
        assert "sample_0" in message
        assert "sample_24" not in message

    def test_a_single_subdirectory_is_not_pluralised(self):
        message = describe_unmatched_run_scan("/data", "^run", ["only_one"])

        assert "1 subdirectory:" in message


class TestDescribeEmptyScanOutcome:
    """Distinguish a broken scan from a scan that had nothing new to do."""

    def test_nothing_recognised_at_all_is_a_data_root_problem(self):
        message = describe_empty_scan_outcome(runs_scanned=0, files_found=0)

        assert message is not None
        assert "--data-root" in message

    def test_every_run_already_ingested_is_a_legitimate_no_op(self):
        """The common case of re-running the CLI with nothing new. Warning here
        would cry wolf on every repeat run and train the user to ignore it."""
        assert (
            describe_empty_scan_outcome(runs_scanned=0, files_found=0, runs_skipped_as_existing=12)
            is None
        )

    def test_runs_without_files_blames_the_patterns_not_the_data_root(self):
        message = describe_empty_scan_outcome(runs_scanned=3, files_found=0)

        assert message is not None
        assert "no file matched any data collection" in message
        assert "--data-root" not in message

    def test_a_scan_that_found_something_is_silent(self):
        assert describe_empty_scan_outcome(runs_scanned=2, files_found=17) is None


class TestFileMatchesDataCollection:
    """The single matcher shared by the scanner and the dry-run preview."""

    def test_matches_on_the_basename(self):
        assert file_matches_data_collection(
            "/runs/run_1/nested/sample.csv", "/runs/run_1", r".*\.csv"
        )

    def test_path_shaped_pattern_matches_the_run_relative_path(self):
        assert file_matches_data_collection(
            "/runs/run_1/variants/bowtie2/calls.vcf", "/runs/run_1", r"variants/bowtie2/.*\.vcf"
        )

    def test_a_plain_pattern_does_not_match_through_a_directory_name(self):
        """Without a separator the pattern is a filename pattern. Falling back to
        the relative path here would let a directory called `variants` pull in
        every file beneath it."""
        assert not file_matches_data_collection(
            "/runs/run_1/variants/calls.vcf", "/runs/run_1", r"variants"
        )

    def test_no_match(self):
        assert not file_matches_data_collection("/runs/run_1/sample.txt", "/runs/run_1", r".*\.csv")


class TestCollectRunCandidates:
    """Run enumeration, shared so the preview and the scan agree on what a run is."""

    def test_a_flat_location_is_itself_one_run(self, tmp_path):
        candidates = collect_run_candidates(str(tmp_path / "my_run"), "flat")

        assert candidates.matched == [("my_run", str(tmp_path / "my_run"))]
        assert candidates.subdirectories == []

    def test_sequencing_runs_keeps_unmatched_subdirectories_for_the_error_message(self, tmp_path):
        (tmp_path / "run_1").mkdir()
        (tmp_path / "run_2").mkdir()
        (tmp_path / "results").mkdir()
        (tmp_path / "samplesheet.csv").write_text("a,b\n")

        candidates = collect_run_candidates(str(tmp_path), "sequencing-runs", "^run_")

        assert [tag for tag, _ in candidates.matched] == ["run_1", "run_2"]
        assert candidates.subdirectories == ["results", "run_1", "run_2"]

    def test_a_missing_regex_matches_nothing(self, tmp_path):
        (tmp_path / "run_1").mkdir()

        candidates = collect_run_candidates(str(tmp_path), "sequencing-runs", None)

        assert candidates.matched == []
        assert candidates.subdirectories == ["run_1"]


class TestCountDataCollectionMatches:
    """The dry-run file counts."""

    @staticmethod
    def _recursive_dc(pattern: str) -> DataCollection:
        return DataCollection(
            data_collection_tag="tab",
            config={
                "type": "table",
                "scan": {
                    "mode": "recursive",
                    "scan_parameters": {"regex_config": {"pattern": pattern}},
                },
                "dc_specific_properties": {"format": "csv"},
            },
        )

    def test_counts_matching_files_across_every_run(self, tmp_path):
        for run in ("run_1", "run_2"):
            nested = tmp_path / run / "tables"
            nested.mkdir(parents=True)
            (nested / "counts.csv").write_text("a\n")
            (nested / "notes.txt").write_text("a\n")

        counts = count_data_collection_matches(
            [self._recursive_dc(r".*\.csv")],
            [str(tmp_path / "run_1"), str(tmp_path / "run_2")],
        )

        assert counts == [2]

    def test_a_pattern_that_matches_nothing_counts_zero(self, tmp_path):
        (tmp_path / "run_1").mkdir()
        (tmp_path / "run_1" / "counts.tsv").write_text("a\n")

        counts = count_data_collection_matches(
            [self._recursive_dc(r".*\.csv")], [str(tmp_path / "run_1")]
        )

        assert counts == [0]

    def test_every_collection_is_counted_in_one_walk(self, tmp_path, monkeypatch):
        """Each run directory is walked once and every pattern tested against
        that one listing, as the scanner does. Walking per collection would be
        N times the I/O for the same answer."""
        nested = tmp_path / "run_1" / "tables"
        nested.mkdir(parents=True)
        (nested / "counts.csv").write_text("a\n")
        (nested / "counts.tsv").write_text("a\n")
        (nested / "notes.txt").write_text("a\n")

        walked: list[str] = []
        real_walk = scan_utils.os.walk
        monkeypatch.setattr(
            scan_utils.os,
            "walk",
            lambda top, *args, **kwargs: (walked.append(top), real_walk(top, *args, **kwargs))[1],
        )

        counts = count_data_collection_matches(
            [self._recursive_dc(r".*\.csv"), self._recursive_dc(r".*\.tsv")],
            [str(tmp_path / "run_1")],
        )

        assert counts == [1, 1]
        assert walked == [str(tmp_path / "run_1")]

    def test_a_single_file_collection_counts_its_one_file(self, tmp_path):
        metadata = tmp_path / "metadata.csv"
        metadata.write_text("a\n")
        dc = DataCollection(
            data_collection_tag="meta",
            config={
                "type": "table",
                "scan": {"mode": "single", "scan_parameters": {"filename": str(metadata)}},
                "dc_specific_properties": {"format": "csv"},
            },
        )

        assert count_data_collection_matches([dc], []) == [1]

        metadata.unlink()
        assert count_data_collection_matches([dc], []) == [0]

    def test_a_capitalised_mode_is_counted_the_way_it_is_scanned(self, tmp_path):
        """The model stores the spelling the config used, while the scanner
        compares `scan.mode.lower()`. A preview that did not would report
        "unknown" for a collection the scan handles fine."""
        run = tmp_path / "run_1"
        run.mkdir()
        (run / "counts.csv").write_text("a\n")
        dc = DataCollection(
            data_collection_tag="tab",
            config={
                "type": "table",
                "scan": {
                    "mode": "Recursive",
                    "scan_parameters": {"regex_config": {"pattern": r".*\.csv"}},
                },
                "dc_specific_properties": {"format": "csv"},
            },
        )

        assert count_data_collection_matches([dc], [str(run)]) == [1]

    def test_a_collection_with_no_scan_is_unknown_rather_than_zero(self):
        """A derived collection has no files to count. Reporting 0 would send the
        user hunting for a data-root problem that does not exist."""
        dc = DataCollection(
            data_collection_tag="joined",
            config={
                "type": "table",
                "source": "joined",
                "dc_specific_properties": {"format": "parquet"},
            },
        )

        assert count_data_collection_matches([dc], []) == [None]


class TestResolveRunLocations:
    """Run directories the preview walks, resolved from a workflow."""

    @staticmethod
    def _workflow(structure: str, locations: list[str], runs_regex: str | None = None) -> Workflow:
        data_location: dict = {"structure": structure, "locations": locations}
        if runs_regex:
            data_location["runs_regex"] = runs_regex
        return Workflow(
            name="wf",
            engine={"name": "snakemake"},
            data_location=data_location,
            data_collections=[],
        )

    def test_resolves_each_matching_run_directory(self, tmp_path):
        (tmp_path / "run_1").mkdir()
        (tmp_path / "run_2").mkdir()
        (tmp_path / "logs").mkdir()

        resolved = resolve_run_locations(
            self._workflow("sequencing-runs", [str(tmp_path)], "^run_")
        )

        assert resolved.locations == [str(tmp_path / "run_1"), str(tmp_path / "run_2")]
        assert resolved.warnings == []

    def test_a_location_that_does_not_exist_is_a_warning_not_an_exception(self, tmp_path):
        """The preview reports it; crashing would hide every other data
        collection's count behind one bad path."""
        workflow = self._workflow("flat", [str(tmp_path)])
        workflow.data_location.locations = [str(tmp_path / "gone")]

        resolved = resolve_run_locations(workflow)

        assert resolved.locations == []
        assert "does not exist" in resolved.warnings[0]

    def test_a_data_root_one_level_too_deep_names_what_it_looked_at(self, tmp_path):
        """The failure the dry run exists to catch: --data-root pointing inside a
        run instead of at the parent of the runs."""
        (tmp_path / "tables").mkdir()
        (tmp_path / "multiqc").mkdir()

        resolved = resolve_run_locations(
            self._workflow("sequencing-runs", [str(tmp_path)], "^run_")
        )

        assert resolved.locations == []
        assert "tables" in resolved.warnings[0]
        assert "multiqc" in resolved.warnings[0]

    def test_a_flat_workflow_is_never_warned_about(self, tmp_path):
        """Its single location is the run, so there is no pattern to fail to match."""
        resolved = resolve_run_locations(self._workflow("flat", [str(tmp_path)]))

        assert resolved.locations == [str(tmp_path)]
        assert resolved.warnings == []
