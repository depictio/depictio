# Data Import

Import and process data using the Depictio CLI for data collection creation and management.

## Usage

When the user wants to import data, scan files, or process data collections, use the Depictio CLI wrapper.

## CLI Access

The Depictio CLI is accessed via:
```bash
/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio-venv-dash-v3/bin/python -c "from depictio.cli.depictio_cli import app; app()" data COMMAND
```

Or create an alias:
```bash
alias depictio-cli="/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio-venv-dash-v3/bin/python -c 'from depictio.cli.depictio_cli import app; app()'"
```

## Available Data Commands

### 1. Scan Files

Scan files to prepare for data collection creation.

```bash
depictio-cli data scan [OPTIONS]
```

**What it does**:
- Scans specified directory for data files
- Identifies file types and formats
- Validates file structure
- Prepares metadata for import

**Common options**:
- `--path PATH`: Directory to scan
- `--recursive`: Scan subdirectories
- `--pattern PATTERN`: File pattern filter (e.g., "*.csv", "*.parquet")
- `--verbose`: Detailed output

**Supported formats**:
- CSV files (.csv)
- Parquet files (.parquet)
- Delta tables
- Genomic data formats

### 2. Process Data Collections

Process data collections for a specific tag.

```bash
depictio-cli data process --tag TAG [OPTIONS]
```

**What it does**:
- Processes scanned data files
- Converts to Delta Lake format
- Stores in S3/MinIO
- Registers in MongoDB
- Creates data collection metadata

**Options**:
- `--tag TAG`: Tag to identify data collection
- `--verbose`: Detailed processing output
- `--force`: Force reprocessing of existing data

### 3. Complete Workflow (Run Command)

Run the complete Depictio workflow: validate, sync, scan, and process.

```bash
depictio-cli run [OPTIONS]
```

**What it does**:
1. Validates configuration
2. Syncs with backend API
3. Scans for data files
4. Processes data collections
5. Registers in database

**This is the recommended way** for complete data import workflow.

## Data Import Workflow

### Basic Import Workflow

1. **Scan files**:
   ```bash
   depictio-cli data scan --path /path/to/data --recursive --verbose
   ```

2. **Review scan results**:
   - Check identified files
   - Verify file formats
   - Confirm data structure

3. **Process data**:
   ```bash
   depictio-cli data process --tag my_dataset --verbose
   ```

4. **Verify import**:
   - Check MongoDB for data collection metadata
   - Verify Delta tables in S3/MinIO
   - Test data access in API/Dash

### Complete Workflow (Recommended)

Use the `run` command for end-to-end import:

```bash
depictio-cli run --config /path/to/config.yaml --verbose
```

**Configuration file** should specify:
- Data sources
- Processing options
- Storage configuration
- Metadata tags

## Process for Using This Skill

1. **Determine import scope**:
   - Single file or directory
   - File formats and types
   - Target data collection name/tag

2. **Check prerequisites**:
   - MongoDB running (localhost:27018)
   - MinIO/S3 accessible
   - API server running (for registration)
   - Sufficient storage space

3. **Scan files first**:
   ```bash
   depictio-cli data scan --path /data/path --verbose
   ```

4. **Review scan output**:
   - Confirm files detected correctly
   - Check for any validation errors
   - Verify data structure

5. **Process data**:
   ```bash
   depictio-cli data process --tag dataset_name --verbose
   ```

6. **Verify successful import**:
   - Check API endpoints
   - View in Dash dashboard
   - Query data collections

## Common Use Cases

### Import CSV Dataset

```bash
# Scan CSV files
depictio-cli data scan --path /data/csv_files --pattern "*.csv" --verbose

# Process and import
depictio-cli data process --tag csv_dataset --verbose
```

### Import Parquet Files

```bash
# Scan parquet files
depictio-cli data scan --path /data/parquet --pattern "*.parquet" --recursive --verbose

# Process
depictio-cli data process --tag parquet_dataset --verbose
```

### Batch Import Multiple Datasets

```bash
# Use run command with config
depictio-cli run --config batch_import.yaml --verbose
```

Config file (batch_import.yaml):
```yaml
datasets:
  - name: dataset1
    path: /data/dataset1
    tag: dataset1_v1
  - name: dataset2
    path: /data/dataset2
    tag: dataset2_v1
```

### Re-process Existing Dataset

```bash
# Force reprocessing
depictio-cli data process --tag existing_dataset --force --verbose
```

## Data Collection Types

Depictio supports various data collection types:

1. **Table Data**:
   - CSV files
   - Parquet files
   - Delta tables
   - Analytical datasets

2. **Genomic Data**:
   - BED files
   - VCF files
   - BAM/SAM files
   - Custom genomic formats

3. **Time Series Data**:
   - Temporal datasets
   - Log files
   - Metrics data

## Error Handling

**File not found errors**:
- Verify file paths are correct
- Check file permissions
- Use absolute paths

**Format validation errors**:
- Check file format is supported
- Verify data structure
- Review error messages for specific issues

**Storage errors**:
- Check MinIO/S3 connectivity
- Verify credentials
- Ensure sufficient storage space

**Registration errors**:
- Check API server is running
- Verify MongoDB connection
- Check authentication credentials

**Processing errors**:
- Review data for malformed entries
- Check memory availability
- Verify data types

## Data Validation

The CLI validates data during import:

1. **Format validation**: File format matches expected structure
2. **Schema validation**: Data matches expected schema
3. **Type validation**: Data types are correct
4. **Integrity validation**: No corrupted or missing data

## Performance Tips

- **Parallel processing**: CLI may support parallel processing for multiple files
- **Chunking**: Large files processed in chunks
- **Delta format**: Use Delta Lake for efficient storage and updates
- **Compression**: Data automatically compressed in storage

## Storage Architecture

Data import workflow stores data in:

1. **Delta Lake (S3/MinIO)**:
   - Parquet files with Delta protocol
   - Efficient analytics
   - ACID transactions

2. **MongoDB**:
   - Metadata and configuration
   - Data collection registry
   - User permissions

3. **GridFS** (for large files):
   - Binary file storage
   - Chunked uploads

## Integration with Other Skills

- Use `/db-operations` to backup before large imports
- Run `/run-tests` to verify import functionality
- Use `/check-quality` for code related to import logic
- Document new data types in `/update-docs`

## Monitoring Import Progress

During import, monitor:

- **File scanning**: Number of files detected
- **Processing**: Files being converted
- **Storage**: Data being written to Delta/S3
- **Registration**: Collections registered in MongoDB
- **Validation**: Data validation status

## Best Practices

1. **Test with small dataset first**: Verify workflow before large import
2. **Use verbose mode**: Get detailed output for debugging
3. **Validate before processing**: Scan first, review, then process
4. **Backup before re-import**: Use `/db-operations` to backup
5. **Tag meaningfully**: Use descriptive tags for data collections
6. **Monitor resources**: Check disk space and memory during import
7. **Verify after import**: Test data access and visualization

## Configuration Management

Create reusable configuration files for common import patterns:

```yaml
# import_config.yaml
data_sources:
  - path: /data/source1
    tag: source1_v1
    format: csv
  - path: /data/source2
    tag: source2_v1
    format: parquet

storage:
  backend: s3  # or minio
  bucket: depictio-data

processing:
  parallel: true
  chunk_size: 10000
```

Use with:
```bash
depictio-cli run --config import_config.yaml --verbose
```
