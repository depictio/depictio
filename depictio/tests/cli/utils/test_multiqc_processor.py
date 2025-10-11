"""Tests for MultiQC processor utilities."""

from unittest.mock import MagicMock, patch

import pytest

from depictio.cli.cli.utils.multiqc_processor import (
    extract_multiqc_metadata,
    process_multiqc_data_collection,
    validate_multiqc_parquet,
)


class TestMultiQCProcessor:
    """Test suite for MultiQC processor functionality."""

    @pytest.fixture
    def mock_multiqc_module(self):
        """Mock the multiqc module for testing."""
        mock_multiqc = MagicMock()
        mock_multiqc.reset.return_value = None
        mock_multiqc.parse_logs.return_value = None
        mock_multiqc.list_samples.return_value = ["sample1", "sample2", "sample3"]
        mock_multiqc.list_modules.return_value = ["fastqc", "cutadapt"]
        mock_multiqc.list_plots.return_value = {
            "fastqc": ["quality", "length"],
            "cutadapt": ["trimmed"],
        }
        return mock_multiqc

    @pytest.fixture
    def sample_data_collection(self):
        """Create a mock data collection for testing."""
        data_collection = MagicMock()
        data_collection.id = "507f1f77bcf86cd799439012"
        data_collection.data_collection_tag = "test_multiqc"
        data_collection.config = MagicMock()
        data_collection.config.model_copy.return_value = MagicMock()
        return data_collection

    @pytest.fixture
    def sample_cli_config(self):
        """Create a mock CLI config for testing."""
        cli_config = MagicMock()
        cli_config.s3_storage = MagicMock()
        cli_config.s3_storage.bucket = "test-bucket"
        cli_config.api_url = "http://localhost:8000"
        return cli_config

    @pytest.fixture
    def sample_workflow(self):
        """Create a mock workflow for testing."""
        workflow = MagicMock()
        workflow.data_location = MagicMock()
        workflow.data_location.locations = ["/test/data/location"]
        return workflow

    @patch("depictio.api.v1.endpoints.multiqc_endpoints.utils.build_sample_mapping")
    def test_extract_multiqc_metadata_success(self, mock_build_sample_mapping, mock_multiqc_module):
        """Test successful metadata extraction from MultiQC parquet file."""
        # Mock build_sample_mapping to avoid database connection
        mock_build_sample_mapping.return_value = {
            "sample1": ["sample1"],
            "sample2": ["sample2"],
            "sample3": ["sample3"],
        }

        # Patch multiqc at sys.modules level to intercept import
        import sys

        with patch.dict(sys.modules, {"multiqc": mock_multiqc_module}):
            result = extract_multiqc_metadata("/path/to/multiqc.parquet")

            # Verify multiqc module calls
            mock_multiqc_module.reset.assert_called_once()
            mock_multiqc_module.parse_logs.assert_called_once_with("/path/to/multiqc.parquet")
            mock_multiqc_module.list_samples.assert_called_once()
            mock_multiqc_module.list_modules.assert_called_once()
            mock_multiqc_module.list_plots.assert_called_once()

            # Verify extracted metadata
            assert result["samples"] == ["sample1", "sample2", "sample3"]
            assert result["modules"] == ["fastqc", "cutadapt"]
            assert result["plots"] == {"fastqc": ["quality", "length"], "cutadapt": ["trimmed"]}

    @patch("depictio.api.v1.endpoints.multiqc_endpoints.utils.build_sample_mapping")
    def test_extract_multiqc_metadata_plots_error(
        self, mock_build_sample_mapping, mock_multiqc_module
    ):
        """Test metadata extraction when plots extraction fails."""
        # Configure plots to raise an exception
        mock_multiqc_module.list_plots.side_effect = Exception("Plots extraction failed")

        # Mock build_sample_mapping to avoid database connection
        mock_build_sample_mapping.return_value = {
            "sample1": ["sample1"],
            "sample2": ["sample2"],
            "sample3": ["sample3"],
        }

        # Patch multiqc at sys.modules level to intercept import
        import sys

        with patch.dict(sys.modules, {"multiqc": mock_multiqc_module}):
            result = extract_multiqc_metadata("/path/to/multiqc.parquet")

            # Should still return samples and modules, but empty plots
            assert result["samples"] == ["sample1", "sample2", "sample3"]
            assert result["modules"] == ["fastqc", "cutadapt"]
            assert result["plots"] == {}

    def test_extract_multiqc_metadata_import_error(self):
        """Test handling of missing multiqc module."""
        # Patch sys.modules to make multiqc import fail
        import builtins
        import sys

        # Save original import
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "multiqc":
                raise ImportError("No module named 'multiqc'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            # Also ensure multiqc is not in sys.modules
            with patch.dict(sys.modules, {"multiqc": None}, clear=False):
                sys.modules.pop("multiqc", None)
                with pytest.raises(ImportError):
                    extract_multiqc_metadata("/path/to/multiqc.parquet")

    def test_extract_multiqc_metadata_parse_error(self, mock_multiqc_module):
        """Test handling of parse errors."""
        mock_multiqc_module.parse_logs.side_effect = Exception("Parse failed")

        import sys

        with patch.dict(sys.modules, {"multiqc": mock_multiqc_module}):
            with pytest.raises(Exception) as exc_info:
                extract_multiqc_metadata("/path/to/multiqc.parquet")
            assert "Parse failed" in str(exc_info.value)

    def test_validate_multiqc_parquet_success(self, mock_multiqc_module):
        """Test successful validation of MultiQC parquet file."""
        import sys

        with patch.dict(sys.modules, {"multiqc": mock_multiqc_module}):
            result = validate_multiqc_parquet("/path/to/multiqc.parquet")

            assert result is True
            mock_multiqc_module.reset.assert_called_once()
            mock_multiqc_module.parse_logs.assert_called_once_with("/path/to/multiqc.parquet")

    def test_validate_multiqc_parquet_no_data(self, mock_multiqc_module):
        """Test validation failure when no samples or modules found."""
        mock_multiqc_module.list_samples.return_value = []
        mock_multiqc_module.list_modules.return_value = []

        import sys

        with patch.dict(sys.modules, {"multiqc": mock_multiqc_module}):
            result = validate_multiqc_parquet("/path/to/multiqc.parquet")

            assert result is False

    def test_validate_multiqc_parquet_exception(self, mock_multiqc_module):
        """Test validation handling of exceptions."""
        mock_multiqc_module.parse_logs.side_effect = Exception("Invalid file")

        import sys

        with patch.dict(sys.modules, {"multiqc": mock_multiqc_module}):
            result = validate_multiqc_parquet("/path/to/multiqc.parquet")

            assert result is False

    def test_process_multiqc_data_collection_no_files_in_db(
        self, sample_data_collection, sample_cli_config, sample_workflow, mock_multiqc_module
    ):
        """Test processing when no files found in database."""
        # Mock no files found in database
        with patch("depictio.cli.cli.utils.deltatables.fetch_file_data") as mock_fetch:
            mock_fetch.side_effect = Exception("No files found")

            # Mock no files found in filesystem either
            with patch("glob.glob") as mock_glob:
                mock_glob.return_value = []

                with patch("depictio.cli.cli.utils.multiqc_processor.Path") as mock_path:
                    # Mock Path instance for path checking
                    mock_path.return_value.exists.return_value = False

                    # Mock Path.cwd() to return a mock instead of real Path
                    mock_cwd = MagicMock()
                    mock_cwd.iterdir.return_value = []
                    mock_path.cwd.return_value = mock_cwd

                    result = process_multiqc_data_collection(
                        sample_data_collection, sample_cli_config, workflow=sample_workflow
                    )

                    assert result["result"] == "error"
                    assert "No MultiQC parquet files found" in result["message"]

    @patch("depictio.api.v1.endpoints.multiqc_endpoints.utils.build_sample_mapping")
    def test_process_multiqc_data_collection_file_discovery(
        self,
        mock_build_sample_mapping,
        sample_data_collection,
        sample_cli_config,
        sample_workflow,
        mock_multiqc_module,
    ):
        """Test processing with file discovery from workflow data locations."""
        # Mock build_sample_mapping to avoid database connection
        mock_build_sample_mapping.return_value = {
            "sample1": ["sample1"],
            "sample2": ["sample2"],
            "sample3": ["sample3"],
        }

        # Mock no files found in database
        with patch("depictio.cli.cli.utils.deltatables.fetch_file_data") as mock_fetch:
            mock_fetch.side_effect = Exception("No files found")

            # Mock glob finding files
            with patch("glob.glob") as mock_glob:
                mock_glob.return_value = ["/test/data/location/run1/multiqc_data/multiqc.parquet"]

                # Mock api_check_duplicate_multiqc_report to avoid Pydantic validation errors
                with patch(
                    "depictio.cli.cli.utils.multiqc_processor.api_check_duplicate_multiqc_report"
                ) as mock_check_duplicate:
                    mock_check_duplicate.return_value = None  # No duplicate found

                    # Mock file operations
                    with patch("depictio.cli.cli.utils.multiqc_processor.Path") as mock_path:
                        # Make exists() selective - only return True for the glob-returned file
                        def mock_exists_for_path(path_str):
                            # Return True only for the file from glob
                            return (
                                str(path_str)
                                == "/test/data/location/run1/multiqc_data/multiqc.parquet"
                            )

                        mock_path_instance = MagicMock()
                        mock_path_instance.exists = MagicMock(
                            side_effect=lambda: mock_exists_for_path(mock_path_instance._path)
                        )

                        # Mock absolute() to return a mock instead of real Path
                        mock_absolute = MagicMock()
                        mock_absolute.__str__.return_value = (
                            "/test/data/location/run1/multiqc_data/multiqc.parquet"
                        )
                        mock_path_instance.absolute.return_value = mock_absolute

                        mock_path_instance.stat.return_value.st_size = 1024000

                        # Configure Path() to return our mock instance and track the path
                        def path_constructor(path_str):
                            mock_path_instance._path = str(path_str)
                            return mock_path_instance

                        mock_path.side_effect = path_constructor

                        # Mock S3 and API operations
                        import sys

                        with patch.dict(sys.modules, {"multiqc": mock_multiqc_module}):
                            with patch(
                                "depictio.models.s3_utils.turn_S3_config_into_polars_storage_options"
                            ) as mock_s3_opts:
                                mock_s3_opts.return_value = MagicMock(
                                    endpoint_url="http://localhost:9000",
                                    aws_access_key_id="test",
                                    aws_secret_access_key="test",
                                    region="us-east-1",
                                )

                                with patch("boto3.client") as mock_boto3_client:
                                    mock_s3_client = MagicMock()
                                    mock_boto3_client.return_value = mock_s3_client

                                    with patch(
                                        "depictio.cli.cli.utils.multiqc_processor.api_create_multiqc_report"
                                    ) as mock_api:
                                        mock_response = MagicMock()
                                        mock_response.status_code = 200
                                        mock_response.json.return_value = {
                                            "report": {"id": "saved_report_id"}
                                        }
                                        mock_api.return_value = mock_response

                                        result = process_multiqc_data_collection(
                                            sample_data_collection,
                                            sample_cli_config,
                                            workflow=sample_workflow,
                                        )

                                        assert result["result"] == "success"
                                        assert "Processed 1 MultiQC files" in result["message"]

                                        # Verify S3 upload was called
                                        mock_s3_client.upload_file.assert_called_once()

                                        # Verify API call was made
                                        mock_api.assert_called_once()

    @patch("depictio.api.v1.endpoints.multiqc_endpoints.utils.build_sample_mapping")
    def test_process_multiqc_data_collection_with_existing_files(
        self,
        mock_build_sample_mapping,
        sample_data_collection,
        sample_cli_config,
        mock_multiqc_module,
    ):
        """Test processing with files already in database."""
        # Mock build_sample_mapping to avoid database connection
        mock_build_sample_mapping.return_value = {
            "sample1": ["sample1"],
            "sample2": ["sample2"],
            "sample3": ["sample3"],
        }

        # Mock files found in database
        mock_file = MagicMock()
        mock_file.file_location = "/path/to/multiqc.parquet"

        with patch("depictio.cli.cli.utils.deltatables.fetch_file_data") as mock_fetch:
            mock_fetch.return_value = [mock_file]

            # Mock api_check_duplicate_multiqc_report to avoid Pydantic validation errors
            with patch(
                "depictio.cli.cli.utils.multiqc_processor.api_check_duplicate_multiqc_report"
            ) as mock_check_duplicate:
                mock_check_duplicate.return_value = None  # No duplicate found

                # Mock file operations
                with patch("depictio.cli.cli.utils.multiqc_processor.Path") as mock_path:
                    mock_path_instance = MagicMock()
                    mock_path_instance.exists.return_value = True
                    mock_path_instance.stat.return_value.st_size = 2048000
                    mock_path.return_value = mock_path_instance

                    # Mock S3 and API operations
                    import sys

                    with patch.dict(sys.modules, {"multiqc": mock_multiqc_module}):
                        with patch(
                            "depictio.models.s3_utils.turn_S3_config_into_polars_storage_options"
                        ) as mock_s3_opts:
                            mock_s3_opts.return_value = MagicMock(
                                endpoint_url="http://localhost:9000",
                                aws_access_key_id="test",
                                aws_secret_access_key="test",
                                region="us-east-1",
                            )

                            with patch("boto3.client") as mock_boto3_client:
                                mock_s3_client = MagicMock()
                                mock_boto3_client.return_value = mock_s3_client

                                with patch(
                                    "depictio.cli.cli.utils.multiqc_processor.api_create_multiqc_report"
                                ) as mock_api:
                                    mock_response = MagicMock()
                                    mock_response.status_code = 200
                                    mock_response.json.return_value = {
                                        "report": {"id": "saved_report_id"}
                                    }
                                    mock_api.return_value = mock_response

                                    result = process_multiqc_data_collection(
                                        sample_data_collection, sample_cli_config
                                    )

                                    assert result["result"] == "success"
                                    assert "metadata" in result
                                    assert set(result["metadata"]["samples"]) == {  # type: ignore[index]
                                        "sample1",
                                        "sample2",
                                        "sample3",
                                    }

                                    # Verify API call was made after function execution
                                    mock_api.assert_called_once()

    @patch("depictio.api.v1.endpoints.multiqc_endpoints.utils.build_sample_mapping")
    def test_process_multiqc_data_collection_s3_upload_failure(
        self,
        mock_build_sample_mapping,
        sample_data_collection,
        sample_cli_config,
        mock_multiqc_module,
    ):
        """Test handling of S3 upload failures."""
        # Mock build_sample_mapping to avoid database connection
        mock_build_sample_mapping.return_value = {
            "sample1": ["sample1"],
            "sample2": ["sample2"],
            "sample3": ["sample3"],
        }

        mock_file = MagicMock()
        mock_file.file_location = "/path/to/multiqc.parquet"

        with patch("depictio.cli.cli.utils.deltatables.fetch_file_data") as mock_fetch:
            mock_fetch.return_value = [mock_file]

            # Mock api_check_duplicate_multiqc_report to avoid Pydantic validation errors
            with patch(
                "depictio.cli.cli.utils.multiqc_processor.api_check_duplicate_multiqc_report"
            ) as mock_check_duplicate:
                mock_check_duplicate.return_value = None  # No duplicate found

                with patch("depictio.cli.cli.utils.multiqc_processor.Path") as mock_path:
                    mock_path_instance = MagicMock()
                    mock_path_instance.exists.return_value = True
                    mock_path_instance.stat.return_value.st_size = 1024000
                    mock_path.return_value = mock_path_instance

                    import sys

                    with patch.dict(sys.modules, {"multiqc": mock_multiqc_module}):
                        with patch(
                            "depictio.models.s3_utils.turn_S3_config_into_polars_storage_options"
                        ):
                            with patch("boto3.client") as mock_boto3_client:
                                mock_s3_client = MagicMock()
                                mock_s3_client.upload_file.side_effect = Exception(
                                    "S3 upload failed"
                                )
                                mock_boto3_client.return_value = mock_s3_client

                                result = process_multiqc_data_collection(
                                    sample_data_collection, sample_cli_config
                                )

                                # Function succeeds if metadata extraction works, even if S3 upload fails
                                assert result["result"] == "success"
                                assert "metadata" in result
                                assert "Processed 1 MultiQC files" in result["message"]

    @patch("depictio.api.v1.endpoints.multiqc_endpoints.utils.build_sample_mapping")
    def test_process_multiqc_data_collection_api_failure(
        self,
        mock_build_sample_mapping,
        sample_data_collection,
        sample_cli_config,
        mock_multiqc_module,
    ):
        """Test handling of API save failures."""
        # Mock build_sample_mapping to avoid database connection
        mock_build_sample_mapping.return_value = {
            "sample1": ["sample1"],
            "sample2": ["sample2"],
            "sample3": ["sample3"],
        }

        mock_file = MagicMock()
        mock_file.file_location = "/path/to/multiqc.parquet"

        with patch("depictio.cli.cli.utils.deltatables.fetch_file_data") as mock_fetch:
            mock_fetch.return_value = [mock_file]

            with patch("depictio.cli.cli.utils.multiqc_processor.Path") as mock_path:
                mock_path_instance = MagicMock()
                mock_path_instance.exists.return_value = True
                mock_path_instance.stat.return_value.st_size = 1024000
                mock_path.return_value = mock_path_instance

                import sys

                with patch.dict(sys.modules, {"multiqc": mock_multiqc_module}):
                    with patch(
                        "depictio.models.s3_utils.turn_S3_config_into_polars_storage_options"
                    ):
                        with patch("boto3.client") as mock_boto3_client:
                            mock_s3_client = MagicMock()
                            mock_boto3_client.return_value = mock_s3_client

                            with patch(
                                "depictio.cli.cli.utils.multiqc_processor.api_create_multiqc_report"
                            ) as mock_api:
                                mock_response = MagicMock()
                                mock_response.status_code = 500
                                mock_response.text = "Internal server error"
                                mock_response.json.side_effect = Exception("JSON decode error")
                                mock_api.return_value = mock_response

                                # Should still succeed even if API save fails
                                result = process_multiqc_data_collection(
                                    sample_data_collection, sample_cli_config
                                )

                                assert result["result"] == "success"
                                assert "Processed 1 MultiQC files" in result["message"]

    def test_process_multiqc_data_collection_non_parquet_files(
        self, sample_data_collection, sample_cli_config, mock_multiqc_module
    ):
        """Test processing with non-parquet files (should be skipped)."""
        mock_file = MagicMock()
        mock_file.file_location = "/path/to/data.txt"  # Non-parquet file

        with patch("depictio.cli.cli.utils.deltatables.fetch_file_data") as mock_fetch:
            mock_fetch.return_value = [mock_file]

            # Mock turn_S3_config_into_polars_storage_options to avoid Pydantic validation
            with patch("depictio.models.s3_utils.turn_S3_config_into_polars_storage_options"):
                result = process_multiqc_data_collection(sample_data_collection, sample_cli_config)

                assert result["result"] == "error"
                assert "No MultiQC parquet files were successfully processed" in result["message"]

    def test_process_multiqc_data_collection_metadata_merging(
        self, sample_data_collection, sample_cli_config, mock_multiqc_module
    ):
        """Test metadata merging from multiple files."""
        # Mock multiple files
        mock_file1 = MagicMock()
        mock_file1.file_location = "/path/to/multiqc1.parquet"
        mock_file2 = MagicMock()
        mock_file2.file_location = "/path/to/multiqc2.parquet"

        # Configure different metadata for second file
        def mock_extract_metadata(file_path):
            if "multiqc1" in file_path:
                return {
                    "samples": ["sample1", "sample2"],
                    "modules": ["fastqc"],
                    "plots": {"fastqc": ["quality"]},
                }
            else:
                return {
                    "samples": ["sample3", "sample4"],
                    "modules": ["cutadapt"],
                    "plots": {"cutadapt": ["trimmed"]},
                }

        with patch("depictio.cli.cli.utils.deltatables.fetch_file_data") as mock_fetch:
            mock_fetch.return_value = [mock_file1, mock_file2]

            with patch("depictio.cli.cli.utils.multiqc_processor.Path") as mock_path:
                mock_path_instance = MagicMock()
                mock_path_instance.exists.return_value = True
                mock_path_instance.stat.return_value.st_size = 1024000
                mock_path.return_value = mock_path_instance

                with patch(
                    "depictio.cli.cli.utils.multiqc_processor.extract_multiqc_metadata"
                ) as mock_extract:
                    mock_extract.side_effect = mock_extract_metadata

                    with patch(
                        "depictio.models.s3_utils.turn_S3_config_into_polars_storage_options"
                    ):
                        with patch("boto3.client") as mock_boto3_client:
                            mock_s3_client = MagicMock()
                            mock_boto3_client.return_value = mock_s3_client

                            with patch(
                                "depictio.cli.cli.utils.multiqc_processor.api_create_multiqc_report"
                            ) as mock_api:
                                mock_response = MagicMock()
                                mock_response.status_code = 200
                                mock_response.json.return_value = {"report": {"id": "test_id"}}
                                mock_api.return_value = mock_response

                                result = process_multiqc_data_collection(
                                    sample_data_collection, sample_cli_config
                                )

                                assert result["result"] == "success"
                                assert "metadata" in result

                                # Check merged metadata (duplicates should be removed)
                                merged_samples = result["metadata"]["samples"]  # type: ignore[index]
                                merged_modules = result["metadata"]["modules"]  # type: ignore[index]
                                merged_plots = result["metadata"]["plots"]  # type: ignore[index]

                                assert set(merged_samples) == {
                                    "sample1",
                                    "sample2",
                                    "sample3",
                                    "sample4",
                                }
                                assert set(merged_modules) == {"fastqc", "cutadapt"}
                                assert "fastqc" in merged_plots
                                assert "cutadapt" in merged_plots

    def test_extract_multiqc_metadata_real_world_structure(self, mock_multiqc_module):
        """Test metadata extraction with real-world complex data structure."""
        # Configure mock to return complex real-world data
        mock_multiqc_module.list_samples.return_value = [
            "NMP_R2_L1_2_val_2",
            "NMP_R1_L2_1_val_1",
            "test_2",
            "test_1 - polya",
            "sample1_S1_L001_R2_001",
            "NMP_R1_L2_1",
            "NMP_R1_L1_1_val_1",
        ]
        mock_multiqc_module.list_modules.return_value = ["fastqc"]
        mock_multiqc_module.list_plots.return_value = {
            "fastqc": [
                "Sequence Counts",
                "Sequence Quality Histograms",
                "Per Sequence Quality Scores",
                {"Per Sequence GC Content": ["Percentages", "Counts"]},
                "Per Base N Content",
                "Sequence Length Distribution",
            ]
        }

        import sys

        with patch.dict(sys.modules, {"multiqc": mock_multiqc_module}):
            result = extract_multiqc_metadata("/path/to/real_multiqc.parquet")

            assert len(result["samples"]) == 7
            assert result["modules"] == ["fastqc"]
            assert "fastqc" in result["plots"]
            assert len(result["plots"]["fastqc"]) == 6
            assert isinstance(result["plots"]["fastqc"][3], dict)  # Complex nested structure
