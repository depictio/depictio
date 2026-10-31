# nf-core/sarek 3.10.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in four groups, read as a funnel from the
reads to the genes the calls hit, with a Somatic group for the runs that have tumours. A run that stopped after mapping keeps the Overview, MultiQC,
Coverage and Locus tabs; every tab behind a caller or SnpEff appears only when the run made its
inputs (see "Which `--tools` light up which tab"). [nf-core/sarek](https://nf-co.re/sarek) trims and aligns
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
| Variant calls | Structural variants | Which structural variants did the SV callers find, and how big? |
| Somatic | Somatic calls | What did the somatic callers find, and how clean are the calls? |
| Somatic | Copy number & MSI | Which regions gained or lost copies, and is the tumour unstable? |
| Somatic | Germline vs somatic | Are the somatic calls really absent from the normal? |
| Annotation | Consequences | What do the calls do to the transcripts? |
| Annotation | Genes | Which genes carry the calls, and which do the callers share? |
| Annotation | Protein | Where on the protein do the coding variants sit? |
| Annotation | Locus | What do depth and calls show at one region? |

The design comes from sarek's own CSV manifests (`csv/recalibrated.csv`,
`csv/markduplicates*.csv`, `csv/variantcalled.csv`): the `samples` hub reads patient, sex and
status (shown as `status_label`: Normal, Tumour or Unknown) and counts the callers per sample.
It also derives each patient's `design`: **Paired** (a tumour and a normal), **Tumour-only** or
**Germline only**. Nothing is parsed from sample names, so the template has no `GROUP_COL`. A
callset is one caller on one sample. "Concordance" is agreement between callers and samples, never a truth
comparison: nf-core/variantbenchmarking has its own template for that.

## Samples, pairs and units of calls

Sarek calls variants per *unit*, and the unit is written only in the file name:

| Unit | Named | Called by | Read by |
|---|---|---|---|
| A normal sample (status 0), or a sample the sheet does not describe | `<sample>` | the germline callers | the Variant calls and Annotation tabs (`vcf_variants`, `sv_calls`, `snpeff_ann_variants`, the bcftools, VCFtools and SnpEff reports) |
| A tumour with no matched normal (status 1) | `<sample>` | whatever caller was run on it | the Somatic tabs (`somatic_calls`) |
| A tumour/normal pair | `<tumour>_vs_<normal>` | Mutect2, Strelka (somatic), CNVkit, MSIsensor-pro, ASCAT, Control-FREEC | the Somatic tabs |

The split is made from the `samples` hub (`recipes/samples.py`, `depictio/recipes/lib/sarek_units.py`),
the only place the status lives. The three kinds are never mixed on one scale: the germline
collections hold germline units only, so a pair's or a tumour's calls cannot leak into a Ts/Tv, a
PASS share or a concordance figure, and the Somatic tabs split by `unit_type` (`paired`, `tumour_only`)
because a tumour-only callset keeps the patient's own germline variants. The optional `pairs`
collection lists each tumour against each normal of a patient.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: the sarek wordmark, what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first also says how samples of
  different types mix: every sample is called on its own, a tumour with its matched normal is also
  called as a pair named `<tumour>_vs_<normal>`, the Variant calls and Annotation tabs read the
  normal samples called on their own, and the Somatic group appears when the run has pairs or
  tumours to show (the Status and Design filters split tumour from normal and the paired patients
  from the rest). The second lists the
  samples and patients, the callsets and callers, the genome and the aligner, from the sample hub, the
  bcftools summary and the run parameters. The `tools` parameter is not printed: a
  comma-joined list has no space to wrap at.
- **Pipeline**: six steps (map, cover, call, check, compare, annotate), each opening the
  parameters that drive it and the tab that shows its output. A step past the depth cites a
  count from its tab's collection, so the import drops the line with its data and a
  mapping-only run keeps the first two steps.
- **Key figures** (a mapping-only run keeps the patients and depth cards): the patients on
  the sheet ranked by design, the median depth over the intervals (with its spread), the variant calls
  summed over the callsets (split by caller) and the median Ts/Tv of the callsets with SNPs against a
  1.8 floor. A caller and a sample filter above them narrow these four only. The PASS-share card
  gave its slot to the patients card; the share is on Call quality.
- **Findings**: result rows computed under the filters, each linking its tab: the median depth
  over the intervals, the median Ts/Tv, the share of a sample's PASS calls that two callers or
  more made (from the caller overlap collection), and the HIGH-impact calls with the genes
  they hit. Below them, four figures in two rows: the substitution spectrum beside the FILTER
  partitions per caller, then the allele fraction per caller beside the impact classes per
  caller. The bar of this section filters
  by caller and sample.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (status, design, patient, sample) sit in the collapsed left panel and
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
intervals or the whole contig (it opens on the intervals, where the callers look for calls, and
the section description says so), and the X against Y sex check: one
point per library coloured by the sex its ratio implies, with the XX and XY zones shaded (the
description gives the cut-off: X depth ten times Y depth, a male near 1 and a female far above).
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
the per-caller count table. The block is drawn per caller as a share of that caller's own
records, so the caller with the most calls does not flatten the others. A numeric block (depth,
indel length, allele frequency) is a line per caller over the bins that hold 99% of the records,
on a log axis when a few bins dominate the rest; the substitution and singleton blocks are
grouped bars, largest first. The bcftools QUAL histogram is not ingested: it outweighed every
other block and repeats the quality sweep. Filters: caller and bcftools block (it opens on read depth, the first check of a call; the section description says so).

**Call quality.** Strip: the Ts/Tv against a 1.8 floor, the PASS share (out of 100), the het to
hom ratio (box plot) and the allele fraction of heterozygous calls (distribution); each
description says what a normal value is. Then the callset QC profile (five numbers per callset
on parallel axes; the record count stays on Variant yield and the het allele fraction has its
card), the calls per FILTER value per caller (a stacked composition per caller, one bar each: the
controls switch between shares and counts, sort the callers on a value such as PASS and hide
values), and, side by side, the Ts/Tv of every callset
as a sorted bar in its caller's colour with the 1.8 floor and 1.5 warning lines (the description
gives their source: a genome near 2.0 to 2.1, an exome near 2.8 to 3.0, false calls dilute the
transitions below 1.8, random errors give about 0.5), and the Ts/Tv
above a rising quality floor on a log axis (callers write QUAL on scales a thousand-fold
apart), its legend under the plot. Collapsed: the FILTER breakdown and the
Ts/Tv per callset. Filters: caller, FILTER value and a Ts/Tv range.

**Caller concordance.** Strip: the calls (the callers that call most), the calls by variant
type (a ring), the allele fraction (box plot) and the depth at the call (distribution). Then
the UpSet of PASS calls shared between callers (one set per caller, built by
`recipes/caller_overlap.py`: an element is a PASS call in one sample, so the sample filter of
the left panel reads one library, and the tab's own pickers do not narrow it), then the
allele fraction per caller: the share of each caller's calls in 40 bins, one line per caller
in its colour, with the heterozygous band (0.35 to 0.65) and the homozygous-alternate band
(0.9 to 1) shaded and explained in the description. A heterozygous peak off 0.5 or a shoulder of low fractions flags contamination or
noise calls. The rainfall plot is not on the dashboard: it duplicated the Locus tab's view of
where calls sit. Collapsed: the call table. Filters: caller, variant type, contig and
a depth range.

**Structural variants.** Read from `sv_calls`, one row per record of the SV callers (Manta
and TIDDIT; Manta's `candidate_*` VCFs are left out). A breakend (BND) is two records that name
each other, so every count of events keeps one side of each pair (`primary`); the table lists
both. Strip: the events (a bar splitting them by type), the events per sample (a ring), the
median length per type and the longest event (the bars rank the types). Then one stacked bar
per sample by type, and the length histogram on a log axis, overlaid by type. Collapsed: the
record table (type, locus, end, length, QUAL, FILTER, mate for a breakend), where a click
centres the Locus browser on the record. A breakend has no length, so a length range filter
leaves it out. Filters: type, caller and length. The tab appears only when the run called
structural variants (`--tools manta` or `tiddit`); the types keep one colour on every tile
(`category_colors.svtype`).

**Somatic calls.** Read from `somatic_calls`, one row per call of a pair or of a tumour called
on its own (`recipes/somatic_calls.py`, parsers in `depictio/recipes/lib/vcf_somatic.py`). Only
Mutect2 (the `.filtered` VCF of a pair) and Strelka (`somatic_snvs`, `somatic_indels`) have a paired
parser, and a tumour-only VCF is read with the single-sample one; any other paired caller is left out
rather than guessed at. Each caller writes its evidence under its own FORMAT keys, so the tumour
(and normal) allele fraction and depth are computed per caller. Strip: the calls (a bar by calling
design), the PASS calls (by caller), the median tumour allele fraction (ranked by design: a
tumour-only callset is not pooled with a paired one) and the tumour depth (distribution). Then the
tumour allele fraction in 20 bins, one panel per design and one colour per caller, and the calls per
caller stacked by variant type, one panel per design. Collapsed: the call table, where a click
centres the Locus browser. Filters: design, caller and variant type. No tumour mutation burden is
shown: it needs the size of the sequenced target, which the run does not state per sample.

**Copy number & MSI.** A short text says how to read the tab (what a log2 ratio is, the 0.3 and -0.3
cut-offs, what MSI measures). Strip, two rows of four cards: the fraction of the genome altered,
the megabases gained and lost and the chromosomes altered (from `cnv_summary`, the whole genome per
sample, so the contig filter does not change them), then the highest MSI score, the sites tested,
the strongest gain and the deepest loss. Then one row per sample of called segments along the genome,
chromosomes in karyotype order, gains orange and losses blue with the 0.3 and -0.3 cut-offs drawn and
labelled. Then the `cnv_profile` tile on Plotly (the template has a genome browser, so no GenomeSpy
toggle): the log2 ratio of each bin with the called segments over it, one sample at a time, a
chromosome to zoom on in its controls; CNVkit gives no B-allele frequency, so none is drawn. Then a
samples-by-chromosomes heatmap of the mean log2 ratio, the fraction of the genome altered per sample
(gain and loss stacked), and the MSIsensor-pro score per tumour against a dashed 20% line, the cut-off
most often used, drawn as a convention and not as a call (the right one depends on the assay). A tumour
called without a normal has no MSI score. `cnv_segments` prefers the pair's `.somatic.call.cns`, then a
sample's `.germline.call.cns`, then a plain `.call.cns`; `call_source` says which. Collapsed: the MSI
summary and the segment and bin tables. Filters: contig and design.

**Germline vs somatic.** Pairs only. A somatic caller subtracts the patient's variants with the
normal; a somatic call that is also a PASS germline call of the normal is probably inherited and
slipped through. Strip: the distinct PASS variants of the normals and of the pairs (by class), the
somatic calls (a bar by whether the normal's germline calls hold the same variant), and the allele
fraction in the normal and in the tumour (box plots). Then the distinct PASS variants per patient
(germline of the normal beside somatic of the pair, a variant several callers agree on counted
once) and a scatter of each somatic call by its allele fraction in the normal against the tumour,
with the diagonal and a colour for the overlap. The normal's fraction is the paired caller's own
when it wrote one, else that of the matching germline call (`normal_vaf_source`). Collapsed: the
comparison table. Filters: overlap and caller. The tab exists only when a pair has somatic calls.

**Consequences.** Strip: the annotated calls (a ring by impact class), the HIGH-impact calls
(split by variant type), the genes with a HIGH or MODERATE call (the callers that hit most)
and the depth at HIGH-impact calls (distribution). Then SnpEff's own counts for the summary
section picked in the left panel (opening on impact, the shortest summary of what the annotation
says; the section description gives the reason), and the impact recomputed on the calls:
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
callers agree on least named; its description describes the scatter and says a click picks the gene
the lollipop draws). Then the lollipop, the main figure of
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
under it; the browser follows its brush and its window shows as a band on the lanes. The lanes
are bars at a fixed height, titled with the sample and drawn in the colour that sample has on
every other tile, with the 20x floor of the depth card as a dashed line. They draw the depth held
at three times the sample's median window depth (`depth_capped`, at least 40x), because a few
windows over repeats read many times the rest and flatten a shared axis. The navigator has no default region: a contig-wide region would
filter the whole contig, the browser would follow it and every track would ask to be
force-loaded, so the browser opens on the span of the 20 best calls by quality when they lie within
2 Mb of each other (`span_top`, `max_span`), else on the best call, with 100 kb around it, so the
window holds many calls and genes. `fetch_size_limit_mb: 20` lets its alignments load without the
force-load prompt. The region reaches the
cards through the region links. The four
cards (calls by caller, depth per interval, allele fraction, depth at the call) take
`follow_region_filter: true`, so they follow the region and recount it on every brush or locus
entry. Filters: caller and variant type. The browser is the only one of the template: it opens
on the categories it names (`initial_categories: [Small variants, Alignments, Structural
variants, Somatic variants]`), that is every small-variant caller of the first sample, that sample's reads (whose
coverage is the depth at the region, so no per-interval depth track repeats it), that sample's
structural-variant calls, and the dbSNP and ClinVar tracks (`ucsc_tracks`), follows the navigator's brush without filtering, and offers the
circular view of the structural variants (`views: [circular]`). The tracks carry a `caller`
column and no `color` column, and the browser sets `color_by: caller`, so its legend names the
callers in the colours of the caller figures. The depth lanes colour by `sample_id` instead
(`category_col`), so a sample never wears a caller's colour.

## Genome tracks

The `tracks` collection lists the files the genome browser reads: every caller's VCF of every
sample (the snpEff-annotated twin when the run has one, so calls take their impact colour; a run
without SnpEff, as `variant_calling/` and `pipeline_info/params*.json` show, lists the
unannotated VCF) and
the CRAM of every sample, built by `recipes/tracks.py` from sarek's own `csv/` manifests. The
VCFs come first and the CRAMs last, but the first rows are every small-variant caller of the
first sample followed by that sample's CRAM, then the sample's structural-variant callers
(Manta, TIDDIT). A pair's callers and a tumour called on its own are listed too, in the category
`Somatic variants` (track id `<unit>.<caller>`), with the tumour's CRAM among the alignments; they
sit after the germline VCFs, so a run with a normal still opens on it. The browser opens on a
caller comparison with the reads under it and the structural-variant calls below, picked by
category rather than by a row count (`initial_categories` on the Locus browser): the tracks of the
categories that belong to the sample of the first such row. A run with one more caller, or none,
opens on whatever it holds. Picking a patient in the sample filters loads the tumour and the normal
side by side, the somatic calls under the reads. The reference
sequence of a CRAM comes from the `{GENOME}` preset, so `GENOME` must name the build the run was
aligned to. With `--var TRACKS_URI=<results folder>` the files are read in place; without it the
VCFs and CRAMs that DATA_ROOT holds, with their index, are uploaded. The sample links carry a sample pick to the tracks and a track click back to
the sample filter. The use cases are in `docs/design/jbrowse/sarek.md`.

## Routes and pruning

| Route | What changes |
|---|---|
| No caller (`--tools` empty) | Only the Overview, MultiQC, Coverage and Locus tabs; the Overview keeps the depth card and the findings and pipeline lines that read depth. The Locus browser shows the reads and the depth, with no calls. |
| No SV caller | No Structural variants tab. |
| No SnpEff (`--tools` without `snpeff`) | No Consequences, Genes or Protein tab, no shared-calls UpSet (so no caller-agreement row on the Overview), no HIGH-impact row or impact highlight on the Overview. |
| VCFtools skipped | No FILTER partitions, quality sweep or FILTER filter on Call quality; the FILTER highlight is dropped. |
| No X/Y sex check | No sex-check scatter or table on Coverage. |
| No `TRACKS_URI` and no VCF or CRAM under DATA_ROOT | The genome browsers list the files a run publishes and load none. |
| No tumour on the sheet | No Somatic tab; the germline dashboard is unchanged. |
| A pair or a tumour, but no paired caller found a call (empty VCFs) | No Somatic calls or Germline vs somatic tab; Copy number & MSI stays when CNVkit or MSIsensor-pro wrote files. |
| A tumour called on its own, no pair | Somatic calls (and Copy number if CNVkit ran); no Germline vs somatic tab, no MSI score. |
| ASCAT, Control-FREEC, NGSCheckMate | Loaded when present, with no tiles yet. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Which `--tools` light up which tab

nf-core/sarek runs mapping, duplicate marking and recalibration with no `--tools` at all, and
every other stage is chosen with `--tools`. The tabs follow the same split: the Data & QC group
needs no caller, the Variant calls group needs a caller, the Annotation group needs SnpEff.

| `--tools` | Tabs it lights up | Collections behind them |
|---|---|---|
| none (the default) | MultiQC, Coverage, Locus (depth and reads, no calls); the Overview without its variant figures | `multiqc_data`, `mosdepth_*`, `samples`, `tracks` |
| a variant caller: `haplotypecaller`, `deepvariant`, `freebayes`, `strelka`, `manta`, `tiddit` | Variant yield, Call quality, Caller concordance, and the calls in the Locus browser | `bcftools_stats_*`, `callset_qc`, `vcf_calls_raw`, `vcf_variants`, `tracks`; the `vcftools_*` panels of Call quality when VCFtools was not skipped |
| `manta`, `tiddit` (structural variants) | The Structural variants tab, and the same tabs as extra callsets (Ts/Tv cards keep `ts_tv > 0`). In the Locus browser the structural-variant track opens by default and the circular view draws them | `sv_calls`, `tracks` rows of kind `sv` |
| `snpeff` | Consequences, Genes, Protein, the shared-calls UpSet and the HIGH-impact rows of the Overview, the SnpEff panels of MultiQC | `snpeff_*`, `protein_genes`, `snpeff_vcf_files` |
| `vep` | The VEP panels of the MultiQC tab only; the annotation tabs read SnpEff output, so VEP alone adds no tab | `multiqc_data` |
| `mutect2`, `strelka` on a tumour/normal pair, or on a tumour alone | Somatic calls; Germline vs somatic when the pair also has a germline callset for the normal | `somatic_calls`, `pairs`, `somatic_vs_germline`, `patient_call_counts`, `tracks` rows of kind `somatic` |
| `cnvkit` | Copy number & MSI (the profile and cards) | `cnv_segments` (from `cnvkit_segments_raw`, `cnvkit_bins_raw`), `cnv_summary` (from `cnv_segments`) |
| `msisensorpro` (needs a pair) | Copy number & MSI (the MSI card and table) | `msi` (from `msisensorpro_raw`) |
| `ascat`, `ngscheckmate` | No tab yet; the collections are ingested when present | `ascat_segments`, `ngscheckmate_matches` |

The germline demo data is the AWS megatest `test_full_germline_ncbench_agilent`, run with
`--tools deepvariant,freebayes,haplotypecaller,manta,strelka,snpeff,vep`, so it shows every tab
of the table above except the Somatic ones. The Somatic group is shown on a small local run of
sarek's `-profile test` (one patient, tumour `test2` against normal `test`, `--tools
strelka,mutect2,cnvkit,msisensorpro`; see `megatest.yaml`). Its paired VCFs hold no record, so it
adds the Copy number & MSI tab only; the two other Somatic tabs need somatic calls.

A tab is dropped at import when what it needs is absent for the run: an optional collection
with no data removes its tiles, a section left without a data tile goes with them, and a tab
left without a filter or without a visualisation is not imported. Everything derived from a
VCF is declared optional (`bcftools_stats_*`, `bcftools_*_spectrum`, `vcf_calls_raw`,
`vcf_variants`, `sv_calls`, `callset_qc`, with the `snpeff_*`, `vcftools_*`,
`mosdepth_xy_sex_check`, `pairs`, `somatic_*`, `cnv_segments`, `msi` and the other somatic
collections already so), so a mapping-only run ingests
cleanly: the ingestion summary lists the optional collections it skipped, and the import
keeps the Overview, MultiQC, Coverage and Locus tabs. Required are the collections every run
writes: `samples`, `tracks`, `multiqc_data` and `mosdepth_*`. A Locus source (`locus_from`)
that names a skipped collection resolves to nothing instead of reading a table that is not
there. `megatest.yaml` holds a `mapping_only` subset
(`python scripts/nfcore_megatest.py fetch --pipeline sarek --version 3.10.0 --subset
mapping_only`) with the files such a run holds, and
`depictio/tests/cli/utils/test_sarek_mapping_only.py` asserts the tab set offline.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the callers are
pinned off the palette slots the first samples take, so a caller never shares a colour with a
sample in the same section; any other caller takes a free slot. The impact classes, variant types,
mutation and indel classes, inferred sex, mosdepth scope, status, patient design, unit type, call
class, overlap with the normal and copy-number state are written out, and the
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

## Limits

- Report-level collections (`bcftools_stats_*`, `vcftools_*`, the SnpEff summaries) leave a pair
  out by its file name (`_vs_`). A tumour called on its own is told apart from the hub only where a
  call is parsed, so its reports stay with the callsets: the report-level tabs can include it.
- Only Mutect2 and Strelka have a paired parser; a pair called by another caller is not read.
- A tumour with several normals, or a patient with several tumours, gives one pair per tumour and
  normal; the comparison joins each pair to its own normal.
- The project name (`project_tag`) still reads "Sarek Germline Variant Calling".

## Reproducing

```bash
bash depictio/projects/nf-core/sarek/3.10.0/download_test_data.sh <DATA_ROOT>
depictio-cli ingest --template nf-core/sarek/3.10.0 --data-root <DATA_ROOT>
```
