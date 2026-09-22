# nf-core/eager 2.4.5: Depictio dashboards

This template turns the output of [nf-core/eager](https://nf-co.re/eager) 2.4.5 into a
single eight-tab Depictio dashboard. eager trims and collapses ancient-DNA reads, maps
them, deduplicates, profiles the misincorporation damage pattern that says whether the DNA
is really ancient, and genotypes what is left. The dashboard follows that chain and adds
the two questions eager answers with optional branches: is this extract contaminated, and
what else is in it.

Data comes from the AWS megatest run `results-42c9d5f8602e5e88fdcec28f194d2cd4cff61c75`
(the 2.4.5 release tag): two Atlantic cod libraries (`COD076E1bL1`, `COD092E1bL1i69`; three
sequencing lanes each), mapped with BWA, deduplicated with Picard MarkDuplicates,
damage-profiled with DamageProfiler and genotyped with GATK HaplotypeCaller.

> **This template reads a REPROCESSED MultiQC report.**
> eager 2.4.5 published MultiQC 1.13.dev0, which writes `multiqc_data.json` and no
> parquet. Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so the MultiQC
> tab is bound to a report this repository generates by re-running the pinned MultiQC 1.35
> over the run's own raw tool outputs. See `VALIDATION_REPORT.md`.

> **The samplesheet is not part of the AWS megatest fetch.**
> Unlike ampliseq or rnaseq, eager's test data carries no `input/` prefix and no
> `pipeline_info/params.json` to recover the `--input` TSV from.
> `input/benchmarking_vikingfish.tsv` here is a hand-reconstructed manifest against the six
> ENA runs the megatest fetched. A real `--data-root` needs it copied to
> `{DATA_ROOT}/input/benchmarking_vikingfish.tsv` by hand; see `VALIDATION_REPORT.md`.

---

## How the dashboard is built

- **One funnel, eight tabs.** MultiQC, then the run and library hub, then read fate, then
  mapping and endogenous DNA and duplication, then damage authentication, then
  contamination and sex, then coverage and genotyping, then metagenomic screening. Each tab
  answers the question the previous one raises: what was sequenced, where every read went,
  how much of the extract is the target organism and how much of that survives, whether the
  damage pattern says the DNA is ancient, whether anything foreign is mixed in, how deep
  the coverage is and what was called from it, and what the off-target remainder is.
- **The library hub is the hub.** `samples` is one row per eager LIBRARY (`Library_ID`,
  the name every downstream file uses once eager has merged its sequencing lanes, not
  `Sample_Name`, which can in principle carry several libraries). A persistent
  `Sample filters` section is pinned to the top of every tab, and the template's links fan
  a pick there out to the MultiQC panels and every per-library table at once. The two
  bcftools collections key on `Sample_Name` instead, because `bcftools stats` reads the
  sample name out of the VCF header rather than the BAM's library id, so the hub carries a
  second filter and the template two extra links on `sample_name`.
- **A four-card glance strip on every tab.** `Run at a glance` is a persistent grid section
  pinned to the top: endogenous DNA, terminal deamination, mean coverage and lanes merged,
  the four numbers an ancient-DNA run is read on. It rides every tab including MultiQC,
  which the MultiQC-only rule exempts pinned persistent sections from. Every other tab
  opens with its own four-card row, always filling the eight-column width.
- **Pinned library sheet and reference metrics.** The library hub sits in a collapsed
  `Sample sheet` section pinned to the top of every tab, and the Qualimap BamQC summary in
  a collapsed `Reference metrics` section pinned to the bottom, next to a collapsed
  `QC thresholds` section holding the coverage, duplication-rate and endogenous-DNA floors.
- **Every tab has its own filters.** Beyond the persistent sample scope, each tab declares
  a local filter section on the factor that tab actually varies over: the terminal C-to-T
  damage window on the MultiQC tab, lane and sequencing run on the hub, trimming and final fate on read fate, filter stage and duplication on
  mapping, read end / position / strand / fragment length on damage, contig and relative
  depth on contamination, contig and position and depth threshold on coverage.
- **Catalog provenance.** 88 of 104 dense tiles (84.6%) carry a `use:` catalog reference.
  The 16 without one are the tiles reading this pipeline's own lane sheet
  (`eager_lane_stats`) and read-fate flow (`eager_read_fate`), plus the library hub itself:
  no catalog module owns a pipeline's own sample sheet, its per-lane trimming ledger, or a
  flow assembled from four different tools' reports, so those stay pipeline-local, the same
  convention every other nf-core template follows.
- **Everything matches on file name, never on directory names.** `deduplication/<library>/`,
  `damageprofiler/<library>_rmdup/`, `qualimap/<library>_rmdup_stats/` and
  `adapterremoval/output/` all encode the library or lane in the PATH eager publishes it
  under, not the file content. No scan regex matches on those directory names; the catalog
  recipes parse them out of `source_path` instead, which is what keeps the template
  portable to eager 3.x, whose directory layout differs.

---

## Reproducing

```bash
bash download_test_data.sh                       # AWS megatest fetch, no input/
# input/benchmarking_vikingfish.tsv is not part of the fetch, copy it by hand:
mkdir -p ~/Data/depictio-nfcore/eager/2.4.5/megatest/input
cp input/benchmarking_vikingfish.tsv ~/Data/depictio-nfcore/eager/2.4.5/megatest/input/

python -m depictio.dev_scripts.multiqc_reprocess \
  --src ~/Data/depictio-nfcore/eager/2.4.5/megatest \
  --dest ~/Data/depictio-nfcore/eager/2.4.5/megatest

depictio-cli run --template nf-core/eager/2.4.5 \
  --data-root ~/Data/depictio-nfcore/eager/2.4.5/megatest --dry-run
```

---

## MultiQC

The landing tab, MultiQC panels only. `MultiQC overview` holds the general statistics
table, including endorSpy's endogenous DNA percentage, which MultiQC never gives its own
panel (it is `generalstats`-only custom content). `Read quality and trimming` holds FastQC
on the raw lanes and AdapterRemoval's retained/discarded/collapsed counts and length
ladder. A high collapse rate here is the expected shape of an ancient-DNA library, where
fragments are usually shorter than the read length, not a warning sign the way it would be
for a modern shotgun run.

## Run and library hub

eager 2.x trims and collapses each sequencing lane on its own, then merges the lanes into a
library before mapping, so the lane is the only samplesheet column of this run with more
than one value, and the AdapterRemoval `.settings` reports are the only per-lane numbers
eager publishes. This tab recovers them: `adapterremoval/settings` parses the
`[Trimming statistics]` block, and the pipeline-local `eager/lane_stats.py` recipe joins it
to the samplesheet on a key rebuilt from the R1 file name plus the `Lane` column, so the
lane, the sequencing run accession and the library each report belongs to all become real
filter factors. The scatter reuses `adapterremoval/collapse_vs_length` with the lane as the
label: within a library, collapse rate and retained length move together; between the two
they separate.

The organism, sequencing type, UDG treatment and strandedness columns are constant across
this run, so no filter or card is spent on them. They stay in the hub table, where a run
that does vary over them can still read them.

## Reads and read fate

One sankey, five stages, and the reads that fall out at each. The pipeline-local
`eager/read_fate.py` recipe chains AdapterRemoval, samtools flagstat and Picard
MarkDuplicates into a single flow, and the accounting is exact rather than apportioned:
AdapterRemoval's own identity `2 x total_read_pairs = retained + collapsed + discarded`
holds per lane, and summed over a library's lanes `retained_reads` equals the pre-filter
flagstat total to the read, so the reports chain without a fudge factor.

Collapsing is an outflow at the trimming step rather than a stage of its own on purpose:
one read of each merged pair stops existing there, and no report says which of the
survivors were merged, so a collapse stage would have to apportion the mapped reads between
collapsed and uncollapsed, which would be invention. Terminal fates are carried forward to
the last column so each flow ends where the read did rather than stopping mid-diagram.

## Mapping, endogenous DNA and duplication

`Endogenous DNA` binds the new `endorspy/endogenous` catalog output, which reads eager's
`*_endogenous_dna_mqc.json` custom-content files directly rather than through MultiQC's
general statistics table. The headline number of an ancient-DNA screen is the fraction of
the mapper's input that placed on the reference; the scatter plots it before against after
the quality filter and deduplication, so the distance below the diagonal is the on-target
signal lost to ambiguous placement and PCR copies.

`Alignment` reads this template's own `samtools/flagstat` output (one row per library, per
filter stage) next to MultiQC's Flagstat panels. A low pre-filter mapped percentage is
normal for sediment or bone extracts, where most recovered DNA is environmental.

`Duplication and complexity` binds the new `picard/markduplicates_metrics` output, which
parses the `## METRICS CLASS` block of eager's `*_rmdup.metrics` files by reading the
header row rather than assuming a column order, next to `preseq/complexity_curve`. Read the
two together: high duplication with a flattened complexity curve means the extract, not the
sequencing, is the limit.

## Damage authentication

The tab this template was built to carry, and the one where two signals are read together
rather than separately. `damageprofiler/authenticity` is a second-order recipe consuming
the tidied misincorporation table and the new `damageprofiler/lgdistribution` output: it
reduces each library to its terminal deamination at both read ends, the substitution
background that rate is read against, and its fragment length statistics. The resulting
plane separates the three cases a single number cannot: short and damaged is ancient, long
and undamaged is modern contamination, and short but undamaged is usually over-sheared
modern material rather than old DNA.

Below it, `damageprofiler/misincorporation` tidies DamageProfiler's per-position,
per-read-end substitution table into one row per `(library, end, position, base_change)`,
keeping `C>T` and `G>A` as their own curves and summing the other twelve substitution types
into `other`, the background they are read against. `damageprofiler/fragment_length_profile`
draws the length distribution itself, one curve per library and strand, normalised so
libraries of different depth are comparable.

## Contamination and sex

This megatest ran with Sex.DetERRmine, MTNucRatio and the ANGSD X-chromosome contamination
estimate disabled, and the reference is Atlantic cod, which has no assembled sex chromosome
to call from anyway. The template declares all three as `optional: true` collections with
the file names the eager output documentation publishes, so a run that enables them ingests
with no template edit; the tab opens with a text tile saying they did not run here.

What is on disk instead is the quantity all three build on. `qualimap/coverage_per_contig`
parses the `Coverage per contig` block of `genome_results.txt` and normalises each contig's
depth by the library's own genome-wide mean, so a sex call (a depth ratio between a sex
chromosome and the autosomes) and a contamination baseline are both one filter away. The
mitochondrion is visible on the scatter as the single sequence around 59 times the nuclear
depth, which is the mitochondrial-to-nuclear ratio MTNucRatio would have reported.

## Coverage and genotyping

`qualimap/coverage_across_reference` is the largest new output here: Qualimap's windowed
depth table, 627 rows per library. Qualimap writes those windows on a single concatenated
axis with no contig column, so the recipe takes an optional second source (the same run's
`genome_results.txt`), builds a running sum of the per-contig lengths and maps each window
back onto the contig it falls in with a per-sample `join_asof`. That is what makes the
contig filter work, and what lets the same table drive both a `coverage_track` and a
`genome_view`, GenomeSpy's chromosome-aware locus axis with native zoom. If the optional
source is missing the recipe falls back to a single pseudo-contig rather than failing.

`Depth distribution` answers what a mean depth cannot: `qualimap/coverage_histogram` is how
many bases sit at each depth, and `qualimap/genome_fraction_coverage` is the share of the
reference covered at least that deep. A library at 0.9X mean could be spread evenly or
piled on a tenth of the genome, and only these two say which.

`Variant calls` binds the `bcftools/stats_summary` and `bcftools/stats_tstv` outputs to the
GATK HaplotypeCaller VCFs eager published but which nothing read before. Both key on
`Sample_Name` rather than `Library_ID`, because `bcftools stats` reads its sample name from
the VCF header. The transition-to-transversion ratio is worth a second look on ancient
data: deamination turns cytosines into thymines, which is a transition, so a caller with no
damage model reads damage as extra real variants.

There is no per-caller dot plot here. This run genotyped with one caller, so a comparison
across callers would have a single column; a run with several would want one, and the
`bcftools/stats_summary` output already carries the `caller` column it would need.

## Metagenomic screening

eager can hand the reads that do not map to the target reference to MALT and MaltExtract,
or to Kraken, to say what else is in the extract. This megatest enabled none of them, so
the MaltExtract authentication heatmap and the Kraken report are declared `optional: true`
with the globs the eager output docs publish, and the tab opens with a text tile saying so.

What it shows instead is the size of the problem: nearly two thirds of each library did not
place on the cod reference, and that off-target fraction is exactly what a screen would
have been given. The two FastQC panels beside it are the only screen this run actually
carries, an unexpected GC peak or a duplication profile that does not match the target
organism being the cheapest hint that something else is in the extract.

---

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
