# nf-core/riboseq 2.0.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from the
reads to the ORFs being translated. [nf-core/riboseq](https://nf-co.re/riboseq) takes
ribosome profiling (Ribo-seq) and total RNA (RNA-seq) libraries, removes rRNA with SortMeRNA,
aligns with STAR, quantifies with Salmon, checks footprint periodicity with riboWaltz, calls
ORFs with Ribo-TISH and RiboCode and tests translational regulation per contrast with
anota2seq. The family rules live in `depictio/projects/nf-core/RULES.md`.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did the reads survive trimming, rRNA removal and alignment? |
| Data & QC | Ribo-seq QC | Do the footprints come from translating ribosomes? |
| Data & QC | Sample space | Do the libraries separate by assay first, then by design? |
| Translation | Translational efficiency | Which genes carry more ribosomes than their mRNA level predicts? |
| Translation | Translational regulation | Which genes change translation between conditions, and through which mode? |
| ORFs | ORF discovery | Which ORFs are translated, and do Ribo-TISH and RiboCode agree? |

The design comes from an optional design table, declared through `METADATA_FILE`,
`METADATA_ID_COL` and `GROUP_COL` (`GROUP_COL_DISPLAY` is the reader label). The group
filters read `{GROUP_COL}`; the assay (`type`) and the library id come from the sample sheet
and are there on every run. The contrasts are the pipeline's own (`--contrasts`). Route flags
read from `pipeline_info/params.json` prune the data collections a run did not produce: a
tab left without data is dropped, and so are the Overview tiles and rows that pointed at it.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (libraries,
  contrasts, the rRNA removal tool, the aligners and the efficiency method), read from the
  run parameters and the sample sheet.
- **Pipeline**: six steps (clean, P-sites, quantify, efficiency, regulation, ORFs). Each step
  opens the parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Libraries
  (split by assay), the median frame-0 share of CDS P-sites (with its spread), the median
  genes expressed per library (with its spread) and the ORFs either caller reports (split by
  class). No card reads anota2seq, so a run without `--contrasts` keeps four; regulation is a
  Findings row and highlight. A group and a library filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link
  to its tab: the median frame-0 share, the genes with a translational efficiency of 2 or
  more (pooled over the run, so no sample filter changes it), the genes anota2seq calls
  translation and buffering for the contrasts in view, and the ORFs outside the annotated
  CDS that both callers report. Below them, four figures in two rows, each linking its tab:
  the start-codon metagene profile (its legend hidden) beside the efficiency plane, then the
  fold-change plane beside the caller UpSet. The bar of this section filters by group and
  contrast.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (group, library, assay) sit in the collapsed left panel and
narrow every tab that reads per-library data; the gene-level tabs are pooled over the run and
do not follow them. The `Sample sheet` section (the sample sheet and the optional design
table) is pinned to the bottom of every child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read
the tab), then a strip of four key numbers, each card with its own colour and a secondary
that reads it (a box plot, a distribution, a gauge, a threshold, a ranking or a share), then
at most three open sections; tables and details follow, collapsed.

**MultiQC.** MultiQC panels only. Open: FastQC sequence counts and adapter content on the raw
reads, counts and lengths after rRNA removal, the SortMeRNA rRNA share, the STAR summary and
the Ribo-TISH frame and length panels. Collapsed: the Salmon fragment lengths, the raw
quality histograms, lengths after trimming, the status checks after rRNA removal and the
samtools mapping rate. Its filters read the MultiQC report and the read layout, so they work
on a run without a design table.

**Ribo-seq QC.** Strip: P-sites assigned (a distribution over libraries), the median frame-0
share in the CDS (a box plot), the lowest frame margin (a threshold at 20 points, warning
under 10) and the median CDS share of P-sites (a gauge). Then the frame composition per
library (opening on the CDS, a UTR one switch away), the start and stop metagene profiles
side by side, and the phasing plane beside the footprint length profiles. Collapsed: the
region composition, the library table with its record card, and the region table with the
share each region would get from its length alone. Filters: frame-0 and CDS-share ranges.

**Sample space.** Strip: the libraries placed (a ring by the sheet's leading factor), the
median genes detected per library (a distribution), and the median genes expressed and median
TPM per library (box plots). Then the PCA on Salmon TPMs, coloured by the leading factor, any
sheet column one switch away, without centroid marks; a lasso becomes an analysis group. Collapsed: the PCA table
with the library record beside it. Filter: a genes-expressed range.

**Translational efficiency.** Pooled over every library of the run, so it needs no
contrast. Strip: the genes both assays reach (spread by the Ribo-seq libraries that see
them), the median log2 efficiency (a box plot) and the median Ribo-seq and RNA-seq abundance
(distributions). Then the plane of Ribo-seq against RNA-seq abundance, coloured by
efficiency, with the diagonal of equal efficiency; it carries no point labels (the top-ranked
genes are the most abundant, piled at the top of the diagonal), and hover names a gene. Collapsed: the per-gene table with the gene record beside it. Filters:
an efficiency range and the gene.

**Translational regulation.** Pick a contrast first. Strip: the regulated calls (a ring by
mode), the translation calls (a share by direction), the median translation effect (a box
plot) and the smallest translation adjusted p-value (a threshold at anota2seq's 0.15). Then
the fold-change plane (ribosome-bound against total mRNA, coloured by mode, the five
strongest genes labelled), then the translation volcano (unlabelled, since its adjusted p
plateaus and the top genes share one height) beside a volcano of any one of the four
anota2seq analyses; each has a View switch to the QQ plot of its raw p-values. Collapsed: the regulation table with the
gene record beside it, across the four analyses. Filters: contrast, mode, gene and analysis.

**ORF discovery.** Strip: the pooled ORFs (a ring by class), the ORFs Ribo-TISH and the ORFs
RiboCode report (each spread by the libraries reporting an ORF) and the median protein length
(a box plot). All four read the pooled table, so a skipped caller keeps its card and reads 0.
Then the ORF classes per library, one caller at a time (opening on the first caller the run
has), and the UpSet of Ribo-TISH, RiboCode and the annotated CDS. Collapsed: the pooled
table with the ORF record beside it, then each caller's calls per library. Filters: ORF
class, gene and a protein-length range.

## Routes and pruning

| Route | What changes |
|---|---|
| No `METADATA_FILE` | No design table, group filters or group breakdowns; the assay and library filters remain. |
| `--skip_ribowaltz` | No Ribo-seq QC tab, frame-0 card, frame-0 row or start-profile highlight; the Key figures keep three cards. |
| No `--contrasts` | No Translational regulation tab, contrast filter, regulation row or fold-change highlight. The Key figures keep four cards. |
| `--skip_ribotish` or `--skip_ribocode` | That caller's per-library table goes and its card reads 0; the pooled ORF table, the UpSet and the tab stay. |
| Both ORF callers skipped | No ORF discovery tab, ORFs card, ORF row or UpSet highlight; the Key figures keep three cards. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the group column
is coloured `auto` (each value takes a colour-blind-safe colour at import, kept on a
re-import), and the known vocabularies are written out: the assay, the reading frame (frame 0
red, the two background frames grey), the transcript region, the regulatory mode (not
regulated grey), the direction and the six ORF classes. Stacked figures draw at most eight
categories, so they share the palette with the cards and rings.

## Cross-selection

Tables select rows, and the phasing plane, the PCA and the efficiency and fold-change planes
select points; a pick becomes a dashboard filter that narrows the other tiles of the same
collection and, through the project links, the collections downstream of it. Row selection
is on `sample` in the sample sheet and the riboWaltz tables, `sample_id` in the PCA table,
`gene_id` in the regulation and efficiency tables and `orf_id` in the pooled ORF table. Each
record card sits beside the table that drives it, in its collapsed section, and waits for a
picked row or point.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of
a narrower one. Nothing is set per tab or per tile.

## Data collections

| DC | Source | Recipe |
|---|---|---|
| multiqc_data | `multiqc/star/multiqc_report_data/multiqc.parquet` | MultiQC |
| samples | sample sheet | `recipes/samplesheet.py` |
| metadata (optional) | `METADATA_FILE` | none (table scan) |
| gene_counts, sample_pca | Salmon merged gene matrices | `salmon/*` via `use:` |
| ribowaltz_* (6 DCs, optional) | `psites/ribowaltz/ribowaltz_qc/*.tsv` | `ribowaltz/*` |
| anota2seq_results, anota2seq_regulation (optional) | `translational_efficiency/anota2seq/*.anota2seq.results.tsv` | `anota2seq/*` |
| translational_efficiency (optional) | `quantification/inframe_psite/gene_counts.tsv` and the sample sheet | `recipes/translational_efficiency.py` |
| ribotish_orfs, ribocode_orfs (optional) | `orf_predictions/ribotish/*_pred.txt`, `orf_predictions/ribocode/*_collapsed.txt` | `ribotish/orfs.py`, `ribocode/orfs.py` |
| orf_calls, orf_overlap (optional) | the two ORF DCs | `recipes/orf_calls.py`, `recipes/orf_overlap.py` |

## Method notes

- **Regulatory mode** follows anota2seq's default selection: adjusted p below 0.15 and an
  absolute effect of at least log2(1.2), with the APV slope inside [-1, 2] for translation
  and [-2, 1] for buffering. Priority: translation, buffering, mRNA abundance (total and
  ribosome-bound both significant with the same sign), otherwise not regulated.
- **ORF key.** Ribo-TISH and RiboCode are compared on `chrom:strand:stop`, the genomic stop
  codon, so alternative start sites of one ORF collapse onto one row.
- **Translational efficiency** is log2 of Ribo-seq CPM over RNA-seq CPM, computed from the
  in-frame P-site count matrix, genes kept when both assays reach 1 CPM on average.
- **Frame 0 share** is taken on frame 0 explicitly, not the dominant frame, so a mis-set
  P-site offset shows as a low value rather than hiding behind another frame.

## Reproducing

```bash
bash download_test_data.sh            # tables only, about 100 MB
depictio-cli ingest --template nf-core/riboseq/2.0.0 --data-root <dest> \
  --var METADATA_FILE=<dest>/input/metadata.tsv
```
