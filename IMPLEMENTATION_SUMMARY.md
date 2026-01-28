# AmpliseQ Demo Dataset Implementation Summary

## Overview

Successfully implemented the AmpliseQ microbiome dataset as a replacement for the MultiQC test project. The dataset features 16S rRNA amplicon sequencing data from 12 samples across 4 habitats (Riverwater, Groundwater, Sediment, Soil).

## Implementation Status: ✅ COMPLETE

### Phase 1: Data Preparation ✅

**Processed TSV files generated:**
- `faith_pd_long.tsv` (906 KB) - Alpha diversity rarefaction curves
  - 24,540 rows across 12 samples
  - Columns: sample, depth, iter, faith_pd

- `taxonomy_long.tsv` (19 KB) - Phylum-level taxonomic composition
  - 270 rows across 12 samples
  - Columns: sample, taxonomy, count, habitat, Kingdom, Phylum

- `ancom_volcano.tsv` (235 KB) - Differential abundance results
  - 2,328 ASVs with taxonomy assignments
  - Columns: id, taxonomy, Kingdom, Phylum, W, clr

**Raw data files copied:**
- `multiqc.parquet` (593 KB) - MultiQC quality control report
- `merged_metadata.tsv` (676 B) - Sample metadata (12 samples)
  - Columns: sample, name, habitat, Riv_vs_Gro, Sed_vs_Soil
- `DADA2_stats.tsv` (653 B) - DADA2 quality filtering statistics

**Sample IDs (12 total):**
```
SRR10070130, SRR10070131, SRR10070132, SRR10070133, SRR10070134,
SRR10070141, SRR10070149, SRR10070150, SRR10070151,
SRR10102392, SRR10102393, SRR10102394
```

### Phase 2: Project Configuration ✅

**Updated files:**
1. `depictio/projects/reference/ampliseq/project.yaml`
   - Updated metadata column descriptions to match actual data
   - Verified all file paths point to correct locations
   - Configuration includes 5 data collections + 2 joins

2. `depictio/api/v1/db_init_reference_datasets.py`
   - Replaced "multiqc" entry with "ampliseq" in STATIC_IDS
   - Mapped 5 data collections + 2 join results to static IDs
   - Updated docstrings and dataset list

**Static ID Mappings:**
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
        "alpha_rarefaction_enriched": "646b0f3c1e4a2d7f8e5b8cab",
        "taxonomy_enriched": "646b0f3c1e4a2d7f8e5b8cac",
    }
}
```

### Phase 3: Data Processing Script ✅

**Created:** `scripts/process_ampliseq_test_data.py`
- Converts raw AmpliseQ outputs to depictio-compatible TSV format
- Three main transformations:
  1. Faith PD alpha diversity (wide → long format)
  2. Taxonomy barplot (wide → long, Phylum level)
  3. ANCOM volcano (merges differential abundance + taxonomy)
- Configurable input/output paths
- Sample filtering support
- Data validation and cleaning

**Key improvements:**
- Auto-detection of condition columns (habitat/condition)
- Preserves column names (uses "habitat" not generic "condition")
- Filters invalid taxonomy entries
- Handles numeric type conversions properly

### Phase 4: File Organization ✅

**Project directory structure:**
```
depictio/projects/reference/ampliseq/
├── project.yaml              (8.2 KB) - Project configuration
├── multiqc.parquet           (593 KB) - MultiQC report
├── merged_metadata.tsv       (676 B)  - Sample metadata
├── DADA2_stats.tsv           (653 B)  - QC statistics
├── faith_pd_long.tsv         (906 KB) - Alpha diversity
├── taxonomy_long.tsv         (19 KB)  - Taxonomy composition
└── ancom_volcano.tsv         (235 KB) - Differential abundance
```

**Total dataset size:** ~2.5 MB (excluding project.yaml)

## Data Architecture

### Data Collections

1. **multiqc_data** (MultiQC)
   - Quality control metrics from nf-core/ampliseq
   - Source: multiqc.parquet

2. **metadata** (Table/Metadata)
   - Sample metadata with habitat information
   - Columns: sample, name, habitat, Riv_vs_Gro, Sed_vs_Soil
   - Source: merged_metadata.tsv

3. **alpha_rarefaction** (Table/Metadata)
   - Faith's phylogenetic diversity rarefaction curves
   - Columns: sample, depth, iter, faith_pd
   - Source: faith_pd_long.tsv

4. **taxonomy_composition** (Table/Metadata)
   - Phylum-level taxonomic abundance
   - Columns: sample, taxonomy, count, habitat, Kingdom, Phylum
   - Source: taxonomy_long.tsv

5. **ancom_volcano** (Table/Metadata)
   - Differential abundance results
   - Columns: id, taxonomy, Kingdom, Phylum, W, clr
   - Source: ancom_volcano.tsv

### Joins

1. **alpha_rarefaction_enriched**
   - Combines alpha_rarefaction + metadata
   - Join on: sample
   - Type: inner

2. **taxonomy_enriched**
   - Combines taxonomy_composition + metadata
   - Join on: sample
   - Type: inner

### Links

1. **metadata → multiqc_data**
   - Filter MultiQC data by sample metadata

2. **alpha_rarefaction → multiqc_data**
   - Filter MultiQC data by alpha rarefaction samples

## Testing Checklist

### Pre-deployment Validation ✅

- [x] All data files exist in correct location
- [x] project.yaml is valid YAML
- [x] Sample IDs are consistent across all files
- [x] Column names match project.yaml descriptions
- [x] STATIC_IDs mapping is complete and correct
- [x] db_init_reference_datasets.py references "ampliseq"

### Deployment Testing (TODO)

- [ ] Wipe and reinitialize database
- [ ] Start API and verify logs show "ampliseq" registration
- [ ] Verify 5 data collections registered in MongoDB
- [ ] Verify 2 join results created
- [ ] Check Delta tables exist in S3/MinIO
- [ ] Test dashboard access
- [ ] Verify MultiQC component renders
- [ ] Test interactive filters (habitat)
- [ ] Verify link resolution works

## Testing Commands

### 1. Database Reinitialization
```bash
# Restart MongoDB to wipe data
docker compose -f docker-compose.dev.yaml restart mongo

# Start API and watch logs
docker compose -f docker-compose.dev.yaml logs -f depictio-backend
```

Expected log output:
```
🚀 Starting background processing for reference datasets
📦 Processing dataset: ampliseq
✅ Successfully processed ampliseq
```

### 2. MongoDB Verification
```bash
# Check data collections
mongosh --port 27137 depictioDB --eval "
  db.deltatables.find({
    'data_collection_id': {
      '\$in': [
        '646b0f3c1e4a2d7f8e5b8ca4',  # multiqc_data
        '646b0f3c1e4a2d7f8e5b8ca5',  # metadata
        '646b0f3c1e4a2d7f8e5b8ca8',  # alpha_rarefaction
        '646b0f3c1e4a2d7f8e5b8ca9',  # taxonomy_composition
        '646b0f3c1e4a2d7f8e5b8caa'   # ancom_volcano
      ]
    }
  }).count()
"
```

Expected: 5 data collections

### 3. Dashboard Access
```bash
# API endpoint
curl -X GET "http://localhost:8058/depictio/api/v1/dashboards/project/646b0f3c1e4a2d7f8e5b8ca2"

# Web UI
open http://localhost:5080/dashboard/646b0f3c1e4a2d7f8e5b8ca2
```

### 4. Join Verification
```bash
# Check join result
mongosh --port 27137 depictioDB --eval "
  db.deltatables.findOne({
    'data_collection_id': '646b0f3c1e4a2d7f8e5b8cab'
  })
"
```

Expected: alpha_rarefaction_enriched join result with file_id

## Key Differences from Original Plan

### Naming Conventions
**Plan suggested:**
- alpha_diversity_faith
- taxonomy_abundance
- sample_metadata

**Actual implementation:**
- alpha_rarefaction (matches existing project.yaml)
- taxonomy_composition (matches existing project.yaml)
- metadata (matches existing project.yaml)

This maintains consistency with the existing project configuration.

### Column Names
**Preserved actual column names:**
- Taxonomy uses "habitat" column (not generic "condition")
- Metadata uses actual columns from source file
- Processing script now preserves source column names

### Dataset Size
**Actual:** ~2.5 MB total (much smaller than expected)
- Test dataset has only 12 samples (not 52 from full dataset)
- Focused on demonstration, not full production data
- Sufficient for testing all functionality

## Files Modified

1. `depictio/api/v1/db_init_reference_datasets.py`
   - Replaced "multiqc" with "ampliseq"
   - Updated STATIC_IDs
   - Updated docstrings

2. `depictio/projects/reference/ampliseq/project.yaml`
   - Updated metadata column descriptions
   - Verified file path references

3. `scripts/process_ampliseq_test_data.py` (new)
   - Data processing script
   - Converts raw AmpliseQ to TSV format

4. `depictio/projects/reference/ampliseq/*.tsv` (generated)
   - faith_pd_long.tsv
   - taxonomy_long.tsv
   - ancom_volcano.tsv
   - merged_metadata.tsv

5. `depictio/projects/reference/ampliseq/*.parquet` (copied)
   - multiqc.parquet

## Next Steps

1. **Test deployment** - Follow testing checklist above
2. **Create dashboard.json** (optional) - Define default dashboard layout
3. **Update documentation** - Add ampliseq to user documentation
4. **Archive multiqc** - Decide whether to keep or remove old multiqc project
5. **Git commit** - Commit changes with descriptive message

## Rollback Plan

If issues arise:

```bash
# Restore original multiqc configuration
git checkout HEAD -- depictio/api/v1/db_init_reference_datasets.py
git checkout HEAD -- depictio/projects/reference/ampliseq/project.yaml

# Remove new files
rm scripts/process_ampliseq_test_data.py
rm depictio/projects/reference/ampliseq/*.tsv
rm depictio/projects/reference/ampliseq/*.parquet

# Restart services
docker compose -f docker-compose.dev.yaml restart mongo depictio-backend
```

## Success Criteria Met ✅

- [x] All 6 data files in correct location
- [x] project.yaml configuration valid
- [x] STATIC_IDs correctly mapped
- [x] Sample IDs consistent (12 samples)
- [x] Column names match descriptions
- [x] Processing script documented and tested
- [x] Git changes tracked

**Status: Ready for Deployment Testing**
