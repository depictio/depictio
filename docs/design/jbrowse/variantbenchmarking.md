# nf-core/variantbenchmarking 1.4.0: the genome browser in the dashboard

Two tabs of the variantbenchmarking dashboard hold a genome browser on the run's `tracks`
collection, in a collapsed section named *Errors on the genome*: **Germline** and
**Structural & CNV**. The Somatic tab does not host it. The browser answers a question the
tables cannot: the summary says how many calls a callset got wrong, the tracks say where. The
generic gestures (Ctrl or Cmd + wheel to zoom, the tracks menu, the metadata panel) are in the dashboard
Guide, part "Browse the genome".

## Tab map

| Tab | The question it answers | Tiles | What drives the browser |
|---|---|---|---|
| Germline | How well does each germline callset recover the truth set? | 4 cards, the vcfeval precision-recall scatter and error counts, hap.py by variant type and its sweep, and, collapsed, *Errors on the genome* and the tables | The callset filter (`label`) and the vcfeval table's row pick, through the summary to tracks link |
| Structural & CNV | How well do the structural callsets match the truth set? | 4 cards, the Truvari precision-recall scatter and error counts, SVanalyzer and Wittyer, and, collapsed, *Errors on the genome* and the tables | The callset filter (`label`) and the Truvari table's row pick, through the Truvari summary to tracks link |

There is no `locus_from`: no collection of this template holds a per-call coordinate (the
tables are one row per callset), so the browser opens on the first region that holds data in its first tracks. The tracks are the
way to find the loci. A click on a track in the browser filters the summary tables back to
that callset (tracks to summary link on `sample_id`, which is the callset id).

The section description says why the browser is on the tab: where the picked callsets' false
positives and false negatives sit. Both sections start collapsed, to keep the tabs inside the
open-height budget of `RULES.md`.

## Tracks

The `tracks` collection is built by `depictio/projects/nf-core/variantbenchmarking/recipes/tracks.py`
from the aggregated summary tables the dashboard already reads. One row per file, keyed on the
callset id (`sample_id`); per callset the false positives and false negatives come first (the
two tracks the browser opens on), then the true positives. The files are small.

| Track | Published path (relative to the results folder) | Index | Verified |
|---|---|---|---|
| rtg-tools false positives | `small/<id>/benchmarks/rtgtools/<id>.<truth>.<caller>.fp.vcf.gz` | `.tbi` | listing |
| rtg-tools false negatives | `small/<id>/benchmarks/rtgtools/<id>.<truth>.<caller>.fn.vcf.gz` | `.tbi` | listing |
| rtg-tools true positives (comparison) | `small/<id>/benchmarks/rtgtools/<id>.<truth>.<caller>.tp.vcf.gz` | `.tbi` | listing |
| Truvari false positives | `structural/<id>/benchmarks/truvari/<id>.<truth>.<caller>.fp.vcf.gz` | `.tbi` | assumed (nf-core output docs) |
| Truvari false negatives | `structural/<id>/benchmarks/truvari/<id>.<truth>.<caller>.fn.vcf.gz` | `.tbi` | assumed (nf-core output docs) |
| Truvari true positives (comparison) | `structural/<id>/benchmarks/truvari/<id>.<truth>.<caller>.tp-comp.vcf.gz` | `.tbi` | assumed (nf-core output docs) |

"Verified" means the key exists in the public megatest listing. `<id>.<truth>.<caller>` is the
`File` column of the summary table without its last two tokens (`<id>.<truth>.<caller>.summary.txt`
for rtg-tools, `.summary.json` for Truvari), so a truth-set name with dots keeps its name.
The collapsed threshold sweep of the rtg-tools table is read as its canonical row.

Not listed: the truth and query VCFs the pipeline standardises under `<variant_type>/<id>/preprocess/`
(their names carry a pipeline-internal suffix), hap.py's labelled VCF
(`benchmarks/happy/`, a single file mixing truth and query records), SVanalyzer and Wittyer
files (not every release writes an index for them) and every somatic route file.

### Megatest

The pinned 1.4.0 run holds the germline `small/` and the somatic `indel/` routes, and an empty
`structural/`:

```
s3://nf-core-awsmegatests/variantbenchmarking/results-8b21c01749c4447b285d242a198127736f3ffe51
https://nf-core-awsmegatests.s3-eu-west-1.amazonaws.com/variantbenchmarking/results-8b21c01749c4447b285d242a198127736f3ffe51
```

The germline callsets of that run are scored against a GRCh37 truth set, so the live check
passes the matching preset:

```bash
depictio-cli ingest --template nf-core/variantbenchmarking/1.4.0 --data-root <DATA_ROOT> \
  --var GENOME=hg19 \
  --var TRACKS_URI=s3://nf-core-awsmegatests/variantbenchmarking/results-8b21c01749c4447b285d242a198127736f3ffe51
```

Without `TRACKS_URI` the collection uploads the VCFs (with their `.tbi`) that DATA_ROOT holds
and leaves out a file whose index is missing. The tables-only data root has none, so every
expected row is then listed and loads nothing. The megatest holds no structural data, so the
structural rows have not been seen against a real run.

## Use cases

**An error that is only a representation difference** (Germline)
1. Open *Germline* and expand *Errors on the genome*.
2. In the left panel, pick one callset. Its false positive and false negative tracks open.
3. Scan along a chromosome. A false positive that sits a few bases from a false negative is the
   same event written two ways (an indel left-aligned differently, a split multi-allelic record):
   the caller found it and the comparison missed it.
4. Add the true positives from the tracks menu to see the neighbouring calls both sides agree on.

**Two callsets, one region** (Germline)
1. Pick two callsets in the callset filter. Both callsets' false positive and false negative
   tracks are in the track list (the first two open; raise the count from the tracks menu).
2. Compare their false negatives over the same window: a miss shared by both is a hard region of
   the truth set, a miss of one is a caller weakness.

**A breakpoint the caller misplaced** (Structural & CNV)
1. Pick a callset in *Structural & CNV*; its Truvari false positive and false negative tracks
   open.
2. A false positive with a false negative next to it is a call that found the event but
   missed the match by breakpoint or length tolerance, which the per-event score of Wittyer
   shows as a gap against the per-base one.

## Limits

- Germline (rtg-tools) and structural (Truvari) only. The somatic route writes rtg-tools and
  som.py files under `indel/` or `snv/`, and the sompy summary has no per-call output.
- No jump from a table row to a locus: the tables carry no coordinates. The reader finds the
  locus in the tracks.
- The build is the `GENOME` variable (default hg38), not read from the run. A GRCh37 run must be
  ingested with `--var GENOME=hg19`, or the contigs and the gene lane do not match the calls.
- A data root that holds two routes lists both, one block per route, rtg-tools first.
- Ranges only reach the browser through the API proxy, so a run needs the megatest bucket on
  the allow-list (the default) or its own.
- The Truvari paths come from the nf-core output documentation, not from a listing; the
  megatest has no structural run.
- With no `locus_from`, no collection gives the browser rows to frame, so there is no stepper and
  no Breakpoint view: it opens on the first region that holds data in its first tracks.

## Status

Recipe-tested and template-tested (`depictio/tests/recipes/test_variantbenchmarking_tracks.py`:
file names and order, dotted truth sets, both routes, the index filter, in-place reads, the
missing-source error, then the `tracks` collection validated by `DCGenomicTracksConfig` with
`GENOME` substituted, and the `TRACKS_URI` override). Not yet checked live: start with the
germline `small/` route of the megatest above, and confirm the Truvari paths on a structural run.
