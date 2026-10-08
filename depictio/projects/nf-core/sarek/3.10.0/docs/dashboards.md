# nf-core/sarek 3.10.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from the
reads to the genes the calls hit. [nf-core/sarek](https://nf-co.re/sarek) trims and aligns
reads, marks duplicates, recalibrates base quality, calls variants with any mix of callers and
annotates the calls with SnpEff and VEP. The dashboard follows that chain past the summary
counts: it reads the VCFs themselves, so callers are compared call by call and gene by gene.
The family rules are in `depictio/projects/nf-core/RULES.md`.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did reads, mapping and recalibration work for every sample? |
| Data & QC | Coverage | How deeply were the intervals covered, sample by sample? |
| Variant calls | Variant yield | How much did each caller call, and of what kind? |
| Variant calls | Call quality | Do the callsets look like clean germline calls? |
| Variant calls | Caller concordance | Which calls do the callers share, and where do they differ? |
| Annotation | Consequences | What do the calls do to the transcripts? |
| Annotation | Genes | Which genes carry the calls, and where on the protein? |
| Annotation | Locus | What do depth and calls show at one region? |

The design comes from sarek's own CSV manifests (`csv/recalibrated.csv`,
`csv/markduplicates*.csv`, `csv/variantcalled.csv`): the `samples` hub reads patient, sex and
status (shown as `status_label`: Normal, Tumour or Unknown) and counts the callers per sample.
Nothing is parsed from sample names, so the template has no `GROUP_COL`. A callset is one
caller on one sample. "Concordance" is agreement between callers and samples, never a truth
comparison: nf-core/variantbenchmarking has its own template for that.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters. No sarek wordmark ships with
  the viewer, so the hero has no logo.
- **About this dashboard** and **The run**: two cards side by side. The second lists the
  samples, the callsets and callers, the genome and the tools, from the sample hub, the
  bcftools summary and the run parameters.
- **Pipeline**: six steps (map, cover, call, check, compare, annotate), each opening the
  parameters that drive it and the tab that shows its output.
- **Key figures**: the callsets (split by caller), the median depth over the intervals (with
  its spread), the median records per callset (with its spread) and the median Ts/Tv of the
  callsets with SNPs against a 1.8 floor. All four read collections every run writes. A caller
  and a sample filter above them narrow these four only.
- **Findings**: result rows computed under the filters, each linking its tab: the median depth
  over the intervals, the median Ts/Tv, the caller that keeps most PASS calls and its share,
  and the HIGH-impact calls with the genes they hit. Below them, four figures in two rows: the
  substitution spectrum beside the FILTER partitions per caller, then the allele fraction
  against depth density beside the impact classes per caller. The bar of this section filters
  by caller and sample.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (status, patient, sample) sit in the collapsed left panel and
narrow every tab through the sample links. The `Sample sheet` section is pinned to the bottom
of every child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read
the tab), then a strip of four key numbers, each card with its own colour and a secondary that
reads it, then at most three open sections; tables follow, collapsed. Structural-variant
callers call few SNPs, so every Ts/Tv card and filter keeps `ts_tv > 0`.

**MultiQC.** MultiQC panels only. Open: general statistics, fastp filtered reads, Samtools
percent mapped, MarkDuplicates and the mosdepth cumulative coverage. Collapsed: the FastQC
panels, the BQSR fit and insert sizes, the bcftools and VCFtools panels, and the SnpEff and
VEP panels. Its own sample filter reads the MultiQC report, where a library carries a lane and
a read suffix.

**Coverage.** Strip: the depth over the intervals per sample (box plot), the median depth of
an interval against a 20x floor, the depth across contigs (distribution) and the intervals
under 20x (the contigs with most). Then the mean depth per contig, with a bar that picks the
intervals or the whole contig (it opens on the intervals), and the X against Y sex check.
Collapsed: the per-contig and sex-check tables. Filter: a mean-depth range, not a contig or
scope picker, which would empty the first card (it reads mosdepth's `total` row of the
intervals).

**Variant yield.** Strip: the records per callset (box plot), SNPs (split by caller), indels
(the callers that call most) and multiallelic sites (distribution). Then SNPs and indels per
caller, one bar per sample, and the substitution and indel spectra as shares of each callset.
Collapsed: the bcftools distribution blocks (picked in the left panel, opening on depth) and
the per-caller count table. The bcftools QUAL histogram is not ingested: it outweighed every
other block and repeats the quality sweep. Filters: caller and bcftools block.

**Call quality.** Strip: the Ts/Tv against a 1.8 floor, the PASS share (out of 100), the het to
hom ratio (box plot) and the allele fraction of heterozygous calls (distribution). Then the
callset QC profile (eight numbers per callset on parallel axes), the calls per FILTER value
per caller, and the Ts/Tv above a rising quality floor. Collapsed: the FILTER breakdown and the
Ts/Tv per callset. Filters: caller, FILTER value and a Ts/Tv range.

**Caller concordance.** Strip: the calls (the callers that call most), the calls by variant
type (a ring), the allele fraction (box plot) and the depth at the call (distribution). Then
the UpSet of PASS calls shared between callsets (fixed: the pickers do not narrow it), the
allele fraction against depth as a density beside its histogram per caller, and the rainfall
of the calls along the genome. Collapsed: the call table. Filters: caller, variant type,
contig and a depth range.

**Consequences.** Strip: the annotated calls (a ring by impact class), the HIGH-impact calls
(split by variant type), the genes with a HIGH or MODERATE call (the callers that hit most)
and the depth at HIGH-impact calls (distribution). Then SnpEff's own counts for the summary
section picked in the left panel (opening on impact), and the impact recomputed on the calls:
the impact classes per caller as shares (MODIFIER left out), and the allele fraction against
depth scatter with the variant record beside it. The impact class and consequence pickers sit
in the bar of that section, because three cards pin an impact class. Collapsed: the SnpEff
summary and annotated call tables. Filters: caller and SnpEff section.

**Genes.** Strip: the genes with a call (the callers that hit most), the HIGH-impact variants
(split by caller), the coding variants per gene (distribution) and the protein changes (a ring
by impact class). Then the gene by callset burden heatmap, the UpSet of genes the callers
share (fixed), and the coding variants along the protein. Collapsed: the per-gene burden and
protein position tables. Filters: biotype, caller and impact class.

**Locus.** A depth navigator in 1 Mb windows drives three tracks on one axis through the
region links: the depth per interval, the calls over the gene lane and the annotated VCFs read
from their files. It opens on a default region in the second megabase of chromosome 1, small
enough for the file track to fetch. The four cards (calls by caller, depth per interval,
allele fraction, depth at the call) follow the region and recount it on every brush or locus
entry. Filters: caller and variant type.

## Routes and pruning

| Route | What changes |
|---|---|
| No SnpEff (`--tools` without `snpeff`) | No Consequences or Genes tab, no shared-calls UpSet or annotated VCF track, no HIGH-impact row or impact highlight on the Overview. |
| VCFtools skipped | No FILTER partitions, quality sweep or FILTER filter on Call quality; the FILTER highlight is dropped. |
| No X/Y sex check | No sex-check scatter or table on Coverage. |
| Somatic outputs | Loaded when present (ASCAT, CNVkit, MSIsensor-pro, NGSCheckMate), with no tiles yet. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: callers take
`auto` (a colour-blind-safe colour each at import), the impact classes, variant types,
mutation and indel classes, inferred sex, mosdepth scope and status are written out, and the
FILTER values take `auto:n_variants` (the commonest eight of the run take the palette) with
PASS pinned green. The impact figure reads the same map.

## Cross-selection

Tables and point views select on their entity column, and a pick narrows the tiles of the same
collection and, through the project links, the collections downstream of it. The sample sheet
selects on `sample_id`, which the links carry to every collection and the MultiQC panels; the
contig, sex-check, FILTER and distribution tables and the sex-check scatter on `sample`; the
bcftools and SnpEff summary tables on `caller`; the rainfall plot, the impact scatter and the
call tables on `variant_key`; the per-gene table on `gene_name`, which reaches the protein
lollipop. The variant record on Consequences shows the call picked in the scatter beside it.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of a
narrower one. Nothing is set per tab or per tile.

## Reproducing

```bash
bash depictio/projects/nf-core/sarek/3.10.0/download_test_data.sh <DATA_ROOT>
depictio-cli ingest --template nf-core/sarek/3.10.0 --data-root <DATA_ROOT>
```
