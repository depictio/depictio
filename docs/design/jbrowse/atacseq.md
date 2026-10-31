# Genome browser in nf-core/atacseq 1.2.2

The genome browser (`jbrowse` tile) sits in one tab of the atacseq dashboard, *Locus*, under
the navigator it follows. The Peaks tab has none: its significance panel reaches the browser
through an *Open in genome browser* action. The generic browser gestures (locus field, track
selector, pinning) are in the dashboard Guide and are not repeated here.

Scope: template `nf-core/atacseq/1.2.2`. Release 2.1.2 is out of scope (its megatest prefix is
empty and its 2.x layout needs its own recipe); nothing of it is touched.

## Tab map

| Tab | Question it answers | Tiles around the browser | What drives the browser |
|---|---|---|---|
| Peaks | How many peaks did each library yield, and how strong? | Peak filters, four cards, the genome-wide significance panel, width histogram, peak table. No browser | The significance panel's *Open in genome browser* action: the peak clicked, the region selected or the window in view becomes the opening locus of the *Locus* tab |
| Locus | What do the libraries call at one genomic region? | The navigator (one lane per library), four region cards, then the browser at full width | A brush or a typed locus on the navigator moves the view without filtering it. With nothing else, the browser opens on the most significant peak (`sort_by: neg_log10_qvalue`) and the stepper walks the peaks in that order |

The browser sits in the section `Peaks on one axis`, directly under the navigator. The consensus
and HOMER lanes that used to follow the navigator, and the second browser of the Peaks tab,
were removed: the cards still follow the region, and the browser shows the signal and calls of
every library there. The tile does not write back: a picked track would narrow the calls to
one library and reframe the view.

The Differential accessibility tab is not wired. Its volcano is not selectable, the DESeq2 rows
carry no coordinates (they reach one only through the link to the consensus intervals), and the
tab already fills its 20 open rows.

## Tracks

Collection `tracks` (type `genomic_tracks`), written by the recipe
`depictio/projects/nf-core/atacseq/1.2.2/recipes/tracks.py` from `pipeline_info/design_reads.csv`.
One row per file, keyed on the merged-library name (`<sample>.mLb.clN`, the spelling the peak
calls use). Rows are ordered signal first (replicate 1 of every group before replicate 2, groups by
name), then peaks, then BAMs. Each group keeps one colour across its replicates and kinds.

| Kind | Format | Path under the results folder | Display |
|---|---|---|---|
| signal | bigWig | `bwa/mergedLibrary/bigwig/<sample>.mLb.clN.bigWig` | wiggle, 60 px, local autoscale |
| peaks | broadPeak | `bwa/mergedLibrary/macs/broadPeak/<sample>.mLb.clN_peaks.broadPeak` (a narrow run: `macs/narrowPeak/..._peaks.narrowPeak`) | basic feature, 30 px |
| alignments | BAM | `bwa/mergedLibrary/<sample>.mLb.clN.sorted.bam` (+ `.bai`) | alignments (default) |

The megatest (`results_sha` of the template's `megatest.yaml`, 6 merged libraries in 3 protocol
groups, 2 replicates each) holds all three kinds; the paths above were checked against its bucket
listing and against the nf-core output page for 1.2.2:

- bigWig: 6 files, 31 to 244 MB, in `bwa/mergedLibrary/bigwig/`.
- broadPeak: 6 files, 0.3 to 7.5 MB, read whole by the browser (plain BED, no index).
- BAM: 6 files, 0.4 to 2.7 GB, each with a `.bai` of 2.5 to 3.5 MB.

Live check:

```bash
depictio-cli ingest --template nf-core/atacseq/1.2.2 --data-root <DATA_ROOT> \
  --var GENOME=hg19 \
  --var TRACKS_URI=s3://nf-core-awsmegatests/atacseq/results-f327c86324427c64716be09c98634ae0bc8165f6
# or the https form, which the browser-facing proxy reads the same way:
#   https://nf-core-awsmegatests.s3-eu-west-1.amazonaws.com/atacseq/results-f327c86324427c64716be09c98634ae0bc8165f6
```

`GENOME` must be `hg19` for the megatest (UCSC chromosome names); the template default is `hg38`.
`DATA_ROOT` is the tables-only subset from `download_test_data.sh` (it holds `design_reads.csv`,
which is all the recipe reads).

## Use cases

1. **One accessible region across protocols.** Locus tab, type a locus in the navigator header
   (or brush its axis). The browser follows it and shows the six signal tracks, replicate 1 of
   every protocol first. Compare the heights between protocols; open the
   `Peaks (MACS2)` folder in the track selector to put a library's calls under its own signal.
2. **Replicate agreement.** Peaks tab, click a strong peak on the significance panel and choose
   *Open in genome browser* (or use the browser's next button on the Locus tab to walk the
   peaks, strongest first). The view frames that peak: the two replicates of a protocol have the
   same colour, so a replicate that loses the signal stands out. Add the replicate 2 peak tracks from the selector to see whether
   its call is there.
3. **A peak and its reads.** Peaks tab, click a peak and open it in the genome browser, then open
   the `Alignments` folder and add the BAM of the library the peak was called in.

## Limits

- BAM files are large: the browser reads them by range, but the first open of a BAM at a
  locus is slower than a bigWig. They come last and are never part of the opening tracks.
- Merged-replicate files (`bwa/mergedReplicate/`: one bigWig and BAM per group) exist in the
  megatest but are not listed: every other collection binds the merged-library level.
- Peaks are read whole (plain BED, no tabix index): fine at the sizes of an ATAC run, slow for
  hundreds of thousands of calls.
- No gene annotation is added beyond the assembly preset; UCSC tracks are not configured.
- Open rows: the Locus tab holds the cards, the navigator (6) and the browser (9) open, which
  stays within the 20 open rows RULES.md allows.

## Status

Recipe-tested (`depictio/tests/recipes/test_atacseq_tracks.py`: missing files dropped, tables-only
keeps every row, reads in place keeps every row, ordering, colours, narrow-peak fallback, template
`tracks` collection validated with `DCGenomicTracksConfig`). Live-testable against the megatest
with the `TRACKS_URI` above; not yet seen in a browser.
