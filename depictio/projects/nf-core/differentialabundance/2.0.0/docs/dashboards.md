# nf-core/differentialabundance 2.0.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from the
samples to the gene sets that move.
[nf-core/differentialabundance](https://nf-co.re/differentialabundance) runs DESeq2 over a
count matrix and a contrast sheet; the template shows the variance-stabilised sample space,
the per-contrast statistics, the gene annotation joined onto them and the GSEA report. The
family rules live in `depictio/projects/nf-core/RULES.md`.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | Samples | Do the samples separate by design, and are they normalised alike? |
| Differential | Differential expression | Which genes change in each contrast, and can the test be trusted? |
| Differential | Genome view | Where on the genome do the calls sit? |
| Gene sets | Enrichment | Which gene sets move in each contrast, and at which pole? |

Scope: the DESeq2 route (`--differential_method deseq2`, the pipeline default). The limma,
propd and dream routes write differently named tables and are not bound.

There is no MultiQC tab: differentialabundance runs no MultiQC (its report is an R/shinyngs
application, with nothing Depictio can read), so the `Data & QC` group holds the Samples tab
alone. It carries the run-level quality read: group balance, library-size normalisation,
the sample space and the expression distribution of every sample.

The design comes from the pipeline's own `--input` sheet. The samples recipe aliases its
most factor-like column as `group` and the next three as `factor_2`, `factor_3` and
`factor_4` (each with a `factor_<n>_name` column holding the original name), so the filters
bind without the template knowing what a run's sheet calls them; nothing is parsed from
sample names. The contrasts are the pipeline's own.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (samples,
  contrasts, the test, the cut-offs and the number of gene sets GSEA scored), read from the
  run parameters and the tables.
- **Pipeline**: five steps (sheet, explore, test, place, enrich). Each step opens the
  parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples
  (split by group), the DESeq2 size factor (a box plot), the gene tests that kept an
  adjusted p (a strip of those under 0.05) and the significant calls (split by direction).
  All four read tables every route writes, so the row stays four wide without a GTF or
  GSEA; the placed calls and the enriched sets are Findings rows. A group and a contrast
  filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link
  to its tab: the genes called out of those tested, how many go up and down, the chromosome
  that carries the largest share of the placed calls and the number of enriched gene sets.
  Below them, four figures in two rows, each linking its tab: the volcano beside the sample
  PCA, then the Manhattan plot beside the GSEA dot plot. The bar of this section filters by
  contrast and group.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

Two persistent filter sections sit in the collapsed left panel. `Sample filters` (group,
sample and the three further factors) narrows the Samples tab and the sample sheet; a
contrast pools its samples, so the differential tables have no sample column, and the
section is left off the three analysis tabs. `Contrast` narrows the three analysis tabs: it
is sourced on `deseq2_results.contrast` and reaches the annotated table and the GSEA report
through the template links, so one pick follows the reader from tab to tab. The `Sample
sheet` section is pinned to the bottom of every child tab, collapsed, and absent from the
Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read
the tab), then a strip of four key numbers, each card with its own colour and a secondary
that reads it (a box plot, a distribution, a gauge, a threshold, a completeness bar, a
ranking or a share), then at most three open sections; tables and details follow, collapsed.

**Samples.** Strip: the samples (a ring by group), the DESeq2 size factor (a box plot), the
median variance-stabilised expression per sample (a distribution) and the share of features
at the matrix floor (a box plot, 0 to 1). Then the PCA, and under it the sample-to-sample
distance heatmap (`ward`, `Blues`) at full width, since sample ids label both its axes; a
lasso on the PCA carries those samples to the other panels. Then the expression
distribution of every sample on one shared grid, the panel a PCA cannot replace: a curve
out of the bundle is a library normalised differently; hover names a curve, there is no
legend. Last, the most variable features, row z-scored and clustered both ways. Filter: a
size-factor range.

**Differential expression.** Pick a contrast first. Strip: the gene tests that kept an
adjusted p-value (DESeq2's independent filtering removes the rest), the significant calls
(a share by direction), the median log2 fold change (a box plot, near zero when the
normalisation is sound) and the median adjusted p-value (a threshold strip at 0.05). Then
the volcano, cut at the pipeline's thresholds (padj 0.05, a two-fold change), whose View
switch draws the MA plot (`log2_base_mean` on x) or the QQ plot of the raw p-values; it
carries no point labels, since the results hold Ensembl ids only, and hover names a gene.
Then the test diagnostics: the raw p-value histogram per contrast beside a scatter pairing
the first two contrasts gene by gene (a single-contrast run shows its MA view there). Then
the 10 strongest calls per contrast beside the effect sizes per biotype.
Collapsed: the annotated table with the gene record beside it, then the full DESeq2 table.
Filters: direction, log2 fold change, significance, expression level and biotype.

**Genome view.** Needs the run's GTF. Strip: the gene tests the annotation places (a
share by biotype), the placed calls (the busiest chromosomes), the call strength (a box plot
of -log10 padj) and the biotypes the up and the down calls reach (a ranking). Then the
Manhattan plot (height -log10 padj, threshold line at 0.05, the six strongest genes
labelled, selectable by gene) and the
lollipop panel: one lane per contrast, one head per gene at its start coordinate, coloured
by direction and sized by significance. Pick a chromosome before turning the stems on.
Filters: chromosome, significance and log2 fold change.

**Enrichment.** Needs a GSEA run. Strip: the set reports (a ring by pole, all four poles
of two contrasts), the strongest
absolute normalised enrichment score (a box plot), the median FDR (a threshold at 0.05,
warning at 0.25) and the median leading-edge share of each set (a gauge). Then the dot plot
of every set on its normalised enrichment score, sized by the genes found and coloured by
significance, and the same scores as bars grouped by contrast, one bar per set, which
shows whether a set moved in both comparisons or one. Collapsed: the GSEA report table. Filters: pole,
significance and set size.

## Routes and pruning

| Route | What changes |
|---|---|
| No `--gtf` | No annotated table: no Genome view tab, chromosome row or Manhattan highlight; on Differential expression no biotype views, gene record or biotype filter. The full DESeq2 table remains, and the Key figures keep four cards. |
| `NO_GSEA` | No Enrichment tab, gene-set row, gene-set line in The run or dot-plot highlight. The Key figures keep four cards. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the group, the
contrast and the GSEA pole are coloured `auto` (each value takes a colour-blind-safe colour at
import, kept on a re-import), and the call direction is written out (up red, down blue, not
significant grey). The contrast-against-contrast scatter reads the same map, so genes called
in neither contrast are grey.

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The sample sheet
and the PCA select on `sample_id`, which narrows the distance matrix, the heatmap and the
distribution panel. The DESeq2 tables, the contrast-against-contrast scatter and the
Manhattan plot select on `gene_id`, and the GSEA table on `term`. The gene record sits
beside the annotated table, in its collapsed section, and waits for a picked row.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of
a narrower one. Nothing is set per tab or per tile.

## Reading notes

- **-log10(padj) is capped at 300.** A padj that underflowed to exactly 0 has no finite
  logarithm, so those rows are drawn at 300, above every finite value. A point at 300 is
  "beyond measurement", not "measured at 300".
- **padj is null for part of the features.** That is DESeq2's independent filtering: those
  features never reached the multiple-testing correction, count as not significant and have
  no volcano or Manhattan height.
- **The annotated table is shorter than the full one.** Features the GTF does not place on
  the genome have no coordinate and are dropped from it.
- **Read the normalised enrichment score.** Normalising for set size is what makes a small
  set comparable with a large one. GSEA writes an FDR of zero for anything below its own
  resolution, so the significance axis is clipped at the smallest q-value the run resolved.

## Reproducing

```bash
bash depictio/projects/nf-core/differentialabundance/2.0.0/download_test_data.sh
# then follow post_fetch_help in megatest.yaml for the sample sheet and contrasts
depictio-cli ingest --template nf-core/differentialabundance/2.0.0 --data-root <DATA_ROOT>
```

Leave `--project-name` off: the dashboard carries `project_tag: Differential Abundance
Analysis`, and `depictio dashboard import` resolves that tag by name, so a renamed project
cannot take a re-imported dashboard later.
