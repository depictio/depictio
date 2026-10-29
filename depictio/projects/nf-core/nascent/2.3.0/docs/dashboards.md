# nf-core/nascent 2.3.0: Depictio dashboards

This template turns the output of [nf-core/nascent](https://nf-co.re/nascent) 2.3.0 into an
Overview and five tabs in two groups. nascent aligns run-on libraries of nascent RNA (GRO-seq,
PRO-seq and their relatives), counts their reads over every gene body, writes their coverage strand
by strand and, when it completes, identifies nascent transcripts (groHMM, PINTS, HOMER). A run-on
library measures transcription while it happens, so a time course of it shows a response within
minutes rather than once mRNA has accumulated. The template reads the gene counts and the strand
coverage; the family rules it follows are in `depictio/projects/nf-core/RULES.md`.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `metadata` | the design table (`METADATA_FILE`, optional) | library |
| `subread_gene_counts` | `quantification/gene/<group>.featureCounts.txt` | gene and library |
| `subread_library_summary`, `subread_correlation` | `subread_gene_counts` | library, library pair |
| `bedgraph_strand_index` | `coverage_graphs/<sample>.plus.bedGraph`, `.minus.bedGraph` (first row only) | file |
| `bedtools_strand_windows` | the strand bedGraphs, streamed into 250 kb windows (libraries in name order) | library and window |
| `bedtools_strand_summary` | the strand bedGraphs, streamed into per-library totals | library |
| `samples` | the two library summaries and the design table; `strand_skew_pct` is the distance of the plus-strand share from half | library |
| `bedtools_strand_bins` | `bedtools_strand_windows` and the hub, the same rows with the libraries in time order (recipe `nf-core/nascent/strand_bins.py`), so the binned lanes stack 0h, 30min, 1h, ... rather than by name | library and window |
| `gene_dynamics`, `gene_trajectories` | `subread_gene_counts` and the hub's time points | gene; gene and time point |
| `top_gene_trajectories`, `top_gene_heatmap` | the gene calls and trajectories | gene and time point; gene |
| `sample_similarity`, `sample_drift` | `subread_gene_counts` and the hub | library; comparison and time point |
| `signal_window_dynamics`, `signal_window_series`, `signal_window_heatmap`, `chromosome_signal` | `bedtools_strand_bins` and the hub | window; window and time point; window; chromosome and time point |
| `tracks` | `coverage_graphs/<sample>.plus.bigWig`, `.minus.bigWig`, read by the browser (`genomic_tracks`, recipe `nf-core/nascent/tracks.py`), with each library's `time_point` and `time_order` from the hub | file (library and strand) |

The featureCounts matrix is parsed once into a long table; every other gene collection reads it
through `dc_ref`. The strand bedGraphs (4 to 10 million intervals each on a human genome) are
never ingested: the index collection reads one row per file to carry its path, and the two
bedtools recipes stream each file through `depictio/recipes/lib/strand_coverage.py` and
`genomic_bins.py`. The bigWigs are range-read by the browser for the region in view, through
their own index: in place when `TRACKS_URI` names the results folder, uploaded as they are
otherwise. The manifest lists both strands of the first, a middle and the last time point first
(six tracks, the browser's `initial_tracks`), then every other library's plus strand, earliest time
point first, then the other minus strands, so a gene on either strand shows signal on open. It
carries no colour column: the browser colours the tracks along the time course (below).

Not read: the BAMs, the dREG bedGraph (`<sample>.dreg.bedGraph`, a signed 3' end count for
dREG, not coverage), the QC reports (FastQC, fastp, preseq, RSeQC, BBMap) and the transcript
identification outputs. The megatest run published none of the last two (its PINTS caller
failed and aborted groHMM and HOMER, and the QC directories hold markers only) and wrote no
MultiQC report, so there is nothing to reprocess with MultiQC 1.35: the template declares no
MultiQC collection and has no MultiQC tab, and it has no Transcripts tab. A run that publishes
`transcript_identification/` is a candidate for one, to be built against such a run.

The pipeline publishes no samplesheet and no design. The template ships the test_full
samplesheet and a design table written for the megatest (`input/design.tsv`: `sample`, `stage`,
`time_point`, `time_h`), which `download_test_data.sh` copies into the data root.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | unset (reference: `{DATA_ROOT}/input/design.tsv`) | design table read by the hub; without it the metadata collection is pruned |
| `METADATA_ID_COL` | first column, else `sample` | design id column; the hub always names it `sample` |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | first factor column of the design (`stage`) | group filter, colours and splits |
| `TIME_COL` | `time_h` | design column holding each library's hours |
| `TRACKS_URI` | unset | `s3://` or `https://` folder holding the run's results: the browser then reads the bigWigs in place instead of uploading them from `DATA_ROOT` |
| `GENOME` | `hg38` | UCSC assembly of the genome tracks' axis and gene lane |

Without a design table, a library id ending in a duration (`<name>_30min`, `<name>_2h`, `_1d`)
still gives each library its hours and a time point label; a library with neither has no time
point and drops out of the time-course panels, while its QC stays on Library QC.

## Keys and definitions

- **Library**: the samplesheet `sample`, the featureCounts column name and the bedGraph prefix
  with their suffixes stripped (`<sample>.sorted.bam`, `<sample>.plus.bedGraph`).
- **Time point**: the design's `time_point` label (else written from the hours); libraries of
  one time point are averaged in every time-course panel. **Baseline**: the earliest time point.
- **Time axis**: `log2(1 + hours)`. A nascent time course is sampled every few minutes at the
  start and every day at the end; on a linear axis the first hour would take a few pixels.
- **Phase**: `Baseline`, then the tertiles of the later time points by rank: `Early`, `Mid`,
  `Late`. Rank-based, so the classes hold for any sampling of the course.
- **Expressed gene**: at least 10 reads in at least half of the libraries. The correlation, the
  PCA and the gene calls all read these genes, on `log2(cpm + 1)`.
- **Peak change**: the log2 fold change against the baseline at the later time point where it is
  largest in absolute value.
- **Induced, Repressed**: a peak change of at least 1 (twofold) with at least two time points
  changed by 1 or more in the same direction; otherwise **Stable**. Two time points because a
  time course is rarely replicated, and one time point alone (a spike) is not evidence. On a run
  with a single later time point, that point is enough. **Response class**: the direction with
  the phase of the peak (`Induced early` ... `Repressed late`).
- **Read bases**: depth times interval width, summed over a window's bedGraph intervals, so a
  1 bp interval does not weigh like a 5 kb one. **Signal per million**: a window's read bases
  over the library's total read bases (every contig included), times a million.
- **Windows**: 250 kb, on the contigs holding at least 20 windows with signal (the chromosomes);
  every library gets every window, 0 where it has no read. **Comparable windows**: those whose
  mean signal lies between the median window's and the 99.5th percentile, the transcribed half
  of the genome without the hotspots. **Rising, Falling**: the gene rule on `log2(rpm + 1)`.
- **Strand skew**: how far a library's plus-strand share sits from half, in points (`|plus - 50|`).
  Genes sit on both strands, so within 10 points (a share of 40 to 60%) reads as balanced, and
  past 15 a library has lost one strand.
- **Chromosome share against baseline**: the log2 of a chromosome's share of the signal over its
  own share at the baseline (`log2_ratio` in `chromosome_signal`). A raw share mostly says how
  long the chromosome is; the ratio says whether it moves.
- **Hotspot share**: the share of a library's chromosome signal in its busiest 1% of windows;
  ribosomal DNA arrays and a few very highly transcribed loci make it, and it grows when a
  library is poorly depleted. **Off the chromosomes**: signal on unplaced and alt scaffolds,
  the mitochondrion and episomes, in the library total but in no window.

## Tabs

The Overview follows the family layout (`RULES.md` section 3): hero, About and run cards, a five
step pipeline flow, four key figures (libraries, reads in genes, responsive genes, strand skew
with a pass, warn and fail count against the 10 and 15 point cut-offs) with a group and library
filter bar, four findings with a highlight each (the third names the chromosome whose share moves
most against its baseline), and a link list
of the tabs. The persistent sample filters (group, library, time point) and the collapsed
sample sheet sit in the left panel and at the bottom of every other tab.

**Data & QC**

1. **Library QC.** *Does each library have the depth and balance to be read?* Four cards: reads
   in genes, genes detected, the share of the 100 most counted genes and the hotspot share. Reads
   in genes per library in time order against the median and half of it (a bar under the dotted
   line has under half the typical depth), and the genes detected per library in time order
   against their median (a click narrows the other tiles); the plus-strand share per library
   against the even split with the balanced band (40 to 60%) shaded, and the hotspot,
   off-chromosome and mitochondrial shares. The library bars wear the colour of their time point
   (below). The gene-count and strand tables are collapsed.

**Time course**

2. **Gene dynamics.** *Which genes change transcription over the time course, and when?* Four
   cards: expressed genes by direction, induced and repressed genes by phase of the peak, and
   the peak change. The median trajectory of each response class with its quartile band, the ten
   genes that move most (one curve each, coloured by response class as the median curves are,
   the gene named at the end of its curve), and the forty most dynamic genes as a heatmap (rows
   z-scored, columns in time order). The call per gene and the value per time point are collapsed tables.
3. **Sample similarity.** *How far has each time point moved from the baseline?* Four cards:
   libraries by phase, the variance on the first component, the correlation with the baseline and
   the largest step. The library correlation matrix, a PCA of the libraries (PC1 against PC2,
   coloured by phase, on the time ramp; the embedding draws points, not a path, so the course
   reads as a move along PC1), and the correlation of each time point with the baseline and with
   the previous one.
4. **Genome signal.** *Where along the genome is nascent transcription read?* Four cards that
   follow the region in view: window signal, plus-strand share, silent windows and the busiest
   window. The binned signal, one thin lane per library (18 px, the chromosome axis stays in view
   while the lanes scroll), linked to a JBrowse browser below: brush a region in Select mode, or type one, and the
   browser (the plus and minus strand bigWigs of the first, a middle and the last time point, the
   other libraries in the track selector) zooms to it, and zooming the browser comes back
   on the lanes as a band. Lanes and tracks are coloured along the time course, the later the
   darker. Each chromosome's share of the signal against its own baseline share, per time point,
   on a diverging scale. The binned table is collapsed.
5. **Signal dynamics.** *Which genomic windows gain or lose nascent signal over time?* The gene
   rule applied to the comparable 250 kb windows, so a change outside annotated genes shows too.
   Four cards: the windows that change (rising or falling, of the transcribed windows compared,
   most of which are stable, so the ring shows only the two directions), rising and falling windows by phase, the peak
   change. The forty
   windows that change most as a heatmap, and the median course of each trend. The window table
   is collapsed.

The sample filters reach the per-library collections by `sample` and the correlation curves and
chromosome shares by `time_point`; the per-gene and per-window calls follow them by the time
point of their peak, so picking late libraries shows the genes and windows that peak late. The
gene and window trajectories (and so the median curves and the heatmaps) follow the calls in
scope, not the picked time points: a curve cut down to one time point would be a dot, so each
keeps its whole time course. The baseline never peaks, so picking only the baseline library
leaves no gene or window in scope (the curves say "No data" and the heatmaps "No rows in scope"). A tab's own filters reach
every tile of the tab: the median curves of Gene dynamics and Signal dynamics are computed in the
tile from one row per gene (or window) and time point, over the genes or windows in scope, and
the top-N curves and heatmaps keep those of their fixed selection that are in scope. On Genome
signal the chromosome filter narrows the binned tiles and the per-chromosome shares; the browser
follows the region brushed on the binned lanes (`follow_window`); panning the lanes leaves it in place.

### One colour code for the time course

The browser's tile sets `color_scale: {column: time_point, order_by: time_order, scheme: viridis}`
over the `tracks` manifest, which carries both columns from the hub, so the libraries take one
ramp in time order whatever their names. The binned lanes (`genome_view`, `sample_col: sample`)
wear the colour the browser gives the same library, so the two tiles agree without a second
setting. A `color_scale` on the `genome_view` itself would need the time point among its own rows,
and `bedtools_strand_bins` does not carry it.

The other tiles that colour a library draw on the same ramp, so a library keeps one colour on
every tab. The library bars of Library QC compute their colours in the code figure from the same
nine stops (`px.colors.sample_colorscale`, ordinal over the time points, as the browser spreads
them), unless Analysis mode picks groups. `category_colors` takes categorical values only and the
time points of a run are not known when the template is written, so the phases carry the ramp
instead: `Baseline`, `Early`, `Mid` and `Late` are pinned on four stops of it (also under
`{GROUP_COL}`, which is the design's phase column or the phase itself), and the PCA, the phase
donut and the peak-phase bars use them. The response and direction classes of a gene keep their
own warm and cool colours: they say what a gene does, not when a library was taken.

## Reading the dashboard

- Start on Library QC. A library more than 10 points from an even strand split has lost one strand; one with a
  large hotspot share reads its genes from what the ribosomal DNA left, and its counts per
  million are depressed across the board, which the correlation shows as an outlier.
- On Gene dynamics, the response classes say what kind of programme the time course runs: an
  early induced class that comes back down is a transient response, a late class that keeps
  climbing a secondary one. The heatmap shows which genes carry each shape.
- On Sample similarity, a time course moves along the first components in time order; a library
  off that line, or a dip in the step correlation that the neighbouring steps do not share, is a
  candidate outlier rather than biology.
- On Genome signal, the binned lanes are on log2 of the signal: the ribosomal DNA hotspot towers
  over everything on a linear scale. The browser's bigWig tracks are the raw coverage of each strand, listed earliest
  time point first and drawn on one shared signal scale, so a darker (later) track that stands
  taller than a paler one is more transcription, not a rescaled axis.
- Without replicates every call is a fold-change rule on consecutive time points agreeing, not a
  statistical test; read a single gene's trajectory before trusting its class.
