# nf-core/chipseq 2.1.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from
library quality to the regions the replicates agree on. The template follows the family
rules in `depictio/projects/nf-core/RULES.md` and keeps the groups, tab names, tags and
key-figure logic of `nf-core/chipseq 1.2.0` wherever the 2.x outputs allow. 2.0.0 removed
the DESeq2 differential binding test, so the 1.2.0 Differential binding tab has no 2.x
counterpart; the DESeq2 sample-space QC that remains moved to the Consensus tab.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did sequencing, alignment and filtering work for every library? |
| Data & QC | Signal | How enriched and how complex is each library? |
| Peak calls | Peaks | How many peaks did each library yield, and how strong? |
| Peak calls | Annotation | Where do the peaks fall relative to genes? |
| Peak calls | Locus | What do the libraries call at one genomic region? |
| Comparison | Consensus | Which peaks do the libraries agree on? |

The `design` hub is the 2.1.0 override of `nf-core/chipseq/design_factors.py`: it reads the
validated samplesheet (`pipeline_info/samplesheet.valid.csv`, one row per sequencing
library) and returns the 1.2.0 hub, one row per merged library (`<sample>_REP<n>`, the id
every downstream file uses), the ChIPs and their input controls, with `role`, `antibody`,
`replicate` and `condition`. `condition` is the `GROUP_COL` column of the optional design
table (`METADATA_FILE`) and, without one, the sample name without its replicate suffix; the
hub column is always called `condition`, so the dashboard reads it literally and works with
or without the table. `GENOME` is empty by default: the Locus axis is then laid out from the
contigs of the calls, which suits any reference; pass a UCSC assembly name to use its
built-in axis.

> **Two MultiQC reports, two sets of module ids.** 2.1.0 pins MultiQC 1.23, which writes no
> parquet. A run forced to a parquet-era MultiQC publishes its own report, whose
> `multiqc_config` files some tools under stage ids (`samtools-1`, `mlib_deeptools`); a
> report regenerated with `depictio.dev_scripts.multiqc_reprocess` files each tool under one
> id (`samtools`, `deepTools`). The tiles bind the pipeline's ids; the deepTools fingerprint
> has a twin on the other id in the same slot. Read a `selected_plot` from
> `multiqc.list_plots()` on the parquet, never from the published HTML.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters (2.x writes a `params.json`
  and a software versions YAML; the dialog lists both).
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the libraries and ChIPs, the
  antibodies and conditions, the aligner and read length (`{{param:aligner}}`,
  `{{param:read_length}}`) and the peaks called with their type, read from the run's tables.
  No genome line: a 2.x run on a custom FASTA names no iGenomes key.
- **Pipeline**: five steps (trim, align, call, annotate, merge). Each step opens the
  version of the tool that ran it, or its settings, and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Libraries
  (split by condition), peaks called (the box shows the spread per ChIP), the consensus
  intervals (split by how many libraries call each) and the median FRiP score, its strip
  counting the ChIPs at or above the ENCODE floor of 1%. All four read collections every
  route writes. A condition and a library filter above them narrow these four only.
- **Findings**: result rows computed under the filters, each with a link to its tab: the
  median fold enrichment of the calls, the most common HOMER feature class and its share,
  the consensus intervals called by more than one library, and the furthest a library's
  coverage sits from a uniform one (the deepTools fingerprint distance). Below them, four
  figures in two rows: the peak significance along the genome beside the peaks around the
  nearest start site, then the DESeq2 QC PCA of the consensus counts, coloured by condition,
  beside the fingerprint scatter. The PCA takes the place the 1.2.0 volcano held: with no
  contrast to test, whether the libraries group by condition is the comparison 2.x still
  draws. Peak ids are not drawn as point labels, and the per-library highlights hide their
  legends. The bar of this section filters by condition and antibody.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (condition, antibody, library, replicate, role) sit in the
collapsed left panel and narrow every tab; `QC thresholds` (FRiP, peak count) sit collapsed
under them. The `Sample sheet` and `Reference tables` (the per-ChIP peak QC rows) sections
are pinned to the bottom of every child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of four key numbers, each card with its own colour and a
secondary that reads it, then at most three open sections; tables and details follow,
collapsed.

**MultiQC.** MultiQC panels only. Open: general statistics, FastQC sequence counts beside
samtools percent mapped (the unfiltered merged libraries, `samtools-1`), then the deepTools
fingerprint, FRiP scores and the NSC and RSC strand coefficients. Collapsed `QC details`:
per-base quality, Trim Galore kept reads, Picard duplicates, featureCounts assignments and
the strand shift correlation curve. Its own `Library scope` filter narrows the panels by
sequencing library (`<sample>_REP<n>_T<n>`, the `samplesheet` collection). A regenerated
report has no `samtools-1`, so that tile drops out there and FastQC takes the row.

**Signal.** 2.x runs plotFingerprint without a JSD sample, so it writes no Jensen-Shannon
distance or CHANCE metric against the input; every fingerprint reading is against a uniform
library instead, and the inputs are rows of their own (the Role filter leaves them out).
Strip: coverage concentration (the fingerprint area ratio, box plot), the distance from a
uniform coverage (distribution), the genome left at background (the fingerprint elbow,
distribution) and, in one slot, the duplicate share Picard MarkDuplicates flags (box plot)
or, when the run kept preseq, the distinct fragments preseq expects at a billion reads.
Then the fingerprint scatter (background share against distance from uniform, sized by the
bins with no read, one colour per library), then, one per row so their legends wrap under
the plot, the deepTools metagene profile with the start site marked and the gene body
shaded and, when preseq ran, the complexity curves with their 95% band. Filters: genome at
background, and the duplicate share or the extrapolated depth.

**Peaks.** Strip: peaks in view (the chromosomes with the most), peak width (box plot), fold
enrichment (distribution) and the median -log10 q-value (box plot: MACS3 calls at q 0.05 by
default, so every call passes that line). Then the genome-wide significance panel, without
point labels, the width distribution on a log axis, and the two summit profiles: the other
libraries' summits around each summit (replicates of a sharp factor pile up) beside the
average footprint of a call. Neither profile is a read coverage: the recipe aggregates the
calls themselves. On a broadPeak run the summit is the centre of the region. The MACS3
table is collapsed. Filters: significance, fold enrichment, width and chromosome.

**Annotation.** Strip: annotated peaks (a ring by feature class), genes reached (by feature
class), the distance to the nearest start site (box plot) and the peak score. Then the
feature classes per library as 100% bars and the peaks around the nearest start site, with
the promoter window shaded. The collapsed `Peak annotation` holds the HOMER table with the
peak record card beside it: the card waits for a picked row. Filters: feature class and
distance to the start site.

**Locus.** Three collections on one genome axis. Strip: calls in the region (split by
library), libraries per consensus interval, feature classes and nearest genes; the cards
follow the region like the tracks. Then the navigator (`macs2/peak_genome_view`, one lane
per library, `assembly: {GENOME}`, opening on the first contig the calls carry), a coverage
track of the consensus intervals with one lane per consensus set, and the HOMER annotation
coloured by feature class (it stands in for a gene lane, so the locus field takes
coordinates, not gene symbols). Filters: significance, libraries per interval and feature
class.

**Consensus.** Pick one consensus set first: the libraries of two antibodies never meet.
Strip: consensus intervals (the chromosomes with the most), libraries per interval (box
plot), peaks merged and the support of the strongest intervals (a ring). Then the UpSet of
the libraries calling each interval, and the open `Sample space`: the PCA the pipeline's
DESeq2 QC computed on each antibody's consensus counts, coloured by condition (the 2.1.0
recipe joins it from the hub; the consensus set is one switch away), above the library
distance heatmap (`ward`, `Blues`), both full width. The fold-enrichment heatmap over the
250 strongest intervals of each set sits folded below them. The four tables are collapsed.
Filters: consensus set, libraries per interval and chromosome.

chipseq writes one count matrix, and so one PCA and one distance matrix, per antibody. The
distance matrix is block diagonal, and the PCA resolves the components per matrix (the
shared `nf-core/chipseq/deseq2_qc_pca.py`, which the 2.1.0 override calls) while keeping the
catalog output's columns.

## Routes and pruning

| Route | What changes |
|---|---|
| No `METADATA_FILE` | The `metadata` collection is pruned; `condition` falls back to the sample group. No tile changes. |
| preseq skipped (the 2.x default) | The two preseq collections are empty and pruned with their tiles: the distinct-fragments card, the depth filter and the complexity curves. The Picard duplication card and filter hold their slots. |
| `--skip_preseq false` with `--var PRESEQ_RAN=true` | The two Picard collections are removed, so the preseq card and filter take the slots alone. Without the variable both cards are kept and the strip wraps to a second row. |
| `--skip_deseq2_qc` | Both DESeq2 QC collections are pruned: the Sample space section, its two tables and the Overview PCA highlight; the fingerprint highlight widens to its row. |
| broadPeak (the pipeline default) | `recipes/peaks.py` reads `*_peaks.broadPeak`; the region centre stands in for the summit. No tile changes. |
| Report regenerated by the reprocess tool | The `samtools-1` tile drops out, and the fingerprint tile on `deepTools` replaces the one on `mlib_deeptools`. |

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: `condition` and
`antibody` are coloured `auto` (each value takes a colour-blind-safe colour at import, kept
on a re-import), and the library roles and the HOMER feature classes are written out. Code
figures read the same map and follow Analysis mode's groups when it has some.

## Cross-selection

Tables select rows; the fingerprint scatter, the complexity, metagene and summit curves
and the PCA select libraries; the genome-wide panel and the Locus tracks select peaks. A
pick becomes a dashboard filter that narrows the other tiles of the same collection and,
through the project links, the collections downstream of it. The hub reaches the MultiQC
panels, the peak calls and summary, the HOMER annotation, the signal and duplication tables
and the DESeq2 QC on the library id; the consensus sets have no library column, so the
antibody reaches them, and the PCA, through a prefix (`wildcard`) link on the set name. The
set is named after the longest common prefix of its samples, so that link holds when the
sample names start with the antibody. The MACS3 and HOMER peak tables are linked both ways
on `peak_id`. On the Locus tab, two region links rename the navigator's chromosome and
position filters onto the consensus and HOMER tracks.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top
of a narrower one. Nothing is set per tab or per tile.

## Reproducing

No AWS megatest is pinned for 2.1.0 (`results_sha: null` in `megatest.yaml`); the template
was validated on HPC runs of the release's `test` profile under every aligner. A run of the
megatest design (`test_full`) needs `--var GENOME=<assembly>` for the built-in axis.

```bash
bash depictio/projects/nf-core/chipseq/2.1.0/download_test_data.sh
python -m depictio.dev_scripts.multiqc_reprocess --src <DATA_ROOT> --dest <DATA_ROOT>
depictio-cli ingest --template nf-core/chipseq/2.1.0 --data-root <DATA_ROOT>
```

Add `--var METADATA_FILE=<table>` for a design table, `--var PRESEQ_RAN=true` for a run made
with `--skip_preseq false`, and `--var GENOME=<assembly>` for a run on a UCSC assembly.
The reprocess step is needed only for a run that published MultiQC 1.23: without a parquet
`multiqc_data` finds nothing and the MultiQC tab is empty. Do not re-run it over a directory
that already holds the regenerated parquet. Do not pass `--project-name`: the dashboard's
`project_tag` is resolved by project name, so a renamed project breaks a later
`depictio dashboard import`.
