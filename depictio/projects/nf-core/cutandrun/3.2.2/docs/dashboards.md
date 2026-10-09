# nf-core/cutandrun 3.2.2: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from the
libraries to the peaks that a target's replicates reproduce. The family rules are in
`depictio/projects/nf-core/RULES.md`; `ampliseq/2.18.0` is the reference implementation.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did reads trim, align and rise above the IgG control? |
| Data & QC | Libraries | How deep and duplicated is each library, and is it enriched? |
| Chromatin signal | Fragments | Did the digestion work, and how nucleosomal are the fragments? |
| Chromatin signal | Peaks | What did each sample call, and how much signal do peaks hold? |
| Agreement | Caller agreement | Do SEACR and MACS2 call the same peaks on each sample? |
| Agreement | Consensus | Which peaks do a target's replicates reproduce? |
| Agreement | Locus | Do the callers and the replicates agree on one region? |

[nf-core/cutandrun](https://nf-co.re/cutandrun) trims and aligns CUT&RUN and CUT&Tag
libraries against the target genome and a spike-in, turns the alignments into fragment
coverage, calls enriched regions with SEACR against the IgG control (and, optionally, with
MACS2 over the same fragments), and merges the calls of each target's replicates into a
consensus set.

The design comes from the samplesheet the pipeline validated, through the `samples` hub:
one row per sample with its `target` (the samplesheet group: a histone mark, a protein or the
IgG control), its replicate and its `role` (target or IgG control). The template has no
metadata file and no `GROUP_COL`: `target` is the grouping every grouped tile reads, and
nothing is parsed from sample names. The IgG controls are samples, not noise: they carry the
MultiQC panels, the spike-in factors and the fingerprint that says whether a target is
enriched at all. Only the peak collections omit them, because no caller ran on a control.

There is no usable AWS megatest for 3.2.2 (every 3.2.x prefix in the bucket is empty), so the
template was validated on two EMBL HPC runs of the release: `test_full`, the megatest design
(two histone marks in two replicates each, plus two IgG controls), and `test_full_small`, the
same design on a 10,000-read subset against one chromosome, with linear duplicate removal and
mitochondrial filtering on. The dashboard is the v2 rebuild of the 3.1 one; only the MultiQC
binding and the MultiQC tab changed with the release.

> **Which MultiQC report this template reads.**
> cutandrun 3.2.2 pins MultiQC 1.19, which writes `multiqc_data.json` and no parquet, and
> Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later). A run that uses a newer
> MultiQC (the Nextflow trigger runs force 1.35) publishes
> `04_reporting/multiqc/multiqc_data/multiqc.parquet` itself, and that is what the MultiQC tab
> binds by default. A run on the pinned 1.19 needs its report re-generated with MultiQC 1.35
> from the run's own raw tool outputs, which writes `multiqc/multiqc_data/multiqc.parquet`;
> ingest that one with `--var MULTIQC_REPROCESSED=true`. The template never binds both. The
> panels name the modules of the pipeline's own report. A re-generated report has no separate
> spike-in Bowtie 2 module, so the spike-in tile is dropped at import and the target tile
> shows both genomes. See Reproducing below and `VALIDATION_REPORT.md`.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters. cutandrun 3.2.2 still writes
  no `params.json`, so the dialog holds the software versions, the run's only provenance.
- **About**: two cards side by side. `About this dashboard` says what the run does and how
  the two filter levels work; `The run` lists facts read from the data (samples, targets,
  IgG controls, peak callers), since there are no parameters to print.
- **Pipeline**: six steps (trim, align, fragments, call, compare, merge). Each step opens
  the versions of its tool and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples
  (split by target, IgG controls included), the median fragment length (with its spread),
  the SEACR peaks (split by target) and the median FRiP (a box plot over the samples). A
  target and a sample filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link to
  its tab: the median mononucleosome to sub-nucleosome ratio, the target holding the most
  SEACR peaks and its share, the median share of a sample's SEACR peaks that MACS2 also
  called, and how many consensus intervals two replicates or more support. Below them, four
  figures in two rows, each linking its tab: the fragment-length distribution beside the mean
  pile-up at the SEACR summits, then the MACS2 against SEACR scatter beside the reproducible
  share per target. The Locus tab has no figure here: it is a browser, not a summary. The bar
  of this section filters by target and sample.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (target, sample, replicate, role) sit in the collapsed left
panel and narrow every tab through the project links. Replicate filters on `replicate_label`,
the categorical twin of `replicate`, because an integer column only takes a slider. The
`Sample sheet` section is pinned to the bottom of every child tab, collapsed, and absent from
the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read
the tab), then a strip of four key numbers, each card with its own colour and a secondary that
reads it (a box plot, a distribution, a ranking or a share), then at most three open
sections; tables, details and alternate views follow, collapsed.

**MultiQC.** MultiQC panels only. Open: general statistics, FastQC sequence counts (raw reads)
and the reads kept after trimming; the Bowtie 2 alignments to the target genome beside those to
the spike-in genome (`bowtie2` and `bowtie2-1` in the pipeline's report); the deepTools
fingerprint plot. Collapsed: samtools percent mapped, base quality, GC content, insert sizes and
reads per contig. On a re-generated report the spike-in tile is dropped at import and the target
tile, now full width, shows both genomes (the spike-in libraries carry a `.spikein` suffix).
Filters: the target alignment rate and the spike-in scale factor, read from the spike-in table
and carried into the report by a reverse link.

The pipeline's report also carries modules no tile binds: FastQC on the trimmed reads
(`fastqc-1`), Picard duplication, its own fragment-length histogram and peak QC (FRiP, peak
counts, reproducibility). The Libraries, Fragments and Peaks tabs read the same outputs from the
files the pipeline publishes, so they work on either report.

**Libraries.** The tables the pipeline publishes beside the report. Strip: read pairs (the
total, with the pairs per library as a distribution), the spike-in scale factor (box plot),
duplicate reads (the share the three most duplicated libraries hold) and the median
Jensen-Shannon distance to a uniform library (box plot). Then the scale factor and the
duplicate share per library, the fingerprint
metrics scatter (`deeptools/fingerprint_scatter`: targets sit apart from the IgG controls,
point size is the share of the genome with no reads), and the PCA beside the clustered
correlation matrix of the genome-wide bin counts. Collapsed: target against spike-in depth,
duplication against depth, and the spike-in table. The scale factors are recomputed from the
two Bowtie 2 logs, since the run publishes no table of them. Filters: the spike-in scale
factor and the coverage concentration.

**Fragments.** The nucleosomal ladder. Strip: the median fragment length (box plot), the
fragments counted (split by target), the fragments by nucleosome class (a ring) and the
mononucleosome to sub-nucleosome ratio per target. Then the fragment-length distribution
(25 to 800 bp, one curve per sample coloured by target, the sub-nucleosomal (sub) and
mononucleosomal (mono) windows shaded) beside its cumulative twin, and each library split into the
four classes (below 120 bp, to 250, to 450, above). Collapsed: the class table. Filters:
nucleosome class and fragment length.

**Peaks.** Strip: SEACR regions (split by sample), their median width (box plot), the median
coverage per base (its distribution) and the lowest FRiP in view (with a box plot over every
library). Then the region
width histogram (log axis) beside the mean pile-up on the summits, the summit-centred pile-up
matrix of each sample's 500 strongest regions (`signal_matrix`, one panel per sample), and the
fragment coverage inside and outside peaks per library. FRiP is built in base pairs of
fragment coverage, de-scaled by the spike-in factor, because SEACR reports no read count.
The pile-up tiles are rebuilt from the fragment BEDs (`*.frags.cut.bed`), since no bigWig or
computeMatrix output is mirrored. Collapsed: the SEACR regions, the MACS2 peaks, the per-sample
SEACR summary and the signal budget. Filters: region width, coverage per base and contig on the
regions, then regions called and median coverage per base on the per-sample summary.

**Caller agreement.** Strip: peaks called (a ring by caller), the median peak width by caller,
the share of one caller's peaks the other reproduces (box plot; a sample one caller left empty
is left out, since it shares nothing by construction) and the calls only one caller made
(split by target). Then the MACS2 against SEACR scatter (one point per sample, sized by the
share of calls they share, selectable) beside the calls the other caller did not make, and the
MACS2 significance along the genome (`-log10(q)`, without point labels). Collapsed: the comparison table. Filters: caller
and share reproduced.

**Consensus.** Strip: consensus intervals (a ring by replicate support), the reproducible ones
(two replicates or more, by target), the median interval width (box plot) and the median
coverage per interval (its distribution). Then the UpSet of the replicates calling each
interval, the reproducible share per target beside the interval width by support. The Replicate
support filter keeps every value until narrowed, so the cards include single-replicate
intervals. Collapsed: the consensus table. Filters: replicate support, interval width and
member peaks.

**Locus.** One region on one genome axis. Strip: SEACR regions (by sample), their coverage per
base, the MACS2 peaks (by sample) and the consensus intervals (by support) of the region in
view; the cards
follow the navigator's region as the tracks do. Then the SEACR navigator (`genome_view`, rect
marks, `assembly: {GENOME}`), opening on the first contig the calls sit on, and three tracks that
follow its region through the `region` links of `template.yaml`: the fragment pile-up
(`coverage_track`, one lane per sample, a switch to the GenomeSpy locus view), the MACS2 calls
and the consensus intervals over the gene lane. A tab of its own because those region filters
narrow every tile of their collections on the tab. Filters: SEACR coverage per base, MACS2
q-value and replicate support.

## Routes and pruning

| Route | What changes |
|---|---|
| `--peakcaller seacr` (no MACS2) | No MACS2 peak table, significance plot, Locus MACS2 track or card. The caller comparison keeps one row per sample with 0 MACS2 peaks, so it reads as complete disagreement rather than missing data (`VALIDATION_REPORT.md`, CR-D3). |
| `--peakcaller macs2` (no SEACR) | The SEACR collections drop out, with the Peaks, Consensus and Locus tiles and the Findings rows that read them. |
| No fragment BEDs published | No pile-up profile, pile-up matrix or Locus pile-up track, nor the pile-up highlight on the Overview. |
| Another genome build | Pass `--var GENOME=<assembly>`; every Locus track reads it (default `hg38`). |
| Re-generated MultiQC report (`--var MULTIQC_REPROCESSED=true`) | `multiqc_data` binds `multiqc/multiqc_data/multiqc.parquet` at the root instead of the pipeline's own report. The spike-in Bowtie 2 tile is dropped (no `bowtie2-1` module) and the target tile takes the row. Nothing on the Overview reads the report. |
| A sample a caller found nothing for | The caller still writes its peak file, at 0 bytes; the ingest skips it with a warning. The caller comparison keeps an `n_peaks = 0` row for the sample. |

The import drops a highlight whose source is gone and re-packs the Overview grid, so a lone
highlight takes the full row. Each Findings row cites one collection and is removed with it.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: `target` is
coloured `auto` (each value takes a colour-blind-safe colour at import, kept on a re-import),
and the vocabularies the recipes write are fixed: `role` (the IgG control grey), `caller`,
the four nucleosome classes, the inside and outside of peaks (outside grey) and the replicate
`support` (`auto`). Code figures read the same map and follow Analysis mode's groups when it
has some: the fragment ladder, the mean pile-up and the caller scatter colour by target.

## Cross-selection

Tables select rows and the caller scatter, the depth and duplication scatters, the
fingerprint and PCA tiles and the genome tracks select points; a pick becomes a dashboard
filter that narrows the other tiles of the same collection and, through the project links,
the collections downstream of it. Row selection is on `sample_id` in the sample sheet, `sample`
in the per-sample tables (spike-in, fragment classes, SEACR summary, signal budget, caller
comparison) and `peak_id` in the peak and consensus tables. The PCA emits a selection, but its
collection has no outgoing link, so it narrows no other tile.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of a
narrower one. Nothing is set per tab or per tile.

## Reproducing

A run that used MultiQC 1.31 or later (as the Nextflow trigger runs do) needs nothing beyond
its `--outdir`:

```bash
python -m depictio.cli ingest --template nf-core/cutandrun/3.2.2 --data-root <outdir> --dry-run
python -m depictio.cli ingest --template nf-core/cutandrun/3.2.2 --data-root <outdir>
```

A run on the release's pinned MultiQC 1.19 needs its report re-generated first. The HPC
validation runs were repatriated and reprocessed this way (`--run cutandrun322-small` for the
small profile):

```bash
# 1. Bring the outputs back (alignments, reads and signal tracks stay on the cluster)
python scripts/nfcore_validation_hpc.py fetch --run cutandrun322-full

# 2. Regenerate the MultiQC report Depictio reads (the run wrote 1.19)
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/cutandrun/3.2.2/test_full \
  --dest ~/Data/depictio-nfcore/cutandrun/3.2.2/test_full

# 3. Dry run, then ingest, pointing the MultiQC collection at the reprocessed report
python -m depictio.cli ingest --template nf-core/cutandrun/3.2.2 \
  --data-root ~/Data/depictio-nfcore/cutandrun/3.2.2/test_full \
  --var MULTIQC_REPROCESSED=true --dry-run
python -m depictio.cli ingest --template nf-core/cutandrun/3.2.2 \
  --data-root ~/Data/depictio-nfcore/cutandrun/3.2.2/test_full \
  --var MULTIQC_REPROCESSED=true
```

Without step 2 and the variable, `multiqc_data` finds no parquet and the whole MultiQC tab is
empty. Keep the first `REPROCESSED.json` or delete `multiqc/multiqc_data/` before re-running,
because the source-version probe reads the parquet it just wrote. There
is no megatest to fetch for 3.2.2: `download_test_data.sh` and `megatest.yaml` list the subset a
future one would need.
