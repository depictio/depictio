# nf-core/ampliseq drift report — 2.16.0 → 2.17.0

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/ampliseq/results-d34664b0f57aeefc92a1dd5ea6e44c6955ec13a6/`

## Recipe execution — 3 pass, 0 fail, 13 skipped
- ✅ `alpha_rarefaction` (qiime2/alpha_rarefaction.py) — 24670 rows × 4 cols
- ✅ `taxonomy_composition` (qiime2/taxonomy_composition.py) — 27 rows × 7 cols
- ✅ `ancombc_results` (qiime2/ancombc.py) — 9 rows × 11 cols
- ⚪ `taxonomy_rel_abundance` (nf-core/ampliseq/taxonomy_rel_abundance.py) — consumes upstream DCs (dc_ref)
- ⚪ `taxonomy_heatmap` (qiime2/taxonomy_heatmap.py) — consumes upstream DCs (dc_ref)
- ⚪ `stacked_taxonomy_canonical` (qiime2/stacked_taxonomy_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `embedding_pcoa` (qiime2/embedding_pcoa.py) — consumes upstream DCs (dc_ref)
- ⚪ `rarefaction_canonical` (qiime2/rarefaction_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `alpha_diversity_multi_canonical` (qiime2/alpha_diversity_multi_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `complex_heatmap_canonical` (nf-core/ampliseq/complex_heatmap_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `sunburst_canonical` (nf-core/ampliseq/sunburst_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `sankey_canonical` (nf-core/ampliseq/sankey_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `upset_canonical` (nf-core/ampliseq/upset_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `ma_canonical` (nf-core/ampliseq/ma_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `bray_curtis_canonical` (nf-core/ampliseq/bray_curtis_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `phylogenetic_tree_metadata_canonical` (nf-core/ampliseq/tree_metadata_canonical.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 7 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 8 resolved, 0 missing (of 8)
