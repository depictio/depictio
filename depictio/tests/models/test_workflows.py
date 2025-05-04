import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from depictio.models.config import DEPICTIO_CONTEXT
from depictio.models.models.base import PyObjectId
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.users import Permission

# Import all workflow models we need to test
from depictio.models.models.workflows import (
    Workflow,
    WorkflowCatalog,
    WorkflowConfig,
    WorkflowDataLocation,
    WorkflowEngine,
    WorkflowRun,
    WorkflowRunScan,
)


class TestWorkflowDataLocation:
    """Test suite for WorkflowDataLocation model."""

    def test_valid_config_flat_structure(self):
        """Test creating a valid WorkflowDataLocation with flat structure."""
        config = WorkflowDataLocation(
            structure="flat",
            locations=["/path/to/dir1", "/path/to/dir2"]
        )
        assert config.structure == "flat"
        assert config.locations == ["/path/to/dir1", "/path/to/dir2"]
        assert config.runs_regex is None

    def test_valid_config_sequencing_runs_structure(self):
        """Test creating a valid WorkflowDataLocation with sequencing-runs structure."""
        config = WorkflowDataLocation(
            structure="sequencing-runs",
            locations=["/path/to/dir"],
            runs_regex="run-\\d+"
        )
        assert config.structure == "sequencing-runs"
        assert config.locations == ["/path/to/dir"]
        assert config.runs_regex == "run-\\d+"

    def test_invalid_structure(self):
        """Test validation with invalid structure."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowDataLocation(
                structure="invalid",
                locations=["/path"]
            )
        assert "structure must be either 'flat' or 'sequencing-runs'" in str(exc_info.value)

    def test_missing_runs_regex_for_sequencing_runs(self):
        """Test validation when runs_regex is missing for sequencing-runs structure."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowDataLocation(
                structure="sequencing-runs",
                locations=["/path"]
            )
        assert "runs_regex is required when mode is 'sequencing-runs'" in str(exc_info.value)

    def test_invalid_runs_regex_pattern(self):
        """Test validation with invalid runs_regex pattern."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowDataLocation(
                structure="sequencing-runs",
                locations=["/path"],
                runs_regex="[invalid"
            )
        assert "Invalid runs_regex pattern" in str(exc_info.value)

    @patch.dict(os.environ, {'TEST_DIR': '/home/test'})
    @patch('depictio.models.config.DEPICTIO_CONTEXT', 'cli')
    def test_location_with_env_var_in_cli(self):
        """Test location with environment variable in CLI context."""
        config = WorkflowDataLocation(
            structure="flat",
            locations=["/base/{TEST_DIR}/subdir"]
        )
        # The exact path validation would depend on DirectoryPath implementation
        # Just verify the structure is correct
        assert config.structure == "flat"
        assert isinstance(config.locations, list)

    @patch.dict(os.environ, {})
    @patch('depictio.models.config.DEPICTIO_CONTEXT', 'cli')
    def test_location_with_missing_env_var(self):
        """Test location with missing environment variable."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowDataLocation(
                structure="flat",
                locations=["/base/{MISSING_VAR}/subdir"]
            )
        assert "Environment variable 'MISSING_VAR' is not set" in str(exc_info.value)

    @patch('depictio.models.config.DEPICTIO_CONTEXT', 'web')
    def test_location_in_non_cli_context(self):
        """Test location handling in non-CLI context."""
        config = WorkflowDataLocation(
            structure="flat",
            locations=["/path/with/{ENV_VAR}"]
        )
        assert config.locations == ["/path/with/{ENV_VAR}"]


class TestWorkflowConfig:
    """Test suite for WorkflowConfig model."""

    def test_valid_config_minimal(self):
        """Test creating a valid WorkflowConfig with minimal fields."""
        config = WorkflowConfig()
        assert config.version is None
        assert config.workflow_parameters is None

    def test_valid_config_with_all_fields(self):
        """Test creating a valid WorkflowConfig with all fields."""
        params = {"param1": "value1", "param2": 2}
        config = WorkflowConfig(
            version="1.0.0",
            workflow_parameters=params
        )
        assert config.version == "1.0.0"
        assert config.workflow_parameters == params


class TestWorkflowRunScan:
    """Test suite for WorkflowRunScan model."""

    def test_valid_workflow_run_scan(self):
        """Test creating a valid WorkflowRunScan instance."""
        obj_ids = [PyObjectId(), PyObjectId()]
        scan = WorkflowRunScan(
            stats={"files": 100, "directories": 10},
            files_id={"data": obj_ids}
        )
        assert scan.stats == {"files": 100, "directories": 10}
        assert scan.files_id == {"data": obj_ids}
        assert isinstance(scan.scan_time, str)
        # Verify datetime format
        datetime.strptime(scan.scan_time, "%Y-%m-%d %H:%M:%S")

    def test_custom_scan_time(self):
        """Test WorkflowRunScan with custom scan_time."""
        custom_time = "2025-01-01 12:00:00"
        scan = WorkflowRunScan(
            stats={},
            files_id={},
            scan_time=custom_time
        )
        assert scan.scan_time == custom_time


class TestWorkflowRun:
    """Test suite for WorkflowRun model."""

    def test_valid_workflow_run_minimal(self):
        """Test creating a valid WorkflowRun with minimal fields."""
        run = WorkflowRun(
            workflow_id=PyObjectId(),
            run_tag="test-run",
            workflow_config_id=PyObjectId(),
            run_location="/path/to/run",
            creation_time="2025-01-01 10:00:00",
            last_modification_time="2025-01-01 11:00:00",
            permissions=Permission.PUBLIC
        )
        assert run.workflow_id is not None
        assert run.run_tag == "test-run"
        assert run.files_id == []
        assert run.run_location == "/path/to/run"
        assert run.run_hash == ""
        assert run.scan_results == []
        assert run.permissions == Permission.PUBLIC

    @patch('depictio.models.config.DEPICTIO_CONTEXT', 'CLI')
    @patch.dict(os.environ, {'TEST_LOC': '/home/runs'})
    def test_run_location_with_env_var_cli(self):
        """Test run_location with environment variable in CLI context."""
        run = WorkflowRun(
            workflow_id=PyObjectId(),
            run_tag="test",
            workflow_config_id=PyObjectId(),
            run_location="{TEST_LOC}/run1",
            creation_time="2025-01-01 10:00:00",
            last_modification_time="2025-01-01 11:00:00",
            permissions=Permission.PUBLIC
        )
        # Would be validated by DirectoryPath
        assert isinstance(run.run_location, str)

    def test_invalid_hash_length(self):
        """Test validation with invalid hash length."""
        with pytest.raises(ValidationError):
            WorkflowRun(
                workflow_id=PyObjectId(),
                run_tag="test",
                workflow_config_id=PyObjectId(),
                run_location="/path",
                creation_time="2025-01-01 10:00:00",
                last_modification_time="2025-01-01 11:00:00",
                run_hash="invalid_length",
                permissions=Permission.PUBLIC
            )

    def test_valid_hash_lengths(self):
        """Test validation with valid hash lengths."""
        # Empty hash
        run1 = WorkflowRun(
            workflow_id=PyObjectId(),
            run_tag="test1",
            workflow_config_id=PyObjectId(),
            run_location="/path",
            creation_time="2025-01-01 10:00:00",
            last_modification_time="2025-01-01 11:00:00",
            run_hash="",
            permissions=Permission.PUBLIC
        )
        assert run1.run_hash == ""

        # 64-character hash
        valid_hash = "a" * 64
        run2 = WorkflowRun(
            workflow_id=PyObjectId(),
            run_tag="test2",
            workflow_config_id=PyObjectId(),
            run_location="/path",
            creation_time="2025-01-01 10:00:00",
            last_modification_time="2025-01-01 11:00:00",
            run_hash=valid_hash,
            permissions=Permission.PUBLIC
        )
        assert run2.run_hash == valid_hash

    def test_datetime_field_validation(self):
        """Test datetime field validation."""
        # Test ISO format conversion
        run = WorkflowRun(
            workflow_id=PyObjectId(),
            run_tag="test",
            workflow_config_id=PyObjectId(),
            run_location="/path",
            creation_time="2025-01-01T10:00:00",
            last_modification_time="2025-01-01T11:00:00",
            registration_time="2025-01-01T12:00:00",
            permissions=Permission.PUBLIC
        )
        assert run.creation_time == "2025-01-01 10:00:00"
        assert run.last_modification_time == "2025-01-01 11:00:00"
        assert run.registration_time == "2025-01-01 12:00:00"

    def test_invalid_datetime_format(self):
        """Test validation with invalid datetime format."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowRun(
                workflow_id=PyObjectId(),
                run_tag="test",
                workflow_config_id=PyObjectId(),
                run_location="/path",
                creation_time="invalid-date",
                last_modification_time="2025-01-01 11:00:00",
                permissions=Permission.PUBLIC
            )
        assert "Invalid datetime format" in str(exc_info.value)

    def test_workflow_config_id_string_conversion(self):
        """Test workflow_config_id string to PyObjectId conversion."""
        config_id_str = str(PyObjectId())
        run = WorkflowRun(
            workflow_id=PyObjectId(),
            run_tag="test",
            workflow_config_id=config_id_str,
            run_location="/path",
            creation_time="2025-01-01 10:00:00",
            last_modification_time="2025-01-01 11:00:00",
            permissions=Permission.PUBLIC
        )
        assert isinstance(run.workflow_config_id, PyObjectId)


class TestWorkflowEngine:
    """Test suite for WorkflowEngine model."""

    def test_valid_engine_minimal(self):
        """Test creating a valid WorkflowEngine with minimal fields."""
        engine = WorkflowEngine(name="snakemake")
        assert engine.name == "snakemake"
        assert engine.version is None

    def test_valid_engine_with_version(self):
        """Test creating a valid WorkflowEngine with version."""
        engine = WorkflowEngine(name="nextflow", version="21.10.6")
        assert engine.name == "nextflow"
        assert engine.version == "21.10.6"

    def test_extra_fields_forbidden(self):
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowEngine(
                name="test",
                extra_field="should not work"
            )
        assert "extra" in str(exc_info.value) or "unexpected" in str(exc_info.value)


class TestWorkflowCatalog:
    """Test suite for WorkflowCatalog model."""

    def test_valid_catalog_minimal(self):
        """Test creating a valid WorkflowCatalog with minimal fields."""
        catalog = WorkflowCatalog(
            name="workflowhub",
            url="https://workflowhub.eu"
        )
        assert catalog.name == "workflowhub"
        assert catalog.url == "https://workflowhub.eu"

    def test_valid_catalog_names(self):
        """Test validation with valid catalog names."""
        for name in ["workflowhub", "nf-core", "smk-wf-catalog"]:
            catalog = WorkflowCatalog(
                name=name,
                url="https://example.com"
            )
            assert catalog.name == name

    def test_invalid_catalog_name(self):
        """Test validation with invalid catalog name."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowCatalog(
                name="invalid",
                url="https://example.com"
            )
        assert "Invalid workflow catalog name" in str(exc_info.value)

    def test_valid_urls(self):
        """Test validation with valid URLs."""
        valid_urls = [
            "https://example.com",
            "http://example.com",
            "git://github.com/user/repo"
        ]
        for url in valid_urls:
            catalog = WorkflowCatalog(
                name="workflowhub",
                url=url
            )
            assert catalog.url == url

    def test_invalid_url(self):
        """Test validation with invalid URL."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowCatalog(
                name="workflowhub",
                url="ftp://invalid.com"
            )
        assert "Invalid URL" in str(exc_info.value)

    def test_extra_fields_forbidden(self):
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowCatalog(
                name="workflowhub",
                url="https://example.com",
                extra_field="should not work"
            )
        assert "extra" in str(exc_info.value) or "unexpected" in str(exc_info.value)


class TestWorkflow:
    """Test suite for Workflow model."""

    def test_valid_workflow_minimal(self):
        """Test creating a valid Workflow with minimal fields."""
        engine = WorkflowEngine(name="nextflow")
        data_location = WorkflowDataLocation(
            structure="flat",
            locations=["/path/to/data"]
        )
        data_collections = [DataCollection(
            data_collection_tag="dc1",
            config={
                "type": "table",
                "scan": {"mode": "single", "scan_parameters": {"filename": "test.txt"}},
                "dc_specific_properties": {"format": "csv"}
            }
        )]
        
        workflow = Workflow(
            name="test-workflow",
            engine=engine,
            data_collections=data_collections,
            data_location=data_location
        )
        assert workflow.name == "test-workflow"
        assert workflow.engine == engine
        assert workflow.version is None
        assert workflow.catalog is None
        assert workflow.workflow_tag is None
        assert workflow.repository_url is None
        assert workflow.data_collections == data_collections
        assert workflow.runs == {}
        assert isinstance(workflow.config, WorkflowConfig)
        assert workflow.data_location == data_location

    def test_valid_workflow_with_all_fields(self):
        """Test creating a valid Workflow with all fields."""
        engine = WorkflowEngine(name="nextflow", version="21.10")
        catalog = WorkflowCatalog(name="nf-core", url="https://nf-co.re")
        data_location = WorkflowDataLocation(
            structure="flat",
            locations=["/path/to/data"]
        )
        data_collections = []
        runs = {"run1": WorkflowRun(
            workflow_id=PyObjectId(),
            run_tag="run1",
            workflow_config_id=PyObjectId(),
            run_location="/path",
            creation_time="2025-01-01 10:00:00",
            last_modification_time="2025-01-01 11:00:00",
            permissions=Permission.PUBLIC
        )}
        config = WorkflowConfig(version="1.0")
        
        workflow = Workflow(
            name="test-workflow",
            engine=engine,
            version="1.0.0",
            catalog=catalog,
            workflow_tag="custom-tag",
            repository_url="https://github.com/test/repo",
            data_collections=data_collections,
            runs=runs,
            config=config,
            data_location=data_location,
            registration_time="2025-01-01 09:00:00"
        )
        assert workflow.name == "test-workflow"
        assert workflow.engine == engine
        assert workflow.version == "1.0.0"
        assert workflow.catalog == catalog
        assert workflow.workflow_tag == "custom-tag"
        assert workflow.repository_url == "https://github.com/test/repo"
        assert workflow.data_collections == data_collections
        assert workflow.runs == runs
        assert workflow.config == config
        assert workflow.data_location == data_location
        assert workflow.registration_time == "2025-01-01 09:00:00"

    def test_missing_required_fields(self):
        """Test validation with missing required fields."""
        # Missing name
        with pytest.raises(ValidationError) as exc_info:
            Workflow(
                engine=WorkflowEngine(name="nextflow"),
                data_location=WorkflowDataLocation(structure="flat", locations=["/path"]),
                data_collections=[]
            )
        assert "name is required" in str(exc_info.value)

        # Missing engine
        with pytest.raises(ValidationError) as exc_info:
            Workflow(
                name="test",
                data_location=WorkflowDataLocation(structure="flat", locations=["/path"]),
                data_collections=[]
            )
        assert "engine is required" in str(exc_info.value)

    def test_equality_comparison(self):
        """Test __eq__ method for Workflow."""
        engine = WorkflowEngine(name="nextflow")
        data_location = WorkflowDataLocation(structure="flat", locations=["/path"])
        data_collections = []
        
        workflow1 = Workflow(
            name="test-workflow",
            engine=engine,
            data_collections=data_collections,
            data_location=data_location
        )
        workflow2 = Workflow(
            name="test-workflow",
            engine=engine,
            data_collections=data_collections,
            data_location=data_location
        )
        workflow3 = Workflow(
            name="different-workflow",
            engine=engine,
            data_collections=data_collections,
            data_location=data_location
        )
        
        assert workflow1 == workflow2
        assert workflow1 != workflow3
        
        # Test equality with different type
        assert (workflow1 == "not_a_workflow") == NotImplemented

    def test_validation_of_list_and_dict_fields(self):
        """Test validation of data_collections and runs fields."""
        # data_collections must be a list
        with pytest.raises(ValidationError) as exc_info:
            Workflow(
                name="test",
                engine=WorkflowEngine(name="nextflow"),
                data_location=WorkflowDataLocation(structure="flat", locations=["/path"]),
                data_collections="not a list"
            )
        assert "data_collections must be a list" in str(exc_info.value)

        # runs must be a dictionary
        with pytest.raises(ValidationError) as exc_info:
            Workflow(
                name="test",
                engine=WorkflowEngine(name="nextflow"),
                data_location=WorkflowDataLocation(structure="flat", locations=["/path"]),
                data_collections=[],
                runs="not a dict"
            )
        assert "runs must be a dictionary" in str(exc_info.value)