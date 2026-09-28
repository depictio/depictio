# nf-core/atacseq drift report — 1.2.2 → 2.1.2

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/atacseq/results-f327c86324427c64716be09c98634ae0bc8165f6/`

> ⚠️ nf-core/atacseq 2.1.2: megatest run s3://nf-core-awsmegatests/atacseq/results-1a1dbe52ffbd82256c941a032b0e22abbd925b8a/ is empty, failed or truncated (1 data object(s) outside pipeline_info/, 0 of them under 50 MB, in 139 keys; need 5 of each). Falling back to the newest real run `atacseq/results-f327c86324427c64716be09c98634ae0bc8165f6/` (release 1.2.2).

## Recipe execution — 0 pass, 0 fail, 15 skipped
- ⚪ `sample_design` (nf-core/atacseq/sample_design.py) — glob source not executed
- ⚪ `ataqv_metrics` (ataqv/metrics.py) — glob source not executed
- ⚪ `ataqv_fragment_length` (ataqv/fragment_length.py) — glob source not executed
- ⚪ `ataqv_tss_coverage` (ataqv/tss_coverage.py) — glob source not executed
- ⚪ `ataqv_chromosome_counts` (ataqv/chromosome_counts.py) — glob source not executed
- ⚪ `preseq_complexity_curve` (preseq/complexity_curve.py) — consumes upstream DCs (dc_ref)
- ⚪ `deeptools_fingerprint_metrics` (deeptools/fingerprint_metrics.py) — glob source not executed
- ⚪ `deeptools_plot_profile` (deeptools/plot_profile.py) — glob source not executed
- ⚪ `macs2_peak_summary` (macs2/peak_summary.py) — glob source not executed
- ⚪ `macs2_broad_peaks` (macs2/broad_peaks.py) — glob source not executed
- ⚪ `homer_annotated_peaks` (homer/annotate_peaks.py) — glob source not executed
- ⚪ `homer_tss_distance_profile` (homer/tss_distance_profile.py) — consumes upstream DCs (dc_ref)
- ⚪ `macs2_consensus_boolean` (macs2/consensus_boolean.py) — glob source not executed
- ⚪ `macs2_consensus_fc` (macs2/consensus_fc.py) — glob source not executed
- ⚪ `deseq2_results` (deseq2/results_long.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 37 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 0 resolved, 0 missing, 0 optional-absent (of 0)

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline atacseq --new-version 2.1.2
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
