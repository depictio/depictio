# nf-core/rnasplice drift report — 1.0.4 → 2.0.0

**❌ review needed — major version bump 1.0.4 → 2.0.0** · Megatest: `s3://nf-core-awsmegatests/rnasplice/results-aceb47ab77cf0edfb290a44035328ed5b7eb0be8/`

Upstream changes: https://github.com/nf-core/rnasplice/blob/master/CHANGELOG.md

## Run structure — not compared (the template pins no run)

## Recipe execution — 0 pass, 1 fail, 10 skipped
- ❌ `tracks` (nf-core/rnasplice/tracks.py) — source file absent: pipeline_info/samplesheet.valid.csv
- ⚪ `samples` (nf-core/rnasplice/samples.py) — consumes upstream DCs (dc_ref)
- ⚪ `sample_pca` (salmon/sample_pca.py) — user input, not a run output: input/metadata.tsv
- ⚪ `expression_heatmap` (salmon/top_variable_genes.py) — user input, not a run output: input/metadata.tsv
- ⚪ `dexseq_exon_genes` (dexseq/exon_genes.py) — glob source not executed
- ⚪ `edger_genes` (edger/diffsplice_genes.py) — glob source not executed
- ⚪ `dexseq_dtu` (dexseq/dtu.py) — glob source not executed
- ⚪ `rmats_events` (rmats/events.py) — glob source not executed
- ⚪ `event_junctions` (nf-core/rnasplice/event_junctions.py) — consumes upstream DCs (dc_ref)
- ⚪ `suppa_events` (suppa/local_events.py) — glob source not executed
- ⚪ `splicing_genes` (nf-core/rnasplice/splicing_genes.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 136 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 2 resolved, 2 missing, 1 optional-absent (of 5)
- ❌ `samples` (sheet) → pipeline_info/samplesheet.valid.csv
  - _nearest existing prefix:_ `pipeline_info/`
- ❌ `tracks` (sheet) → pipeline_info/samplesheet.valid.csv
  - _nearest existing prefix:_ `pipeline_info/`
- ⚪ `event_junctions` (sheet) → pipeline_info/samplesheet.valid.csv — optional route, not exercised by megatest

## Next steps
Read the changelog and this report first, then ship the new version with:
```
python scripts/bump_template_version.py --pipeline rnasplice --new-version 2.0.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
