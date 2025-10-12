# """Tests for MultiQC endpoints utility functions."""

# from datetime import datetime
# from unittest.mock import MagicMock, patch

# import pytest
# from bson import ObjectId
# from fastapi import HTTPException

# from depictio.api.v1.endpoints.multiqc_endpoints.utils import (
#     create_multiqc_report_in_db,
#     delete_multiqc_report_by_id,
#     generate_multiqc_download_url,
#     get_multiqc_report_by_id,
#     get_multiqc_report_metadata_by_id,
#     get_multiqc_reports_by_data_collection,
# )
# from depictio.models.models.multiqc_reports import MultiQCMetadata, MultiQCReport

# # TODO : add validation with real parquet file


# class TestMultiQCEndpointUtils:
#     """Test suite for MultiQC endpoint utility functions."""

#     @pytest.fixture
#     def sample_multiqc_metadata(self):
#         """Create sample MultiQC metadata for testing."""
#         return MultiQCMetadata(
#             samples=["sample1", "sample2", "sample3"],
#             modules=["fastqc", "cutadapt"],
#             plots={"fastqc": ["quality", "length"], "cutadapt": ["trimmed"]},
#         )

#     @pytest.fixture
#     def sample_multiqc_report(self, sample_multiqc_metadata):
#         """Create sample MultiQC report for testing."""
#         return MultiQCReport(
#             data_collection_id="507f1f77bcf86cd799439012",
#             metadata=sample_multiqc_metadata,
#             s3_location="s3://test-bucket/507f1f77bcf86cd799439012/multiqc.parquet",
#             original_file_path="/path/to/multiqc.parquet",
#             file_size_bytes=1024000,
#             report_name="Test MultiQC Report",
#         )

#     @pytest.mark.asyncio
#     async def test_create_multiqc_report_in_db_success(self, sample_multiqc_report):
#         """Test successful creation of MultiQC report in database."""
#         # Mock MongoDB collection
#         mock_result = MagicMock()
#         mock_result.inserted_id = ObjectId("507f1f77bcf86cd799439013")

#         with patch(
#             "depictio.api.v1.endpoints.multiqc_endpoints.utils.multiqc_collection"
#         ) as mock_collection:
#             mock_collection.insert_one.return_value = mock_result

#             result = await create_multiqc_report_in_db(sample_multiqc_report)

#             # Verify result structure
#             assert isinstance(result, MultiQCReport)
#             assert result.data_collection_id == "507f1f77bcf86cd799439012"
#             assert result.metadata.samples == ["sample1", "sample2", "sample3"]
#             assert result.s3_location == "s3://test-bucket/507f1f77bcf86cd799439012/multiqc.parquet"

#             # Verify MongoDB call
#             mock_collection.insert_one.assert_called_once()
#             call_args = mock_collection.insert_one.call_args[0][0]
#             assert call_args["data_collection_id"] == "507f1f77bcf86cd799439012"
#             assert "_id" in call_args
#             assert "id" in call_args

#     @pytest.mark.asyncio
#     async def test_create_multiqc_report_in_db_insertion_failure(self, sample_multiqc_report):
#         """Test handling of database insertion failure."""
#         # Mock failed insertion
#         mock_result = MagicMock()
#         mock_result.inserted_id = None

#         with patch(
#             "depictio.api.v1.endpoints.multiqc_endpoints.utils.multiqc_collection"
#         ) as mock_collection:
#             mock_collection.insert_one.return_value = mock_result

#             with pytest.raises(HTTPException) as exc_info:
#                 await create_multiqc_report_in_db(sample_multiqc_report)

#             assert exc_info.value.status_code == 500  # type: ignore[attr-defined]
#             assert "Failed to insert MultiQC report into database" in exc_info.value.detail  # type: ignore[attr-defined]

#     @pytest.mark.asyncio
#     async def test_create_multiqc_report_in_db_exception_handling(self, sample_multiqc_report):
#         """Test exception handling in database creation."""
#         with patch(
#             "depictio.api.v1.endpoints.multiqc_endpoints.utils.multiqc_collection"
#         ) as mock_collection:
#             mock_collection.insert_one.side_effect = Exception("Database connection error")

#             with pytest.raises(HTTPException) as exc_info:
#                 await create_multiqc_report_in_db(sample_multiqc_report)

#             assert exc_info.value.status_code == 500  # type: ignore[attr-defined]
#             assert "Failed to create MultiQC report" in exc_info.value.detail  # type: ignore[attr-defined]
#             assert "Database connection error" in exc_info.value.detail  # type: ignore[attr-defined]

#     @pytest.mark.asyncio
#     async def test_create_multiqc_report_with_complex_data(self):
#         """Test creating MultiQC report with complex real-world data structure."""
#         # Real-world metadata from the tests
#         real_world_metadata = MultiQCMetadata(
#             samples=[
#                 "NMP_R2_L1_2_val_2",
#                 "NMP_R1_L2_1_val_1",
#                 "test_2",
#                 "test_1 - polya",
#                 "sample1_S1_L001_R2_001",
#                 "NMP_R1_L2_1",
#                 "NMP_R1_L1_1_val_1",
#                 "NMP_R2_L1_2",
#                 "single - polya",
#                 "test",
#                 "NP_D8_R2_L1_2",
#             ],
#             modules=["fastqc"],
#             plots={
#                 "fastqc": [
#                     "Sequence Counts",
#                     "Sequence Quality Histograms",
#                     "Per Sequence Quality Scores",
#                     {"Per Sequence GC Content": ["Percentages", "Counts"]},
#                     "Per Base N Content",
#                     "Sequence Length Distribution",
#                     "Sequence Duplication Levels",
#                     "Overrepresented sequences by sample",
#                     "Top overrepresented sequences",
#                     "Adapter Content",
#                     "Status Checks",
#                 ]
#             },
#         )

#         real_world_report = MultiQCReport(
#             data_collection_id="68cd8d3f364450bd1aeb14f3",
#             metadata=real_world_metadata,
#             s3_location="s3://depictio-bucket/68cd8d3f364450bd1aeb14f3/multiqc.parquet",
#             original_file_path="/path/to/multiqc_data/multiqc.parquet",
#             file_size_bytes=2884253,
#             report_name="MultiQC Report - multiqc_data",
#         )

#         # Mock successful insertion
#         mock_result = MagicMock()
#         mock_result.inserted_id = ObjectId("507f1f77bcf86cd799439013")

#         with patch(
#             "depictio.api.v1.endpoints.multiqc_endpoints.utils.multiqc_collection"
#         ) as mock_collection:
#             mock_collection.insert_one.return_value = mock_result

#             result = await create_multiqc_report_in_db(real_world_report)

#             # Verify complex data structure handling
#             assert isinstance(result, MultiQCReport)
#             assert len(result.metadata.samples) == 11
#             assert result.metadata.modules == ["fastqc"]
#             assert "fastqc" in result.metadata.plots
#             assert len(result.metadata.plots["fastqc"]) == 11
#             assert result.file_size_bytes == 2884253

#     # @pytest.mark.asyncio
#     # async def test_get_multiqc_reports_by_data_collection_empty_result(self):
#     #     """Test getting MultiQC reports with empty result."""
#     #     reports, total_count = await get_multiqc_reports_by_data_collection(
#     #         "507f1f77bcf86cd799439012", 50, 0
#     #     )

#     #     assert reports == []
#     #     assert total_count == 0

#     # @pytest.mark.asyncio
#     # async def test_get_multiqc_reports_by_data_collection_with_pagination(self):
#     #     """Test getting MultiQC reports with pagination parameters."""
#     #     reports, total_count = await get_multiqc_reports_by_data_collection(
#     #         "507f1f77bcf86cd799439012", 10, 20
#     #     )

#     #     assert reports == []
#     #     assert total_count == 0

#     # @pytest.mark.asyncio
#     # async def test_get_multiqc_report_by_id_not_found(self):
#     #     """Test getting non-existent MultiQC report by ID."""
#     #     with pytest.raises(HTTPException) as exc_info:
#     #         await get_multiqc_report_by_id("nonexistent_id")

#     #     assert exc_info.value.status_code == 404  # type: ignore[attr-defined]  # type: ignore[attr-defined]
#     #     assert "MultiQC report not found" in exc_info.value.detail  # type: ignore[attr-defined]

#     # @pytest.mark.asyncio
#     # async def test_delete_multiqc_report_by_id_success(self):
#     #     """Test successful deletion of MultiQC report."""
#     #     result = await delete_multiqc_report_by_id("507f1f77bcf86cd799439013", True)

#     #     assert result["deleted"] is True
#     #     assert result["s3_file_deleted"] is True
#     #     assert "MultiQC report 507f1f77bcf86cd799439013 deleted successfully" in result["message"]

#     @pytest.mark.asyncio
#     async def test_delete_multiqc_report_by_id_without_s3_deletion(self):
#         """Test deletion without S3 file removal."""
#         result = await delete_multiqc_report_by_id("507f1f77bcf86cd799439013", False)

#         assert result["deleted"] is True
#         assert result["s3_file_deleted"] is False
#         assert "MultiQC report 507f1f77bcf86cd799439013 deleted successfully" in result["message"]

#     @pytest.mark.asyncio
#     async def test_get_multiqc_report_metadata_by_id_not_found(self):
#         """Test getting metadata for non-existent report."""
#         with pytest.raises(HTTPException) as exc_info:
#             await get_multiqc_report_metadata_by_id("nonexistent_id")

#         assert exc_info.value.status_code == 404  # type: ignore[attr-defined]  # type: ignore[attr-defined]
#         assert "MultiQC report not found" in exc_info.value.detail  # type: ignore[attr-defined]

#     @pytest.mark.asyncio
#     async def test_generate_multiqc_download_url_not_found(self):
#         """Test generating download URL for non-existent report."""
#         with pytest.raises(HTTPException) as exc_info:
#             await generate_multiqc_download_url("nonexistent_id", 24)

#         assert exc_info.value.status_code == 404  # type: ignore[attr-defined]  # type: ignore[attr-defined]
#         assert "MultiQC report not found" in exc_info.value.detail  # type: ignore[attr-defined]

#     @pytest.mark.asyncio
#     async def test_generate_multiqc_download_url_custom_expiration(self):
#         """Test download URL generation with custom expiration."""
#         with pytest.raises(HTTPException) as exc_info:
#             await generate_multiqc_download_url("nonexistent_id", 72)

#         assert exc_info.value.status_code == 404  # type: ignore[attr-defined]

#     @pytest.mark.asyncio
#     async def test_model_dump_serialization_in_create(self, sample_multiqc_report):
#         """Test that model_dump works correctly with datetime serialization."""
#         # Mock successful insertion
#         mock_result = MagicMock()
#         mock_result.inserted_id = ObjectId("507f1f77bcf86cd799439013")

#         with patch(
#             "depictio.api.v1.endpoints.multiqc_endpoints.utils.multiqc_collection"
#         ) as mock_collection:
#             mock_collection.insert_one.return_value = mock_result

#             # Test with a report that has a processed_at datetime
#             sample_multiqc_report.processed_at = datetime(2025, 9, 19, 12, 0, 0)

#             result = await create_multiqc_report_in_db(sample_multiqc_report)

#             # Verify that datetime was properly handled
#             assert isinstance(result, MultiQCReport)
#             assert isinstance(result.processed_at, datetime)

#             # Verify MongoDB call received properly serialized data
#             call_args = mock_collection.insert_one.call_args[0][0]
#             assert "processed_at" in call_args

#     @pytest.mark.asyncio
#     async def test_objectid_generation_and_assignment(self, sample_multiqc_report):
#         """Test that ObjectId is properly generated and assigned."""
#         mock_result = MagicMock()
#         test_object_id = ObjectId("507f1f77bcf86cd799439013")
#         mock_result.inserted_id = test_object_id

#         with patch(
#             "depictio.api.v1.endpoints.multiqc_endpoints.utils.multiqc_collection"
#         ) as mock_collection:
#             with patch(
#                 "depictio.api.v1.endpoints.multiqc_endpoints.utils.ObjectId"
#             ) as mock_objectid:
#                 mock_objectid.return_value = test_object_id
#                 mock_collection.insert_one.return_value = mock_result

#                 await create_multiqc_report_in_db(sample_multiqc_report)

#                 # Verify ObjectId was generated and used
#                 mock_objectid.assert_called_once()
#                 call_args = mock_collection.insert_one.call_args[0][0]
#                 assert call_args["_id"] == test_object_id
#                 assert call_args["id"] == str(test_object_id)

#     @pytest.mark.asyncio
#     async def test_function_parameter_validation(self):
#         """Test parameter validation for utility functions."""
#         # Test with valid parameters
#         reports, count = await get_multiqc_reports_by_data_collection("valid_id", 50, 0)
#         assert isinstance(reports, list)
#         assert isinstance(count, int)

#         # Test with different limit and offset values
#         reports, count = await get_multiqc_reports_by_data_collection("valid_id", 10, 100)
#         assert isinstance(reports, list)
#         assert isinstance(count, int)

#         # Test deletion with boolean flag
#         result = await delete_multiqc_report_by_id("test_id", True)
#         assert isinstance(result, dict)
#         assert "deleted" in result
#         assert "s3_file_deleted" in result
#         assert "message" in result
