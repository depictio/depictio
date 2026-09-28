# nf-core/cutandrun drift report — 3.1 → 3.2.2

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/cutandrun/results-42502fb44975e930eec865353c5481f472bcf766/`

> ⚠️ nf-core/cutandrun 3.2.2: megatest run s3://nf-core-awsmegatests/cutandrun/results-6e1125d4fee4ea7c8b70ed836bb0e92a89e3305f/ is empty, failed or truncated (0 data object(s) outside pipeline_info/, 0 of them under 50 MB, in 33 keys; need 5 of each). Falling back to the newest real run `cutandrun/results-42502fb44975e930eec865353c5481f472bcf766/` (release 3.1).

## Recipe execution — 1 pass, 0 fail, 9 skipped
- ✅ `samples` (nf-core/cutandrun/samples.py) — 6 rows × 9 cols
- ⚪ `deeptools_fingerprint_metrics` (deeptools/fingerprint_metrics.py) — glob source not executed
- ⚪ `deeptools_sample_pca` (deeptools/sample_pca.py) — glob source not executed
- ⚪ `deeptools_correlation_matrix` (deeptools/correlation_matrix.py) — glob source not executed
- ⚪ `seacr_peaks` (seacr/peaks.py) — consumes upstream DCs (dc_ref)
- ⚪ `seacr_peak_summary` (seacr/peak_summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `macs2_peaks` (macs2/peaks.py) — glob source not executed
- ⚪ `seacr_consensus_peaks` (seacr/consensus_peaks.py) — glob source not executed
- ⚪ `seacr_fragment_lengths` (seacr/fragment_lengths.py) — consumes upstream DCs (dc_ref)
- ⚪ `caller_agreement` (nf-core/cutandrun/caller_agreement.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 37 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 1 resolved, 0 missing, 0 optional-absent (of 1)

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline cutandrun --new-version 3.2.2
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
