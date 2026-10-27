# nf-core/sarek 3.10.0: the genome browser in the dashboard

One tab of the sarek dashboard, *Locus*, holds a genome browser on the run's `tracks`
collection, in a section named *Reads under the calls*. The other tabs do not host it: they
compare callsets as tables and figures, and the browser is where a single call is checked
against the reads. The rainfall of *Caller concordance* reaches it through its *Open in genome
browser* action, which opens *Locus* on the call clicked. The generic gestures (Ctrl or Cmd + wheel to zoom, the tracks menu, the metadata panel) are in the
dashboard Guide, part "Browse the genome".

## Tab map

| Tab | The question it answers | Tiles | What drives the browser |
|---|---|---|---|
| Caller concordance | Which calls do the callers share, and where do they differ? | 4 cards, the UpSet of shared PASS calls, allele fraction against depth, rainfall of the calls along the genome, the call table. No browser | The rainfall's *Open in genome browser* action: the clicked call, the selected region or the visible window becomes the opening locus of the *Locus* tab |
| Locus | What do depth and calls show at one region? | 4 region cards, the depth navigator, depth per interval and *Reads under the calls* (the browser, with the circular view of the structural variants) | The navigator's brush moves the view without filtering; the `locus_from` on `vcf_variants` (at most 60 rows, sorted by quality) opens it on the best call when nothing else says where |

Every tab with a sample pick also drives the tracks: the left panel's sample filters narrow the
tracks to those samples (hub to tracks link), and a call's sample opens its tracks
(`vcf_variants` to tracks link). Clicking a track in the browser filters the dashboard by that
sample (tracks to hub link, `selection_column: sample_id`).

The section description says why the browser is on the tab: it adds the reads of each sample
under every caller's calls, which the depth lanes above leave out.

## Tracks

The `tracks` collection is built by `depictio/projects/nf-core/sarek/recipes/tracks.py` from
sarek's own `csv/` manifests (`variantcalled.csv` for the callers of each sample,
`recalibrated.csv` or `markduplicates*.csv` for the samples with a CRAM). One row per file,
keyed on `sample_id`; the order is VCFs first (per sample: small-variant callers, then
structural-variant callers), CRAMs last.

| Track | Published path (relative to the results folder) | Index | Verified |
|---|---|---|---|
| Caller VCF, snpEff-annotated (preferred) | `annotation/<caller>/<S>/<S>.<caller>[.filtered]_snpEff.ann.vcf.gz` (Manta `<S>.manta.diploid_sv_snpEff.ann.vcf.gz`, Strelka `<S>.strelka.variants_snpEff.ann.vcf.gz`) | `.tbi` | listing and local copy |
| Caller VCF, plain | `variant_calling/<caller>/<S>/<S>.<caller>[.filtered].vcf.gz` | `.tbi` | listing |
| Manta SV VCF | `variant_calling/manta/<S>/<S>.manta.diploid_sv.vcf.gz` | `.tbi` | listing |
| CRAM, recalibrated | `preprocessing/recalibrated/<S>/<S>.recal.cram` (1 to 3 GB each) | `.crai` | listing |
| CRAM, duplicates marked (fallback) | `preprocessing/markduplicates/<S>/<S>.md.cram` | `.crai` | listing |

"Verified" means the key exists in the public megatest listing (and, for the annotated VCFs, in
the local copy under `~/Data/depictio-nfcore/sarek`). The annotated twin is used first because its `ANN` field
colours the calls by snpEff impact (`variant_color_by: impact`, the colours of the figures), and
because the plain FreeBayes VCFs of the megatest are stubs of a few hundred bytes while the
annotated twin carries the calls. Callers: HaplotypeCaller, DeepVariant, Strelka, FreeBayes,
Manta and TIDDIT have their own colour; another caller takes the file name
`<S>.<caller>.vcf.gz`.

### Megatest

The `test_full_germline_ncbench_agilent` profile of the 3.10.0 release (two exome libraries of
one individual, five callers) is the run the template was validated on:

```
s3://nf-core-awsmegatests/sarek/results-8ccac7ad37b05dd792447763bf9671b719824587/test_full_germline_ncbench_agilent
https://nf-core-awsmegatests.s3-eu-west-1.amazonaws.com/sarek/results-8ccac7ad37b05dd792447763bf9671b719824587/test_full_germline_ncbench_agilent
```

Pass either as `--var TRACKS_URI=...` (the host and the bucket are on the default allow-list):

```bash
depictio-cli ingest --template nf-core/sarek/3.10.0 --data-root <DATA_ROOT> \
  --var TRACKS_URI=s3://nf-core-awsmegatests/sarek/results-8ccac7ad37b05dd792447763bf9671b719824587/test_full_germline_ncbench_agilent
```

Without `TRACKS_URI` the collection uploads the VCFs (with their `.tbi`) that DATA_ROOT holds
and leaves out a file whose index is missing. The local megatest copy has the annotated VCFs
and their indexes, and no CRAM, so a local ingest lists the ten VCFs and no reads.

## Use cases

**A call checked against the reads** (Caller concordance)
1. Open *Caller concordance*.
2. In the left panel, pick one sample. Its tracks are narrowed to its callers' VCFs and its CRAM.
3. In *Calls along the genome*, click a dot, then *Open in genome browser*. The *Locus* tab
   opens with the browser on the call. Before any pick it opens on the call with the highest
   quality (`sort_by: qual`), and the stepper walks the calls in that order.
4. Open the sample's CRAM from the tracks menu if it is not among the first tracks shown (the
   CRAMs come last, so an unfiltered view opens on the VCFs only). Zoom in until the reads draw.

**Callers compared on one locus** (Caller concordance)
1. Leave the sample filter empty, click a dot in the rainfall and open it in the genome browser.
2. The browser shows the callers' VCFs of the first sample (three tracks open by default) at the call.
   Step to the next call with the header's next button instead of going back to the plot.
3. Read which callers carry it; the colour of a call is its snpEff impact.
4. Click a VCF track: the dashboard filters on that sample, and the UpSet and cards above follow.

**An SV breakpoint** (Caller concordance)
1. In *Call filters*, set Caller to the Manta caller and Variant type to SV.
2. Click the breakpoint's dot in the rainfall (the *Call table* lists the same calls) and open
   it in the genome browser. The view frames the call's start, 300 bp either side.
3. Open the CRAM of the sample to see the discordant and split reads at the breakpoint.
4. **Circular view** in the toolbar draws every structural-variant VCF of the run as chords
   (the `Structural variants` category).

**A region's reads** (Locus)
1. Type a short locus in the depth navigator's header, or brush a narrow window.
2. *Reads under the calls* follows the window.
3. Pick a sample in the left panel to add its CRAM under the callers' calls.

## Limits

- Germline runs only. A somatic pair (`<tumour>_vs_<normal>`) has no row, as on the sample hub;
  sarek publishes no somatic profile on the megatest.
- Read in place, the recipe uses the first layout of each file (snpEff-annotated VCF,
  recalibrated CRAM) without checking that it exists. A run without snpEff in `--tools` has no
  `annotation/` folder: ingest it without `TRACKS_URI`, or the VCF tracks load nothing.
- A CRAM needs the reference sequence, which comes from the `GENOME` preset. The preset must be the
  build the run was aligned to; the `@SQ` names must match the preset's contigs (UCSC names
  with `chr`, or a name `chromAlias` resolves). A run aligned to a reference with alt or decoy
  contigs shows reads only on the primary ones.
- The CRAMs are gigabytes: they are read by range, and only the window in view is downloaded.
  They are never in the first tracks shown.
- Ranges only reach the browser through the API proxy, so a run needs the megatest bucket on
  the allow-list (the default) or its own.
- A BAM (`--save_output_as_bam`) is not listed. The structural-variant call's end is not a column
  of `vcf_variants`, so a jump frames its start, not its span.
- With no filter the browser opens on the first call by quality. No `mate` is declared (the end
  of an SV call is not a column of `vcf_variants`), so there is no Breakpoint view.

## Status

Recipe-tested and template-tested (`depictio/tests/recipes/test_sarek_tracks.py`: manifest
rules, then the `tracks` collection validated by `DCGenomicTracksConfig` with `GENOME`
substituted, and the `TRACKS_URI` override). Not yet checked live: the CRAM against the preset
reference is the first thing to check, with the megatest `TRACKS_URI` above on a local stack.
