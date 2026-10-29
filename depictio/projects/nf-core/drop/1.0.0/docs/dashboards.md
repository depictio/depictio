# nf-core/drop 1.0.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in two groups, read as a funnel from the
run to the genes that stand out in a patient's RNA, each tab answering one question. It follows the family
rules in `depictio/projects/nf-core/RULES.md`; nf-core/ampliseq 2.18.0 is the reference.

| Group | Tab | The question it answers |
|---|---|---|
| Triage | Candidates | Which genes stand out in a sample, and in how many analyses? |
| Analyses | Expression | Which genes are expressed far from what the cohort predicts? |
| Analyses | Splicing | Which junctions are used far more or less than in the cohort? |
| Analyses | Mono-allelic | Which variants are read from one allele only? |
| Analyses | Locus | Where on the genome do the called genes sit, and what do the reads show? |

nf-core/drop is the Nextflow port of DROP. It counts RNA reads per sample, then asks of
every gene, junction and heterozygous variant whether the sample departs from the other
samples of its analysis group: OUTRIDER (an autoencoder fit of the gene counts) for aberrant
expression, FRASER (a model of the split-read counts) for aberrant splicing, and an allelic
test on the RNA reads of heterozygous variants for mono-allelic expression (MAE). Each
analysis is optional (`--ae_skip`, `--as_skip`, `--mae_skip`).

DROP renders its own report from R rather than from MultiQC modules, so the template has no
MultiQC tab. The same answers are rebuilt from the result tables.

## Test data and the background of the tests

The AWS megatest bucket publishes no result tables for drop: its `results-dev/` folder holds
only `pipeline_info/`, and no release results folder exists. The template was therefore
validated against the real DROP outputs of the pipeline's own small test run, published in
the nf-core/test-datasets `drop` branch, and against the small alignments and genotypes of
that run. `download_test_data.sh` lays them out the way the pipeline writes them. That run
is degenerate on purpose (a handful of genes, ten samples, no significant call), so it
exercises the recipes and the layout rather than the statistics. Its OUTRIDER and FRASER
tables were written with cut-offs that admit every row, so they hold every tested gene and
junction, which makes them a small model of a full run.

A default run does not. OUTRIDER and FRASER write only the rows that pass the pipeline's
own cut-offs, so the volcanoes would show a hit and nothing behind it. To give them a cloud,
run the pipeline with `--ae_padj_cutoff 1 --ae_z_score_cutoff 0 --as_padj_cutoff 1
--as_delta_psi_cutoff 0`: the tables then hold every tested gene and junction. No export
script is needed, and the R objects (`.Rds`) are not read. A run left at the defaults still
works, with the volcanoes showing the significant rows alone.

A full table is large (every gene of every sample), so the expression and splicing recipes
keep a row when it is called, when its adjusted p-value is at most 0.5, or when it is one of
the `BACKGROUND_ROWS` most significant rows of its sample (300 by default; a negative value
keeps all). The dropped rows are the near-null bulk. The calls are read before the trim and
do not change with it. The kept rows still outline the volcano, but they are not a fair
sample of the tests, so the dashboard draws no QQ view and no p-value histogram for the two
analyses. The mono-allelic table is always complete and keeps its QQ view.

## Called and nominal

A **call** needs an adjusted p-value: OUTRIDER and FRASER test thousands of genes or
junctions per sample and correct for it, then keep what passes `AE_PADJ` (with `AE_MIN_Z`) or
`AS_PADJ` (with `AS_MIN_DPSI`). A run of ten samples, such as the nf-core test set, has so
little power that every adjusted p-value is 1, so nothing is called and the cards that count
calls read 0. That is the honest answer, not an empty table: the raw p-values still rank the
genes, and a few reach 0.01 or less.

The expression and splicing tables therefore carry a `status` column and a second count.
`called (adjusted p)` is a call. `nominal p only` is a row whose raw p-value is at or below
`NOMINAL_P` (0.05 by default) without passing the adjusted cut-off. `not significant` is the
rest. `nominal` is true for the first two. The volcanoes plot the raw p-value, with the
dashed line at p = 0.05, and colour the points by status; the tables are sorted by raw p-value;
the cards add the nominal hits, the samples that carry one and the strongest -log10 p; the
samples-and-genes views count the nominal hits and split them into called and not called.
The Overview findings list the nominal counts beside the calls. A nominal hit is a lead: a
share `NOMINAL_P` of all tests passes by chance, so a count near that share of the genes tested
is what chance alone gives. The tables keep the near-null background out, so the number of
tests per sample is not known and the dashboard states the rate, not an expected count.

A nominal hit is a lead. Out of 20 000 genes tested, 1 000 pass p = 0.05 by chance alone, so
read it as a gene worth a look in the raw reads or in the other analyses, never as a finding.
In the Candidates tab a gene that a second analysis also puts at a nominal p-value (the
`n_nominal` column of the per-sample list) is a better lead than one seen once. The
mono-allelic analysis is left as it was: its adjusted p-values are meaningful on a small run,
and its calls are real.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how the filters work; the second lists the run's facts (samples,
  groups, and the OUTRIDER and FRASER implementations read from the run parameters).
- **Pipeline**: six steps (group, count, expression, splicing, alleles, locate). Each step
  opens the parameters that drive it and the tab that shows its result.
- **Key figures**: four headline cards, each opening the tab that explains it. The cohort size
  (samples in the largest analysis group, with a threshold at 30 and a warning from 20: OUTRIDER
  and FRASER learn what is normal from that cohort and have little power below it; a group is
  the set of samples one analysis fits together), outliers called (by group, most first), the
  heaviest sample (its genes at the raw p-value, with the spread over all samples as a box) and
  calls on a phenotype gene. All four read the per-sample table, which every
  route builds, so none of them disappears when an analysis is skipped. A group and a sample
  filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link to
  its tab: expression outliers and the samples that carry them, genes with a splicing
  outlier, mono-allelic variants, genes called by two or more analyses in a sample and the
  hits at the raw p-value (with the share that passes by chance). Below them, four figures in
  two rows of two even halves: the hits in each sample (genes at the raw p-value for expression
  and splicing, plus the mono-allelic calls), stacked by analysis (the quality read: a sample
  far above the others is usually a quality or batch problem; calls alone are too few on a
  small run to draw), then the expression volcano, the splicing
  volcano and the allelic volcano, each linking its tab. This is where the former Cohort and
  Sample QC tabs went: the cohort's size is the first key figure and the groups are on the run
  card, the quality read is the first figure.
- **How to read this dashboard**: the tabs by group, each as a link.

Two persistent filter sections sit in the collapsed left panel. `Sample filters` (group, then
sample) narrow every tab through the sample hub. `Gene filters` (gene symbol) narrow every
tab that reads gene calls, through the gene links. The `Sample sheet` section is pinned to
the bottom of every child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of four key numbers, each card with its own colour and a
secondary that reads it (a box plot, a distribution, a ring, a composition bar or a
ranking), then at most three open sections; tables and details follow, collapsed.

**Candidates.** The triage view. Strip: genes called (split by how many analyses agree),
samples with a call, genes called by two or more analyses, and phenotype matches. Then the
list first: a ranked table of each sample's genes, the strongest evidence first (medals on the
first three, the analyses that call the gene, the support and the phenotype match as badges, the
summed -log10 p as a bar, 2 being p = 0.01 for one analysis, the statistics in a popover on hover), beside a record card for the
picked gene (the evidence of each analysis, the position, the gene linked to GeneCards and the
locus to the UCSC browser).
Picking a sample in the left panel reads that sample's list. A gene enters the list when an
analysis calls it or when it is among the sample's best-supported genes, so a run with no
call still ranks its strongest evidence, labelled "not called". Then a gene by analysis
grid of the cohort's best-supported genes: the strongest -log10 p-value each analysis gave
the gene in any sample, so a gene lit in one column only is supported by one analysis, and
one lit in many samples is more often technical. Filters: how many analyses call the gene,
and the phenotype match. Genes without a symbol (unannotated junctions, intergenic variants)
have nothing to join on and stay in their own tab.

**Expression.** Strip: calls (split by direction), nominal hits (split by direction),
samples with a nominal hit (by group) and the strongest signal (the highest -log10 p, with
its spread); see "Called and nominal" above. Then the OUTRIDER volcano of fold change
against the raw p-value, coloured by status, with the MA view (no QQ view, see the
background note above), and two ranked views of the hits: the samples with the most hits and
the genes hit in the most samples (a gene hit again and again is more often technical).
Collapsed: the result table, strongest first, with the call record card beside it (evidence,
counts and the phenotype match). Filters: call direction and absolute z-score.

**Splicing.** Strip: outlier genes (split by direction), nominal hits (split by direction),
samples with a nominal hit (by group) and the strongest signal (the highest -log10 p). Then
the FRASER volcano of delta PSI against the raw p-value, coloured by status, with the MA
view, and the samples with the most hits beside what the hit
junctions do (an intron used less or more, an exon extended or shortened). Collapsed: the junction table, strongest first, with its record card. Filters: call
direction, absolute delta PSI and splicing metric. There is no sashimi: the pipeline
publishes no junction counts to draw one from.

**Mono-allelic.** Strip: variants tested (a ring by call), mono-allelic calls (by allele),
rare calls and the read depth (a box plot). Then the volcano of the allelic ratio against
the raw p-value (most variants of a small run share one adjusted p-value, which would draw a
flat line; the markers are enlarged for the few points), full width (the reads of each allele are in the variant record). Collapsed:
the variant table with its record card (counts, test and population frequency). Filters:
call and the alternative allele share. Only samples with a DNA genotype take part, so a
cohort without one leaves the tab empty and it is dropped.

**Locus.** A filter section (how many analyses call the gene, the phenotype match and the
evidence), a strip of four cards that recount on the region in view (genes, samples, called
genes and the strongest evidence), then one linked section: a single GenomeSpy navigator
carrying the genes of every sample's triage list on one genome axis, one lane per sample,
coloured by the sample's group, and the genome browser under it. The navigator sets no
default region (one on the whole first contig would make the browser load it all); a brush on
it or a locus typed in its header moves the browser. The browser shows the alignments (with
splice-junction arcs) and the genotypes of the samples in view, coloured by the same group
key, with common dbSNP sites and ClinVar from UCSC. It opens on the best-supported gene (it
steps through the genes by evidence, labelled by symbol) and on the reads and genotypes of
that gene's sample, then the reads of one sample of each other group; the other samples are
in the track menu. A gene sits where its span, else its junction, else its variant is. It is the
only browser of the template: the three analysis tabs reach it through the volcanoes'
open-in-browser action.

## Routes and pruning

Every analysis collection is optional. An analysis the run skipped prunes its cards,
figures, filters, findings row and highlight; a tab left without data is dropped, and so is
its link under How to read. The per-sample table (`sample_outliers`) is always built, so the
Overview key figures survive any combination of analyses. The triage list and the gene grid
are built from whichever analyses ran, and their tab goes only when none did.

| Route | What changes |
|---|---|
| `--ae_skip` | No Expression tab, expression findings row or volcano highlight; counts read zero in the per-sample burden; the triage list loses its expression column. |
| `--as_skip` | No Splicing tab, splicing findings row or volcano highlight; the triage list loses its splicing column. |
| `--mae_skip`, or no DNA in the sheet | No Mono-allelic tab, MAE findings row or allelic highlight; the triage list loses its allele column. |
| All three skipped | Only the Overview remains, with its samples. |
| Samples counted from exported counts only | No alignments to show; the browser keeps its genotype tracks when the sheet gives VCFs. |
| No BAM or VCF paths in the sheet | The Locus tab keeps the navigator and the cards, the browser has no tracks. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab. The group column
is coloured `auto` (each value takes a colour-blind-safe colour at import, kept on a
re-import). The analysis kind, the call directions (red for more, blue for less, grey for not
significant), the allele call, the count source, the number of analyses that call a gene
and the phenotype match are written out, so every figure draws a value in one colour. The code figures read the same map.

## Cross-selection

Tables select rows; a pick becomes a dashboard filter that narrows the other tiles of the
same collection and, through the project links, the collections downstream of it. Row
selection is on `sample` in the sample sheet and on `call_id` in the triage list and the
three call tables. The three record cards wait for a pick in their
tab's table.

## Data collections

| DC | Source | Recipe |
| --- | --- | --- |
| samples | the sample sheet (`SAMPLESHEET`) | `recipes/samples.py` |
| group_membership | the sample sheet | `recipes/group_membership.py` |
| expression_outliers (optional) | `processed_results/aberrant_expression/**/OUTRIDER_results.tsv`, gene coordinates from `processed_results/mae/gene_name_mapping_*.tsv`; called rows plus the trimmed background | `recipes/expression_outliers.py` |
| splicing_outliers (optional) | `processed_results/aberrant_splicing/results/**/results.tsv`; called rows plus the trimmed background | `recipes/splicing_outliers.py` |
| mae_variants (optional) | `processed_results/mae/**/MAE_results_all_*.tsv.gz` | `recipes/mae_variants.py` |
| sample_outliers | the sample hub and the three call tables | `recipes/sample_outliers.py` |
| outlier_genes (optional) | the three call tables joined per sample and gene, ranked within the sample | `recipes/outlier_genes.py` |
| gene_evidence (optional) | the triage list collapsed to the cohort's best genes, one column per analysis | `recipes/gene_evidence.py` |
| tracks | the sample sheet's BAM and VCF paths, the sample of the strongest gene from `outlier_genes` (optional) to order the rows; no colour column, the tile colours by `drop_group` | `recipes/tracks.py` |

## Variables

| Variable | Default | Role |
| --- | --- | --- |
| `SAMPLESHEET` | `input/samplesheet.tsv` | the sample sheet given to `--input`; the pipeline does not publish it |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `drop_group`, `DROP group` | grouping column of the filters, cards and colours |
| `GENOME` | `hg38` | UCSC assembly the browser and the locus links open on |
| `TRACKS_URI` | none | `s3://` or `https://` folder that relative track paths of the sheet are read under, in place |
| `AE_PADJ`, `AE_MIN_Z` | `0.05`, `0` | cut-offs of an OUTRIDER call |
| `NOMINAL_P` | `0.05` | raw p-value at or below which a gene or junction is a nominal hit (a lead, not a call; see "Called and nominal") |
| `BACKGROUND_ROWS` | `300` | rows per sample the expression and splicing tables keep besides the called ones and those with an adjusted p-value of 0.5 or less (a negative value keeps every row) |
| `CANDIDATES_PER_SAMPLE` | `25` | best-supported genes per sample kept in the triage list besides the called ones |
| `AS_PADJ`, `AS_MIN_DPSI` | `0.1`, `0.3` | cut-offs of a FRASER call (gene-level adjusted p-value, absolute delta PSI) |
| `MAE_PADJ`, `MAE_MIN_RATIO` | `0.05`, `0.8` | cut-offs of a mono-allelic call |

## Method notes

- **Groups.** A sample can belong to several DROP groups. The sample hub keeps the most
  specific one (the group the fewest samples share) as `drop_group`; `group_membership`
  keeps all of them. Each analysis fits within its own group, so a group of fewer than about
  thirty samples gives weak calls.
- **Gene coordinates.** OUTRIDER results carry no position. The only gene coordinates the
  pipeline publishes are in the MAE gene name mapping, so expression calls get a position
  from it (matched on the gene id). Without that file the calls stay in the tables and the
  volcano but leave the Locus tab.
- **FRASER layout.** `results.tsv` is read as one row per sample and gene at its most
  significant junction. The per-junction file the pipeline can also publish is not read.
- **No sex check.** The 1.0.0 sheet has no sex column, so the cohort tab cannot compare a
  declared with an inferred sex.
- **Tracks.** Alignments and genotypes come from the paths of the sample sheet, not from the
  pipeline outputs: relative paths are looked up under the data root, by name when needed.
- **Empty result files.** A run that calls no outlier writes header-only tables. The shared
  glob resolver raises when every file it matches is empty, so such a run needs its
  analysis skipped or the file removed before ingestion.

## Running it

```bash
bash download_test_data.sh            # real DROP outputs of the test run, about 55 MB
depictio-cli ingest --template nf-core/drop/1.0.0 --data-root <dest>
```
