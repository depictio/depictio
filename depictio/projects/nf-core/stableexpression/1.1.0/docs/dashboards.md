# nf-core/stableexpression 1.1.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in two groups, read as a funnel from the
public datasets that reached the merged matrix to the genes that hold steadiest in it. The
template follows the family rules in `depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0 is
the reference implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | Datasets | Which datasets reached the merged matrix, and with how many samples? |
| Data & QC | ID mapping | How many gene ids of each dataset map to an Ensembl gene? |
| Stability | Ranking | Which genes are the most stable at each expression level? |
| Stability | Candidates | What makes a candidate stable, measure by measure? |
| Stability | Sections | How does stability change with expression level? |

stableexpression looks for the most stable genes of a species, the reference genes a qPCR
assay can normalise against. It takes a species, not a samplesheet: it downloads every
Expression Atlas experiment of that species (and, with `--fetch_geo_accessions`, GEO series),
maps each dataset's gene ids to Ensembl genes with g:Profiler, drops the samples with too many
zeros (`--max_zero_ratio`) or missing values (`--max_null_ratio`), normalises each dataset
(TPM or CPM for raw RNA-seq counts, then a quantile normalisation to a uniform distribution,
so every value lies between 0 and 1), merges them into one gene by sample matrix and imputes
the genes a platform never measured. Genes are cut into `--nb_sections` sections of equal
size by mean expression (`Section 01` the most expressed), the `--nb_candidates_per_section`
least variable genes of each section are scored with Normfinder, geNorm and two coefficients
of variation, and the candidates are ranked within their section by a stability score, lower
being steadier.

There is no MultiQC tab. A 1.1.0 run writes a MultiQC report of custom content only (the
gene tables and boxes per section, dataset statistics, ID mapping) and a Plotly Dash app;
the pinned megatest run published neither (both tasks failed). The Dash app is the design
reference for the Ranking tab: it opens on the best gene of each section as horizontal boxes
of normalised expression, beside a table of every gene's statistics.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `samples` | `merged_data/whole_design.csv` (`METADATA_FILE`), the dataset directories, `statistics/ratio_nulls_per_sample.csv` | sample |
| `stableexpression_dataset_summary` | `datasets/*/*/*/*.design.csv`, `statistics/*.csv`, `errors/`, `warnings/` | dataset |
| `stableexpression_dataset_funnel` | the same | dataset and step |
| `stableexpression_id_mapping` | the same (optional, needs `statistics/id_mapping_stats.csv`) | dataset and fate of the ids |
| `stableexpression_gene_statistics` | `reporting/all_genes_summary.csv` | gene |
| `stableexpression_gene_stability` | the same, candidates only | candidate gene |
| `stableexpression_score_components` | the same | candidate gene and score part |
| `stableexpression_stable_gene_distribution` | the same and `merged_data/all_counts.parquet` | gene, the best `TOP_PER_SECTION` of each section |
| `stableexpression_stable_gene_values` | the same and `merged_data/whole_design.csv` | gene and sample, the best `VALUES_PER_SECTION` of each section |

Not read: the per-step matrices under `datasets/` (debugging copies of each dataset at each
step, 3 GB on the megatest; the statistics tables summarise them), the imputed matrix
(`all_counts.imputed.parquet`, see Methods), `id_mapping/` (the global mapping and gene
metadata, whose gene names `all_genes_summary.csv` already carries), `annotation/` and
`accessions/`.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/merged_data/whole_design.csv` | design read by `samples`; an annotated copy (tissue, treatment) adds columns |
| `METADATA_ID_COL` | `sample` | design id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `platform`, `Platform` | group filters, the Samples card and the group colours |
| `TOP_PER_SECTION` | `25` | genes per section in the box statistics (the pipeline's report draws 25) |
| `VALUES_PER_SECTION` | `2` | genes per section kept sample by sample (one row per gene and sample) |
| `NO_ID_MAPPING` | unset | set for a run with `--skip_id_mapping`: drops the ID mapping collection and tab |

## Overview

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: what the dashboard shows and how its filters
  work; the species, datasets merged, samples analysed, genes in the matrix, and the number
  of sections and candidates per section.
- **Pipeline**: five steps (download, map, filter, score, rank), each opening the parameters
  that drive it and the tab that shows its output. The map step cites the gene ids the ID
  mapping collection counts and goes with it.
- **Key figures**: datasets (downloaded, then ID-mapped and merged, as an attrition strip),
  samples analysed (split by the group), genes of the matrix (a ring of the candidates) and
  the best stability score (with the box of every candidate's score). The group and dataset
  filters above them narrow the first two; the gene cards are cohort-wide.
- **Findings**: four rows under the filters: the most stable candidate in view and its score,
  the share of samples that measured the median section leader, the score part that weighs
  most (on the megatest, the missing-value penalty), and the share of datasets that reached
  the merged matrix with the count that mapped no gene. Then the ranking, Normfinder rank against
  geNorm rank, the scores by section and the sample funnel. The bar filters by group and
  expression section.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (group, dataset, sample) sit in the collapsed left panel. They
narrow the dataset tabs (by dataset) and the per-sample values of the Ranking tab (by sample).
They never move a stability score: a score is a statistic of the whole cohort.

## Child tabs

**Datasets.** Strip: datasets through the steps (attrition), samples through the steps
(attrition: downloaded, ID-mapped, after the zero filter, after the missing-value filter),
datasets by outcome, and the median share of the matrix's genes a merged dataset's samples
miss. Then the samples after each step stacked by platform, the datasets of each platform by
outcome, and the share of the genes each dataset misses, one strip per array design (an array
measures a fixed set of probes, RNA-seq almost every gene). Collapsed: the dataset table with its record card (accession linked to
Expression Atlas). Filters: outcome and samples kept.

**ID mapping.** Strip: gene ids in by fate, the median share kept, genes per mapped dataset
and the rare-gene ids by platform. Then one stacked bar per dataset, open, grouped by platform and
sorted by the share kept (sorting by name, total or another fate, regrouping and the axis zoom
are the tile's controls); then the fate of the ids per platform (stacked, as shares) and the
datasets by the share of each fate. Collapsed: the table. Filters:
fate and dataset outcome. Every tile reads the ID mapping collection, so `NO_ID_MAPPING`
removes the tab whole.

**Ranking.** Strip: genes ranked (by expression level), the best score with the spread of the
ranked genes, the median share of samples that measured a ranked gene, and the median spread.
Then the `ranked_distribution` of the best genes of each section: it ranks by the rank within
the section, so the first ten rows are the best gene of each of ten sections and Top N adds
the second best of each; a section filter turns it into that section's top N. The box is the
normalised expression over the samples that measured the gene; the lollipop is the score.
Below, the same leaders as violins from the per-sample values, the only gene tile the sample
filters redraw (pick a platform to see whether a leader holds on it). Collapsed: the table of
box statistics. Filters: section, score and measured share.

**Candidates.** Strip: candidates (by the platforms that measured them), the median score,
the share of samples measured and geNorm M. Then each section's score split into its five parts
(a stacked bar, as shares of the score; Normalise off stacks the summed parts), and Normfinder rank against geNorm M rank within the section (one point per
candidate, coloured by section, the diagonal where both measures agree).
Collapsed: the candidate table with its record card (ranks, the parts of the score, the four
measures, expression; the gene id linked to Ensembl). Filters: section, expression level and
measured share.

**Sections.** Strip: genes (a ring of the candidates), the median coefficient of variation,
the median measured share and the genes by expression level. Then the candidates' scores per
section, every gene's CV per section (candidates beside the rest) and every gene by mean
expression against CV. Collapsed: the gene table. Filters: expression level, candidacy and
platforms.

## Routes and pruning

| Route | What changes |
|---|---|
| `--skip_id_mapping` (`NO_ID_MAPPING`) | No mapping statistics: the ID mapping collection, the ID mapping tab and the gene id count of the map step go. Every dataset counts as mapped in the dataset collections. |
| `--skip_genorm` | geNorm M is null for every candidate and its score part 0: the geNorm card prints "–" and the Normfinder against geNorm rank scatter is empty. No variable; the collections keep their columns. |
| One platform only | The group splits have one segment; nothing is pruned. |

The Key figures read collections every route writes.

## Colours

`category_colors` is declared once, on the Overview: the group column is `auto`; the ten
default sections take a colour-blind-safe sequential ramp (`Section 01` dark to `Section 10`
light, any further section `auto`); the five expression levels, the candidacy, the dataset
outcomes, the fates of the ids, the score parts and the sample status are written out.

## Cross-selection

- The sample sheet selects on `sample`; the samples hub carries a pick to the dataset
  collections by `dataset` and to the per-sample values by `sample`.
- The dataset table selects on `dataset` and opens its record card; a dataset pick reaches
  the funnel and the ID mapping.
- The ranking selects on `gene_id`, which reaches the per-sample values; the candidate table
  selects on `gene_id` and opens its record card; the scatters select on `gene_id`.

## Methods and assumptions

- **Measured values.** The boxes are computed from `merged_data/all_counts.parquet`, the
  merged matrix before imputation, so a box shows what was measured. The pipeline's report
  and app draw the imputed matrix, which fills the samples whose platform never measured the
  gene: on the megatest the median section leader was measured by about half of the samples.
  Point the `counts` source of `stable_gene_distribution` at `all_counts.imputed.parquet` to
  draw the imputed values instead.
- **Box statistics.** Quartiles are linearly interpolated; each whisker ends at the furthest
  value within 1.5 IQR of its quartile; mean, standard deviation, minimum and maximum come
  with them.
- **Score parts.** The score is `missing penalty + sum(weight * normalised measure)`, the
  measures rescaled to 0-1 over the candidates. The weights (`--stability_score_weights`) are
  not in any table, so they are solved for by least squares over the candidates (0.25 each on
  the megatest, the default) and the parts add up to the score.
- **Ranks.** `section_rank` is the pipeline's rank within the section, kept for candidates
  only (the rank the pipeline gives the other genes orders nothing). `overall_rank` ranks
  every candidate by score; `rank_weight` (its inverse) lets a text value name the most stable
  gene in view.
- **Datasets.** The platform and normalisation state are the directory names under
  `datasets/`. A dataset's gene ids are kept, collapsed into another id of the same gene,
  dropped as rare or unmapped; the pipeline's `merged` count includes the rare genes, which
  is why `ids_collapsed` is `merged - not_valid`.
- **Samples.** The design keeps the samples a filter removed; `status` marks them, from the
  per-sample table of the merged matrix.
