# nf-core/ampliseq drift report — 2.18.0 → 3.1.0

**❌ review needed — major version bump 2.18.0 → 3.1.0** · Megatest: `s3://nf-core-awsmegatests/ampliseq/results-b9bd579c0480ee23ecf24655f51c0c67777cd6b3/`

Upstream changes: https://github.com/nf-core/ampliseq/blob/master/CHANGELOG.md

## Run structure vs 2.18.0 — 3557 → 3559 keys
- ❌ `manifest` (keys) reads `input/Samplesheet_full.tsv`, gone from the run folder
- ❌ `manifest` (keys) reads `qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv`, gone from the run folder
- ➕ `summary_tables/` only in the release

## Recipe execution — 4 pass, 0 fail, 18 skipped
- ✅ `read_tracking` (nf-core/ampliseq/read_tracking.py) — 12 rows × 6 cols
- ✅ `alpha_rarefaction` (qiime2/alpha_rarefaction.py) — 24670 rows × 4 cols
- ✅ `taxonomy_composition` (qiime2/taxonomy_composition.py) — 895 rows × 9 cols
- ✅ `alpha_diversity_multi_canonical` (qiime2/alpha_diversity_multi_canonical.py) — 12 rows × 8 cols
- ⚪ `alpha_rarefaction_summary` (qiime2/alpha_rarefaction_summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `taxonomy_rel_abundance` (nf-core/ampliseq/taxonomy_rel_abundance.py) — consumes upstream DCs (dc_ref)
- ⚪ `sintax_rel_abundance` (vsearch/sintax_abundance.py) — consumes upstream DCs (dc_ref)
- ⚪ `taxonomy_heatmap` (qiime2/taxonomy_heatmap.py) — consumes upstream DCs (dc_ref)
- ⚪ `ancombc_results` (qiime2/ancombc.py) — glob source not executed
- ⚪ `stacked_taxonomy_canonical` (qiime2/stacked_taxonomy_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `embedding_pcoa` (qiime2/embedding_pcoa.py) — consumes upstream DCs (dc_ref)
- ⚪ `rarefaction_canonical` (qiime2/rarefaction_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `complex_heatmap_canonical` (nf-core/ampliseq/complex_heatmap_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `sunburst_canonical` (nf-core/ampliseq/sunburst_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `sankey_canonical` (nf-core/ampliseq/sankey_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `upset_canonical` (nf-core/ampliseq/upset_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `ma_canonical` (nf-core/ampliseq/ma_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `bray_curtis_canonical` (nf-core/ampliseq/bray_curtis_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `beta_adonis` (nf-core/ampliseq/beta_adonis.py) — glob source not executed
- ⚪ `phylogenetic_tree_metadata_canonical` (nf-core/ampliseq/tree_metadata_canonical.py) — consumes upstream DCs (dc_ref)
- ⚪ `sidle_reconstructed` (sidle/reconstructed.py) — optional route not exercised by megatest (source absent: sidle/reconstructed/reconstructed_merged.tsv)
- ⚪ `sidle_reconstruction_qc` (sidle/reconstruction_qc.py) — optional route not exercised by megatest (source absent: sidle/DB/3_reconstructed/reconstruction_summary/metadata.tsv)

## Catalog validate — ✅ PASS
- OK: 136 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 19 resolved, 0 missing, 6 optional-absent (of 25)
- ⚪ `stacked_taxonomy_canonical` (genus) → qiime2/rel_abundance_tables/rel-table-7.tsv — optional route, not exercised by megatest
- ⚪ `sunburst_canonical` (asv_tax) → qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv — optional route, not exercised by megatest
- ⚪ `sankey_canonical` (asv_tax) → qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv — optional route, not exercised by megatest
- ⚪ `phylogenetic_tree_metadata_canonical` (asv_tax) → qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv — optional route, not exercised by megatest
- ⚪ `sidle_reconstructed` (reconstructed) → sidle/reconstructed/reconstructed_merged.tsv — optional route, not exercised by megatest
- ⚪ `sidle_reconstruction_qc` (qc) → sidle/DB/3_reconstructed/reconstruction_summary/metadata.tsv — optional route, not exercised by megatest

## Next steps
Read the changelog and this report first, then ship the new version with:
```
python scripts/bump_template_version.py --pipeline ampliseq --new-version 3.1.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
