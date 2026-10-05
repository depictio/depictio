# nf-core/ampliseq 2.18.0: Depictio dashboards

One dashboard, up to seven tabs, read as a funnel: **MultiQC -> Alpha Diversity
-> Community & Diversity -> Ordination & Clustering -> Differential Abundance
-> Phylogeny**, plus **Reconstructed Community (SIDLE)** on the multi-region
route only. Route flags read from `pipeline_info/params.json` prune the data
collections a run did not produce, and a tab left without data is dropped.

The design comes from the sample metadata file (`--metadata`), declared through
`METADATA_FILE`, `METADATA_ID_COL` and `GROUP_COL` (`GROUP_COL_DISPLAY` is the
reader label). Every grouped tile, the group filter and the ANCOM-BC contrast
read `{GROUP_COL}`; nothing is parsed from sample names.

A pinned strip of four cards (samples split by group, number of groups, phyla
detected, median Shannon) opens every tab and is never repeated as a tab card.
Under it, the collapsed `Sample sheet` section holds the metadata table.

## Tabs

**MultiQC.** MultiQC panels only: general statistics, Cutadapt filtered reads,
FastQC sequence counts and quality histograms, the other FastQC and Cutadapt
panels in a collapsed section. No per-sequence GC panel: amplicon reads occupy
a narrow GC band and the panel reads as a flat line.

**Alpha Diversity.** Cards: observed features, Faith's PD and evenness (median
with a box plot each), and the deepest rarefaction depth. Then the rarefaction
curves (metric switch in the tile header), the indices per group, and the
per-sample table collapsed at the end.

**Community & Diversity.** The 15 most abundant phyla by mean relative
abundance per group (percent), the stacked per-sample composition (rank switch
in the header), the sunburst hierarchy, and the UpSet of taxa shared between
groups (annotated by phylum). One hierarchy view only: the Sankey restated the
sunburst on the same data and was removed. SINTAX tiles appear only on
`--skip_qiime` runs.

**Ordination & Clustering.** PCoA on Bray-Curtis (lasso selection enabled),
the Bray-Curtis distance heatmap (`ward`, `Blues`) and the clustered phylum by
sample heatmap.

**Differential Abundance.** Pick a contrast first. Cards: taxa tested,
significant taxa (FDR 5%), enriched taxa (FDR 5% and a positive log-fold
change), the log-fold-change distribution. Then the volcano and the ranked
differential-abundance bars. The `Taxon detail` section at the end holds the
full ANCOM-BC table with the taxon record card beside it (`linked_component`): the
card stays a thin rail until a row is picked, then opens on that taxon (no default record).
There is no MA view: `ancombc_results` has no mean-abundance column, and the
contrast filter does not reach `ma_canonical`.

**Phylogeny.** The ASV tree, pruned to the clade picked in the left panel,
coloured by any rank. Cards: ASVs, genus-level classification, classifier
confidence, genera.
The tip-metadata recipe also computes, per ASV, the `GROUP_COL` level that
carries most of its abundance (passed to the recipe as the `group_col` param;
without it, the second metadata column). The column keeps its historical name
`dominant_habitat` whatever factor fills it.

**Reconstructed Community (SIDLE).** Multi-region route only: reconstructed
composition per sample (phylum, and the 15 most abundant genera with the rest
as Other), and the reconstruction QC (regions and k-mers per feature).

## Cross-selection

Tables select rows and the SIDLE k-mer scatter selects points; a pick becomes a dashboard
filter that narrows the other tiles of the same collection and, through the project links,
the collections downstream of it. Row selection is on the metadata id column in the pinned
sample sheet, `sample_id` in the alpha-diversity table, `taxonomy` in the two relative
abundance tables, `id` in the ANCOM-BC table, `taxon` in the tip taxonomy table and
`feature_id` in both SIDLE tables and the SIDLE scatter. The bar and box figures do not
select. The ordination embedding emits a selection, but its collection has no outgoing
link, so it narrows no other tile.

## Filters

The persistent `Sample filters` section (sample id and `{GROUP_COL}`, both on
the metadata collection, the source of every sample link) reaches every tab;
the tabs carry no sample or group filter of their own. A non-persistent
`MultiQC report` section keeps a sample list read from the MultiQC report, for
runs without `--metadata`. Each tab then filters its own columns: the Shannon
range on Alpha Diversity, kingdom, phylum and relative abundance on Community,
phylum on Ordination, contrast, taxonomy, W and log-fold change on
Differential Abundance, kingdom and phylum on Phylogeny, phylum on SIDLE.

## Controls

`advanced_viz_controls: header` on every tab.

## Reference project

The bundled reference project is imported from
`dashboards/reference_extended.yaml`, generated from `base.yaml` by
`build_reference_dashboard.py` (never hand-edited). The generator adds the demo
layer the generic template cannot carry: the sampling campaign and environment
tabs, the map, group colours on the UpSet and heatmaps, and the tree's
`dominant_habitat` colour option.

## Reproducing

```bash
python scripts/nfcore_megatest.py fetch --pipeline ampliseq --version 2.18.0 --dest <DATA_ROOT>
depictio-cli run --template nf-core/ampliseq/2.18.0 --data-root <DATA_ROOT> --var GROUP_COL=habitat
python depictio/projects/nf-core/ampliseq/2.18.0/build_reference_dashboard.py
```
