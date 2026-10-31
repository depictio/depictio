# Genome browser in nf-core/methylseq 2.3.0: not added

No genome browser tile was added to the methylseq template. The pipeline's published files
on the template's route (Bismark) cannot be shown by the browser as they are, so there is
no `tracks` recipe, no `tracks` collection and no `jbrowse` tile in `Group comparison`.
Nothing of the template, its dashboard, its recipes or its docs was changed.

## What the run publishes (Bismark route, release 2.3.0)

Checked against the nf-core output page for 2.3.0 and the megatest bucket listing
(`methylseq/results-<results_sha>/bismark/bismark/`, `results_sha` in the template's
`megatest.yaml`):

| File | Path | Why it cannot be browsed |
|---|---|---|
| Methylation bedGraph | `methylation_calls/bedGraph/<sample>_1_val_1_bismark_bt2_pe.deduplicated.bedGraph.gz` | Plain gzip (the first bytes carry no BGZF extra field), not bgzip, with a `track type=bedGraph` header and contigs in name order. There is no `.tbi` (a request for it returns 404). The browser's bedGraph path needs a tabix index for a `.gz`, and the manifest cannot switch it off: the index is inferred from the extension. Reading the file whole means downloading 44 to 279 MB per sample, per region |
| Coverage | `methylation_calls/methylation_coverage/<sample>_..._pe.deduplicated.bismark.cov.gz` | Same: plain gzip, no index, a `.cov` text format the browser has no adapter for |
| Alignments | `deduplicated/<sample>_1_val_1_bismark_bt2_pe.deduplicated.bam` | Header says `SO:unsorted`, and no `.bai` is published (the run writes none). A BAM cannot be range-read without a coordinate sort and an index. 2 to 22 GB each |
| bigWig | none | The Bismark route writes no bigWig |

The sample name inside the file names is also not the samplesheet's: Bismark appends
`_1_val_1_bismark_bt2_pe` (paired end) or `_trimmed_bismark_bt2` (single end), so a recipe
would have to spell both layouts.

The bwa-meth route of the same run does publish sorted, indexed BAMs
(`bwa-mem_markDuplicates/*.sorted.markDups.bam` and `.bai`, only with `--save_align_intermeds`)
and MethylDackel bedGraphs, but the template binds the Bismark route only, and a
route-specific browser would need its own recipe and dashboard variant.

## What would unblock it

Any one of these, upstream of Depictio, makes the Bismark route browsable:

- a bigWig of the per-CpG methylation (the natural track for the `Group comparison` tab: a
  differential window's CpGs next to their coverage);
- the bedGraph written as bgzip with a tabix index (`bedGraph` then loads through the tabix
  adapter, which the manifest already supports: format `bedgraph`, `.bedGraph.gz` plus `.tbi`);
- a coordinate-sorted, indexed BAM published beside the deduplicated one.

The intended design, once such a file exists: a `tracks.py` recipe like atacseq's, one
signal row per sample coloured by the design's group, then the BAMs last; a `jbrowse` tile in
the `Group comparison` tab whose `locus_from` reads the window table
(`bismark_window_group_compare`), so a picked differential window frames its CpGs; and a
section description saying what the browser adds over the window plots (the CpG-level
methylation and coverage inside the window).

## Status

Dropped. Not live-tested and not recipe-tested, because there is nothing to test.
