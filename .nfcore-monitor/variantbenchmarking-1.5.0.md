# nf-core/variantbenchmarking drift report — 1.4.0 → 1.5.0

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/variantbenchmarking/results-8b21c01749c4447b285d242a198127736f3ffe51/`

## Recipe execution — 0 pass, 0 fail, 9 skipped
- ⚪ `germline_vcfeval_summary` (rtgtools/vcfeval_summary.py) — glob source not executed
- ⚪ `germline_happy_summary` (happy/summary.py) — glob source not executed
- ⚪ `germline_happy_roc` (happy/roc.py) — glob source not executed
- ⚪ `somatic_vcfeval_summary` (rtgtools/vcfeval_summary.py) — glob source not executed
- ⚪ `somatic_sompy_summary` (sompy/summary.py) — glob source not executed
- ⚪ `somatic_sompy_regions` (sompy/regions.py) — glob source not executed
- ⚪ `sv_truvari_summary` (truvari/summary.py) — glob source not executed
- ⚪ `sv_svbenchmark_summary` (svanalyzer/svbenchmark.py) — glob source not executed
- ⚪ `cnv_wittyer_summary` (wittyer/summary.py) — glob source not executed

## Catalog validate — ✅ PASS
- OK: 37 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 0 resolved, 0 missing, 0 optional-absent (of 0)

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline variantbenchmarking --new-version 1.5.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
