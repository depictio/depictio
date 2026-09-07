# nf-core/variantbenchmarking drift report — 1.4.0 → 1.5.0

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/variantbenchmarking/results-8b21c01749c4447b285d242a198127736f3ffe51/`

## Recipe execution — 4 pass, 0 fail, 5 skipped
- ✅ `germline_vcfeval_summary` (rtgtools/vcfeval_summary.py) — 3 rows × 9 cols
- ✅ `somatic_vcfeval_summary` (rtgtools/vcfeval_summary.py) — 3 rows × 9 cols
- ✅ `somatic_sompy_summary` (sompy/summary.py) — 3 rows × 12 cols
- ✅ `somatic_sompy_regions` (sompy/regions.py) — 5 rows × 8 cols
- ⚪ `germline_happy_summary` (happy/summary.py) — glob source not executed
- ⚪ `germline_happy_roc` (happy/roc.py) — glob source not executed
- ⚪ `sv_truvari_summary` (truvari/summary.py) — optional route not exercised by megatest (source absent: sv/summary/tables/truvari/truvari.summary.csv)
- ⚪ `sv_svbenchmark_summary` (svanalyzer/svbenchmark.py) — optional route not exercised by megatest (source absent: sv/summary/tables/svbenchmark/svbenchmark.summary.csv)
- ⚪ `cnv_wittyer_summary` (wittyer/summary.py) — optional route not exercised by megatest (source absent: cnv/summary/tables/wittyer/wittyer.summary.csv)

## Catalog validate — ✅ PASS
- OK: 13 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 4 resolved, 0 missing, 3 optional-absent (of 7)
- ⚪ `sv_truvari_summary` (truvari_summary) → sv/summary/tables/truvari/truvari.summary.csv — optional route, not exercised by megatest
- ⚪ `sv_svbenchmark_summary` (svbenchmark_summary) → sv/summary/tables/svbenchmark/svbenchmark.summary.csv — optional route, not exercised by megatest
- ⚪ `cnv_wittyer_summary` (wittyer_summary) → cnv/summary/tables/wittyer/wittyer.summary.csv — optional route, not exercised by megatest

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline variantbenchmarking --new-version 1.5.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
