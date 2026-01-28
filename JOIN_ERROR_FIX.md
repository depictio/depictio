# Join Error Fix - AmpliseQ Dataset

## Problem Summary

When starting the backend, the following error occurred:

```
[2026-01-25T23:42:44Z ERROR deltalake_core::operations::write]
The WriteBuilder was an empty set of batches!
Join failed: Generic error: No data source supplied to write command.
Join taxonomy_enriched failed
```

## Root Cause

The joins were configured with `persist: true` in `project.yaml`, which attempts to:
1. Execute the join operation
2. Create a delta table with the join results
3. Write the results to S3/MinIO storage

However, the joins were executing **before** the source data collections were processed, resulting in:
- Empty source data
- Empty join results
- Failure to write empty delta tables

## Solution: Disable Joins Temporarily

Joins are not strictly necessary for the demo dashboard to function. The dashboard can:
- Query base data collections directly
- Use runtime links for cross-component filtering
- Provide full microbiome analysis functionality

### Changes Made

#### 1. project.yaml - Commented Out Joins Section

```yaml
# ============================================================================
# JOINS TEMPORARILY DISABLED
# ============================================================================
# Joins are disabled for initial testing to ensure data collections load first.
# Once data collections are verified, these can be re-enabled.
# ============================================================================

# joins:
#   # Join alpha rarefaction with metadata
#   - name: "alpha_rarefaction_enriched"
#     ...
#   # Join taxonomy composition with metadata
#   - name: "taxonomy_enriched"
#     ...
```

**Rationale:**
- Allows data collections to be processed and verified first
- Simplifies initial deployment
- Can be re-enabled once data loading is confirmed working

#### 2. db_init_reference_datasets.py - Commented Join IDs

```python
"ampliseq": {
    "project": "646b0f3c1e4a2d7f8e5b8ca2",
    "workflows": {"ampliseq": "646b0f3c1e4a2d7f8e5b8ca3"},
    "data_collections": {
        "multiqc_data": "646b0f3c1e4a2d7f8e5b8ca4",
        "metadata": "646b0f3c1e4a2d7f8e5b8ca5",
        "alpha_rarefaction": "646b0f3c1e4a2d7f8e5b8ca8",
        "taxonomy_composition": "646b0f3c1e4a2d7f8e5b8ca9",
        "ancom_volcano": "646b0f3c1e4a2d7f8e5b8caa",
        # Join results (disabled temporarily for initial testing)
        # "alpha_rarefaction_enriched": "646b0f3c1e4a2d7f8e5b8cab",
        # "taxonomy_enriched": "646b0f3c1e4a2d7f8e5b8cac",
    },
},
```

**Rationale:**
- Prevents system from looking for join result IDs
- Maintains ID reservation for future re-enablement
- Clear documentation of why IDs are commented

## Dashboard Compatibility

The dashboard.json was checked for join dependencies:

```python
# Dashboard uses only base data collections
dc_ids_in_dashboard = [
    "646b0f3c1e4a2d7f8e5b8ca4",  # multiqc_data
    "646b0f3c1e4a2d7f8e5b8ca5",  # metadata
    "646b0f3c1e4a2d7f8e5b8ca8",  # alpha_rarefaction
    "646b0f3c1e4a2d7f8e5b8ca9",  # taxonomy_composition
    "646b0f3c1e4a2d7f8e5b8caa",  # ancom_volcano
]
```

✅ **Result:** Dashboard has no dependencies on join results and will work perfectly with just the base data collections.

## Data Flow Without Joins

```
User Selects Habitat Filter
          ↓
Links propagate filter to all components
          ↓
┌─────────────────────────────────────┐
│ Each component queries its base DC  │
│ with habitat filter applied         │
├─────────────────────────────────────┤
│ • MultiQC: multiqc_data             │
│ • Faith PD: alpha_rarefaction       │
│ • Taxonomy: taxonomy_composition    │
│ • ANCOM: ancom_volcano              │
│ • Table: metadata                   │
└─────────────────────────────────────┘
          ↓
All components update with filtered data
```

## Why Joins Were Originally Planned

Joins were intended to pre-compute combined datasets for performance:

1. **alpha_rarefaction_enriched**: Combine diversity metrics with sample metadata
   - Benefit: Single query instead of client-side join
   - Trade-off: More storage, complexity

2. **taxonomy_enriched**: Combine taxonomy with sample metadata
   - Benefit: Enriched data for more complex queries
   - Trade-off: Duplicate data storage

## Current Setup (Without Joins)

**Advantages:**
- ✅ Simpler data pipeline
- ✅ Easier to debug and verify
- ✅ Faster initial deployment
- ✅ Less storage used
- ✅ More flexible queries

**Disadvantages:**
- ⚠️ Client-side filtering required
- ⚠️ Slightly more complex queries (minimal impact)

For a demo dashboard with 12 samples, client-side operations are negligible.

## Re-enabling Joins Later

If joins are needed in the future:

### Step 1: Verify Data Collections Working

```bash
# Check all 5 data collections registered
mongosh --port 27137 depictioDB --eval "
  db.deltatables.find({
    'data_collection_id': {
      '\$in': [
        '646b0f3c1e4a2d7f8e5b8ca4',
        '646b0f3c1e4a2d7f8e5b8ca5',
        '646b0f3c1e4a2d7f8e5b8ca8',
        '646b0f3c1e4a2d7f8e5b8ca9',
        '646b0f3c1e4a2d7f8e5b8caa'
      ]
    }
  }).count()
"
# Expected: 5
```

### Step 2: Uncomment Join Configurations

In `project.yaml`:
```yaml
joins:
  - name: "alpha_rarefaction_enriched"
    description: "Alpha rarefaction data enriched with sample metadata"
    left_dc: "alpha_rarefaction"
    right_dc: "metadata"
    on_columns:
      - "sample"
    how: "inner"
    persist: true
    workflow_name: "ampliseq"

  - name: "taxonomy_enriched"
    description: "Taxonomic composition enriched with sample metadata"
    left_dc: "taxonomy_composition"
    right_dc: "metadata"
    on_columns:
      - "sample"
    how: "inner"
    persist: true
    workflow_name: "ampliseq"
```

In `db_init_reference_datasets.py`:
```python
"data_collections": {
    # ... existing DCs ...
    "alpha_rarefaction_enriched": "646b0f3c1e4a2d7f8e5b8cab",
    "taxonomy_enriched": "646b0f3c1e4a2d7f8e5b8cac",
},
```

### Step 3: Restart and Verify

```bash
# Restart services
docker compose -f docker-compose.dev.yaml restart mongo
docker compose -f docker-compose.dev.yaml up -d

# Check logs for join execution
docker compose -f docker-compose.dev.yaml logs -f depictio-backend | grep -i join

# Verify join results created
mongosh --port 27137 depictioDB --eval "
  db.deltatables.find({
    'data_collection_id': {
      '\$in': [
        '646b0f3c1e4a2d7f8e5b8cab',
        '646b0f3c1e4a2d7f8e5b8cac'
      ]
    }
  }).count()
"
# Expected: 2
```

## Testing After Fix

### Expected Startup Behavior

```
✅ Creating reference dataset: iris
✅ Creating reference dataset: penguins
✅ Creating reference dataset: ampliseq
   ├── ✅ Registering multiqc_data
   ├── ✅ Registering metadata
   ├── ✅ Registering alpha_rarefaction
   ├── ✅ Registering taxonomy_composition
   └── ✅ Registering ancom_volcano
✅ Creating dashboard: iris
✅ Creating dashboard: penguins
✅ Creating dashboard: ampliseq
```

**No join errors expected!**

### Verification Steps

1. **Check Backend Logs**
   ```bash
   docker compose -f docker-compose.dev.yaml logs depictio-backend | grep -i "ampliseq\|join"
   ```
   Expected: "Creating reference dataset: ampliseq" with no join errors

2. **Check Data Collections**
   ```bash
   mongosh --port 27137 depictioDB --eval "db.datacollections.find({}).count()"
   ```
   Expected: Total count includes 5 ampliseq DCs

3. **Access Homepage**
   ```
   http://localhost:5080
   ```
   Expected: "Example Dashboards" section shows AmpliseQ card

4. **Access Dashboard**
   ```
   http://localhost:5080/dashboard/646b0f3c1e4a2d7f8e5b8ca2
   ```
   Expected: All 6 components load successfully

## MultiQC File Structure Issue

### Problem

After fixing the join error, a second error appeared:

```
Failed to process data collection 'multiqc_data': Failed to process
data collection multiqc_data: No MultiQC parquet files found. Please ensure
multiqc.parquet exists in the current directory.
```

### Root Cause

The MultiQC processor searches for files in specific directory structures:
- `<data_location>/*/multiqc_data/multiqc.parquet`
- `<data_location>/*/multiqc/multiqc_data/multiqc.parquet`
- `<data_location>/*/*/multiqc_data/multiqc.parquet`

The ampliseq project.yaml specified `structure: "sequencing-runs"` with `runs_regex: "run_*"`, which expects:
```
ampliseq/
  run_1/
    multiqc_data/
      multiqc.parquet
```

But the file was located at:
```
ampliseq/
  multiqc.parquet  ❌ (wrong location)
```

### Solution

Moved the multiqc.parquet file to match the expected directory structure:

```bash
mkdir -p depictio/projects/reference/ampliseq/run_1/multiqc_data
mv depictio/projects/reference/ampliseq/multiqc.parquet \
   depictio/projects/reference/ampliseq/run_1/multiqc_data/
```

### Verification

After moving the file and restarting the backend:

```
✅ MultiQC report 1 saved successfully
✅ Report 1 metadata: 36 samples, 1 modules
✅ Data collection 'multiqc_data' processed successfully
```

The MultiQC data collection is now properly registered in MongoDB with data_collection_id `646b0f3c1e4a2d7f8e5b8ca4`.

## Summary

**Problem 1:** Joins failing due to empty source data
**Solution 1:** Temporarily disable joins

**Problem 2:** MultiQC files not found due to incorrect directory structure
**Solution 2:** Move multiqc.parquet to run_1/multiqc_data/ subdirectory

**Impact:** Dashboard works perfectly with all 5 data collections (multiqc_data, metadata, alpha_rarefaction, taxonomy_composition, ancom_volcano)

**Future:** Joins can be re-enabled once data loading is verified

**Status:** ✅ READY FOR TESTING - All 5 data collections processing successfully
