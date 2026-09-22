# nf-core/methylseq 2.3.0: Depictio dashboards

This template turns the Bismark route of [nf-core/methylseq](https://nf-co.re/methylseq) 2.3.0
into a single eight-tab Depictio dashboard. methylseq trims bisulfite reads, aligns them with
Bismark against a bisulfite-converted genome, removes PCR duplicates, and extracts per-cytosine
methylation calls in three contexts (CpG, CHG, CHH). The dashboard follows that chain and then
keeps going: the reprocessed MultiQC report first, then the run's own numbers read to the
methylome, the per-library alignment and duplication counts, the coverage the calls rest on,
whether the calls themselves are trustworthy, the methylome as a whole, the comparison the
cohort was sequenced for, and what a bundled genome annotation would add on top.

Data comes from the AWS megatest run `results-93bc5811603c287c766a0ff7e03b5b41f4483895` (the
2.3.0 release tag), Bismark route: two human ESC lines from E-MTAB-6511, MShef11 under three
low-oxygen replicates (Q1-Q3) and MShef4 across a bulk sample and three passage/differentiation
conditions (J1-J3).

> **This template reads a REPROCESSED MultiQC report.**
> methylseq 2.3.0 published MultiQC 1.13, which writes `multiqc_data.json` and no parquet.
> Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so the MultiQC tab is bound
> to a report this repository generates by re-running the pinned MultiQC 1.35 over the run's own
> raw tool outputs. Mandatory: without it the MultiQC tab is empty. See the Reproducing section
> below and `VALIDATION_REPORT.md`.

> **Bismark route only.** methylseq also publishes a `bismark_hisat/` and a `bwameth/` route
> for the same samples; this template covers the default `bismark/` route only. A run launched
> with `--aligner bismark_hisat` or `--aligner bwameth` needs a different template. Every
> Bismark recipe here matches `bismark_[a-z0-9]+` rather than the literal `bismark_bt2`, so the
> sample ids parse identically on the hisat2 route once that route has a template.

---

## How the dashboard is built

- **One funnel, eight tabs.** MultiQC, Run QC, Alignment and duplication, Coverage, Bias and
  context, Global methylome, Group comparison, Features and metagenes. Each tab answers the
  question the previous one raises: is the run clean overall, what did it actually yield, how
  much of each library aligned and survived deduplication, how deep and even is the coverage
  behind those calls, can the calls be trusted at all, what does the methylome look like as a
  whole, does the cohort's design move it, and what would an annotation add.
- **The sample hub is the hub.** `samples` is one row per sample with the cell line, the
  treatment and the replicate parsed out of the AWS megatest's SRA/GEO-derived sample name
  (`<SRR>_<GSM>_<cell_line>_<condition>`). A persistent `Sample filters` section (sample, cell
  line, treatment) is pinned to the top of every tab, and the template's fourteen links fan a
  pick there out to the MultiQC panels and every per-library collection at once. In this
  megatest MShef11 is exactly the low-oxygen arm and MShef4 exactly the normoxic one, so cell
  line and oxygen condition are the same split and neither can be attributed separately; the
  sample-sheet intro says so on the dashboard itself.
- **Every tab has its own filters too.** Beside the persistent sample and threshold sections,
  each tab declares a non-persistent section on its own columns: contig and depth on Coverage,
  context, read and read position on Bias and context, contig, CpG-density class and window
  methylation on Global methylome, contig, call, effect size and adjusted p on Group comparison.
- **Pinned sample sheet, tables and thresholds.** The sample hub sits in a collapsed
  `Sample sheet` section pinned to the top of every tab, the alignment and deduplication
  summaries in a collapsed `Reference tables` section pinned to the bottom, next to a collapsed
  `QC thresholds` section holding the mapping-efficiency floor, the duplication-rate ceiling and
  the bisulfite-conversion floor.
- **Catalog provenance.** Every panel outside the MultiQC tab carries a `use:` catalog
  reference: `bismark/*` for the twelve Bismark outputs this template owns, `qualimap/*` for the
  coverage panel shared with nf-core/eager, and `multiqc/<module>` for the tool-module QC
  panels.
- **Everything matches on file name.** No data collection or recipe glob spells out a directory
  prefix, so a run published with a different `--outdir` layout still lands in the same
  collections; only `megatest.yaml` knows the AWS run's own `bismark/` aligner-route prefix.

---

## MultiQC

The main tab, and the one reading the reprocessed report. It holds MultiQC panels only, and it
holds all of them: every module the reprocessed report carries is placed here rather than
declared and left off the grid.

`Run at a glance`, pinned to the top of every tab, carries the run in four numbers (mapping
efficiency, CpG methylation, bisulfite conversion efficiency, samples by cell line). A tab-local
`Glance scope` slider narrows it by CpG methylation level.

`MultiQC general statistics` opens the report with the general statistics table, one row per sample.

`Read quality` carries all ten FastQC panels. A bisulfite library legitimately fails the
per-base sequence content and GC checks, because converting unmethylated cytosines to thymines
is the point, so the quality, length and adapter panels are the ones to read.

`Trimming` carries the two Cutadapt (Trim Galore) panels: reads kept, and the trimmed-length
distribution where an over-aggressive adapter setting shows up.

`Bisulfite alignment` is Bismark's own five plots: alignment rates, which bisulfite strand each
read pair came from, the deduplication share, the per-context cytosine methylation table, and
the six-panel M-bias picker. The queryable version of each is on the tabs beside this one.

`Coverage` reads Qualimap BamQC: the coverage histogram, cumulative genome coverage, insert
size and the GC content of mapped reads. This panel is shared with nf-core/eager.

---

## Run QC

Bismark's own run-level summary, `bismark2summary`'s table, one row per library, with the
ratios the template derives from it.

`Run funnel` opens with the whole pipeline as one attrition card (reads analysed, reads with a
unique best alignment, alignments left after deduplication, CpG calls extracted), then the
bisulfite conversion rate as a gauge. Conversion is read off the CHH calls: mammalian CHH
methylation is biologically near zero, so an apparent CHH call is an unconverted cytosine and
`100 - %CHH` is the conversion efficiency. Below about 98 % the CpG calls inherit the same
false-positive rate. On this megatest every library sits between 98.6 % and 99.2 %.

`Cytosine yield` reads the same table from the cytosine end: CpG methylation level and its
spread, the CpG-call count per library, the CHH percentage as the conversion warning, and the
total cytosines seen.

---

## Alignment and duplication

What the MultiQC bar plots draw relative to each other, read as exact numbers.

`Alignment summary` reads Bismark's own "Final Alignment report": mapping efficiency and its
spread, a mapping-efficiency floor, pairs analysed, pairs with no alignment, and the full table.
Bisulfite alignment searches four converted genomes instead of one, so an efficiency in the
seventies or eighties is the expected ceiling, not a failure.

`Deduplication summary` reads `deduplicate_bismark`'s report the same way. On this megatest one
sample (the MShef4 bulk library) carries a duplication rate over 36 %, against 0.7-0.8 % for
every other sample, the usual signature of a library sequenced well past its complexity.

Both bar figures on this tab are coloured by cell line rather than by the library's own name, so
the bar carries a second variable instead of restating its x axis.

---

## Coverage

Qualimap BamQC read at full resolution rather than as a MultiQC picture.

`Depth summary` gives the per-library depth, duplication, mapping quality and GC of mapped
bases, plus the full BamQC table. Mean depth is over the whole reference including the bases at
zero, so a whole-genome bisulfite run at these read counts is under 1X on average and the
interesting number is the genome fraction, not the mean. GC near 20 % is the bisulfite
conversion showing up in the mapped bases.

`Depth along the reference` maps Qualimap's windows back onto their contigs using the
per-contig lengths in the same run's `genome_results.txt`, and draws one faceted lane per
library, with the same windows on Qualimap's own concatenated coordinate underneath.

`Depth distribution` carries the two curves a shallow whole-genome library is actually judged
on: how many bases sit at each depth, and how much of the reference clears a given threshold.

---

## Bias and context

Whether the calls themselves can be trusted.

`Methylation by context` reads the extractor's "Final Cytosine Methylation Report". CpG sits far
above CHG and CHH for every sample here, which is the expected mammalian pattern; CHG and CHH
near zero is the bisulfite-conversion sanity check, not signal.

`CpG M-bias` is the per-position methylation bias in CpG context, read 1 and read 2 as separate
lines. A curve that has not flattened out by the end of the read is Bismark's own advice to add
an `--ignore` / `--ignore_r2` trim and re-extract. This tile is deliberately CpG-only and is not
narrowed by the context selector, because it is the curve the extraction decision turns on.

`M-bias in every context` is all six tables Bismark writes into the M-bias file, with context
and read as filters on the left rather than as six separate tiles. The CHH panel is the
read-position view of bisulfite conversion: a CHH curve that climbs at the 5' end says the first
bases of the read are not converting, which the run-level conversion percentage averages away.

---

## Global methylome

The methylome itself, out of the per-CpG bedGraph files: 7 gzipped files, 756 MB, 8 to 46
million rows each. Nothing is ever read into memory whole. Each file is streamed through
`depictio/recipes/lib/genomic_bins.py`, which bins it to 10 kb windows with a lazy `group_by`,
and what lands in the collection is a small comparable matrix rather than 300 million rows.

`Per-CpG methylation` is the distribution of methylation across every covered CpG, 2 % buckets,
one curve per library. A healthy mammalian methylome is sharply bimodal: a peak at 0 % for the
unmethylated islands and promoters, a taller one at 100 % for the methylated bulk. A library
that has lost the bimodality, or whose 0 % peak has drifted upward, is reporting incomplete
conversion or a depth too low for a site call, long before any mean does.

`Methylation along the genome` draws the binned windows twice: as a faceted Plotly coverage
track, and as intervals on GenomeSpy's locus scale with the hg38 gene lane underneath, where a
brushed region narrows the rest of the tab. The windows kept are those with at least twenty CpGs
in **every** library, strided evenly across the genome; a uniform stride is the honest decimation
for a genome-wide screen, because keeping the CpG-densest windows instead would quietly turn
every downstream panel into a CpG-island panel.

`Cohort structure` reads the same sample-by-window matrix three ways: the first components of a
PCA over it, the pairwise correlation between libraries, and the 150 windows whose methylation
varies most across the cohort. What you want to see is the design in the first two and nothing
else; a library that lands with the wrong block in all three is a swap, a mislabelled sheet, or a
conversion failure that flattened its methylome.

---

## Group comparison

Every 10 kb window tested between the cohort's two arms with a pooled t-test on the arcsine
square-root transform of its methylation proportion, then Benjamini-Hochberg corrected. The
volcano and the Manhattan read the same table, the first by effect size against significance and
the second along the genome.

The unit is a window, not a CpG and not a called DMR: a significant window is a region worth
looking at, not one a caller has delimited. nf-core/methylseq ships no differential-methylation
caller at any version, so this is the screen the published files support and it is labelled as
one. With three libraries against four it is low-powered by construction, and on this megatest a
single window clears both cut-offs, which is the honest answer rather than a missing panel.
Per-CpG coverage counts would allow a beta-binomial model instead, and this 2.3.0 run does not
publish them.

---

## Features and metagenes

nf-core/methylseq bundles no CpG-island or TSS annotation at any version, so the question a
reader asks next, is this window an island or the bulk genome, has no annotated answer here.

`CpG density classes` gives the annotation-free stand-in. CpG density is the property an island
is defined by, so the tertiles of the CpG count per 10 kb window stratify the same axis:
CpG-poor, Intermediate, CpG-dense. It is a proxy and the tab names it as one. A CpG-dense window
is island-like, not an island.

`What an annotation would add` records what a bundled GRCh38 CpG-island and TSS annotation would
unlock without a new pipeline run: methylation by feature class (island, shore, shelf, open sea),
a TSS metagene over the signed distance to the transcription start site, and the same metagene as
a signal matrix, one row per promoter. All three read the per-CpG bedGraph this tab's windows
already come from, so the work is the asset and the interval join, not the data.

---

## Reproducing

```bash
# 1. Fetch the megatest subset
bash depictio/projects/nf-core/methylseq/2.3.0/download_test_data.sh \
  ~/Data/depictio-nfcore/methylseq/2.3.0/megatest

# 2. Regenerate the MultiQC report Depictio reads (the run wrote 1.13)
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/methylseq/2.3.0/megatest \
  --dest ~/Data/depictio-nfcore/methylseq/2.3.0/megatest

# 3. Dry run, then ingest
python -m depictio.cli run --template nf-core/methylseq/2.3.0 \
  --data-root ~/Data/depictio-nfcore/methylseq/2.3.0/megatest --dry-run
python -m depictio.cli run --template nf-core/methylseq/2.3.0 \
  --data-root ~/Data/depictio-nfcore/methylseq/2.3.0/megatest
```

Step 2 is mandatory, not optional: without it `multiqc_data` finds no parquet and the whole
MultiQC tab is empty. Keep the first `REPROCESSED.json` or delete `multiqc/multiqc_data/` before
re-running, because the source-version probe reads the parquet it just wrote.

The bedGraph recipes stream 756 MB on the way through, so step 3 spends about twenty seconds
longer than a tables-only template. It is not a step to background.
