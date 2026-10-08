# nf-core/ampliseq 2.18.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from
the run to the taxa that differ between groups. This template is the reference
implementation of the family rules in `depictio/projects/nf-core/RULES.md`.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did sequencing and primer trimming work for every sample? |
| Diversity | Alpha Diversity | How diverse is each sample, and was it sequenced deeply enough? |
| Diversity | Ordination & Clustering | Which samples have similar communities? |
| Taxa | Community & Diversity | Which taxa make up the samples, and which do groups share? |
| Taxa | Differential Abundance | Which taxa differ in abundance between groups? |
| Taxa | Phylogeny | How are the ASVs related, and how deeply are they classified? |
| Taxa | SIDLE | What does the community rebuilt across amplicon regions contain? |

The design comes from the sample metadata file (`--metadata`), declared through
`METADATA_FILE`, `METADATA_ID_COL` and `GROUP_COL` (`GROUP_COL_DISPLAY` is the reader
label). Every grouped tile, the group filters, the PERMANOVA term and the ANCOM-BC
contrasts read `{GROUP_COL}`; nothing is parsed from sample names. Route flags read from
`pipeline_info/params.json` prune the data collections a run did not produce: a tab left
without data is dropped, and so are the Overview tiles and rows that pointed at it.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (samples,
  primers, reference taxonomy, removed taxa), read from the run parameters and the sample
  sheet.
- **Pipeline**: six steps (trim, denoise, classify, alpha, beta, test). Each step opens the
  parameters that drive it and the tab that shows its output. The classify step prints the
  reference taxonomy the run used, read from the run parameters.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples
  (split by group), phyla (split by kingdom), the median Shannon diversity (with its
  spread) and the median share of each sample's reads kept through the pipeline (from
  `overall_summary.tsv`). A group and a sample filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link
  to its tab: the most abundant phylum and its share, the median Shannon diversity, the
  share of variation explained by the group (PERMANOVA on Bray-Curtis, computed by the
  pipeline on all samples, so no filter changes it) and the number of phyla ANCOM-BC calls
  significant at 5% FDR. Below them, four figures in two rows, each linking its tab: phylum
  composition per group beside the ANCOM-BC volcano, then the PCoA beside a tree of the
  ten largest phyla (dot area: share of the reads, split by group). The bar of this
  section filters by group and kingdom.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (group, then sample id) sit in the collapsed left panel
and narrow every tab. The `Sample sheet` section is pinned to the bottom of every child
tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a compact strip of key numbers, then at most three open
sections; tables, details and route alternates follow, collapsed.

**MultiQC.** MultiQC panels only. Open: general statistics, Cutadapt filtered reads,
FastQC sequence counts and quality histograms. Collapsed: the other FastQC and Cutadapt
panels. No per-sequence GC panel: amplicon reads occupy a narrow GC band and the panel
reads as a flat line. Its own sample filter reads the MultiQC report, so it works on a
run without `--metadata`.

**Alpha Diversity.** Strip: median Shannon, observed ASVs, Faith's PD and evenness. Then
the rarefaction curves (metric switch on the tile, curves per group) and Shannon
diversity per group as a box plot with one point per sample. The per-sample table is
collapsed. Filter: a Shannon range.

**Ordination & Clustering.** Strip: the samples placed by the PCoA and, when the run
tested a PERMANOVA formula, the share of variation the group explains. Then the PCoA on
Bray-Curtis (a lasso makes an analysis group) beside the Bray-Curtis distance heatmap
(`ward`, `Blues`), and the clustered phylum by sample heatmap. Filter: phylum, on the
heatmap rows.

**Community & Diversity.** Strip: distinct phyla (by kingdom), classes, orders and
families. Then the phylum composition per group (ten phyla and Other, as 100% bars), the
stacked composition per sample, and the sunburst hierarchy. Collapsed: the UpSet of taxa
shared between groups, and the relative abundance table. No Sankey: it restates the
sunburst. Filters: kingdom and phylum.

**Differential Abundance.** Pick a contrast first. Strip: taxa tested, significant at 5%
FDR, enriched and depleted (significant, by sign of the log-fold change). Then the volcano
and the largest effects per contrast. The collapsed `Taxon detail` holds the ANCOM-BC
table with the taxon record card beside it: the card waits for a picked row. No MA view:
`ancombc_results` has no mean-abundance column, and the contrast filter does not reach
`ma_canonical`. Filters: contrast, phylum, kingdom and a log-fold-change range.

**Phylogeny.** Strip: ASVs, ASVs classified to genus, the median classifier confidence
and distinct genera. Then the ASV tree, coloured by any rank and pruned to the clade
picked in the left panel. The tip taxonomy table is collapsed. The tip-metadata recipe
also computes, per ASV, the `GROUP_COL` level that carries most of its abundance; the
column keeps its historical name `dominant_habitat` whatever factor fills it. Filters:
kingdom and phylum.

**SIDLE.** Multi-region route only. Strip: reconstructed features, samples, phyla and the
mean number of regions per feature. Then the composition per sample (phylum, and the
fifteen most abundant genera with the rest as Other) and the reconstruction QC (regions
and k-mers per feature). The two tables are collapsed. Filter: phylum.

## Routes and pruning

A run takes one taxonomy route: QIIME 2 (default), SINTAX (`--skip_qiime`) or SIDLE
(multi-region). The components bound to the alternatives share one grid slot, and the one
whose data the run produced takes it: the phyla card, the kingdom filter of the Findings
bar, the dominant-phylum row, the composition highlight, and on Community & Diversity the
filters, the phyla card, the composition bar and the table.

| Route | What changes |
|---|---|
| No `--metadata` | No sample filters, Samples card, PERMANOVA and ANCOM-BC rows, volcano highlight, UpSet or Differential Abundance tab. The group figures show all samples as one group. |
| `--skip_qiime` | SINTAX alternates replace the QIIME 2 ones; MultiQC and Community & Diversity are the only child tabs. |
| Multi-region | The SIDLE tab and alternates; MultiQC and SIDLE are the only child tabs. |
| `--skip_taxonomy` | No Community & Diversity, Ordination & Clustering or Differential Abundance tab, nor the Overview tiles and rows that point at them. The Overview tree sizes its dots by ASVs instead of reads. |
| `--skip_alpha_rarefaction` | No Alpha Diversity tab, Shannon card or row. |
| `--skip_ancom` | No Differential Abundance tab, ANCOM-BC row or volcano highlight. |
| No PERMANOVA formula | No R² card or row. |
| No `overall_summary.tsv` | No reads-kept card. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the group
column is coloured `auto` (each value takes a colour-blind-safe colour at import, kept on
a re-import), kingdoms are written out, and the Other and Unclassified phylum buckets are
grey. Code figures read the same map and follow Analysis mode's groups when it has some;
the UpSet colours its sets through `set_category_column`.

## Cross-selection

Tables select rows and the SIDLE k-mer scatter selects points; a pick becomes a dashboard
filter that narrows the other tiles of the same collection and, through the project links,
the collections downstream of it. Row selection is on the metadata id column in the sample
sheet, `sample_id` in the alpha-diversity table, `taxonomy` in the relative abundance
tables, `id` in the ANCOM-BC table, `taxon` in the tip taxonomy table and `feature_id` in
the SIDLE tables and scatter. A lasso on the PCoA becomes an analysis group.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top
of a narrower one. Nothing is set per tab or per tile.

## Reference project

The bundled reference project is imported from `dashboards/reference_extended.yaml`,
generated from `base.yaml` by `build_reference_dashboard.py` (never hand-edited). The
generator adds the demo layer the generic template cannot carry: the sampling campaign and
environment tabs, the map, and the tree's `dominant_habitat` colour option.

## Reproducing

`GROUP_COL` is the metadata column the ANCOM-BC slices were computed on; the megatest
`post_fetch_help` names it for the reference run.

```bash
python scripts/nfcore_megatest.py fetch --pipeline ampliseq --version 2.18.0 --dest <DATA_ROOT>
depictio-cli ingest --template nf-core/ampliseq/2.18.0 --data-root <DATA_ROOT> --var GROUP_COL=<column>
python depictio/projects/nf-core/ampliseq/2.18.0/build_reference_dashboard.py
```
