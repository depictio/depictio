# nf-core/nanoseq drift report — 3.0.0 → 3.1.0

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/nanoseq/results-1e60482a2c4621234393a6eef8e9a104309c20ae/`

> ⚠️ nf-core/nanoseq 3.1.0: megatest run s3://nf-core-awsmegatests/nanoseq/results-6e563e54362cddb8e48d15c156251708c22d0e8d/ is empty, failed or truncated (2 data object(s) outside pipeline_info/, 2 of them under 50 MB, in 26 keys; need 5 of each). Falling back to the newest real run `nanoseq/results-1e60482a2c4621234393a6eef8e9a104309c20ae/` (release 3.0.0).

## Recipe execution — 0 pass, 0 fail, 15 skipped
- ⚪ `samples` (nf-core/nanoseq/samples.py) — consumes upstream DCs (dc_ref)
- ⚪ `nanostats` (nanoplot/nanostats.py) — consumes upstream DCs (dc_ref)
- ⚪ `nanostats_quality` (nanoplot/nanostats_quality.py) — consumes upstream DCs (dc_ref)
- ⚪ `samtools_stats_sections` (samtools/stats_sections.py) — consumes upstream DCs (dc_ref)
- ⚪ `samtools_read_length_nx` (nf-core/nanoseq/read_length_nx.py) — consumes upstream DCs (dc_ref)
- ⚪ `bambu_counts_gene_long` (bambu/counts_gene_long.py) — glob source not executed
- ⚪ `bambu_counts_transcript_long` (bambu/counts_transcript_long.py) — glob source not executed
- ⚪ `bambu_sample_pca` (bambu/sample_pca.py) — glob source not executed
- ⚪ `bambu_sample_correlation` (bambu/sample_correlation.py) — glob source not executed
- ⚪ `bambu_top_variable_genes` (bambu/top_variable_genes.py) — glob source not executed
- ⚪ `deseq2_results` (nf-core/nanoseq/deseq2_results.py) — consumes upstream DCs (dc_ref)
- ⚪ `deseq2_top_expressed` (nf-core/nanoseq/deseq2_top_expressed.py) — consumes upstream DCs (dc_ref)
- ⚪ `dexseq_results` (dexseq/results.py) — glob source not executed
- ⚪ `dexseq_usage` (nf-core/nanoseq/dexseq_usage.py) — glob source not executed
- ⚪ `gtf_transcripts` (gtf/transcripts.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 120 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 3 resolved, 0 missing, 0 optional-absent (of 3)

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline nanoseq --new-version 3.1.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
