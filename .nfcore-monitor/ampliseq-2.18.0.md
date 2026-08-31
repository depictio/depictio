# nf-core/ampliseq drift report — 2.16.0 → 2.18.0

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/ampliseq/results-2723d4c298d48321594920d0324697e14d73ee94/`

## Recipe execution — 4 pass, 0 fail, 16 skipped
- ✅ `alpha_rarefaction` (qiime2/alpha_rarefaction.py) — 24670 rows × 4 cols
- ✅ `taxonomy_composition` (qiime2/taxonomy_composition.py) — 36 rows × 9 cols
- ✅ `ancombc_results` (qiime2/ancombc.py) — 9 rows × 11 cols
- ✅ `alpha_diversity_multi_canonical` (qiime2/alpha_diversity_multi_canonical.py) — 12 rows × 8 cols
- ⚪ `alpha_rarefaction_summary` (qiime2/alpha_rarefaction_summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `taxonomy_rel_abundance` (nf-core/ampliseq/taxonomy_rel_abundance.py) — consumes upstream DCs (dc_ref)
- ⚪ `sintax_rel_abundance` (nf-core/ampliseq/sintax_rel_abundance.py) — consumes upstream DCs (dc_ref)
- ⚪ `taxonomy_heatmap` (qiime2/taxonomy_heatmap.py) — consumes upstream DCs (dc_ref)
- ⚪ `stacked_taxonomy_canonical` (qiime2/stacked_taxonomy_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `embedding_pcoa` (qiime2/embedding_pcoa.py) — consumes upstream DCs (dc_ref)
- ⚪ `rarefaction_canonical` (qiime2/rarefaction_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `complex_heatmap_canonical` (nf-core/ampliseq/complex_heatmap_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `sunburst_canonical` (nf-core/ampliseq/sunburst_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `sankey_canonical` (nf-core/ampliseq/sankey_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `upset_canonical` (nf-core/ampliseq/upset_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `ma_canonical` (nf-core/ampliseq/ma_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `bray_curtis_canonical` (nf-core/ampliseq/bray_curtis_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `phylogenetic_tree_metadata_canonical` (nf-core/ampliseq/tree_metadata_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `sidle_reconstructed` (nf-core/ampliseq/sidle_reconstructed.py) — optional route not exercised by megatest (source absent: sidle/reconstructed/reconstructed_merged.tsv)
- ⚪ `sidle_reconstruction_qc` (nf-core/ampliseq/sidle_reconstruction_qc.py) — optional route not exercised by megatest (source absent: sidle/DB/3_reconstructed/reconstruction_summary/metadata.tsv)

## Catalog validate — ✅ PASS
- OK: 7 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 25 resolved, 0 missing, 2 optional-absent (of 27)
- ⚪ `sidle_reconstructed` (reconstructed) → sidle/reconstructed/reconstructed_merged.tsv — optional route, not exercised by megatest
- ⚪ `sidle_reconstruction_qc` (qc) → sidle/DB/3_reconstructed/reconstruction_summary/metadata.tsv — optional route, not exercised by megatest

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline ampliseq --new-version 2.18.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
