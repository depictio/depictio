# nf-core/eager 2.4.5: Depictio dashboards

This template turns the output of [nf-core/eager](https://nf-co.re/eager) 2.4.5 into a
single five-tab Depictio dashboard. eager maps ancient-DNA reads, deduplicates them,
profiles the misincorporation damage pattern that says whether the DNA is really ancient,
and genotypes what is left. The dashboard follows that chain: sequencing and trimming QC,
then mapping and duplication, then coverage and library complexity, then the damage
signature itself, then the genotypes called from it.

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
> `pipeline_info/params.json` to recover the `--input` TSV from. `input/benchmarking_vikingfish.tsv`
> here is a hand-reconstructed manifest against the six ENA runs the megatest fetched. A real
> `--data-root` needs it copied to `{DATA_ROOT}/input/benchmarking_vikingfish.tsv` by hand ,
> see `VALIDATION_REPORT.md`.

---

## How the dashboard is built

- **One funnel, five tabs.** MultiQC, then Mapping & duplication, then Coverage &
  complexity, then Damage authentication, then Genotyping. Each tab answers the question
  the previous one raises: did the reads trim and collapse cleanly, how many placed and how
  many were PCR duplicates, how much of the genome they cover and how much more sequencing
  would still buy, whether the misincorporation pattern at the read ends says the DNA is
  ancient, and what GATK called from what survived.
- **The library hub is the hub.** `samples` is one row per eager LIBRARY (`Library_ID`,
  the name every downstream file uses once eager has merged its sequencing lanes, not
  `Sample_Name`, which can in principle carry several libraries). A persistent
  `Sample filters` section (library, UDG treatment) is pinned to the top of every tab, and
  the template's links fan a pick there out to the MultiQC panels and every per-library
  table at once.
- **Pinned library sheet and reference metrics.** The library hub sits in a collapsed
  `Sample sheet` section pinned to the top of every tab, and the Qualimap BamQC summary in a
  collapsed `Reference metrics` section pinned to the bottom, next to a collapsed
  `QC thresholds` section holding the coverage and duplication-rate floors.
- **Damage tab carries a selection forward.** Picking a library on the misincorporation
  profile (or its table) narrows the coverage and complexity tables on the previous tab
  through the project links, so a viewer can immediately check whether a library with a
  strong damage signature also has the depth to back a genotype call.
- **Catalog provenance.** 36 of 38 dense tiles (94.7%) carry a `use:` catalog reference: this
  template's own `samtools/flagstat`, `qualimap/bamqc_genome_results` and
  `damageprofiler/misincorporation` outputs it owns, the reused `preseq/complexity_curve`
  recipe (see the note below), and `multiqc/<module>` for every MultiQC panel. The two
  without one are the library-hub card and table, no catalog module owns a pipeline's own
  sample sheet, the same convention every other nf-core template follows.
- **`damage_profile` is a lot-2 kind.** The misincorporation tile
  (`use: damageprofiler/misincorporation`, `kind: damage_profile`) binds a kind added in the
  same lot as this template. If the advanced-viz models land after this template merges, that
  one `use:` may fail model validation until they do, see `VALIDATION_REPORT.md`.
- **Everything matches on file name, never on directory names.** `deduplication/<library>/`,
  `damageprofiler/<library>_rmdup/` and `qualimap/<library>_rmdup_stats/` all encode the
  library in the PATH eager publishes it under, not the file content, three of the four
  catalog recipes this template uses parse that path rather than the file's own text (see
  each recipe's docstring). No scan regex matches on those directory names; only the
  recipes read them.

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

## MultiQC

The main tab. `Run at a glance` holds the general statistics table only, including
endorSpy's endogenous DNA percentage, which MultiQC never gives its own panel (it is
`generalstats`-only custom content). `Read quality and trimming` holds FastQC on the raw
lanes and AdapterRemoval's retained/discarded/collapsed counts and length ladder. A high
collapse rate here is the expected shape of an ancient-DNA library, where fragments are
usually shorter than the read length, not a warning sign the way it would be for a modern
shotgun run.

## Mapping & duplication

`Alignment` reads this template's own `samtools/flagstat` output (one row per library,
per filter stage) next to MultiQC's own Flagstat panel: a low pre-filter mapped percentage
is normal for sediment or bone extracts, where most DNA recovered is environmental.
`Duplication` reads MultiQC's Picard Mark Duplicates panel plus the duplication rate
Qualimap independently estimates.

## Coverage & complexity

`Genome coverage` reads `qualimap/bamqc_genome_results`: mean depth, mapping quality, GC
content and duplication, next to MultiQC's own coverage-histogram, cumulative-coverage and
GC-content panels. `Library complexity` binds `preseq/complexity_curve` to the `profile`
kind, see the note below on why the recipe that feeds it is pipeline-local rather than the
shared catalog one.

## Damage authentication

The one tab this template was built to carry. `damageprofiler/misincorporation` tidies
DamageProfiler's per-position, per-read-end substitution table into one row per
`(library, end, position, base_change)`, keeping `C>T` and `G>A`: the two deamination
signatures ancient DNA is read by, as their own curve and summing the other twelve
substitution types into `other`, the background they are read against. The `damage_profile`
advanced-viz tile draws both ends; the line figure below it pools libraries and ends for a
second read of the same signal; the MultiQC panels show DamageProfiler's own version of the
same two curves.

## Genotyping

bcftools stats over the GATK HaplotypeCaller VCFs, MultiQC panels only. This template does
not bind a `bcftools/stats_*` table: those catalog outputs belong to nf-core/sarek (see the
ownership split recorded in this pipeline's planning notes), and this template only
references, never creates, another pipeline's catalog tool.

---

## Note: the preseq recipe here is pipeline-local, not the shared catalog one

`depictio/catalog/preseq/complexity_curve.py` recovers the library name from the file name
via `depictio.recipes.lib.sample_ids.strip_stage_suffixes`, which strips known
dot-separated stage tokens (`ccurve`, `mkd`, `sorted`, ...). eager's own `preseq lc_extrap`
step writes `<library>.filtered.preseq`: `filtered` and `preseq` are not in that shared
list, so the helper would hand back the file stem unchanged rather than the library id.
Rather than widen a list shared by every other pipeline that reuses it on behalf of one
pipeline's naming, `depictio/projects/nf-core/eager/recipes/complexity_curve.py` matches
eager's fixed suffix directly and keeps the rest of the catalog recipe's contract ,
including the `profile` kind's decimation rule (<= 200 points per library, never sampled) ,
unchanged. The dashboard still binds `use: preseq/complexity_curve`: the output schema is
byte-identical, only the file that produces it differs. eager's own `lc_extrap` run also
wrote no bootstrap confidence interval, so `lower_ci`/`upper_ci`/`ci_width` are present
(the `profile` kind's optional band roles need the columns to exist) but always null.
