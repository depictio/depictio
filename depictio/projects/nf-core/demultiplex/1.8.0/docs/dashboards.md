# nf-core/demultiplex 1.8.0: Depictio dashboards

One dashboard for [nf-core/demultiplex](https://nf-co.re/demultiplex) 1.8.0, built for a
sequencing facility: an **Overview**, then child tabs in two groups, read in the order a
facility signs a run off: what the checks flagged, whether the instrument delivered, how the
reads were shared between the libraries, what went to Undetermined, and how each library reads.
The layout follows the family rules in `depictio/projects/nf-core/RULES.md`; `ampliseq/2.18.0`
is the reference implementation.

demultiplex converts a run folder to FASTQ with bcl2fastq or BCL Convert, splits the reads
between the libraries of the sample sheet, runs fastp and Falco on every library, holds the
result to instrument limits with CheckQC, and gathers everything in MultiQC. The reference data
is the AWS megatest run `results-daade37c4a75a4c1709ccf12434deb3424141319`, demultiplexed with
**bcl2fastq** (the pipeline default).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | What did CheckQC and the read QC tools flag? |
| Data & QC | Run health | Did the instrument deliver on every lane, read and cycle? |
| Demultiplexing | Library balance | How evenly were each lane's reads shared between the libraries? |
| Demultiplexing | Undetermined reads | What did no index match, and is it an index swap? |
| Demultiplexing | Library QC | Which libraries stand out on read QC within their group? |

## Variables

| Variable | Default | What it does |
| --- | --- | --- |
| `DATA_ROOT` | required | The run's output directory (the flowcell folders, `multiqc/`, `pipeline_info/`). |
| `METADATA_FILE` | none | Library metadata TSV, first column the library name as written in the sample sheet. Every other column becomes a design column of the library hub. |
| `METADATA_ID_COL` | first metadata column | Library-name column of the metadata file. |
| `GROUP_COL` | first annotation column, else a single group | The design column the dashboards colour and filter by. |
| `GROUP_COL_DISPLAY` | title-cased `GROUP_COL` | Label used in titles and captions. |
| `IS_BCLCONVERT` | unset | Set for a `--demultiplexer bclconvert` run. |

The design comes from a file, never from library names. `libraries` is the hub: one row per
library, with its reads over all its lanes, its share of the run, its share of an even split
(`pct_of_expected`, where 100 is exactly its share), base quality and index purity from the
demultiplexer, the fastp read QC, and the design columns of the metadata file (as text, so a
numeric factor such as an input amount groups like a label). It is the source of every library
link in `template.yaml`. Without a metadata file the hub carries a single `__no_group__` group,
"All libraries", and every tile still renders.

## How the collections are built

- **Two demultiplexers, one set of collections.** `demux_stats`, `lane_summary`,
  `read_quality` and `unknown_barcodes` read the bcl2fastq `Stats/Stats.json` by default. With
  `--var IS_BCLCONVERT=true` the template repoints the same four collections at the BCL Convert
  recipes, which read `Reports/Demultiplex_Stats.csv`, `Quality_Metrics.csv` and
  `Top_Unknown_Barcodes.csv` and write the same columns, so every tile renders unchanged. BCL
  Convert reports no raw cluster count: `clusters_raw` and `pct_pf` are empty on that route.
- **Lanes and reads are rows, never names.** Every run-level collection is one row per lane
  (and per read), labelled `Lane n` and `Read n`, so a one-lane benchtop run and a four-lane
  production flowcell ingest through the same template and the lane filters list what the run
  has.
- **Worst lane, never an average of percentages.** The cards read the lowest lane for base
  quality and pass-filter rate and the highest lane for the Undetermined share, with the spread
  over lanes or libraries underneath.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (the
  demultiplexer from `params.json`, the libraries, the lanes and the yield).
- **Pipeline**: five steps (convert, split, leftovers, read QC, check). Each step opens the
  parameter or tool version behind it and the tab that shows its result.
- **Key figures**: four headline cards, each opening the tab that explains it. Libraries (split
  by group), the share of bases at Q30 on the weakest lane, the smallest library against an
  even share of the run (with the spread over every library), and the Undetermined share of the
  lane that lost the most. A group and a library filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link to its
  tab: the lowest median quality at any cycle, the coefficient of variation of the reads per
  library on the least even lane, the largest class of the unknown barcodes with its share of
  their reads, and the median share of reads fastp kept. Below them, four figures in two rows,
  one per tab behind the funnel: the base quality per cycle beside reads against index purity,
  then the library QC scatter beside the most frequent unknown barcodes. The bar of this
  section filters by group and library.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (group, then library, both on the hub) sit in the collapsed left
panel and narrow every library tab through the project links. Run health reads lanes, which no
library link reaches, so the section is kept off that tab (`exclude_tabs`). The `Sample sheet`
section (the hub table) is pinned to the bottom of every child tab, collapsed, and absent from
the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read
the tab), then a strip of key numbers, each card with its own colour and a secondary that reads
it (a box plot, a gauge, a ranking, a share or a funnel), then at most three open sections;
tables and conditional detail follow, collapsed. Each tab has its own filters in the left panel.

**MultiQC.** MultiQC panels only. Open: the two CheckQC panels (libraries under the read
threshold, the Undetermined share against its limit) and the general statistics, then Falco
read counts, per-read quality and adapter content with the fastp insert sizes. Collapsed: the
Falco status checks and the remaining Falco and fastp panels. The bcl2fastq panels, fastp
Filtered Reads and fastp Sequence Quality are not placed: the other tabs read the same numbers
from the reports themselves. Filters: a library or FASTQ file as MultiQC names it, and the
reads of a library as a share of an even split.

**Run health.** The demultiplexer's lane and read statistics and the per-cycle quality of the
fastp reports. Strip: clusters passing filter (then those assigned to a library), the lowest
pass-filter rate on a gauge, the share of bases at Q30 in the weakest read (with the spread over
lanes and reads) and the yield ranked by lane. Then every lane by Undetermined share and Q30
(sized by yield; a lane low and to the right lost reads to both) beside the lane by read quality
dot plot, and the base quality at every cycle, one curve per lane and read with its 10th to 90th
percentile band. A lane or read that drops alone points at the flowcell or the chemistry, not
at the libraries. Collapsed: the Sequencing Analysis Viewer metrics (below) and the lane table.
Filters: lane, read and cycle.

**Library balance.** How the reads of each lane were shared. Strip: reads assigned to libraries
(the three largest named), the median share of the lane per library (with its spread), the
smallest library against the mean library of the least even lane (a gauge, 100 is the mean) and
the worst perfect index match. Then the composition of each lane (the eight largest libraries
named, the rest pooled, Undetermined kept) beside the run to lane to library sunburst, then
every library's share of its lane and reads against index purity. A library with few reads and
a high perfect-match share was under-pooled; one with few reads and a low perfect-match share
lost reads to index errors. Collapsed: reads per library and lane, Undetermined rows included.
Filters: lane, share of the lane and perfect index match.

**Undetermined reads.** What no index matched. Strip: the Undetermined share of the worst lane
(a gauge), the Undetermined reads ranked by lane, the reads in the top unknown barcodes split by
class, and the three barcodes that carry most of a lane's Undetermined reads. Then the fifteen
most frequent unknown barcodes over the lanes in view, coloured by class. Collapsed: the unknown
barcode table and the CheckQC findings (one row per finding and a pass row for each silent
check). Filters: lane, barcode class and rank in its lane.

**Library QC.** fastp on every demultiplexed library. Strip: the reads fastp was given (then
those it kept), the median duplication ranked by group, the three most adapter-rich libraries and
the median share of bases at Q30 after filtering (with its spread). Then duplication against base
quality (one point per library, sized by reads and coloured by group) beside the library card,
which shows the library lassoed in the scatter or picked in the fastp table, and every numeric
library metric compared between two groups or two saved selections. With a few libraries per
group the test is a screen, not a verdict. Collapsed: the fastp table. Filters: duplication and
GC content.

### Unknown barcode classes

`unknown_barcodes` splits every unassigned index pair into its i7 and i5 and checks each against
the indexes of the libraries on the same lane:

- **Both indexes in use**: both halves belong to libraries of the lane, in a combination the
  sample sheet does not declare. This is the index-hopping or swap signature.
- **Only i7 in use / Only i5 in use**: one half matches; often a library whose other index was
  mistyped in the sample sheet.
- **Neither index in use**: a library that was sequenced but is missing from the sample sheet,
  or a contamination.
- **Poly-G or N index**: the index read failed (dark cycles on two-colour chemistry).

bcl2fastq keeps the top unknown barcodes of each lane; the recipes keep the 100 most frequent per
lane.

### Sequencing Analysis Viewer metrics

Error rate, phasing, prephasing and cluster density live in the InterOp binaries
(`InterOp/*.bin`), which Depictio cannot parse. The `interop` catalog tool instead reads the text
table of `interop_summary --csv=1 <run folder>` (Illumina InterOp). demultiplex 1.8.0 does not
run it and its `multiqcsav` report carries no SAV sections, so on a stock run the
`interop_summary` collection is skipped and the collapsed section on Run health is empty. Drop
the file anywhere under the run (any name containing `interop_summary`, extension `.csv`) and
the section fills: the worst PhiX error rate, the lowest share of clusters passing filter, the
densest lane and the worst phasing per lane, then the error rate per lane and read and phasing
against prephasing.

## Routes and pruning

| Route | What changes |
|---|---|
| No `METADATA_FILE` | The hub carries one group, "All libraries": the group filters list it alone, the group breakdowns show one bar and the captions read "Group". The design comparison on Library QC has nothing to compare until two selections are saved. |
| `IS_BCLCONVERT` | The four run-level collections read the BCL Convert reports. BCL Convert reports no raw cluster count, so the pass-filter card is empty. |
| No unknown barcodes in the report | `unknown_barcodes` is skipped: its cards, figure, table and filters go, with the barcode row of the Findings and its highlight. The lane cards of the tab remain. |
| No fastp reports (`skip_tools fastp`) | `fastp_library_qc` and `cycle_quality` are skipped: the per-cycle profile, the fastp cards and table, the cycle filter, the cycle and fastp rows of the Findings and the cycle highlight go. |
| No CheckQC report | `checkqc_verdicts` is skipped with the findings table. |
| No `interop_summary` table | The SAV section on Run health stays empty (above). |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the group column
and the lanes are coloured `auto` (each value takes a colour-blind-safe colour at import, kept on
a re-import; a flowcell has at most eight lanes), the eight largest libraries by reads take the
palette with Undetermined and the pooled rest in grey, and two known vocabularies are written
out: the unknown barcode classes (both in use red, one in use orange or yellow, neither violet,
poly-G grey) and the CheckQC severities (error red, warning amber, pass green). Code figures read
the same map.

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its collection
and follows the project links to the collections they reach. The lane table and the lane health
and phasing scatters select on `lane_label`; the sample sheet, the per-lane library table, the
index purity scatter, the library QC scatter and the fastp table select on `sample`; the unknown
barcode table selects on `barcode`. The library card on Library QC sits beside the scatter that
drives it (`linked_component`) and stays a thin rail until a library is picked. The per-cycle
quality profile and the CheckQC findings table do not select: their collections have no outgoing
link. The SAV collection has no incoming link either, so the lane filters do not narrow it.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of a
narrower one. Nothing is set per tab or per tile.

## Collections

| Collection | Source | Recipe |
| --- | --- | --- |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` | MultiQC 1.35 |
| `demux_stats`, `lane_summary`, `read_quality`, `unknown_barcodes` | `Stats/Stats.json` or `Reports/*.csv` | `bcl2fastq/*.py` or `bclconvert/*.py` |
| `interop_summary` (optional) | `*interop_summary*.csv` | `interop/summary.py` |
| `fastp_library_qc`, `cycle_quality` (optional) | `*.fastp.json` | pipeline-local |
| `checkqc_verdicts` (optional) | `checkqc_report.json` | pipeline-local |
| `metadata` (optional) | `METADATA_FILE` | none |
| `libraries` | `demux_stats` + `fastp_library_qc` + `metadata` | pipeline-local |

## Reproducing

```bash
bash depictio/projects/nf-core/demultiplex/1.8.0/download_test_data.sh
depictio-cli ingest --template nf-core/demultiplex/1.8.0 \
  --data-root ~/Data/depictio-nfcore/demultiplex/1.8.0/megatest \
  --var METADATA_FILE=depictio/projects/nf-core/demultiplex/1.8.0/input/library_metadata.tsv
```

The vendored `input/library_metadata.tsv` gives the megatest libraries an organism, an input
amount and a replicate number. Pass `--var GROUP_COL=input_ng` to group by input amount instead
of organism.
