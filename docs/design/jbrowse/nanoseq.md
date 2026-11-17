# Genome browser in nf-core/nanoseq 3.0.0

The `Isoform usage` tab carries a genome browser under its isoform lane view: the coverage
and the long-read alignments of the libraries in view, framed on the transcript picked in the
DEXSeq table. Template `nf-core/nanoseq/3.0.0`, recipe `nanoseq/recipes/tracks.py`, collection
`tracks`.

## Tab map

| Tab | Question | Tiles | What drives the browser |
|---|---|---|---|
| Overview | The run in numbers | cards, findings, links | not in this tab |
| MultiQC | Did every library sequence and align as expected? | MultiQC panels | not in this tab |
| Reads | How long and how good are the reads of each library? | cards, NanoStat figures | not in this tab |
| Alignment | How much of each library aligned, and how accurately? | samtools figures | not in this tab |
| Quantification | Do the libraries group by condition, or by preparation? | PCA, correlation, top variable genes | not in this tab |
| Gene expression | Which genes differ between the two conditions? | DESeq2 volcano, MA, tables | not in this tab |
| **Isoform usage** | Which transcripts change their share of their gene? | usage cards, DEXSeq volcano, usage per library, **isoform structures and genome browser** (collapsed), tables | the transcript picked in the DEXSeq table (`locus_from`: the exon blocks of `gtf_transcripts`), the samples picked in the left panel (their tracks), a click on a track (picks its sample back) |

The "why here" sits in the description of the `Isoform structures` section: exon lanes, then
the reads under them, for the transcript picked in the DEXSeq table. The tab's intro is
unchanged.

## Tracks

Paths are relative to the results folder (`TRACKS_URI`, or `DATA_ROOT` when the files are
uploaded). The aligner folder is `minimap2/`, or `graphmap2/` when the run used GraphMap2.

| Track | Path | Format | Verified |
|---|---|---|---|
| Coverage, one per sample | `minimap2/bigwig/<sample>.bigWig` | bigWig, unstranded | listed on the megatest bucket, magic bytes read |
| Long-read alignments, one per sample | `minimap2/<sample>.sorted.bam` and `.bam.bai` | BAM, 0.7 to 2.8 GB | listed on the megatest bucket, BGZF header read |

Left out: `minimap2/bigbed/<sample>.bigBed` (per-read BED12, 30 to 130 MB, repeats the BAM) and
`minimap2/bigwig/<sample>.bedGraph` (the plain twin of the bigWig, 190 to 520 MB).

Row order: coverage of replicate 1 of every condition before replicate 2, the BAMs last.
Colours are fixed per condition.

Assembly: the `GENOME` variable (default `hg38`, deliberate: the usual human build). The
bundled reference dataset sets `hg19` in `template.reference.vars`, which is what the megatest
was aligned to; its Ensembl-style contig names (`1`, `2`) are mapped by the preset's alias
table.

Reading the run in place (megatest, `--var TRACKS_URI=...`):

```
s3://nf-core-awsmegatests/nanoseq/results-1e60482a2c4621234393a6eef8e9a104309c20ae
```

## Use cases

**The reads behind an isoform switch.**
1. Open `Isoform usage`, then the `Isoform tables` section (collapsed) and sort the DEXSeq
   table by its gene-level q-value.
2. Click the row of a transcript with a large usage shift: the isoform lane view redraws on
   its gene and the browser jumps to the exons of that transcript.
3. In the browser's track selector, open one library of each condition (coverage first, then
   a BAM). Compare the coverage over the shifted exon and check whether long reads span the
   junction on both sides. Use the track selector rather than the left panel for this: a
   sample picked in the left panel also empties the isoform lanes (see Limits).

**A library that looks different on the coverage.**
1. In the browser's track selector, open the coverage of every library (`max_tracks` 12).
2. Click a coverage track: its sample is picked in the left panel and every tab narrows to it,
   the Reads and Alignment tabs included.

**A novel isoform.**
1. With `bambu/extended_annotations.gtf` published, open `Isoform structures`: the lanes are
   coloured by transcript class, so a novel isoform shows in its own colour.
2. Pick it in the DEXSeq table (its id is the Bambu transcript id): the browser frames its
   exons, and the reads of the libraries in view show where they start and end.

## Limits

- The isoform lanes and the jump need `bambu/extended_annotations.gtf`, which only a run that
  lets Bambu extend the annotation writes. Without it the browser still opens, on the first
  region that holds data, and the user searches a gene by name (typed in the locus box).
- With no transcript picked the tile opens on a block of the highest-expressed transcript
  (`sort_by: expression`). The stepper is off (`call_stepper: false`): a row of
  `gtf_transcripts` is one exon block, so it would walk blocks, not isoforms.
- The coverage tracks draw their splice junctions as arcs (`show_junctions`), and the tracks
  are coloured and grouped by condition (`color_by: condition`).
- A sample picked in the left panel narrows `gtf_transcripts` too (the hub links to it on
  `sample`, which the run-level annotation carries as `all_samples`), so with a sample picked
  the isoform lanes are empty and the browser does not jump. This predates the browser tile;
  clear the sample filter to jump to a picked transcript.
- The BAMs are range-read from the bucket, but a long-read pileup over a wide window is heavy:
  keep the window under a few tens of kb.
- Transcriptome-input samples (`is_transcripts`) have no genome alignment and no tracks.

## Status

Recipe-tested only (`depictio/tests/recipes/test_nanoseq_tracks.py`: missing files dropped,
all rows when tables-only, reads in place keeps all, ordering, graphmap2 fallback, template
and `DCGenomicTracksConfig` validation). The tables-only megatest subset holds no track file,
so the browser was not run on this template.
