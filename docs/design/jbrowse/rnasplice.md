# Genome browser in nf-core/rnasplice 1.0.4

The `Splicing Events` tab carries a genome browser under the rMATS event table and its record
card: the strand-specific coverage and the reads of the samples in view, framed on the region
of the event picked in the table. Template `nf-core/rnasplice/1.0.4`, recipe
`rnasplice/recipes/tracks.py`, collection `tracks`.

## Tab map

| Tab | Question | Tiles | What drives the browser |
|---|---|---|---|
| Overview | The run in numbers | cards, findings, links | not in this tab |
| MultiQC | Did trimming, alignment and quantification work for every library? | MultiQC panels | not in this tab |
| Sample Space | Do the replicates of each condition sit together? | PCA, heatmap, library rows | not in this tab |
| Tool Agreement | Which genes does each tool call, and where do the tools agree? | UpSet, calls per tool, gene table | not in this tab |
| Exon Usage | Which genes use their exons differently, per DEXSeq and edgeR? | exon volcanoes, gene rows | not in this tab |
| Transcript Usage | Which transcripts change their share of the gene, per DEXSeq DTU? | DTU volcano, transcript rows | not in this tab |
| **Splicing Events** | Which event types change, and by how much inclusion? | event cards and types, rMATS and SUPPA2 volcanoes, sashimi, **event detail (collapsed): rMATS table, record card and genome browser**, SUPPA2 rows | the event row picked in the rMATS table (`locus_from`: `rmats_events`, `chrom`, `start`, `end` of the alternative region), the samples picked in the left panel (their tracks), a click on a track (picks its sample back) |

The "why here" sits in the description of the `Event detail` section: one row per rMATS event;
pick one to read its inclusion and its reads on the genome. The tab's intro is unchanged.
The sashimi above it keeps the junction-level view per condition (STAR's `SJ.out.tab`); the
browser adds the reads and the coverage per sample around the same event.

## Tracks

Paths are relative to the results folder (`TRACKS_URI`, or `DATA_ROOT` when the files are
uploaded), under `star_salmon/` (the `--aligner` folder).

| Track | Path | Format | Verified |
|---|---|---|---|
| Coverage, forward strand | `star_salmon/bigwig/<sample>.forward.bigWig` | bigWig | assumed: publish rules of `conf/modules.config` at tag 1.0.4 (`UCSC_BEDGRAPHTOBIGWIG`, `--skip_bigwig` drops it); not on the AWS bucket |
| Coverage, reverse strand | `star_salmon/bigwig/<sample>.reverse.bigWig` | bigWig | same |
| Alignments | `star_salmon/<sample>_sorted.bam` and `.bam.bai` | BAM, about 15 GB | publish rules at tag 1.0.4 (`SAMTOOLS_SORT` names it `<id>_sorted`, the docs page says `.sorted.bam`); another results prefix of the bucket (not 1.0.4) lists `star_salmon/<sample>_sorted.bam` with its `.bai`. Published with `--save_align_intermeds` |

A sample sequenced over several runs has one sheet row per run (`<sample>_T1`, `_T2`); the
recipe collapses them to the bare sample, which is how the pipeline names its outputs.

Not a track: the junction BED. rnasplice writes STAR's `star_salmon/log/<sample>.SJ.out.tab`,
a text table no browser adapter reads, and no BED. The sashimi tile draws those junctions.

Row order: the coverage pairs first (the first sample of each condition before the second),
the BAMs last. Colours are fixed per condition, the reverse strand lighter.

Assembly: the `GENOME` variable (default `hg38`). The bundled reference dataset sets `hg19`,
which is what the reference run was aligned to; pass `--var GENOME=hg19` for it. Its
Ensembl-style contig names are mapped by the preset's alias table.

The AWS megatest prefix of 1.0.4
(`s3://nf-core-awsmegatests/rnasplice/results-1d0494ae3402d1a46e0adadad24f81a0ff855c77`) is a
truncated sync with no alignment and no bigWig, so there is no URI to read the tracks in place
from; a `TRACKS_URI` is only useful for a run that kept them (an EMBL cluster run, for
instance).

## Use cases

**A differential splicing event, seen in the reads.**
1. Open `Splicing Events`, keep the called events (the call filter), and open the collapsed
   `Event detail` section.
2. Click the row of a skipped exon with a large PSI change: the record card shows its
   inclusion per condition and the browser jumps to the event's region. With no row picked the
   browser opens on the event with the largest PSI difference (`sort_by: abs_dpsi`), and the
   stepper walks the events in that order, the gene name beside the rank.
3. Open the coverage of one sample per condition from the track selector: the exon's coverage
   steps up in the condition that includes it. Open a BAM to see the split reads that skip it.

**A retained intron.**
1. Filter the event type to retained intron, pick an event with a high inclusion in the
   treatment.
2. Read the coverage across the intron in both conditions: a retained intron shows as a
   plateau of coverage, where a spliced one drops to the junction reads.

**A sample out of line.**
1. Click its coverage track: its sample is picked in the left panel and every tab narrows to
   it, the Sample Space tab included.

## Limits

- Not run on real tracks: the reference run is tables only, so the track paths above follow
  the pipeline's publish rules, not a listing. Check one with `TRACKS_URI` before relying
  on them.
- A pseudo-alignment-only run (`QUANT_ROUTE=salmon`) has no BAM and no bigWig. The collection
  stays and lists files that do not exist; drop it with the `tracks` DC tag or read a run that
  has them.
- The BAMs are only written with `--save_align_intermeds`.
- Without rMATS there is no event table, so no jump and no stepper; the browser opens on the
  first region that holds data.
- The coverage tracks draw their splice junctions as arcs (`show_junctions`), and the tracks are
  coloured and grouped by condition (`color_by: condition`).

## Status

Recipe-tested only (`depictio/tests/recipes/test_rnasplice_tracks.py`: missing files dropped,
all rows when tables-only, reads in place keeps all, runs of a sample collapsed, ordering,
colours, template and `DCGenomicTracksConfig` validation). The browser was not run on this
template.
