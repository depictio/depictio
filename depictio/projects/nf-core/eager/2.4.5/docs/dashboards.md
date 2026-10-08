# nf-core/eager 2.4.5: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from the
reads to the genotypes called from an ancient extract. The template follows the family
rules in `depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0 is the reference
implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did sequencing and trimming work for every library? |
| Data & QC | Libraries | How do the libraries compare on every tool at once? |
| Data & QC | Read fate | Where does every sequenced read stop? |
| Ancient DNA | Endogenous DNA | How much of each extract is the target organism? |
| Ancient DNA | Complexity | How many distinct molecules does each library hold? |
| Ancient DNA | Authentication | Is the DNA damaged and short, as ancient DNA is? |
| Genome | Coverage | How deep and how evenly is the reference covered? |
| Genome | Locus | How deep and how well mapped is one region? |
| Genome | Genotypes | How many variants did each sample yield, and how clean? |

eager trims and collapses ancient-DNA reads, maps them, deduplicates, profiles the
misincorporation damage that says whether the DNA is really ancient, and genotypes what is
left. The library hub (`samples`) is one row per eager library (`Library_ID`); the sample
filters (biological sample, library, UDG treatment) fan out from it through the template
links to the MultiQC panels and every per-library table. The two bcftools collections key
on `Sample_Name` (bcftools reads it from the VCF header), so the hub carries both ids and
two links on `sample_name`. eager has no `GROUP_COL`: the biological sample plays the
group's part on the Overview.

The template was validated on the AWS megatest run
`results-42c9d5f8602e5e88fdcec28f194d2cd4cff61c75` (the 2.4.5 release tag; see
`megatest.yaml`). No dashboard text names that run's samples, organism or contigs.

> **This template reads a REPROCESSED MultiQC report.**
> eager 2.4.5 published MultiQC 1.13.dev0, which writes `multiqc_data.json` and no
> parquet. Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so the MultiQC
> tab is bound to a report this repository generates by re-running the pinned MultiQC 1.35
> over the run's own raw tool outputs. See `VALIDATION_REPORT.md`.

> **Copy the run's `--input` TSV under `{DATA_ROOT}/input/`.**
> eager 2.x does not publish its samplesheet. The two recipes that read it
> (`eager/samples.py`, `eager/lane_stats.py`) take any `input/*.tsv`, so copy the TSV the
> run was launched with there. For the megatest, `input/benchmarking_vikingfish.tsv` in
> this template directory is a hand-reconstructed manifest against the six ENA runs the
> megatest fetched.

### Template variables

| variable | default | use |
| --- | --- | --- |
| `DATA_ROOT` | required | eager output root, plus `input/*.tsv` and the reprocessed MultiQC parquet |
| `SHORT_FRAGMENT_BP` | `70` | short-fragment cut-off. The `damageprofiler/authenticity` recipe receives it as a param and counts the fragments shorter than it (the column keeps the name `fraction_under_70bp`); the Authentication tab names it on its card |

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters. DSL1 wrote no
  `params.json`, so the dialog lists the software versions the run recorded.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the libraries and samples,
  the most common UDG treatment, the organism, and the lanes and reads sequenced, read from
  the run's tables.
- **Pipeline**: six steps (trim, map, deduplicate, authenticate, cover, genotype). Each step
  opens the version of the tool that ran it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Libraries
  (split by biological sample), the median endogenous DNA (a share of 100%), the median
  C to T frequency at the first base (the box shows its spread across libraries) and the
  median share of the reference covered at 1X. A sample and a library filter above them
  narrow these four only.
- **Findings**: result rows computed under the filters, each with a link to its tab: the
  endogenous DNA left after filtering, the share of PCR duplicates, the median fragment
  length and the median depth over the reference. Below them, four figures in two rows:
  endogenous DNA before against after filtering beside the preseq complexity curves, then
  the ancient-DNA plane beside the genome fraction curves. Each draws one point or curve
  per library, so the highlights hide the legend and point labels are off on their
  sources. The bar of this section filters by sample and UDG treatment.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (sample, library, UDG treatment) sit in the collapsed left
panel and narrow every tab. The persistent, collapsed `QC thresholds` filter the Qualimap
BamQC summary (mean coverage, duplication rate) and endorS.py (endogenous DNA); both
collections link back to the hub, so a floor narrows the hub and the hub fans the
surviving libraries out. The `Sample sheet` (the library hub) and `Reference tables` (the
BamQC summary the thresholds read) are pinned to the bottom of every child tab, collapsed,
and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read
the tab), then a strip of four key numbers, each card with its own colour and a secondary
that reads it, then at most three open sections; tables, record cards and the optional
branches follow, collapsed.

**MultiQC.** MultiQC panels only, those no tile redraws from a tool table. Open: general
statistics (endorS.py's endogenous DNA included), FastQC sequence counts and the
AdapterRemoval collapsed-read length, then per-base quality and GC content. Collapsed:
adapter content and duplication levels, and the four bcftools panels (substitution types,
quality, indel lengths, depths). Filter: the report's own sample.

**Libraries.** Strip: libraries (split by sample), reads per lane (their spread), reads
sequenced (a funnel to the reads AdapterRemoval kept) and the mapping quality (its
spread). Then the per-library QC profile: the pipeline-local `eager/library_qc.py` recipe
joins the tidied endorS.py, Picard, Qualimap and DamageProfiler collections on the library
id, and a `parallel_coordinates` tile draws one line per library across seven axes, each
rescaled to its range (past seven, the column-name axis titles overlap at full width). Collapsed: the pooled table with the library record beside it, and
the per-lane AdapterRemoval table. Filters: clonality range and lane.

**Read fate.** Strip: reads sequenced (split by trimming outcome), the same reads by final
fate (a ring), the collapse rate and the discard rate per lane. Then one sankey, five
stages, and the reads that fall out at each, its flows coloured by where they end: the pipeline-local `eager/read_fate.py` recipe
chains AdapterRemoval, samtools flagstat and Picard MarkDuplicates, and the accounting is
exact rather than apportioned (AdapterRemoval's identity `2 x total_read_pairs = retained
+ collapsed + discarded` holds per lane, and a library's `retained_reads` equals its
pre-filter flagstat total). Then the lane yield: reads kept and the discard share per
lane, and the collapse rate against the retained length. Collapsed: the fate table.
Filters: final fate and lane. There is no trimming-outcome filter: it would leave the
strip's first card on one outcome.

**Endogenous DNA.** Strip: endogenous DNA before filtering (its spread), after filtering (a
share of 100%), the points lost between them (their distribution) and the reads given to
the mapper (a funnel to those mapped; flagstat scoped to `stage == pre-filter`, because
flagstat has one row per library and stage). Then the before against after scatter, the
on-target signal lost to filtering below the diagonal, and mapped reads per library and
stage. Collapsed: the off-target screen (MaltExtract and Kraken, when the run enabled
them) and the endorS.py and flagstat tables. Filter: endogenous DNA after filtering. There
is no stage filter, for the same reason as on Read fate.

**Complexity.** Strip: the Picard duplication rate (its spread), the reads checked (a
funnel to the unique reads kept), the duplicates removed and the unique reads kept. Then
the screening plane (endogenous DNA against clonality, marker sized by depth), and side by
side the duplication against the unique reads kept and the preseq complexity curves.
Collapsed: the Picard table. Filter: Picard duplication range.

**Authentication.** Strip: C to T at the 5 prime end and G to A at the 3 prime end, the mean
fragment length and the share under the short-fragment cut-off. Then the ancient-DNA plane
(mean length against terminal deamination) beside the fragment length curves, and the
misincorporation profile (`C>T`, `G>A` and the pooled background by position from each read
end). Collapsed: the contamination estimates (ANGSD nuclear contamination and MTNucRatio,
when the run enabled them) and the authenticity, misincorporation and fragment length
tables. Filters: read end, distance from the read end, strand and fragment length.
DamageProfiler 0.4.9 writes no length-binned damage table, so the profile is not split by
length.

**Coverage.** Strip: the mean coverage per library (its spread), the share of the reference
covered at 1X and at 2X (each a share of 100%), and the depth of the sequences of 1 Mb or
more relative to the library mean (their distribution; organelles and unplaced scaffolds
would leave one bar). Then the relative depth against contig length (the quantity a sex
call and an organelle ratio are made from), and side by side the depth histogram and the
share of the reference covered at least X deep, on a log depth axis. There is no per-contig
bar: on a reference with hundreds of scaffolds its axis cannot be read. Collapsed: the
Sex.DetERRmine table (when the run enabled it) and the per-contig and genome fraction
tables. Filters: relative depth and contig length. There is no depth-threshold filter: the
1X and 2X cards would print a dash once it excluded their threshold.

**Locus.** Strip: window depth (its spread), the windows in view (those at 1X or deeper
against the rest), the depth spread within a window and the mapping quality. The four
cards set `follow_region_filter`, so they read the whole reference until a region is
picked, then that region. Then the locus
navigator, a `genome_view` on Qualimap's windows mapped back onto their contigs, and a
`coverage_track` of mean mapping quality under it, from the pipeline-local
`eager/mapq_across_reference.py`. A `region` link carries the navigator's chromosome and
position onto that collection, so a brush or a typed locus moves both tracks and the strip
together. Collapsed: the window table. Filter: window depth; the navigator owns the region.

**Genotypes.** Strip: SNPs called (split by sample), indels, the Ts to Tv ratio and
multiallelic sites. The VCF record count is not a card: a VCF that emits reference sites
counts them as records too. Then SNPs and the Ts to Tv ratio per sample, one bar per
caller. Collapsed: the bcftools summary and TSTV tables. Filter: variant caller.

The locus navigator sets no `default_region`: it opens on the whole reference, since no
contig name holds across references. A non-model reference has no GenomeSpy built-in assembly, so the
contig list comes from the data and there is no gene lane.

## Routes and pruning

eager has no route that prunes a tab: every tab reads collections the default run writes.
The optional branches are `optional: true` collections, each bound to one table tile in a
collapsed section; the import drops a tile whose collection is absent.

| Branch | Where it shows |
|---|---|
| MALT with MaltExtract, Kraken | `Off-target screen` on Endogenous DNA |
| ANGSD nuclear contamination, MTNucRatio | `Contamination` on Authentication |
| Sex.DetERRmine | `Sex determination` on Coverage |

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the UDG
treatments, the read fate at every stage of the sankey, the flagstat stage, the read end
and the substitution classes are written out. eager has no `GROUP_COL`, so there is no
`auto` group colour.

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The pinned sample
sheet selects on `sample_id` and the BamQC reference table on `sample`; the lane table and
the collapse scatter select on `lane_id`; every per-library table and scatter of the
Ancient DNA and Genome tabs selects on `sample`, as do the fragment length and genome
fraction profiles. Not selectable: the complexity curve and depth histogram profiles and
the coverage track, and the raw MaltExtract, Kraken, contamination and Sex.DetERRmine
tables, whose columns are not declared. The screening plane emits a selection, but its
collection has no outgoing link, so it narrows no other tile.

## Reproducing

```bash
bash download_test_data.sh                       # AWS megatest fetch, no input/
mkdir -p ~/Data/depictio-nfcore/eager/2.4.5/megatest/input
cp input/benchmarking_vikingfish.tsv ~/Data/depictio-nfcore/eager/2.4.5/megatest/input/

python -m depictio.dev_scripts.multiqc_reprocess \
  --src ~/Data/depictio-nfcore/eager/2.4.5/megatest \
  --dest ~/Data/depictio-nfcore/eager/2.4.5/megatest

depictio-cli ingest --template nf-core/eager/2.4.5 \
  --data-root ~/Data/depictio-nfcore/eager/2.4.5/megatest --dry-run
```

## Note: the preseq recipe here is pipeline-local, not the shared catalog one

`depictio/catalog/preseq/complexity_curve.py` recovers the library name from the file name
via `depictio.recipes.lib.sample_ids.strip_stage_suffixes`, which strips known
dot-separated stage tokens (`ccurve`, `mkd`, `sorted`, ...). eager's own `preseq lc_extrap`
step writes `<library>.filtered.preseq`: `filtered` and `preseq` are not in that shared
list, so the helper would hand back the file stem unchanged rather than the library id.
Rather than widen a list shared by every other pipeline that reuses it on behalf of one
pipeline's naming, `depictio/projects/nf-core/eager/recipes/complexity_curve.py` matches
eager's fixed suffix directly and keeps the rest of the catalog recipe's contract,
including the `profile` kind's decimation rule (<= 200 points per library, never sampled),
unchanged. The dashboard still binds `use: preseq/complexity_curve`: the output schema is
byte-identical, only the file that produces it differs. eager's own `lc_extrap` run also
wrote no bootstrap confidence interval, so `lower_ci`/`upper_ci`/`ci_width` are present
(the `profile` kind's optional band roles need the columns to exist) but always null.
