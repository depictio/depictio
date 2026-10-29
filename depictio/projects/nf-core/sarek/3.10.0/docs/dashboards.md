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
| Annotation | Genes | Which genes carry the calls, and which do the callers share? |
| Annotation | Protein | Where on the protein do the coding variants sit? |
| Annotation | Locus | What do depth and calls show at one region? |

The design comes from sarek's own CSV manifests (`csv/recalibrated.csv`,
`csv/markduplicates*.csv`, `csv/variantcalled.csv`): the `samples` hub reads patient, sex and
status (shown as `status_label`: Normal, Tumour or Unknown) and counts the callers per sample.
Nothing is parsed from sample names, so the template has no `GROUP_COL`. A callset is one
caller on one sample. "Concordance" is agreement between callers and samples, never a truth
comparison: nf-core/variantbenchmarking has its own template for that.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: the sarek wordmark, what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The second lists the
  samples and patients, the callsets and callers, the genome and the aligner, from the sample hub, the
  bcftools summary and the run parameters. The `tools` parameter is not printed: a
  comma-joined list has no space to wrap at.
- **Pipeline**: six steps (map, cover, call, check, compare, annotate), each opening the
  parameters that drive it and the tab that shows its output.
- **Key figures**: the variant calls summed over the callsets (split by caller), the median
  depth over the intervals (with its spread), the median PASS share of a callset (with its
  spread) and the median Ts/Tv of the callsets with SNPs against a 1.8 floor. All four read
  collections every run writes. A caller and a sample filter above them narrow these four
  only.
- **Findings**: result rows computed under the filters, each linking its tab: the median depth
  over the intervals, the median Ts/Tv, the share of a sample's PASS calls that two callers or
  more made (from the caller overlap collection), and the HIGH-impact calls with the genes
  they hit. Below them, four figures in two rows: the substitution spectrum beside the FILTER
  partitions per caller, then the allele fraction per caller beside the impact classes per
  caller. The bar of this section filters
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
panels, the BQSR fit and insert sizes, and the SnpEff region and VEP panels. The bcftools,
VCFtools and SnpEff impact panels are not repeated: the Variant yield, Call quality and
Consequences tabs draw the same numbers per caller. The pinned sample filters narrow its panels, though the report names a library with a
lane and a read suffix.

**Coverage.** Strip: the depth over the intervals per sample (box plot), the median depth of
an interval against a 20x floor, the depth across contigs (distribution) and the intervals
under 20x (the contigs with most). Then the mean depth per contig, with a bar that picks the
intervals or the whole contig (it opens on the intervals), and the X against Y sex check: one
point per library coloured by the sex its ratio implies, with the XX and XY zones shaded.
Collapsed: the per-contig and sex-check tables. Filter: a mean-depth range, not a contig or
scope picker, which would empty the first card (it reads mosdepth's `total` row of the
intervals).

**Variant yield.** Strip: the median records per callset (the callers that call most: a
structural-variant caller writes orders of magnitude fewer, which a box plot would flatten),
SNPs (split by caller), indels (a ring by caller) and multiallelic sites (distribution). Then
SNPs and indels per caller in one stacked bar (variant-type colours, one panel per sample),
and the substitution and indel spectra, one bar per caller with its callsets' shares
averaged, so the legend lists callers, not callsets. The multiallelic card splits its sum by
caller.
Collapsed: the bcftools distribution blocks (picked in the left panel, opening on depth) and
the per-caller count table. The bcftools QUAL histogram is not ingested: it outweighed every
other block and repeats the quality sweep. Filters: caller and bcftools block.

**Call quality.** Strip: the Ts/Tv against a 1.8 floor, the PASS share (out of 100), the het to
hom ratio (box plot) and the allele fraction of heterozygous calls (distribution); each
description says what a normal value is. Then the callset QC profile (five numbers per callset
on parallel axes; the record count stays on Variant yield and the het allele fraction has its
card), the calls per FILTER value per caller, and, side by side, the Ts/Tv of every callset
as a sorted bar in its caller's colour with the 1.8 floor and 1.5 warning lines, and the Ts/Tv
above a rising quality floor on a log axis (callers write QUAL on scales a thousand-fold
apart), its legend under the plot. Collapsed: the FILTER breakdown and the
Ts/Tv per callset. Filters: caller, FILTER value and a Ts/Tv range.

**Caller concordance.** Strip: the calls (the callers that call most), the calls by variant
type (a ring), the allele fraction (box plot) and the depth at the call (distribution). Then
the UpSet of PASS calls shared between callers (one set per caller, built by
`recipes/caller_overlap.py`: an element is a PASS call in one sample, so the sample filter of
the left panel reads one library, and the tab's own pickers do not narrow it), then the
allele fraction per caller: the share of each caller's calls in 40 bins, one line per caller
in its colour, with the heterozygous band around 0.5 and the homozygous-alternate band near 1
shaded. A heterozygous peak off 0.5 or a shoulder of low fractions flags contamination or
noise calls. The rainfall plot is not on the dashboard: it duplicated the Locus tab's view of
where calls sit. Collapsed: the call table. Filters: caller, variant type, contig and
a depth range.

**Consequences.** Strip: the annotated calls (a ring by impact class), the HIGH-impact calls
(split by variant type), the genes with a HIGH or MODERATE call (the callers that hit most)
and the depth at HIGH-impact calls (distribution). Then SnpEff's own counts for the summary
section picked in the left panel (opening on impact), and the impact recomputed on the calls:
the impact classes per caller as shares (MODIFIER left out) beside the allele fraction per
impact class (a box, summarised before plotting). The impact class and consequence pickers sit
in the bar of that section, because three cards pin an impact class. Collapsed: the SnpEff
summary table, and the annotated call table with the variant record of a picked call beside it. Filters: caller and SnpEff section.

**Genes.** Strip: the genes with a call (the commonest biotypes), the HIGH-impact variants
(split by caller), the coding variants per gene (the median over genes that carry any, with
its spread: the maximum only ever named the longest gene) and the protein changes (a ring by impact class). Then the gene by callset burden
heatmap (log1p colour, so one long gene does not wash out the rest) and the UpSet of genes the
callers share (fixed). Collapsed: the per-gene burden table, whose row selection narrows the
cards. Filters: biotype and caller. A high burden on long, repetitive genes is a mappability
signal before it is a biological one.

**Protein.** Strip: the genes on the protein view (a bar by the worst impact class on each),
the coding calls (split by caller), the median share of a gene's calls that two or more callers
made (out of 100) and the allele fraction (box plot). Then the genes: a full-width scatter of the
lollipop's genes (distinct coding variants on a log axis against the share of calls two or more
callers made, coloured by the worst impact class on each, markers enlarged, the six genes the
callers agree on least named). Then the lollipop, the main figure of
the tab, one lane per gene, full width and narrowed to the gene picked on the scatter. Collapsed:
the coding variants with a protein position, one row per call. Filters: caller and impact class. A
gene low on the scatter carries variants one caller sees, which is often a mapping or repeat
artefact.

The scatter and the first and third cards read a per-gene summary of the lollipop's collection
(`protein_genes`, built by `recipes/protein_genes.py`) over the whole run: the sample and caller
pickers do not narrow them, a gene picked on the scatter does.

The tab draws no 3D structure. That tile needs the server's structure resolver
(`DEPICTIO_STRUCTURE_RESOLVER_ENABLED`, off by default, since the gene symbol leaves the server),
and on a deployment without it the tile would be a message above the figure that matters.

**Locus.** A depth navigator in 1 Mb windows, one lane per sample, drives the genome browser
under it, in one linked section held to one screen; the browser follows its brush and its window
shows as a band on the lanes. The navigator has no default region: a contig-wide region would
filter the whole contig, the browser would follow it and every track would ask to be
force-loaded, so the browser opens on its highest-quality call instead. The region reaches the
cards through the region links. The four
cards (calls by caller, depth per interval, allele fraction, depth at the call) take
`follow_region_filter: true`, so they follow the region and recount it on every brush or locus
entry. Filters: caller and variant type. The browser is the only one of the template: it opens
on every small-variant caller of the first sample, that sample's reads (whose coverage is the
depth at the region, so no per-interval depth track repeats it) and the dbSNP and ClinVar
tracks (`ucsc_tracks`), follows the navigator's brush without filtering, and offers the
circular view of the structural variants (`views: [circular]`). Variant tracks take the
caller's colour of the figures (`color_by: caller`); the depth lanes, one per sample, wear the
sample colour. The tracks wear no colour column of their own.

## Genome tracks

The `tracks` collection lists the files the genome browser reads: every caller's VCF of every
sample (the snpEff-annotated twin when the run has one, so calls take their impact colour) and
the CRAM of every sample, built by `recipes/tracks.py` from sarek's own `csv/` manifests. The
VCFs come first and the CRAMs last, but the first rows are every small-variant caller of the
first sample followed by that sample's CRAM, so the browser opens on a caller comparison with
the reads under it. The reference
sequence of a CRAM comes from the `{GENOME}` preset, so `GENOME` must name the build the run was
aligned to. With `--var TRACKS_URI=<results folder>` the files are read in place; without it the
VCFs and CRAMs that DATA_ROOT holds, with their index, are uploaded. Germline runs only: a somatic
pair is not listed. The sample links carry a sample pick to the tracks and a track click back to
the sample filter. The use cases are in `docs/design/jbrowse/sarek.md`.

## Routes and pruning

| Route | What changes |
|---|---|
| No SnpEff (`--tools` without `snpeff`) | No Consequences, Genes or Protein tab, no shared-calls UpSet (so no caller-agreement row on the Overview), no HIGH-impact row or impact highlight on the Overview. |
| VCFtools skipped | No FILTER partitions, quality sweep or FILTER filter on Call quality; the FILTER highlight is dropped. |
| No X/Y sex check | No sex-check scatter or table on Coverage. |
| No `TRACKS_URI` and no VCF or CRAM under DATA_ROOT | The genome browsers list the files a run publishes and load none. |
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
contig, sex-check, FILTER and distribution tables and the sex-check figure on `sample`; the
bcftools and SnpEff summary tables on `caller`; the call tables on `variant_key`; the per-gene table on `gene_name`. The variant record on
Consequences shows the call picked in the call table beside it. On the Protein tab the gene
scatter selects on `gene`, which narrows the lollipop and the table to that gene, and the
lollipop emits a residue selection on `gene` and `aa_pos`, which the coding-variant table
follows.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of a
narrower one. Nothing is set per tab or per tile.

## Reproducing

```bash
bash depictio/projects/nf-core/sarek/3.10.0/download_test_data.sh <DATA_ROOT>
depictio-cli ingest --template nf-core/sarek/3.10.0 --data-root <DATA_ROOT>
```
