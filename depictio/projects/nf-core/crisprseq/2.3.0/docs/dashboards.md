# nf-core/crisprseq 2.3.0: Depictio dashboards

This template turns the output of the targeted analysis of
[nf-core/crisprseq](https://nf-co.re/crisprseq) 2.3.0 into an Overview and five tabs in three
groups. The targeted analysis sequences amplicons around edited loci: the pipeline aligns every
library to its reference amplicon, parses the CIGAR strings of the aligned reads into wild-type,
template-based (HDR) and indel reads, and, unless `--skip_clonality` is set, classifies each
library's zygosity and clonality from its indel peak structure. The screening analysis
(count tables, MAGeCK, BAGEL2) writes different outputs and is not covered. The family rules the
template follows are in `depictio/projects/nf-core/RULES.md`.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `samples` | the samplesheet (`METADATA_FILE`, default `input/samplesheet.csv`) | library |
| `crisprseq_edit_summary` | `cigar/<sample>_reads-summary.csv`, `_edits.csv`, `_QC-indels.csv` | library |
| `crisprseq_edit_outcomes` | `cigar/<sample>_edits.csv` | library and outcome class |
| `crisprseq_clonality` | `clonality/<sample>_edits_classified.csv` | library |
| `crisprseq_indels` | `cigar/<sample>_indels.csv` (one row per indel read) | library and allele |
| `guide_summary`, `guide_outcomes` | the per-library collections joined to the samplesheet's guide | guide, guide and outcome class |
| `guide_alleles` | `crisprseq_indels` pooled per guide (most frequent 200 alleles of each) | guide and allele |
| `guide_indel_sizes`, `guide_cut_site_profile` | `crisprseq_indels` summed per library, summarised per guide | guide and size, guide and offset |
| `guide_substitution_profile` | `cigar/<sample>_subs-perc.csv`, `_cutSite.json`, summarised per guide (guide column `profile_guide`) | guide and offset |
| `guide_substitutions` | `guide_substitution_profile` pivoted to one column per offset | guide |

Every per-library file is read by glob inside a recipe; no raw collection is scanned, so a run
with thousands of libraries still produces a handful of tables. The per-read indel tables are
the heavy input (a few gigabytes of text for thousands of libraries): the recipe reads only the
columns it needs and collapses reads to alleles. Profiles along the amplicon (indel sizes,
deletion and insertion position, substitution and gap rates) are computed per library inside
the recipes and published per guide as the mean library with its median and its first and third
quartile, so the dashboard ships one row per guide and offset rather than one per library and
position (on the reference run, 18,500 to 24,500 rows per profile instead of 250,000 to 1.1
million).

crisprseq does not publish its samplesheet, so the template ships the test_full sheet under
`input/` (without the FASTQ paths and the amplicon and template sequences) and reads it by
default; point `METADATA_FILE` at the sheet of another run. The pipeline writes no MultiQC
report, so the template has no MultiQC tab.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.csv` | samplesheet read by `samples` |
| `METADATA_ID_COL` | `sample` | samplesheet id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `protospacer`, `Protospacer` | grouping filter on the Overview and the left panel |
| `SKIP_CLONALITY` | unset | set for runs with `--skip_clonality`: drops the clonality collection, the Clonality section of Edit outcomes with its filters and tables, and the Classify step |

The CLI's metadata auto-detection picks the first non-id sheet column as `GROUP_COL`, which is
`fastq_1` in a pipeline samplesheet, so pass `--var GROUP_COL=protospacer` (or another design
column). A run has more guides than the category palette has colours, so with the default group
the guides take the brand colours rather than the palette.

## Keys and definitions

- **Library**: the samplesheet `sample`, the prefix of every per-library output file.
- **Guide**: the samplesheet `protospacer`, upper-cased. A run that set one protospacer for all
  libraries with `--protospacer` gets a single guide named `run protospacer`.
- **Classified reads**: wild-type + template-based + indel reads of a library, as counted by the
  CIGAR parser after its filters. Every rate and every allele share uses this denominator.
- **Edited**: classified reads that are not wild type. **Frameshift**: insertions and deletions
  whose length is not a multiple of 3. **Frameshift share of indels**: frameshift reads over
  insertion and deletion reads, the knockout-relevant number once editing happened.
- **Offset**: position minus the cut site the pipeline reports (`cut_site` in the indel table,
  `_cutSite.json`). The cut site is computed by the pipeline from the protospacer; if its
  convention does not match the strand of a guide, the signature shifts by a constant and the
  shape still reads correctly.
- **Main indel peak**: the CIGAR parser's `in_pick` flag, the indels inside the library's
  dominant indel cluster; indels outside it are often sequencing or alignment noise.
- **Substitution rate**: at each position, the share of reads carrying a base other than the
  dominant one. The dominant base stands in for the reference, which the table does not name;
  at a position edited in most reads this reads the edit as the reference.
- **Per-guide profiles** are drawn as the mean library of the guide, with a band from the first
  to the third quartile of its libraries that classified reads. The median is kept beside them
  in the tables. A library without an indel of a given size or at a given offset counts as zero;
  a substitution or gap rate counts only where the library's amplicon reaches the offset. The
  mean, not the median, is the curve because at most sizes and offsets most libraries carry no
  indel, so the median sits on zero even where part of the libraries carry one. A mean above its
  band means a minority of libraries carries the signal; a narrow band around a peak means most
  libraries repair the cut the same way.
- **Aligned window**: the substitution profile keeps only the offsets at least 90% of the
  guide's libraries reach. The amplicon ends that only some libraries reach are alignment
  edges, where the gap rate climbs towards 100% without any edit.
- **Guide summary**: the median over the guide's libraries, so one failed library does not move a
  guide. Its `edit_class` labels the median edited share: High (50 percent and up), Moderate
  (10 and up), Low (1 and up), Unedited.
- **Profile window**: the size and position profiles keep 100 bp either side of the cut site
  (sizes up to 100 bp); the substitution heatmap keeps 20 bp either side.
- **Guide alleles**: per guide, alleles are matched by type, length and offset from the cut
  site (so libraries on different amplicons line up) and the 200 carrying the most reads are
  kept; on the reference run they hold a median of 94% of a guide's indel reads. An allele is
  in the main peak when it is in the main indel peak of at least half the libraries carrying it.
- **Rounding**: rates and shares in the tables are rounded to three significant figures.

## Tabs

The Overview follows the family layout (`RULES.md` section 3): hero, About and run cards, a six
step pipeline flow, four key figures with a group and library filter bar, four findings with a
highlight each, and a link list of the tabs. The persistent sample filters and the collapsed
sample sheet (samplesheet and per-library summary) sit in the left panel and at the bottom of
every other tab.

**Data & QC**

1. **Read QC.** *Did each library have enough reads and alignment to call editing?* Four cards:
   raw reads per library, the clustered reads with the share the CIGAR parser classified, the
   aligned share and the indel reads the filters dropped. Raw reads against the aligned share per
   library, whose lasso narrows the other tiles.

**Editing**

2. **Edit outcomes.** *Which libraries carry disruptive edits, and how were they called?* Four
   cards: edited reads, the frameshift share of the indels, the in-frame reads and the reads by
   outcome. Frameshift share against editing per library, with the library record beside it.
   The Clonality section (zygosity class, clonality label, classifier confidence and indel
   peaks) goes with `SKIP_CLONALITY`. The clonality and outcome tables are collapsed.
3. **Guides.** *Which guides edit well, and which edits disrupt the reading frame?* Four cards:
   guide editing, frameshift share, libraries per guide and the share of the dominant indel
   size (how predictable the repair is). Editing against frameshift share per guide, and the
   repair outcomes of every guide as stacked bars. The guide table and the guide record are
   collapsed.

**Repair signature**

4. **Indel spectrum.** *What is the repair signature of one guide's cut?* Four cards: dominant
   indel size, its share, the frameshift share and the alleles by type. The indel size
   distribution and the deletion coverage and insertion position around the cut site, as the
   mean library with its band. The allele map (offset against size) and the tables of alleles
   are collapsed.
5. **Substitutions.** *Where around the cut do bases change or drop out?* Four cards: the peak
   substitution rate, the peak gap rate (each with the offsets that carry the most), the
   background rate and the libraries behind an offset. The guide by offset substitution matrix
   over every guide in scope (rows clustered, offsets in order, log(1 + rate) colour scale),
   then the substitution and gap profiles of the picked guide. The per-offset table is collapsed.

The library filters (library, `GROUP_COL`, donor template) apply to every tab through the
samplesheet links; guide-level tiles follow them through the `guide` link, so they show the
guides of the selected libraries (their means stay over all of the guide's libraries). Each tab
adds its own filters on the left.

## Filters and the guide pickers

Both Guide pickers are `always_selected`: the Indel spectrum and Substitutions tabs read one guide,
the first of the list until another is picked, on any run and without a run-specific
`default_value`. The pick cannot be cleared, so a profile is always one guide's signature (its
mean library with the band of its libraries) rather than a spread of guides.

Two pickers, two scopes. The Indel spectrum picker sits on the samplesheet's `guide` column, so
it narrows every collection of that tab through the samplesheet links, the cards and the allele
tables included. The Substitutions picker sits on `profile_guide`, a column only the per-guide
profile carries: a dashboard filter also applies to every collection with a column of the same
name, and a picker on `guide` would narrow the guide by offset heatmap as well. The pick narrows
the profile, its cards and its table, and the heatmap stays at the scope of the sample filters.

## Reading the dashboard

- Start on Read QC: a library with few classified reads or a low aligned share gives an editing
  rate that rests on a handful of reads.
- A guide that edits well but whose frameshift share of indels sits near a third makes in-frame
  edits as often as chance, which leaves more intact protein than a knockout needs.
- The per-guide size profile is the repair signature: a dominant 1 bp insertion or a
  microhomology deletion is typical of Cas9 repair and reproducible across a guide's libraries.
- The deletion profile should peak near offset 0. A peak far from it points at a misplaced cut
  site, a second site in the amplicon, or amplicon-end artefacts; the allele map shows which
  alleles make that peak.
- Without a donor template the template-based rate is structurally zero, and without a base
  editor the substitution matrix stays near zero apart from sequencing error.
