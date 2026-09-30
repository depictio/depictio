# nf-core/demultiplex 1.8.0: Depictio dashboards

This template turns the output of [nf-core/demultiplex](https://nf-co.re/demultiplex) 1.8.0
into a five-tab dashboard for a sequencing facility. demultiplex converts a run folder to
FASTQ with bcl2fastq or BCL Convert, splits the reads between the libraries of the sample
sheet, runs fastp and Falco on every library, holds the result to instrument limits with
CheckQC, and gathers everything in MultiQC. The dashboard reads it in the order a facility
signs a run off: what the checks flagged, whether the instrument delivered, how the reads
were shared, what went to Undetermined, and how each library looks.

The reference data is the AWS megatest run
`results-daade37c4a75a4c1709ccf12434deb3424141319`, demultiplexed with **bcl2fastq** (the
pipeline default).

---

## How the dashboard is built

- **Two demultiplexers, one set of collections.** `demux_stats`, `lane_summary`,
  `read_quality` and `unknown_barcodes` read the bcl2fastq `Stats/Stats.json` by default.
  With `--var IS_BCLCONVERT=true` the template repoints the same four collections at the
  BCL Convert recipes, which read `Reports/Demultiplex_Stats.csv`, `Quality_Metrics.csv`
  and `Top_Unknown_Barcodes.csv` and write the same columns, so every tile renders
  unchanged. BCL Convert reports no raw cluster count: `clusters_raw` and `pct_pf` are
  empty on that route.
- **Lanes and reads are rows, never names.** Every run-level collection is one row per lane
  (and per read), labelled `Lane n` and `Read n`, so a one-lane benchtop run and a four-lane
  production flowcell ingest through the same template and the lane filter lists what the
  run has.
- **The library hub.** `libraries` is one row per library: reads over all its lanes, its
  share of the run, its share of an even split (`pct_of_expected`, 100 is exactly its
  share), base quality and index purity from the demultiplexer, the fastp read QC, and the
  design columns of the optional metadata file. The pinned `Library filters` (library,
  design group, lane) and the library card read it, and the template links fan it out to
  MultiQC and every per-library collection.
- **Design metadata comes from a file, never from library names.** `METADATA_FILE` is a TSV
  whose first column is the library name as written in the sample sheet. Every other column
  becomes a hub column (as text, so a numeric factor such as an input amount groups like a
  label). `GROUP_COL` picks the column the tiles group and colour by; without a metadata file
  the hub carries a single `__no_group__` group and every tile still renders.
- **Worst lane, never an average of percentages.** The glance strip shows the lowest lane
  for base quality and the highest lane for the Undetermined share, with the per-lane
  spread as a box plot underneath.

## Tabs

| Tab | Question | Main tiles |
| --- | --- | --- |
| MultiQC | What did CheckQC and the read QC tools flag? | CheckQC panels, general statistics, Falco and fastp panels; the rest collapsed |
| Run health | Did the instrument deliver, per lane, read and cycle? | lane cards, lanes by Undetermined share and Q30 (scatter), base quality per cycle (profile), lane by read quality (dot plot), SAV metrics when an InterOp summary is present |
| Demultiplexing | How evenly were the reads shared between the libraries? | library cards, libraries per lane (stacked composition, top 12), run to lane to library (sunburst), share of the lane (bar), reads against index purity (scatter) |
| Undetermined and index swaps | What did no index match, and is it a swap? | Undetermined cards, unknown barcodes coloured by class (bar), unknown barcodes and CheckQC findings tables |
| Library QC | How does each library look once demultiplexed? | fastp cards, duplication against Q30 (scatter), design groups compared metric by metric (group compare), library card |

Pinned on every tab: `Run at a glance` (libraries, total yield, lowest-lane Q30, highest-lane
Undetermined share), `Sample sheet` (the library hub, collapsed, top) and `Lane table`
(`lane_summary`, collapsed, bottom).

### Unknown barcode classes

`unknown_barcodes` splits every unassigned index pair into its i7 and i5 and checks each
against the indexes of the libraries on the same lane:

- **Both indexes in use**: both halves belong to libraries of the lane, in a combination the
  sample sheet does not declare. This is the index-hopping or swap signature.
- **Only i7 in use / Only i5 in use**: one half matches; often a library whose other index
  was mistyped in the sample sheet.
- **Neither index in use**: a library that was sequenced but is missing from the sample
  sheet, or a contamination.
- **Poly-G or N index**: the index read failed (dark cycles on two-colour chemistry).

bcl2fastq keeps the top unknown barcodes of each lane; the recipes keep the 100 most frequent
per lane.

### Sequencing Analysis Viewer metrics

Error rate, phasing, prephasing and cluster density live in the InterOp binaries
(`InterOp/*.bin`), which Depictio cannot parse. The `interop` catalog tool instead reads the
text table of `interop_summary --csv=1 <run folder>` (Illumina InterOp). demultiplex 1.8.0
does not run it and its `multiqcsav` report carries no SAV sections, so on a stock run the
`interop_summary` collection is skipped and the SAV section is hidden. Drop the file anywhere
under the run (any name containing `interop_summary`, extension `.csv`) and the section
appears.

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The lane table and
the lane health and phasing scatters select on `lane_label`; the sample sheet, the per-lane
library table, the index purity scatter, the library QC scatter and the fastp table select
on `sample`; the unknown barcode table selects on `barcode`. The library card on the Library
QC tab sits beside the scatter that drives it (`linked_component`) and stays a thin rail
until a library is picked. The per-cycle quality profile and the CheckQC verdict table do not
select: their collections have no outgoing link.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATA_ROOT` | required | The run's output directory |
| `METADATA_FILE` | none | Library metadata TSV, first column the library name |
| `METADATA_ID_COL` | first metadata column | Library-name column of the metadata file |
| `GROUP_COL` | first annotation column, else a single group | Design column the tiles group by |
| `IS_BCLCONVERT` | unset | Set for a `--demultiplexer bclconvert` run |

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
depictio-cli run --template nf-core/demultiplex/1.8.0 \
  --data-root ~/Data/depictio-nfcore/demultiplex/1.8.0/megatest \
  --var METADATA_FILE=depictio/projects/nf-core/demultiplex/1.8.0/input/library_metadata.tsv
```

The vendored `input/library_metadata.tsv` gives the megatest libraries an organism, an input
amount and a replicate number. Pass `--var GROUP_COL=input_ng` to group by input amount
instead of organism.
