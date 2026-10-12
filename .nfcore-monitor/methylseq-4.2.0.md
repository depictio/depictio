# nf-core/methylseq drift report — 2.3.0 → 4.2.0

**❌ action needed** · Megatest: `s3://nf-core-awsmegatests/methylseq/results-93bc5811603c287c766a0ff7e03b5b41f4483895/bismark/` · run_root: `bismark/`

> ⚠️ nf-core/methylseq 4.2.0: megatest run s3://nf-core-awsmegatests/methylseq/results-5aa56467a85a5e2d6795ea72dfa5a5f0c9babc23/ is empty, failed or truncated (5 data object(s) outside pipeline_info/, 0 of them under 50 MB, in 56 keys; need 5 of each). Falling back to the newest real run `methylseq/results-93bc5811603c287c766a0ff7e03b5b41f4483895/` (release 2.3.0).

## Recipe execution — 0 pass, 0 fail, 17 skipped
- ⚪ `samples` (nf-core/methylseq/samples.py) — consumes upstream DCs (dc_ref)
- ⚪ `bismark_alignment_summary` (bismark/alignment_summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `bismark_deduplication_summary` (bismark/deduplication_summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `bismark_methylation_context_summary` (bismark/methylation_context_summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `bismark_mbias_curve` (bismark/mbias_curve.py) — consumes upstream DCs (dc_ref)
- ⚪ `bismark_summary_report` (bismark/summary_report.py) — consumes upstream DCs (dc_ref)
- ⚪ `bismark_mbias_all_contexts` (bismark/mbias_all_contexts.py) — consumes upstream DCs (dc_ref)
- ⚪ `bismark_binned_methylation` (bismark/binned_methylation.py) — consumes upstream DCs (dc_ref)
- ⚪ `bismark_methylation_density` (bismark/methylation_density.py) — consumes upstream DCs (dc_ref)
- ⚪ `bismark_window_pca` (bismark/window_pca.py) — consumes upstream DCs (dc_ref)
- ⚪ `bismark_window_correlation` (bismark/window_correlation.py) — consumes upstream DCs (dc_ref)
- ⚪ `bismark_top_variable_windows` (bismark/top_variable_windows.py) — consumes upstream DCs (dc_ref)
- ⚪ `bismark_window_group_compare` (bismark/window_group_compare.py) — consumes upstream DCs (dc_ref)
- ⚪ `qualimap_bamqc_genome_results` (qualimap/bamqc_genome_results.py) — consumes upstream DCs (dc_ref)
- ⚪ `qualimap_coverage_across_reference` (qualimap/coverage_across_reference.py) — consumes upstream DCs (dc_ref)
- ⚪ `qualimap_coverage_histogram` (qualimap/coverage_histogram.py) — consumes upstream DCs (dc_ref)
- ⚪ `qualimap_genome_fraction_coverage` (qualimap/genome_fraction_coverage.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 93 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 0 resolved, 1 missing, 0 optional-absent (of 1)
- ❌ `samples` (samplesheet) → input/samplesheet_full.csv

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline methylseq --new-version 4.2.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
