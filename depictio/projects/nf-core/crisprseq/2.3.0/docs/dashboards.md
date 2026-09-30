# nf-core/crisprseq 2.3.0: Depictio dashboards

This template turns the output of the targeted analysis of
[nf-core/crisprseq](https://nf-co.re/crisprseq) 2.3.0 into a six-tab Depictio dashboard.
The targeted analysis sequences amplicons around edited loci: the pipeline aligns every
library to its reference amplicon, parses the CIGAR strings of the aligned reads into wild-type,
template-based (HDR) and indel reads, and, unless `--skip_clonality` is set, classifies each
library's zygosity and clonality from its indel peak structure. The screening analysis
(count tables, MAGeCK, BAGEL2) writes different outputs and is not covered.

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
the recipes and published per guide as the median (or mean) library with its first and third
quartile, so the dashboard ships one row per guide and offset rather than one per library and
position (on the reference run, 18,500 to 24,500 rows per profile instead of 250,000 to 1.1
million).
crisprseq does not publish its samplesheet, so
the template ships the test_full sheet under `input/` (without the FASTQ paths and the amplicon
and template sequences) and reads it by default; point `METADATA_FILE` at the sheet of another
run.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.csv` | samplesheet read by `samples` |
| `METADATA_ID_COL` | `sample` | samplesheet id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `protospacer`, `Protospacer` | grouping filter on the left panel |
| `SKIP_CLONALITY` | unset | set for runs with `--skip_clonality`: drops the clonality collection |

The CLI's metadata auto-detection picks the first non-id sheet column as `GROUP_COL`, which is
`fastq_1` in a pipeline samplesheet, so pass `--var GROUP_COL=protospacer` (or another design
column).

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
- **Per-guide profiles** give the median, first and third quartile over the guide's libraries
  that classified reads. A library without an indel of a given size or at a given offset counts
  as zero; a substitution or gap rate counts only where the library's amplicon reaches the
  offset. The substitution and gap profiles and the substitution heatmap draw the mean
  instead: at most positions most libraries carry no substitution, so the median sits on zero,
  and the mean still shows a band carried by part of a guide's libraries. A mean above its
  interquartile band means a minority of libraries carries the signal.
- **Aligned window**: the substitution profile keeps only the offsets at least 90% of the
  guide's libraries reach. The amplicon ends that only some libraries reach are alignment
  edges, where the gap rate climbs towards 100% without any edit. The guide summary uses medians over libraries, so one failed
  library does not move a guide. Its `edit_class` labels
  the median edited share: High (50 percent and up), Moderate (10 and up), Low (1 and up),
  Unedited.
- **Profile window**: the size and position profiles keep 100 bp either side of the cut site
  (sizes up to 100 bp); the substitution heatmap keeps 20 bp either side.
- **Guide alleles**: per guide, alleles are matched by type, length and offset from the cut
  site (so libraries on different amplicons line up) and the 200 carrying the most reads are
  kept; on the reference run they hold a median of 94% of a guide's indel reads. An allele is
  in the main peak when it is in the main indel peak of at least half the libraries carrying it.
- **Rounding**: rates and shares in the tables are rounded to three significant figures.

## Tabs

1. **Overview.** Median editing, frameshift and frameshift-of-indels rates over the libraries
   in scope and the edited reads they rest on (sum, with the spread per library); template-based
   repair shows as its own class in the outcome composition bars rather than as a card, since
   it is zero on every run without a donor template. The outcome composition of every guide
   as stacked bars (reads pooled over the guide's libraries); the editing rate of every library against its classified reads.
   The persistent glance strip counts libraries (split by donor template), guides (split by
   editing level), and raw and classified reads (with their spread per library); the sample
   sheet is pinned at the top and the per-library summary at the bottom of every tab.
2. **Read QC.** Raw reads per library, the read funnel (raw, clustered, classified), the aligned
   share and the indel reads the filters dropped; raw reads against the aligned share.
3. **Edit outcomes.** The in-frame rate, the zygosity and clonality calls and the classifier's
   confidence; frameshift share against editing per library, with the library record as a side
   panel of the scatter; collapsed clonality and outcome tables.
4. **Indel spectrum.** One guide at a time, picked in a tab-local Guide picker that always
   holds one guide (the first of the run on opening) and narrows the whole tab through the
   samplesheet: the indel size distribution, deletion coverage and insertion position around
   the cut site (median library with its interquartile band), the allele map (offset against
   size, one point per allele of the guide), and collapsed tables of the guide's alleles pooled
   and per library.
5. **Substitutions.** The guide by offset substitution matrix over every guide (rows
   clustered, offsets in order, log(1 + rate) colour scale), then the substitution and gap
   profiles (mean library with its interquartile band) of the guide picked in the tab-local
   Guide picker. The picker filters the profile collection only: its guide column is named
   `profile_guide`, since a dashboard filter also applies to every collection with a column
   of the same name. The heatmap, the glance cards and the pinned tables stay at the scope of
   the library filters.
6. **Guides.** Median editing and frameshift share, the share of the dominant indel size (how
   predictable the repair is) and library count; editing against frameshift share per guide;
   the guide table (key columns) with the full guide record as its side panel.

The library filters (library, `GROUP_COL`, donor template) apply to every tab through the
samplesheet links; guide-level tiles follow them through the `guide` link, so they show the
guides of the selected libraries (their means stay over all of the guide's libraries). Each tab
adds its own filters on the left.

## Reading the dashboard

- Start on Read QC: a library with few classified reads or a low aligned share gives an editing
  rate that rests on a handful of reads. The Overview scatter shows the same on a log depth axis.
- A guide that edits well but whose frameshift share of indels sits near a third makes in-frame
  edits as often as chance, which leaves more intact protein than a knockout needs.
- The per-guide size profile is the repair signature: a dominant 1 bp insertion or a
  microhomology deletion is typical of Cas9 repair and reproducible across a guide's libraries.
  The interquartile band shows that reproducibility: a narrow band around a peak means most
  libraries repair the cut the same way.
- The deletion profile should peak near offset 0. A peak far from it points at a misplaced cut
  site, a second site in the amplicon, or amplicon-end artefacts; the allele map shows which
  alleles make that peak.
- Without a donor template the template-based rate is structurally zero, and without a base
  editor the substitution matrix stays near zero apart from sequencing error.
