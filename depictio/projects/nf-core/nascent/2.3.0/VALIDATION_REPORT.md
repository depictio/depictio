# nf-core/nascent 2.3.0 template validation report

Validated offline against the AWS megatest `results-7d4fe61975015f652c271886e661764b05cfd3bf`
(the 2.3.0 release tag, written 2026-02-17, `test_full` profile: one GRO-seq time course of 11
single-end libraries, 0 h, 30 min, 1, 2, 4, 6, 9, 12, 18, 48 and 72 h, aligned with BWA to the
iGenomes assembly). No server, no ingestion, no screenshots: the live check of RULES section 15
is still to do (listed at the end as pending).

## Data

- The run is 90 objects, 37 GB, 31 GB of it BAMs. Published besides: `coverage_graphs/` (22
  strand bigWig of 15 to 29 MB, 423 MB in all; 22 strand bedGraph of 107 to 442 MB, 4.8 GB; 10
  dREG bedGraph, not read), `quantification/gene/GM.featureCounts.txt` (15.6 MB) and
  `pipeline_info/` (params, software versions, trace).
- The run did not finish. The trace shows `PINTS_CALLER` FAILED (2) and ABORTED (189), and with
  it groHMM (5 aborted) and HOMER aborted: `transcript_identification/` and
  `quantification/nascent/` hold directory markers only. `preprocessing/` (fastp, FastQC) and
  `quality_control/` (preseq, RSeQC, BBMap) hold markers only too, and no MultiQC report was
  written. Nothing MultiQC 1.35 can parse was published (featureCounts' `.summary` is not among
  the outputs), so the template declares no MultiQC collection: no MultiQC tab (RULES section 2),
  and no Transcripts tab.
- No samplesheet and no design are published. `input/samplesheet.csv` is the pipeline's
  `assets/samplesheet_full.csv` at the 2.3.0 tag; `input/design.tsv` (sample, stage,
  time_point, time_h) was written for the megatest from the library names. Its `stage` is the
  same rank tertile the recipes call `phase` (Baseline; Early 30 min to 4 h; Mid 6 to 12 h; Late
  18 to 72 h).
- Mirror: `/home/user/Data/depictio-nfcore/nascent/2.3.0/megatest`, 960 MB: the 22 bigWigs,
  the gene counts, pipeline_info, input/, and the strand bedGraphs of two time points (0 h and
  9 h, 547 MB). The other 18 bedGraphs (4.2 GB) were streamed one at a time (fetch, bin with the
  recipe lib, delete) to stay inside the disk budget; the full-run row counts of the two
  bedtools collections below are rebuilt from those per-file outputs with the recipes' own
  functions (`strand_bins.windows_from_binned`, `strand_summary.summarise`), and the two
  recipes themselves were run end to end on the four bedGraphs kept.

## Recipe runs on the megatest

In template order (`execute_recipe`, each `dc_ref` fed from the previous results), with the
vendored design table.

| Collection | Full run (rows x columns) | Mirror with 2 bedGraph pairs |
| --- | --- | --- |
| `metadata` | 11 x 4 | same |
| `subread_gene_counts` | 246,026 x 10 (22,366 genes with a read x 11 libraries) | same |
| `subread_library_summary` | 11 x 6 | same |
| `subread_correlation` | 11 x 12 | same |
| `bedgraph_strand_index` | 22 (one row per strand bedGraph) | 4 |
| `bedtools_strand_bins` | 129,437 x 10 (11,767 windows on 24 chromosomes x 11) | 23,502 x 10 |
| `bedtools_strand_summary` | 11 x 10 | 2 x 10 |
| `samples` | 11 x 16 | 11 x 16 (signal columns of 9 libraries empty) |
| `gene_dynamics` | 14,552 x 19 | same |
| `gene_trajectories` | 160,072 x 10 | same |
| `response_profiles` | 77 x 11 (7 classes x 11 time points) | same |
| `top_gene_trajectories` | 110 x 9 | same |
| `top_gene_heatmap` | 40 x 13 | same |
| `sample_similarity` | 11 x 15 | same |
| `sample_drift` | 21 x 6 | same |
| `signal_window_dynamics` | 5,825 x 17 | 5,817 x 17 |
| `signal_trends` | 33 x 10 | 6 x 10 |
| `signal_window_heatmap` | 40 x 13 | 40 x 4 |
| `chromosome_signal` | 264 x 9 | 48 x 9 |
| `coverage_bigwigs` | 22 files (`indexed_file`, bigwig, 15 to 29 MB, under `max_file_size_mb: 64`) | same |

Timings: the gene collections take under 2 s each; one strand bedGraph bins in 0.3 to 0.5 s
(`bedtools_strand_bins` over the four kept files 8.6 s, `bedtools_strand_summary`, which
streams each file twice, 16 s). Without the design table (`metadata` pruned) the chain gives the
same row counts, the hub carries `__no_group__` (the phase) in place of `stage`, and the time
points come off the library ids.

What the run says, as a sanity check of the recipes rather than a claim of the dashboard:

- 14,552 genes are expressed (10 reads in half of the libraries): 1,354 induced (275 early, 312
  mid, 767 late) and 2,062 repressed (713, 384, 965), 11,136 stable. The top of the list is an
  interferon response (IFIT1, IFIT2, RSAD2, CMPK2 induced from 4 to 12 h), which is what a
  stimulated lymphoblastoid time course should show.
- PC1 holds 30% of the variance and orders the libraries by time (0 h and 30 min at -22, 48 h and
  72 h at +23); the correlation with the baseline falls from 0.94 to 0.91 at 48 h.
- The strand coverage is dominated by the ribosomal DNA windows on chr21 (8 to 19% of a library's
  chromosome signal, 75,000 per million in one 250 kb window): the hotspot share is 17 to 28% per
  library, and the plus-strand share 56 to 65%, because those arrays are transcribed from the plus
  strand. Over the 5,825 comparable windows (the hotspots excluded), 85 rise and 71 fall.

## Checks run

| Check | Result |
| --- | --- |
| `python -m depictio.cli dashboard validate dashboards/base.yaml --offline` | pass |
| `pytest test_template_conventions.py test_shipped_dashboard_yamls.py test_template_dc_order.py -k nascent` | 22 passed; no warn-level note (every median of a percentage carries a `filter_expr`) |
| The same three files plus `test_advanced_viz_config_alignment.py` and `test_catalog.py`, whole | 1,829 passed |
| `depictio dev catalog validate` (what `catalog-ci.yaml` runs) | OK, 122 tools, with `subread` and `bedtools` |
| `depictio/tests/recipes/test_nascent_recipes.py` (catalog recipes and libs) and `test_nascent_project_recipes.py` (hub and time course) | 19 + 7 passed |
| `depictio run --template nf-core/nascent/2.3.0 --dry-run` on the mirror with `METADATA_FILE` | 20 collections will ingest, 0 empty, 0 missing sources; GROUP_COL resolves to `stage` |
| Every card and text value computed with the API's own functions (`hero_value`, `compute_breakdown`, `compute_box_plot_stats`, `numeric_layout_payload`) on the full-run collections | every hero and every secondary has a value; no secondary with a single value |
| Import-time pruning simulated route by route with the importer's gates (`_prune_unresolved_text_values`, `_component_has_data`, orphaned sections) | see "Routes" |
| `ruff format`, `ruff check` on every new Python file | clean |

Row budget (open sections, stored `h`): Overview 23 of 24 (hero 1, about 3, steps 3, key figures
2, findings 2 + 5 + 5, how to read 2); Library QC 12, Gene dynamics 15, Sample similarity 15,
Genome signal 20, Signal dynamics 15 of 20. Every KPI strip is 4 cards w2 h2, each with its own
icon, its own `icon_color` and a caption on its secondary; section descriptions are at most 90
characters and subtitles at most 12 words.

Card values on the full run: Libraries 11 (Early 4, Late 3, Mid 3 of the top 3 groups), reads in
genes 48.5 M (median 4.1 M per library), responsive genes 3,416 (2,062 repressed, 1,354 induced),
plus-strand share 61.6%; on the tabs, genes detected 14,476 (median), hotspot share 24.3%, peak
change 1.48 (genes) and 1.35 (windows), first component 30.5%, correlation with the baseline 0.936,
largest step 0.936, window signal 11.1 per million (median), silent windows 25.

## Routes (RULES section 13)

| Route | Result |
| --- | --- |
| Full run with a design table (the megatest with `input/design.tsv`) | nothing dropped |
| No design table | `metadata` pruned; the hub carries `__no_group__` (each library's phase), so the group filter, the colours, the Key figures composition and the embedding colour read the phases; nothing else changes |
| No strand bedGraphs | the seven bedGraph collections go: Signal dynamics loses every data-bound component (the tab goes); Genome signal keeps only the bigWig lanes (its strip, navigator, chromosome heatmap and table go); Library QC loses its hotspot filter and strand table, and its strand and hotspot cards print a dash (hub columns empty); on the Overview the Cover step and the chromosome and window Findings rows go with their values, their two highlights with their sources, and the plus-strand Key figure prints a dash |
| No bigWigs | the Strand coverage section of Genome signal goes; everything else stays |

## Validation scenarios

In the format of `VALIDATION_SCENARIOS.md`:

**Megatest:** `s3://nf-core-awsmegatests/nascent/results-7d4fe61975015f652c271886e661764b05cfd3bf/`
(tag 2.3.0, run_root `.`, manifest megatest.yaml)

**MultiQC:** none published (and nothing MultiQC can parse) -> no MultiQC collection

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| NA1 | **GRO-seq time course, design table (validated)** | `test_full` + `--var METADATA_FILE={DATA_ROOT}/input/design.tsv` | none | All 20 collections populate (129,437 binned windows, 14,552 genes); 6 tabs. |
| NA2 | **no design table** | omit `METADATA_FILE` | `metadata` pruned | Time points come off the library ids (`_<n>h`, `_<n>min`); `__no_group__` carries the phase; every tab renders. A run whose ids carry no duration and no design has no time course: the time-course recipes stop with "no sample has a time point". |
| NA3 | **completed run with transcript identification** | a run where PINTS, groHMM and HOMER finish | `transcript_identification/{grohmm,pints,homer}/` and `quantification/nascent/*.featureCounts.txt` published | Not read. The gene matrix glob is anchored on `gene/`, so the transcript-level matrix does not leak into the gene counts. A Transcripts tab needs such a run. |
| NA4 | **replicated time course** | two or more libraries per time point | several libraries share a time point | Every time-course collection averages the libraries of a time point; the correlation, PCA and QC stay per library. Not exercised on the megatest (no replicates). |
| NA5 | **PRO-seq / `--assay_type PROseq`, UMIs** | `--assay_type PROseq --with_umi` | strand orientation and the `umi_dedup` BAM names | The featureCounts library names strip `umi_dedup`; the plus/minus bedGraphs keep their names, so the recipes read them unchanged. Strand balance reads the same. |
| NA6 | **no bedGraphs or bigWigs fetched** | a tables-only fetch | the coverage collections are absent | See "Routes": Signal dynamics goes, Genome signal keeps what is left. |
| NA7 | **other assembly** | `--genome mm10` + `--var GENOME=mm10` | the axis and gene lane of the genome tracks | The navigator and the bigWig lanes take `GENOME`; an assembly GenomeSpy does not ship draws no gene lane. |

**Ranking by template stress:** NA1 > NA2 > NA4 > NA6 > NA3 > NA5 > NA7

## Live check (RULES section 15): pending

Each item below is pending a live check on a running stack; none was verified here.

- The Overview fits in about two screens, values fill in, highlights draw, `tab:` links open:
  pending live check.
- Controls dock right on the full-width viz and on top of the w4 profiles and the embedding:
  pending live check.
- No tile shows an empty band (autofit) or a cut body; no tick label is cut (the per-library bars
  carry 11 rotated labels), no legend scrolls or overlaps the tick labels (the seven-class
  response legend under a w4 profile is the one to watch): pending live check.
- The map draws its tiles and points: not applicable (no map).
- Each dock shows a few controls and "More options"; every view switch draws: pending live check.
- The group has the same colour on figures, advanced viz and the filter chips: pending live check.
- Every child tab opens on its intro; every KPI card draws its secondary and its caption, no bar
  reads about 1%, each icon shows in its own colour: pending live check.
- The Guide's demos are not empty: pending live check.
- Each conditional route still renders without a broken highlight or a stray `{VAR}`: pending
  live check (simulated above).
- A library picked in the left panel moves every card of a child tab, and the genome tab opens
  on data: pending live check. By design the per-gene and per-window cards follow the pick
  through the time point of their peak, and the two heatmaps do not follow it.
- The bigWig lanes draw on the whole first contig with `file_window_size` at 250 Mb (from the
  bigWig zoom levels), and follow a region brushed on the binned navigator: pending live check.

## Not verified

- Ingestion and rendering (no stack here). In particular the 129,437-row binned table behind a
  table-backed `genome_view` with 11 lanes, and the 22 bigWig lanes of the file-backed one.
- The bedtools recipes on all 22 bedGraphs in one call: they ran per file through the same lib
  calls, and end to end on four files. Memory is one streaming batch per file either way.
- A run with replicates, a run with transcript identification, and a non-human run.
