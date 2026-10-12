# nf-core/airrflow drift report — 5.1.1 → 5.1.2

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/airrflow/results-e69d49e3f23f11a3391755b5fb7aa4283c0a2471/`

> ⚠️ nf-core/airrflow 5.1.2: no megatest run at s3://nf-core-awsmegatests/airrflow/results-601bbe64a4a035b531b70626eeacca9770100e6e/. Falling back to the newest real run `airrflow/results-e69d49e3f23f11a3391755b5fb7aa4283c0a2471/` (release 5.1.0).

## Recipe execution — 16 pass, 0 fail, 2 skipped
- ✅ `sequence_counts` (enchantr/sequence_counts.py) — 10 rows × 17 cols
- ✅ `sequence_fates` (enchantr/sequence_fates.py) — 80 rows × 11 cols
- ✅ `annotation_counts_assembled` (nf-core/airrflow/annotation_counts.py) — 10 rows × 8 cols
- ✅ `annotation_counts_noclonal` (nf-core/airrflow/annotation_counts.py) — 10 rows × 8 cols
- ✅ `repertoire_summary` (enchantr/repertoire_summary.py) — 10 rows × 20 cols
- ✅ `repertoire_summary_noreport` (enchantr/repertoire_summary.py) — 10 rows × 20 cols
- ✅ `clonal_diversity` (enchantr/clonal_diversity.py) — 369 rows × 10 cols
- ✅ `diversity_orders` (enchantr/diversity_orders.py) — 27 rows × 7 cols
- ✅ `clonal_abundance` (enchantr/clonal_abundance.py) — 1296 rows × 8 cols
- ✅ `clone_sizes` (enchantr/clone_sizes.py) — 67770 rows × 7 cols
- ✅ `clone_sets` (enchantr/clone_sets.py) — 45149 rows × 14 cols
- ✅ `clonal_overlap` (enchantr/clonal_overlap.py) — 10 rows × 12 cols
- ✅ `v_gene_usage` (enchantr/v_gene_usage.py) — 490 rows × 9 cols
- ✅ `v_gene_matrix` (enchantr/v_gene_matrix.py) — 10 rows × 59 cols
- ✅ `v_gene_usage_noclonal` (enchantr/v_gene_usage.py) — 490 rows × 9 cols
- ✅ `threshold_summary` (enchantr/threshold_summary.py) — 2 rows × 9 cols
- ⚪ `cdr3_spectratype` (nf-core/airrflow/cdr3_spectratype.py) — glob source not executed
- ⚪ `vj_usage_matrix` (nf-core/airrflow/vj_usage_matrix.py) — glob source not executed

## Catalog validate — ✅ PASS
- OK: 93 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 23 resolved, 0 missing, 0 optional-absent (of 23)

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline airrflow --new-version 5.1.2
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
