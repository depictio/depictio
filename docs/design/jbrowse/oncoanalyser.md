# nf-core/oncoanalyser 3.0.0: the genome browser in the dashboard

Two tabs of the oncoanalyser dashboard hold a genome browser on the run's `tracks`
collection, each in a collapsed section: *Small variants* and *Structural variants*. They are
the exception to one browser per template: their track sets are disjoint (somatic calls and
reads on one, breakpoints and read arcs on the other). The *Copy number* tab has none; its
profile reaches a browser through its *Open in genome browser* action. The other tabs are about
the tumor as a whole (QC, purity, drivers, immune context) and have no locus to show. The generic gestures (Ctrl or Cmd + wheel to zoom, the tracks menu, the
metadata panel) are in the dashboard Guide, part "Browse the genome".

## Tab map

| Tab | The question it answers | Tiles | What drives the browser |
|---|---|---|---|
| Small variants | How many somatic variants are there, and how clonal? | 4 cards, two histograms, the calls along the genome (GenomeSpy), the variant table with its record card and, collapsed, *Reads under the calls* | `locus_from` on `purple_somatic_variants` (`chrom`, `pos`, at most 20 rows, 150 bp padding): a call picked in the collapsed table, or the few calls of a deeply zoomed region of the plot, frames the view |
| Copy number | Which regions are gained or lost, and in which genes? | 4 cards, the PURPLE copy-number profile (`views: [plotly]`), the gene scatter, the gene table with its record card. No browser | The profile's *Open in genome browser* action: the point clicked, the region selected or the window in view becomes the opening locus of a browser tab |
| Structural variants | Which rearrangements shaped the genome, and which fusions follow? | 4 cards, the chord diagram, SVs per resolved event, fusion exons, the tables and, collapsed, *Reads at the breakends* | `locus_from` on `linx_svs` (`chrom_a`, `pos_a`, at most 3 rows, 500 bp padding): an SV picked in the chord diagram or the SV table frames its first breakend |

Every row of the `tracks` collection is keyed on the group's tumor sample, the key every other
collection links on. A sample picked in the left panel opens that tumor's tracks (both
alignments included), and so does a call, a copy-number segment or an SV of that tumor (links
from `purple_somatic_variants`, `purple_cnv_segments` and `linx_svs`). Clicking a track in the
browser filters the dashboard by that sample.

The section descriptions say why the browser is on each tab. On *Small variants* it adds the
reads of the tumor and its normal under a call, which the plot and the table only summarise.
On *Structural variants* it adds the reads at a breakend, where the chord diagram only joins
two loci. The sections start collapsed to keep each tab inside the open-height budget of
`RULES.md`.

## Tracks

The `tracks` collection is built by
`depictio/projects/nf-core/oncoanalyser/recipes/tracks.py` from the samplesheet: for each
analysis group with a tumor DNA sample, one row per file. VCFs first (somatic, somatic SV,
germline, germline SV), then the alignments of every group, tumor before normal. The germline
VCFs and the normal alignment exist only when the group has a normal DNA sample.

| Track | Published path (relative to the outdir) | Index | Size on the megatest | Verified |
|---|---|---|---|---|
| Somatic small variants (PURPLE) | `<group>/purple/<tumor>.purple.somatic.vcf.gz` | `.tbi` | 25 MB | listing and local copy |
| Somatic SVs (PURPLE) | `<group>/purple/<tumor>.purple.sv.vcf.gz` | `.tbi` | 0.4 MB | listing |
| Germline small variants | `<group>/purple/<tumor>.purple.germline.vcf.gz` | `.tbi` | 0.2 MB | listing |
| Germline SVs | `<group>/purple/<tumor>.purple.sv.germline.vcf.gz` | `.tbi` | 4.7 MB | listing |
| Tumor alignment (REDUX) | `<group>/alignments/<tumor>/<tumor>.redux.bam` | `.bai` | 170 GB | listing |
| Normal alignment (REDUX) | `<group>/alignments/<normal>/<normal>.redux.bam` | `.bai` | 86 GB | listing |

"Verified" means the key exists in the public megatest listing and in the nf-core output page of
3.0.0. The somatic VCF's `IMPACT` field (PAVE's gene, effect and HGVS change) colours the calls
by coding effect (`variant_color_by` on `coding_effect`, the colours of the figures). The tumor
RNA alignment (`<group>/alignments/<rna>/<rna>.md.bam`, 10.7 GB on the megatest) is not listed:
no tab reads it.

### Megatest

The `test_full` run of the 3.0.0 release is the run the template was validated on:

```
s3://nf-core-awsmegatests/oncoanalyser/results-7c74c87a43749952b38c9a18915947570f0595a0
https://nf-core-awsmegatests.s3-eu-west-1.amazonaws.com/oncoanalyser/results-7c74c87a43749952b38c9a18915947570f0595a0
```

Pass either as `--var TRACKS_URI=...` (the host and the bucket are on the default allow-list):

```bash
depictio-cli run --template nf-core/oncoanalyser/3.0.0 --data-root <DATA_ROOT> \
  --var TRACKS_URI=s3://nf-core-awsmegatests/oncoanalyser/results-7c74c87a43749952b38c9a18915947570f0595a0
```

The local megatest copy under `~/Data/depictio-nfcore/oncoanalyser` holds the somatic VCF
without its index and no other track file, so a local ingest needs `TRACKS_URI`. Without it the
collection uploads the files (with their index) that DATA_ROOT holds and leaves out a file whose
index is missing.

## Use cases

**A driver's reads in tumor and normal** (Small variants)
1. In the left panel, pick the tumor sample: its six tracks (the four VCFs and both alignments) open.
2. On *Small variants*, expand *Variant detail* and click the row of a reported call (the table
   opens on the PASS calls; sort on `reported`).
3. Expand *Reads under the calls*. The view frames the call; the somatic VCF shows it coloured by
   its coding effect. With nothing picked it opens on the call with the highest purity-adjusted
   allele frequency, and the stepper walks the others in that order.
4. Compare the tumor and normal alignments at the position: reads carrying the alternate allele
   in the tumor and none in the normal make a somatic call. The first read of a BAM can take a
   while: the alignment files are 86 and 170 GB and are read by range.

**A copy-number segment beside its SV breakpoints** (Copy number)
1. In *Copy-number scope*, pick a chromosome. The profile narrows to its segments.
2. On the profile, click a segment edge, or select a region, then click *Open in genome
   browser*. A browser tab opens on that locus and the somatic SV VCF draws the breakpoints
   along it.
3. Zoom the browser to the segment edge and look for a breakpoint there.
4. Click a breakpoint to read its alleles and mate, or click **Circular view** for every SV of
   the run as chords.

**The reads at a rearrangement's breakend** (Structural variants)
1. Click a chord of the chord diagram (or a row of the SV table, collapsed below).
2. Expand *Reads at the breakends*. The view shows both breakends, 500 bp either side ("Both
   sides"). With nothing picked it opens on the SV with the highest junction copy number, and the
   stepper walks the others.
3. Open the tumor and normal alignments from the tracks menu, or pick the tumor sample in the left
   panel to open all its tracks. They open as read arcs (`read_pairs_display: arcs`): a discordant
   pair is an arc between its mates. Split and discordant reads at the breakend support the call.
4. Click **Breakpoint view** for the split view of the two breakends, joined by their reads.

## Limits

- The alignments are the largest files of the run (86 to 170 GB on the megatest). They are read
  by range and never in the first tracks shown, but a first load on a remote bucket is slow.
- The VCFs hold every record, the filtered ones included (PON, low confidence). The tables of the
  dashboard keep PASS calls only, so a call seen in the browser may not be in the table.
- A single breakend (no partner) has no mate: Both sides and the Breakpoint view show nothing for
  it.
- The circular view draws the tracks of the `Structural variants` category
  (`circular_categories`), the somatic and germline SV VCFs.
- The germline VCFs and the normal alignment exist for a group with a normal DNA sample only;
  a tumor-only run lists the somatic VCFs and the tumor alignment.
- Read in place, the recipe does not check that a file exists. A targeted (panel) run is assumed
  to publish the same paths; this was not checked.
- `GENOME` must name the build the run was aligned to (`hg38` for GRCh38_hmf, `hg19` for
  GRCh37_hmf). With no filter the browser opens on the first call of each tab's `locus_from`.
- No tumor RNA alignment, no ESVEE or SAGE VCFs: the PURPLE VCFs are the enriched form of both.

## Status

Recipe-tested and template-tested (`depictio/tests/recipes/test_oncoanalyser_tracks.py`: the
manifest rules, then the `tracks` collection validated by `DCGenomicTracksConfig` with `GENOME`
substituted, and the `TRACKS_URI` override). Not yet checked live: use the megatest `TRACKS_URI`
above on a local stack, VCFs first.
