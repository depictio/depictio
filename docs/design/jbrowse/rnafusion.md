# Genome browser in nf-core/rnafusion 4.1.3

The `Breakpoints` tab carries a genome browser in its own last section: the STAR alignments
of the samples in view, opened on the best supported fusion, or framed on the fusion picked in
the left panel (both breakpoints side by side).
Template `nf-core/rnafusion/4.1.3`, recipe `rnafusion/recipes/tracks.py` (the pipeline had no
recipes folder; only this file was added), collection `tracks`.

## Tab map

| Tab | Question | Tiles | What drives the browser |
|---|---|---|---|
| Overview | The run in numbers | cards, findings, links | not in this tab |
| MultiQC | Did the reads survive trimming and align to transcripts? | MultiQC panels | not in this tab |
| Caller Agreement | Which fusions did the callers agree on, and how are they ranked? | consensus cards, UpSet, ranked fusions | not in this tab |
| Caller Evidence | How much read support did each caller find for each fusion? | evidence figures, caller tables | not in this tab |
| **Breakpoints** | Where on the genome do the two fusion partners sit? | Arriba cards, partner-contig flow and chord, event classes, **reads at the breakpoint** | the persistent Fusion filter of the left panel (it narrows `arriba_fusion_links` through the `fusion` link; `locus_from` reads `chrom_a` and `pos_a`), the samples picked in the left panel (their tracks), a click on a track (picks its sample back) |
| Validation | Which calls hold up when the reads are re-aligned? | FusionInspector figures | not in this tab |
| Protein Domains | Which protein domains would each fusion protein keep? | domain architecture | not in this tab |
| Splice Junctions | Which splice junctions do the reads support, and how strongly? | junction landscape, arcs | not in this tab |

The "why here" sits in the description of the new `Reads at the breakpoint` section: the
aligned reads at the breakpoints of the fusion picked in the left panel. The tab's intro is
unchanged. The section is open, so the tab holds 20 rows of open sections, the budget.

## Tracks

Paths are relative to the results folder (`TRACKS_URI`, or `DATA_ROOT` when the files are
uploaded).

| Track | Path | Format | Verified |
|---|---|---|---|
| Alignments, one per sample | `star/<sample>.Aligned.sortedByCoord.out.bam` and `.bam.bai` | BAM (the test profile's is 1.8 MB) | listed on the megatest bucket, BGZF header read |
| Alignments with `--cram` | `star/<sample>.Aligned.sortedByCoord.out.cram` and `.crai` | CRAM | from the output docs page; not on the bucket. Needs the reference sequence of the assembly |

The recipe lists the BAM; where the run is on disk and holds a CRAM instead, it lists that.

Left out, on purpose: rnafusion publishes no bigWig. FusionInspector's alignments and IGV
inputs (`fusioninspector/<sample>/IGV_inputs/`) are made against a fusion-contig reference,
not the genome, so they do not line up with the assembly; `samtools/<sample>.Aligned.sortedByCoord.bam`
is the Picard/samtools copy of the same alignment.

Assembly: the `GENOME` variable (default `hg38`, deliberate: the usual human build, and the
megatest's; its Ensembl-style contig names are mapped by the preset's alias table).

Reading the run in place (megatest, `--var TRACKS_URI=...`):

```
s3://nf-core-awsmegatests/rnafusion/results-76ad76e7c39b2ba9edc35aa3602e3dc454d842ec
```

## Use cases

**The reads that support a fusion.**
1. Open `Breakpoints` with no fusion picked: the browser opens on the Arriba call with the most
   supporting reads (`sort_by: weight`), both breakpoints side by side ("Both sides").
2. Step through the calls with the next button of the header ("2 / 120", the fusion name beside
   it): the view moves, the filters do not.
3. Or pick one fusion in the Fusion filter of the left panel: the browser frames that call.
4. Open the sample's alignment from the track selector: split reads and soft-clipped ends pile
   up at the breakpoint, and the clipped bases start where the partner begins. The splice
   junctions of the coverage can be drawn as arcs (`show_junctions`).

**A call with doubtful support.**
1. Filter Arriba's confidence to `low` in the tab's filters, and pick one of its fusions in the
   Fusion filter of the left panel.
2. In the browser, count the split reads and discordant pairs at the breakpoint: a handful of
   reads whose clipped ends do not match the partner is a likely artefact, a stack of them with
   the same clip position is a real junction.

**A translocation, from both ends.**
1. Pick a fusion between two contigs in the flow tile or the Fusion filter.
2. The browser shows both breakpoints in one view. Click **Breakpoint view** in the toolbar for
   JBrowse's split view: two panes, one per partner, joined by the split reads and discordant
   pairs of the open alignments.
3. To go to a gene, type its name in the locus box: it is searched by name.

## Limits

- `locus_from` frames the 5' breakpoint; the 3' one comes from the `mate` columns
  (`chrom_b`, `pos_b`), shown beside it by Both sides and in the Breakpoint view.
- No circular view: the tracks collection holds no structural-variant file (no `sv` category),
  so `views` lists `breakpoint` only.
- No coverage track: rnafusion writes no bigWig, so read depth is the pileup only.
- With no fusion picked (more than 20 rows narrows nothing), the browser opens on the first
  call by `weight` and the stepper walks the rest.
- `SKIP_ARRIBA` removes `arriba_fusion_links`, the tab and the jump with it.

## Status

Recipe-tested only (`depictio/tests/recipes/test_rnafusion_tracks.py`: missing files dropped,
all rows when tables-only, CRAM listed as CRAM, reads in place keeps all, ordering, template
and `DCGenomicTracksConfig` validation). The tables-only megatest subset holds no track file,
so the browser was not run on this template.
