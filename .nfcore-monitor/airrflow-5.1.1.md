# nf-core/airrflow drift report — 5.1.0 → 5.1.1

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/airrflow/results-e69d49e3f23f11a3391755b5fb7aa4283c0a2471/`

> ⚠️ nf-core/airrflow 5.1.1: no megatest run at s3://nf-core-awsmegatests/airrflow/results-8bc3e567d0bb3a4c47ead15a8f42e764580f76dc/. Falling back to the newest real run `airrflow/results-e69d49e3f23f11a3391755b5fb7aa4283c0a2471/` (release 5.1.0).

## Recipe execution — 10 pass, 0 fail, 0 skipped
- ✅ `sequence_counts` (enchantr/sequence_counts.py) — 10 rows × 17 cols
- ✅ `sequence_fates` (enchantr/sequence_fates.py) — 80 rows × 11 cols
- ✅ `repertoire_summary` (enchantr/repertoire_summary.py) — 10 rows × 20 cols
- ✅ `clonal_diversity` (enchantr/clonal_diversity.py) — 369 rows × 10 cols
- ✅ `clone_sizes` (enchantr/clone_sizes.py) — 67770 rows × 7 cols
- ✅ `clone_sets` (enchantr/clone_sets.py) — 45149 rows × 14 cols
- ✅ `clonal_overlap` (enchantr/clonal_overlap.py) — 10 rows × 12 cols
- ✅ `v_gene_usage` (enchantr/v_gene_usage.py) — 490 rows × 9 cols
- ✅ `v_gene_matrix` (enchantr/v_gene_matrix.py) — 10 rows × 59 cols
- ✅ `threshold_summary` (enchantr/threshold_summary.py) — 2 rows × 9 cols

## Catalog validate — ✅ PASS
- OK: 37 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 15 resolved, 0 missing, 0 optional-absent (of 15)

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline airrflow --new-version 5.1.1
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
