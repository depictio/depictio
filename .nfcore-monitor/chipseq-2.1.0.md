# nf-core/chipseq drift report — 1.2.0 → 2.1.0

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/chipseq/results-0f487ed76dc947793ab48527d8d3025f5f3060a5/`

> ⚠️ nf-core/chipseq 2.1.0: megatest run s3://nf-core-awsmegatests/chipseq/results-76e2382b6d443db4dc2396e6831d1243256d80b0/ is empty, failed or truncated (29 data object(s) outside pipeline_info/, 1 of them under 50 MB, in 134 keys; need 5 of each). Falling back to the newest real run `chipseq/results-0f487ed76dc947793ab48527d8d3025f5f3060a5/` (release 1.2.1).

## Recipe execution — 0 pass, 0 fail, 10 skipped
- ⚪ `preseq_complexity_curve` (preseq/complexity_curve.py) — consumes upstream DCs (dc_ref)
- ⚪ `deeptools_fingerprint_metrics` (deeptools/fingerprint_metrics.py) — glob source not executed
- ⚪ `deeptools_plot_profile` (deeptools/plot_profile.py) — glob source not executed
- ⚪ `macs2_peaks` (macs2/peaks.py) — glob source not executed
- ⚪ `macs2_peak_summary` (macs2/peak_summary.py) — glob source not executed
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
python scripts/bump_template_version.py --pipeline chipseq --new-version 2.1.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
