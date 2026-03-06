# JBrowse2 x Depictio MVP Plan: BED & BigWig Track Support

## Goal
End-to-end JBrowse2 integration: CLI ingestion of BED/BigWig files -> API session config generation -> JBrowse2 rendering via iframe in Dash.

## Decisions (from clarification)
- **BED indexing**: Support both raw .bed and pre-indexed .bed.gz+.tbi (CLI indexes if needed)
- **BigWig**: Support both single QuantitativeTrack AND MultiQuantitativeTrack (Watson/Crick)
- **Templates**: Built-in defaults (bed, bigwig, multi_bigwig) + user override per-project
- **Assembly**: Configured at project level, inherited by all JBrowse2 DCs
- **Scope**: Backend-first (models + CLI + API), minimal Dash touch

---

## Phase 1: Models & Templates

### 1a. Rewrite `depictio/models/models/data_collections_types/jbrowse.py`

Current `DCJBrowse2Config` is broken (dead validator, minimal fields). Replace with:

```python
class JBrowse2TrackType(str, Enum):
    BED = "bed"
    BIGWIG = "bigwig"
    MULTI_BIGWIG = "multi_bigwig"

class MultiTrackPattern(BaseModel):
    group_by: str          # wildcard name to group files (e.g., "sample")
    pair_by: str           # wildcard name to pair strands (e.g., "strand")
    strand_colors: dict[str, str]  # e.g., {"W": "rgb(244,164,96)", "C": "rgb(102,139,139)"}

class DCJBrowse2Config(BaseModel):
    track_type: JBrowse2TrackType
    assembly_name: str = "hg38"
    index_extension: str | None = "tbi"  # For BED tracks
    category: list[str] | None = None    # JBrowse2 track category hierarchy
    display_config: dict | None = None   # Override display settings (color, height, etc.)
    multi_track_pattern: MultiTrackPattern | None = None  # For multi_bigwig pairing
    jbrowse_template_override: dict | None = None  # Full template override
```

### 1b. New file: `depictio/models/models/data_collections_types/jbrowse_templates.py`

Built-in JBrowse2 track configuration templates with `{placeholder}` substitution:

- `BED_TRACK_TEMPLATE` - FeatureTrack + BedTabixAdapter
- `BIGWIG_TRACK_TEMPLATE` - QuantitativeTrack + BigWigAdapter
- `MULTI_BIGWIG_TRACK_TEMPLATE` - MultiQuantitativeTrack + MultiWiggleAdapter
- `DEFAULT_ASSEMBLIES` - dict with hg38/GRCh38 assembly config (reuse existing `my_assembly` from utils.py)
- `build_jbrowse2_session_config()` - function to assemble full session JSON from assembly + tracks

### 1c. Update `depictio/models/models/data_collections.py`

- Model validator already handles `jbrowse2` type -> `DCJBrowse2Config`. No changes needed if field names match.

---

## Phase 2: CLI Processor

### 2a. New file: `depictio/cli/cli/utils/jbrowse2_processor.py`

Following the GeoJSON/MultiQC processor pattern:

```python
def process_jbrowse2_data_collection(
    data_collection: DataCollection,
    CLI_config: CLIConfig,
    overwrite: bool = False,
) -> dict[str, str]:
```

**Flow:**
1. Fetch scanned files from MongoDB via `fetch_file_data()`
2. For each file, based on `track_type`:

   **BED tracks:**
   - If `.bed` (raw): run `bgzip` + `tabix -p bed` to create `.bed.gz` + `.bed.gz.tbi`
   - If `.bed.gz`: verify `.tbi` exists (or create it)
   - Upload `.bed.gz` + `.bed.gz.tbi` to S3

   **BigWig tracks:**
   - Upload `.bigwig`/`.bw` directly to S3 (no indexing needed)

   **Multi BigWig:**
   - Group files by `multi_track_pattern.group_by` wildcard
   - Pair within groups by `multi_track_pattern.pair_by` wildcard
   - Upload all files to S3

3. Generate track configs from templates (populate placeholders with S3 URIs, names, etc.)
4. Build full JBrowse2 session config JSON (assembly + all tracks)
5. Upload session JSON to S3 or write to shared config directory
6. Call API to register JBrowse2 metadata (session location, track count, etc.)

### 2b. Dependencies for indexing

- `pysam` (provides `tabix` and `bgzip` Python bindings) OR
- Shell out to `bgzip`/`tabix` from htslib (check availability, fallback to pysam)
- Add to `pyproject.toml` dependencies

### 2c. Wire into `client_aggregate_data()` in `deltatables.py`

Add branch at line ~376:
```python
if data_collection.config.type.lower() == "jbrowse2":
    return process_jbrowse2_data_collection(data_collection, CLI_config, overwrite)
```

---

## Phase 3: API Endpoint Updates

### 3a. Update `depictio/api/v1/endpoints/jbrowse_endpoints/routes.py`

- **Modernize `generate_track_config()`**: Support `bigwig` and `multi_bigwig` track types (currently only BedTabix)
- **New endpoint**: `GET /session/{session_id}` - serve session config JSON from S3/filesystem
- **Update `create_trackset()`**: Use new template system instead of hardcoded BedTabix logic
- **Fix sync/async**: Either keep PyMongo (it works) or migrate to Beanie - pragmatic choice for MVP is keep PyMongo

### 3b. New endpoint for assembly configs

- `GET /assemblies` - list available built-in assemblies
- `GET /assemblies/{name}` - get assembly config JSON (hg38, mm10, etc.)

---

## Phase 4: Minimal Dash Updates

- **Do NOT refactor** the existing iframe code heavily
- Just ensure `build_jbrowse()` can construct the correct URL with the new session config
- Optionally re-enable component in `component_metadata.py` for testing (`enabled: True`)

---

## Phase 5: Testing & Example

### 5a. Example project YAML for mosaicatcher

```yaml
project_name: mosaicatcher_test
workflows:
  - workflow_tag: strandseq
    data_location:
      locations:
        - /data/mosaicatcher/
    data_collections:
      - data_collection_tag: segmentation_bed
        config:
          type: jbrowse2
          scan:
            mode: recursive
            scan_parameters:
              regex_config:
                pattern: "(?P<run>[^/]+)/(?P<sample>[^/]+)\\.segments\\.bed(\\.gz)?$"
                wildcards:
                  - name: run
                    wildcard_regex: "(?P<run>[^/]+)"
                  - name: sample
                    wildcard_regex: "(?P<sample>[^/]+)"
          dc_specific_properties:
            track_type: bed
            assembly_name: hg38
            index_extension: tbi
            category: ["Segmentation"]

      - data_collection_tag: strand_counts
        config:
          type: jbrowse2
          scan:
            mode: recursive
            scan_parameters:
              regex_config:
                pattern: "(?P<run>[^/]+)/(?P<sample>[^/]+)-(?P<strand>[WC])\\.bigWig$"
                wildcards:
                  - name: run
                    wildcard_regex: "(?P<run>[^/]+)"
                  - name: sample
                    wildcard_regex: "(?P<sample>[^/]+)"
                  - name: strand
                    wildcard_regex: "(?P<strand>[WC])"
          dc_specific_properties:
            track_type: multi_bigwig
            assembly_name: hg38
            category: ["Strand-seq", "Counts"]
            multi_track_pattern:
              group_by: sample
              pair_by: strand
              strand_colors:
                W: "rgb(244, 164, 96)"
                C: "rgb(102, 139, 139)"
```

### 5b. Unit tests (minimal)

- `test_jbrowse2_model.py` - validate DCJBrowse2Config parsing for bed/bigwig/multi_bigwig
- `test_jbrowse2_templates.py` - validate template population produces valid JBrowse2 JSON
- `test_jbrowse2_processor.py` - mock file processing (S3 upload, indexing)

---

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `depictio/models/models/data_collections_types/jbrowse.py` | Rewrite | New DCJBrowse2Config with track_type, assembly, display, multi_track |
| `depictio/models/models/data_collections_types/jbrowse_templates.py` | New | Built-in BED/BigWig/Multi templates + assembly configs |
| `depictio/cli/cli/utils/jbrowse2_processor.py` | New | CLI processor for jbrowse2 DCs (scan -> index -> upload -> config) |
| `depictio/cli/cli/utils/deltatables.py` | Edit | Add jbrowse2 dispatch in client_aggregate_data() |
| `depictio/api/v1/endpoints/jbrowse_endpoints/routes.py` | Edit | Modernize track generation, add BigWig support |
| `depictio/tests/models/test_jbrowse2.py` | New | Model + template tests |
| `pyproject.toml` | Edit | Add pysam dependency (for bgzip/tabix) |

---

## Implementation Order

1. Models & templates (Phase 1) - foundation, no dependencies
2. CLI processor (Phase 2) - depends on models
3. API updates (Phase 3) - depends on models + templates
4. Wire-up + testing (Phase 4-5) - integration
5. Minimal Dash touch - last, only if time permits

## Out of Scope (for MVP)
- Assembly management UI
- Track color picker in dashboard editor
- Cross-DC filtering (JBrowse tracks filtered by interactive component selections)
- VCF, BAM, CRAM track types
- Multi-assembly support per project
