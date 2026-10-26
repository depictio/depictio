# nf-core/eager drift report — 2.4.5 → 2.5.3

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/eager/results-42c9d5f8602e5e88fdcec28f194d2cd4cff61c75/`

> ⚠️ nf-core/eager 2.5.3: megatest run s3://nf-core-awsmegatests/eager/results-3f9d64ced5e287391bcd5517a0c40153a01268e5/ is empty, failed or truncated (0 data object(s) outside pipeline_info/, 0 of them under 50 MB, in 1 keys; need 5 of each). Falling back to the newest real run `eager/results-42c9d5f8602e5e88fdcec28f194d2cd4cff61c75/` (release 2.4.5).

## Recipe execution — 0 pass, 0 fail, 20 skipped
- ⚪ `samples` (nf-core/eager/samples.py) — glob source not executed
- ⚪ `adapterremoval_settings` (adapterremoval/settings.py) — consumes upstream DCs (dc_ref)
- ⚪ `eager_lane_stats` (nf-core/eager/lane_stats.py) — consumes upstream DCs (dc_ref)
- ⚪ `samtools_flagstat` (samtools/flagstat.py) — consumes upstream DCs (dc_ref)
- ⚪ `endorspy_endogenous` (endorspy/endogenous.py) — consumes upstream DCs (dc_ref)
- ⚪ `picard_markduplicates_metrics` (picard/markduplicates_metrics.py) — consumes upstream DCs (dc_ref)
- ⚪ `eager_read_fate` (nf-core/eager/read_fate.py) — consumes upstream DCs (dc_ref)
- ⚪ `qualimap_bamqc_genome_results` (qualimap/bamqc_genome_results.py) — consumes upstream DCs (dc_ref)
- ⚪ `qualimap_coverage_per_contig` (qualimap/coverage_per_contig.py) — consumes upstream DCs (dc_ref)
- ⚪ `qualimap_coverage_across_reference` (qualimap/coverage_across_reference.py) — consumes upstream DCs (dc_ref)
- ⚪ `qualimap_mapq_across_reference` (nf-core/eager/mapq_across_reference.py) — consumes upstream DCs (dc_ref)
- ⚪ `qualimap_coverage_histogram` (qualimap/coverage_histogram.py) — consumes upstream DCs (dc_ref)
- ⚪ `qualimap_genome_fraction_coverage` (qualimap/genome_fraction_coverage.py) — consumes upstream DCs (dc_ref)
- ⚪ `preseq_complexity_curve` (nf-core/eager/complexity_curve.py) — consumes upstream DCs (dc_ref)
- ⚪ `damageprofiler_misincorporation` (damageprofiler/misincorporation.py) — consumes upstream DCs (dc_ref)
- ⚪ `damageprofiler_lgdistribution` (damageprofiler/lgdistribution.py) — consumes upstream DCs (dc_ref)
- ⚪ `damageprofiler_authenticity` (damageprofiler/authenticity.py) — consumes upstream DCs (dc_ref)
- ⚪ `eager_library_qc` (nf-core/eager/library_qc.py) — consumes upstream DCs (dc_ref)
- ⚪ `bcftools_stats_summary` (bcftools/stats_summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `bcftools_stats_tstv` (bcftools/stats_tstv.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 120 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 0 resolved, 0 missing, 0 optional-absent (of 0)

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline eager --new-version 2.5.3
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
