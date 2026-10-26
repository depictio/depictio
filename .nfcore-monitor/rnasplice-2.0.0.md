# nf-core/rnasplice drift report — 1.0.4 → 2.0.0

**❌ action needed** · Megatest: `s3://nf-core-awsmegatests/rnasplice/results-aceb47ab77cf0edfb290a44035328ed5b7eb0be8/`

## Recipe execution — 0 pass, 0 fail, 10 skipped
- ⚪ `samples` (nf-core/rnasplice/samples.py) — consumes upstream DCs (dc_ref)
- ⚪ `sample_pca` (salmon/sample_pca.py) — unresolved var in {DATA_ROOT}/input/metadata.tsv
- ⚪ `expression_heatmap` (salmon/top_variable_genes.py) — unresolved var in {DATA_ROOT}/input/metadata.tsv
- ⚪ `dexseq_exon_genes` (dexseq/exon_genes.py) — glob source not executed
- ⚪ `edger_genes` (edger/diffsplice_genes.py) — glob source not executed
- ⚪ `dexseq_dtu` (dexseq/dtu.py) — glob source not executed
- ⚪ `rmats_events` (rmats/events.py) — glob source not executed
- ⚪ `event_junctions` (nf-core/rnasplice/event_junctions.py) — consumes upstream DCs (dc_ref)
- ⚪ `suppa_events` (suppa/local_events.py) — glob source not executed
- ⚪ `splicing_genes` (nf-core/rnasplice/splicing_genes.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 120 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 2 resolved, 1 missing, 3 optional-absent (of 6)
- ❌ `samples` (sheet) → pipeline_info/samplesheet.valid.csv
  - _nearest existing prefix:_ `pipeline_info/`
- ⚪ `sample_pca` (samplesheet) → {DATA_ROOT}/input/metadata.tsv — optional route, not exercised by megatest
- ⚪ `expression_heatmap` (samplesheet) → {DATA_ROOT}/input/metadata.tsv — optional route, not exercised by megatest
- ⚪ `event_junctions` (sheet) → pipeline_info/samplesheet.valid.csv — optional route, not exercised by megatest

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline rnasplice --new-version 2.0.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
