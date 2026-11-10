# nf-core/variantbenchmarking drift report — 1.4.0 → 1.6.1

**🟡 probable — 6 path(s) the template reads are unchanged; 2 directory change(s) elsewhere; 0 of 10 recipes ran** · Megatest: `s3://nf-core-awsmegatests/variantbenchmarking/results-c4c9440bfb6e6bc0a7787ff9ecfad4838308f3a1/`

Upstream changes: https://github.com/nf-core/variantbenchmarking/blob/master/CHANGELOG.md

## Run structure vs 1.5.0 — 212 → 392 keys
- ➕ `indel/multiqc/` only in the release
- ➕ `small/multiqc/` only in the release

## Recipe execution — 0 pass, 0 fail, 10 skipped
- ⚪ `germline_vcfeval_summary` (rtgtools/vcfeval_summary.py) — glob source not executed
- ⚪ `germline_happy_summary` (happy/summary.py) — glob source not executed
- ⚪ `germline_happy_roc` (happy/roc.py) — glob source not executed
- ⚪ `somatic_vcfeval_summary` (rtgtools/vcfeval_summary.py) — glob source not executed
- ⚪ `somatic_sompy_summary` (sompy/summary.py) — glob source not executed
- ⚪ `somatic_sompy_regions` (sompy/regions.py) — glob source not executed
- ⚪ `sv_truvari_summary` (truvari/summary.py) — glob source not executed
- ⚪ `sv_svbenchmark_summary` (svanalyzer/svbenchmark.py) — glob source not executed
- ⚪ `cnv_wittyer_summary` (wittyer/summary.py) — glob source not executed
- ⚪ `tracks` (nf-core/variantbenchmarking/tracks.py) — optional route not exercised by megatest (source absent: structural/summary/tables/truvari/truvari.summary.csv)

## Catalog validate — ✅ PASS
- OK: 136 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 1 resolved, 0 missing, 1 optional-absent (of 2)
- ⚪ `tracks` (truvari_summary) → structural/summary/tables/truvari/truvari.summary.csv — optional route, not exercised by megatest

## Next steps
Ship the new version with:
```
python scripts/bump_template_version.py --pipeline variantbenchmarking --new-version 1.6.1
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
