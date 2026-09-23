# nf-core/sarek 3.10.0: Depictio dashboards

This template turns the output of [nf-core/sarek](https://nf-co.re/sarek) 3.10.0 into a
six-tab Depictio dashboard. sarek trims and aligns reads, marks duplicates, recalibrates base
quality with GATK4 BQSR, and calls germline variants with five callers side by side
(DeepVariant, FreeBayes, HaplotypeCaller, Manta, Strelka), annotating each with SnpEff and VEP.
The dashboard follows that chain, and keeps going past the summary counts: it reads the VCFs
themselves, so the caller comparison happens at the level of individual variants and individual
genes, not only at the level of "how many did each one call".

Data comes from the AWS megatest run `results-8ccac7ad37b05dd792447763bf9671b719824587` (the
3.10.0 release tag), `test_full_germline_ncbench_agilent/` profile: one exome (Agilent, WES),
sequenced at two depths (75M and 200M reads), run through the germline-only route.

## The one thing to know before reading any concordance panel

**The two samples are the same individual at two sequencing depths.** `NA12878_75M` and
`NA12878_200M` are one NA12878 exome library, downsampled to 75M reads and 200M reads. So
nothing here is a cohort, and "concordance" never means "do two people agree". It means two
different things, and the dashboard is careful to say which:

- **Between callers, at one depth**: real algorithmic disagreement. DeepVariant, FreeBayes,
  HaplotypeCaller and Strelka are calling the same DNA from the same reads.
- **Between depths, for one caller**: pure sensitivity. Every call found at 75M and missed at
  200M (or the reverse) is a depth effect, not a biological difference.

The persistent `Read depth` filter (`read_depth_millions`, shown as `75M reads` /
`200M reads`) is what separates the two readings: hold one depth and the callers vary; hold one
caller and the depths vary.

## The germline-only caveat

No tumor/normal pair was run, so ASCAT, ControlFREEC, CNVkit, MSIsensor-pro and NGSCheckMate
never produced output. The template declares four of those as `optional: true` data collections
(`ascat_segments`, `cnvkit_segments`, `msisensorpro_summary`, `ngscheckmate_matches`) with their
real output globs, so a somatic `test_full` run lights them up without a template change; on
this run the CLI skips them and reports the skip. They carry no dashboard tiles, because a tile
bound to an absent collection would break the tab it sits on.

**Manta reads near-zero on every SNP/indel panel, on purpose.** Manta is a structural-variant
caller running alongside four small-variant callers: its bcftools stats report `ts=0 tv=0` and
almost no SNPs or indels. Every panel that shows it says so, rather than treating it as missing
data.

---

## How the dashboard is built

- **Six tabs.** MultiQC first, then five tabs computed from the pipeline's own output files:
  Cohort QC, Variant yield, Caller concordance, Consequences, Genes. The reading order is a
  funnel: is the coverage good enough, how much did each caller call, which of those calls do
  the callers share, what do the shared calls do to the protein, and which genes carry them.
- **Every tab opens with a glance strip and an intro.** Four cards sit in the section header,
  so the headline numbers are readable before any panel loads, and a short text tile says what
  the tab answers and how to read it.
- **Box-plot cards.** The distribution cards (quality, depth, allele fraction, per-gene burden)
  use the `box_plot` secondary layout, so a card shows the spread and the outliers, not only a
  median that hides them.
- **The sample hub is the anchor.** `samples` is one row per sample, and a persistent
  `Sample filters` section (sample, read depth) is pinned to the top of every tab, with
  `QC thresholds` (the Ts/Tv floor) pinned to the bottom.
- **Every tab also carries its own filters.** Caller, contig, SnpEff section, impact class,
  consequence term, FILTER value, gene biotype: each tab exposes the axes its own panels are
  cut along, so no tab is a dead end that has to be left to filter something.
- **Catalog provenance.** 77 of the 80 tiles carry a `use:` pointing at a catalog render, so the
  panel inherits its kind, roles and description from the tool's catalog entry rather than
  restating them here.

---

## MultiQC

The main tab, reading the run's native MultiQC 1.35 report (no reprocessing needed).

`Run at a glance`, pinned to the top of every tab, carries the run in four numbers (SNPs called,
indels per callset as a box plot, samples by depth, mean Ts/Tv). `Sample sheet`, pinned beside it
and collapsed, holds the sample hub table. A tab-local `Glance scope` control narrows the strip
and the reference table to one variant caller.

`MultiQC general statistics` opens the report with the general statistics table: one row per sample and tool run,
pooling FastQC, fastp, samtools, mosdepth, bcftools, SnpEff and VEP headline numbers.

`Raw and filtered reads` carries FastQC sequence counts, quality histograms and GC content,
then fastp's kept-reads count.

`Mapping, duplication and base-quality recalibration` is sarek-specific: samtools percent
mapped, GATK4 MarkDuplicates' duplication rate, GATK4 BQSR's reported-against-empirical quality
fit, and mosdepth's coverage distribution, cumulative and per-contig.

`What bcftools and VCFtools see across every caller pooled together` holds the variant-QC
modules MultiQC computes itself: substitution types, indel-length distribution, variant depths,
and VCFtools' Ts/Tv by allele count.

`What kind of variants were called` closes the tab with the annotation summaries: SnpEff
effects by impact and by genomic region, VEP's general statistics and its SIFT summary.

---

## Cohort QC

Coverage is the ceiling on everything the other four tabs do, so it comes first. Every panel
here is computed from mosdepth's own output files, not from MultiQC.

`One locus, three tracks` is a locus section: four tiles that share one region and one
x-axis, opening on the TP53 neighbourhood (`chr17:7,400,000-8,000,000`).

- The navigator is a `genome_view` on `mosdepth_windows`: mosdepth's per-target
  `regions.bed.gz` (850k intervals) binned to 1 Mb windows (10,836 rows, the catalog's
  `mosdepth_regions` renamed to `chrom` / `pos`), so it can hold the whole genome. Its
  header carries the locus field (a region or a gene symbol); typing there or brushing its
  axis emits a chromosome and a position filter.
- `Depth per capture target` is a `coverage_track` on `mosdepth_targets`, the same bed kept
  per target. A region link in `template.yaml` carries the navigator's filters to it, so it
  draws only the few hundred targets in view, one lane per sample and mosdepth pass. The `.md` and `.recal` lanes are identical on this run (SK-D9).
- `Calls over the genes` is a `genome_view` on `vcf_variants`, reached the same way, one lane
  per caller, over the bundled hg38 gene lane.
- `The annotated VCFs, read from the files` is a `genome_view` with `source: file` on the
  `snpeff_vcf_files` indexed_file collection: the eight snpEff-annotated SNV/indel VCFs and
  their tabix indexes, uploaded as files and range-read by the browser for the window in view.

All four name their coordinates `chrom` / `pos`. That is not cosmetic: a `genome_view` that
follows a region only recognises the region filters on the column names it binds itself, so
the navigator reads a renamed copy of the windows rather than `mosdepth_regions`.

At the default region, look for TP53 Pro72Arg at `chr17:7,676,154`: DeepVariant, FreeBayes,
HaplotypeCaller and Strelka all make it, and HaplotypeCaller's CNN filter drops it at 200M
reads while passing it at 75M. The glance cards `Depth per capture target` and
`Captured bases per lane` read `mosdepth_targets` over the whole exome: cards do not read a
genome region, so they stay run-wide while the tracks narrow.

`Depth per contig` reads mosdepth's `summary.txt`: mean, min and max depth per contig, and the
difference between a whole contig and the Agilent capture targets inside it. The `mosdepth pass`
filter separates the duplicate-marked pass from the recalibrated one, on the navigator and on
these bars; the per-target track keeps all four lanes, because a second link between the
navigator's collection and the per-target one would collide with the region link (SK-D15).

`X to Y ratio` is a sex check built from the same summaries: chromosome X mean depth against
chromosome Y mean depth, one point per sample and pass. Both libraries read XX on this run.

`What the same alignments looked like before the depth was measured` closes with the MultiQC
panels for duplication, percent mapped and insert size, so the alignment context sits next to
the coverage it produced.

---

## Variant yield

How much each of the five callers called, and what its own filters threw away.

`Caller yield and SNP fraction, per sample` puts all five callers and both depths on one plane
as a dot plot: colour is `log10(records)`, size is the SNP fraction of that caller's records
(0 for Manta), next to grouped bars of SNP and indel counts.

`Mutation spectra` draws the Ts/Tv ratio as the bars it is made of: the `bcftools stats`
substitution block folded onto the six pyrimidine classes (C to T and T to C are the
transitions), and its indel-length block within 20 bp, each normalised to its callset's own
total so callers compare on shape rather than yield. DeepVariant's lower Ts/Tv (1.82 against
2.5 to 2.6) comes from the RefCall records it keeps in its VCF: its PASS SNPs alone read 2.58,
its RefCall records 0.38.

`Callset QC profile` is a `parallel_coordinates` tile over `callset_qc`, one polyline per
sample and caller across record count, SNP fraction, Ts/Tv, multiallelic share, PASS share,
het to hom ratio, median depth and median heterozygous allele fraction. Manta, which calls no
SNV, is left out. Brushing an axis emits a range filter.

`What each caller threw away` is new in this lot: VCFtools' `FILTER.summary` per caller, as a
stacked bar of calls per FILTER partition plus its table. This is where a caller's internal
filtering becomes visible, rather than only its final PASS count.

`Where a caller's quality score stops meaning anything` draws VCFtools' `TsTv.qual`: Ts/Tv
recomputed above a sliding quality floor, as a `profile` panel with the quality floor on x. A
caller's curve flattening near the germline expectation says its quality score has stopped
separating real transitions from noise. The raw sweep is 106,589 rows, decimated to 1,757 points
by rank stride (first and last always kept) so the curve is drawn honestly without shipping
every step.

`The blocks bcftools writes and no panel breaks out per caller` unpacks the parts of
`bcftools stats` that MultiQC pools: the quality, depth, indel-length, substitution,
singleton and allele-frequency blocks, one row per bin per caller. The `bcftools block` filter
is not optional here: the quality block alone is 97% of the 92,362 rows, so the panel is
unreadable until a block is chosen, and its intro says so.

---

## Caller concordance

The first tab that reads the VCFs. `vcf_variants` is 286,631 calls, one row per variant per
caller per sample, parsed straight out of the caller's own `.vcf.gz`.

`PASS calls shared between callsets` is the variant-level UpSet: each callset is one
caller at one depth, and the intersections are exact variant matches on
`chrom:pos:ref:alt`. Reading it needs the framing at the top of this page: a bar where two
callers meet at the same depth is algorithmic agreement, a bar where one caller meets itself
across the two depths is sensitivity.

`Genes hit by a coding variant, shared between callers` asks the same question one level up,
from SnpEff's per-gene tables: callers that disagree on thousands of individual positions often
agree almost completely on which genes are hit.

`Allele fraction against depth, as a density` is the plane a germline callset is read on: a
clean diploid run stacks at 0.5 and 1.0, and everything off those two bands is either low
coverage or a caller artefact. A marker cloud of that many calls is a solid blob, so the tile
draws a binned 2D histogram (`density: true`) over the row sample the viewer fetches (about
10k of the 286k calls), not over every call. The companion histogram shows the same
distribution per caller. The `Depth at the call` slider in the left panel draws the depth
distribution above itself.

`Where the calls fall` draws the calls along the genome twice: a `manhattan` panel in
`mode: rainfall` (log10 of the distance to the previous call on the same contig, coloured by
variant type; on a germline exome the short-distance clusters are gene-dense exons, not
kataegis), and a `genome_view` with one lane per caller (`facet_by_sample: true`), so a region
where one caller fires and the others do not is visible as a gap in a lane.

---

## Consequences

What SnpEff makes of the calls. Two sources sit side by side on purpose: SnpEff's own summary
CSV (`snpeff_csv_stats`, its published counts) and the same composition recomputed from the
annotated VCFs (`snpeff_ann_variants`, 371,068 rows). They should agree, and a tab that shows
both is a tab where a parsing mistake is visible rather than silent.

`SnpEff's own counts` is the published side: the six composition sections SnpEff writes
(impact, functional class, effect, region, variant type, zygosity) as a bar chart, one section
at a time via the `SnpEff section` filter.

`The same composition, recomputed on the calls` is the computed side: allele fraction against
depth coloured by impact class, and the allele-fraction distribution per impact class. A click
on the scatter fills the `Variant record` card beside it (a `record_card` keyed on
`variant_key`), one card per callset that made the call, with the gene linked to Ensembl; the
card opens on TP53 Pro72Arg (`chr17:7676154:G:C`). HIGH
impact is 3,744 of the 371,068 annotations here, so it is a thin band next to MODIFIER's
168,740 and needs the impact filter to be read at all.

`One row per annotated call` closes with the annotated call table: locus, allele, quality,
filter status, genotype, depth, allele fraction, and SnpEff's gene, impact, consequence and
protein change.

---

## Genes

Which genes carry the calls, how the callsets differ on them, and where on the protein the
variants sit.

`Impact grid over the 30 most damaged genes` is an oncoplot: genes down the rows, one column
per callset (caller and sample), cell coloured by the worst impact class in that gene for that
callset. This is the panel that makes a caller-specific gene visible at a glance: a row that is
filled for four callsets and blank for two is either a real caller difference or a depth effect,
and the column labels say which.

`Variant burden, gene against callset` is the same 40-gene neighbourhood as a clustered heatmap
of counts rather than classes, so a gene that every caller hits but one hits ten times more is
visible where the oncoplot would show them as equal.

`Coding variants along the protein` is a lollipop over the top 40 genes by coding burden: amino
acid position on x, one needle per variant, coloured by impact class and labelled with the HGVS
protein change. 13,993 variants carry a resolvable protein position.

`The per-gene burden behind the panels` closes with the per-gene table (163,557 gene and callset
rows), with row selection enabled so a gene picked here drives the lollipop above it.

---

## A discrepancy worth reading before you trust the "one patient" framing

The megatest samplesheet's `patient` column is **not** a shared `NA12878` value across both
rows: it repeats the `sample` column exactly (`NA12878_200M`/`NA12878_200M`,
`NA12878_75M`/`NA12878_75M`). Both sequencing depths are, biologically, the same individual, but
structurally the samplesheet treats them as two distinct patients. `status` is `0` (normal) for
both either way, and the `samples` hub reflects the samplesheet as published rather than the
biological framing. See `VALIDATION_REPORT.md`, SK-D2.

Two FreeBayes VCFs in the megatest bucket are not VCFs at all but 196-byte Fusion symlink
targets, so FreeBayes contributes no rows to `vcf_variants` (its annotated twins are complete
and do reach `snpeff_ann_variants`). See `VALIDATION_REPORT.md`, SK-D7.

---

## Reproducing

```bash
# 1. Fetch the megatest subset
bash depictio/projects/nf-core/sarek/3.10.0/download_test_data.sh \
  ~/Data/depictio-nfcore/sarek/3.10.0/megatest

# 2. Dry run, then ingest
depictio-cli run --template nf-core/sarek/3.10.0 \
  --data-root ~/Data/depictio-nfcore/sarek/3.10.0/megatest --dry-run
depictio-cli run --template nf-core/sarek/3.10.0 \
  --data-root ~/Data/depictio-nfcore/sarek/3.10.0/megatest
```
