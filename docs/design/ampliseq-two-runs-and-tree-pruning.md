# nf-core/ampliseq 2.18.0: large trees and a second reference database at ingest

Status: implemented on branch `feat/ampliseq-template-automation-3ef27b` (template 2.0.0),
not released. Written for the TREC AML 2024 metabarcoding project, whose custom steps
this moves into the template. Nothing in it is specific to that project.

## Why

A marine 18S/16S project runs nf-core/ampliseq twice on the same reads: once against
SILVA 138.2, once against PR2 5.0.0. SILVA leaves most eukaryotes in an unresolved
`Eukaryota;` group, PR2 resolves them, and PR2 knows little about bacteria. Until now
the project needed three manual steps between the pipeline and Depictio:

| TREC step | Manual work | After this branch |
| --- | --- | --- |
| 4. Merge SILVA and PR2 | `bin/build_trec_dualtax.py` writes an overlay folder with regenerated rel-tables | The `merged_taxonomy` DC does it at ingest; the taxonomy views read it |
| 5. Prune the tree | `scripts/prune_newick.py`, run by hand (127,845 to 3,000 tips) | Ingest prunes any tree over `max_tips` |
| 7. Link the pruned tree | `--var TREE_FILE=<pruned tree>` | Not needed |

The ingest then reads the two raw ampliseq output folders as they are:

```bash
depictio ingest results_silva138_2 --template nf-core/ampliseq/2.18.0 \
  --var PR2_RESULTS=/path/to/results_pr2_5_0_0 --var METADATA_FILE=...
```

## 1. Tree pruning at ingest (done)

- `DCPhylogenyConfig.max_tips` (new, default `None` = never prune). When the tree has
  more tips, `process_phylogeny_data_collection` prunes it before the S3 upload to the
  taxa its metadata DC lists (`metadata_dc_tag` / `metadata_taxon_column`, read from that
  DC's Delta table). A tree at or under the threshold is stored byte for byte.
- Why the metadata DC and not a second ranking: the tip-metadata recipe already caps
  itself to the `MAX_TIPS` most abundant ASVs (`top_taxa`). Pruning to its output keeps
  one rule for both, so the tree never holds a tip the metadata lacks.
- No usable metadata (no tag, not ingested, unreadable, no label matches): the tree is
  stored unpruned with a warning, the behaviour before this change.
- The Newick parser and pruner moved from the ampliseq script to
  `depictio/cli/cli/utils/newick.py`. The script stays, as a thin wrapper.
- Template: the tree DC sets `max_tips: 3000` (the recipe's `MAX_TIPS`), and the
  tip-metadata DC is now declared before it. Collections are ingested in declaration
  order, and that order is what makes the metadata table exist when the tree is
  processed. The reference dataset (2,683 tips) is unchanged.
- Checked on the TREC run: the ingest route (recipe output, then prune) gives a tree
  byte-identical to the one pruned by hand, in under a second.

## 2. A second run with another reference database (done)

### Where to merge

- **View time (#1138)** would let a reader switch the PR2 rank in the dashboard. It needs
  dashboard parameters, parameterised computed columns, and advanced visualisations able
  to read them: a feature of its own, not a template change. It stays open; this branch
  does not close it.
- **Multi-run (#1399, done)** is the wrong shape: a run there is a set of samples, stacked
  under `depictio_run_id`. Two taxonomies of the same samples would count every sample
  twice.
- **Ingest time, in a recipe (chosen).** The rule is fixed per project, which is what the
  TREC project does today. The PR2 rank stays a choice (`EUK_PHYLUM_RANK`), made at
  ingest instead of in the viewer.

### What it does

- `depictio/recipes/lib/dual_taxonomy.py` holds the rule, ported from
  `build_trec_dualtax.py`: per ASV, PR2's lineage if PR2's Domain starts with
  `Eukaryota` (organelles such as `Eukaryota:plas` stay separate kingdoms), else
  SILVA's (Bacteria, Archaea, and ASVs neither assigns, so samples still sum to 1).
- **The PR2 rank shift.** PR2 has nine ranks, two more than SILVA above the Phylum
  (Supergroup, Division). The merged lineage keeps SILVA's seven slots (`slot_ranks()`):
  Kingdom = PR2 Domain, Phylum = `EUK_PHYLUM_RANK` (Subdivision, PR2 level 4), Class,
  Order and Family = the PR2 ranks after it, never past PR2's Family, and Genus and
  Species = PR2's Genus and Species, always. Metazoa read one rank deeper (Phylum = PR2
  Class: Arthropoda, Mollusca ...), so their Family slot is empty. The merged Phylum is
  therefore always at collapse level 2, and PR2's own collapsed outputs (ANCOM-BC slices,
  barplots) must be read at level 4 to match it (`pr2_level()`). The full mapping and the
  join are in "Joins and choices" below.
- New DC `merged_taxonomy` (recipe `nf-core/ampliseq/merged_taxonomy.py`): the SILVA run's
  `rel-table-ASV_with-DADA2-tax.tsv` with merged ranks, without sequences, plus
  `taxonomy_source` (`pr2`, `silva`, `fallback`). It reads the PR2 run's table of the
  same name, which carries the same taxonomy as `dada2/ASV_tax.pr2_5_0_0.tsv` under a
  name that does not change with the database version. Abundances come from the SILVA
  run, so the view stays consistent with that run's diversity results.
- The taxonomy recipes take it as an optional `dc_ref` and prefer it to the SILVA files:
  tip metadata, sunburst, sankey, Phylum relative abundance (collapsed at level 2),
  stacked taxonomy (levels 2 to 6). Heatmaps, ComplexHeatmap, UpSet, PCoA and
  Bray-Curtis are built from those and follow.
- Template variables `PR2_RESULTS` (the PR2 run's results folder) and
  `EUK_PHYLUM_RANK`. Without `PR2_RESULTS` the DC is removed and nothing changes.
- Checked on the TREC run: the merged ASV table matches the hand-made overlay on every
  rank and confidence (both with the Metazoa fix of 25/11/2026, below), the rel-tables at levels 2 to 6 are identical, and the five
  consumers produce the same frames from the new DC as from the overlay folder.

### ANCOM-BC and the MA plot of both runs

The hand-made overlay showed ANCOM-BC per database, tagged `taxonomy = silva | pr2`, from
slices it renamed `lfc_slice.silva.csv` / `lfc_slice.pr2.csv`. The template now reads both
runs' own slices:
- `qiime2/ancombc.py` gains five optional *path* sources for a second run (`lfc_alt` ...).
  Paths, not globs: a recipe glob cannot leave the data root (`Path.glob` refuses an
  absolute pattern). Their rows are labelled `alt_label` (`pr2`), and only then do the
  DATA_ROOT run's unlabelled rows take `label`. A single run keeps an empty `taxonomy`, so
  other templates are unchanged.
- `ma_canonical` takes the second run's barplot (`alt_barplot`) for the abundance of the
  `pr2` rows, whose lineages the SILVA composition does not hold.
- ampliseq 2.18.0 points them, under `PR2_RESULTS`, at
  `{PR2_RESULTS}/qiime2/ancombc/differentials/Category-{GROUP_COL}-level-{PR2_PHYLUM_LEVEL}/`
  and `qiime2/barplot/level-{PR2_PHYLUM_LEVEL}.csv`. Two variables are auto-set by the CLI:
  `PR2_PHYLUM_LEVEL` from `EUK_PHYLUM_RANK` (`pr2_level()`, Subdivision = 4), and
  `REF_DB_NAME`, the bare name of the run's first `--dada_ref_taxonomy` (`silva`).
- Two conditional rules now repoint different sources of `ancombc_results` (the
  `PHYLUM_LEVEL` globs and the `PR2_RESULTS` paths). Overrides used to be last-write-wins
  per DC, so the second rule erased the first; they are now applied in rule order, a later
  field winning and `source_overrides` merging by key. Scalar fields keep their old
  precedence (the tree routes rely on it).

### The comparisons ampliseq does not run, and the merged option

ampliseq tests each level of a metadata column against one reference, the alphabetical
first: with three sites, two of the three pairs. The TREC overlay added the third pair
(Naples vs Barcelona) and a third option, ANCOM-BC on the merged taxonomy, with an R rerun
(`make ancombc`). The recipe now computes both at ingest, for any number of levels:
- `depictio/recipes/lib/ancombc.py` runs ANCOM-BC through scikit-bio's port
  (`skbio.stats.composition.ancombc`, the new `stats` extra, pinned 0.7.4), with the
  settings QIIME2's `composition ancombc` uses in ampliseq: counts + 1, taxa present in at
  least 10% of the samples, Holm per contrast, and `conserve` on.
- **`conserve`.** QIIME2's ANCOM-BC widens each standard error by the spread of its
  contrast's bias estimate. scikit-bio computes that spread but adds it only for
  ANCOM-BC2, so the module reads it back (`_estimate_bias_em`, a private function: hence
  the pin) and adds it. Without it the estimates match but the standard errors are smaller
  by a constant per contrast, and more taxa come out significant than in ampliseq's own
  results.
- **Checked against ampliseq on the TREC run:** 5 contrasts (SILVA and PR2 by city, and
  another metadata column) give the same estimates, standard errors and q-values as
  ampliseq's slices (differences under 1e-6) and the same significant taxa. With
  `conserve` off, the same code reproduces the overlay's own R rerun just as closely,
  merged option included.
- `qiime2/ancombc.py` (params `pairwise`, `group_col`) adds, per run, the pairs its slices
  lack, from that run's barplot counts (`counts`, `alt_counts`), named as QIIME2 would
  (`localityNaples_vs_Barcelona`). It first refits the run's own contrasts and **stops the
  ingest** when they do not reproduce the slices (another taxon set, or log fold change,
  standard error or q-value more than 1e-4 apart): a recipe that does not reproduce the
  pipeline must not add comparisons next to it. A second run with only some of its five
  `*_alt` slices also stops it, rather than dropping that run's rows. With a merged taxonomy (`merged_taxonomy` DC plus the
  run's `feature-table.tsv`, summed per merged Kingdom;Phylum, unresolved lineages left
  out) it adds every pair under `taxonomy = merged`. `ma_canonical` takes the merged rows'
  abundance from the same collapsed counts.
- Without scikit-bio installed (a CLI-only install without `[stats]`) the recipe logs a
  warning and loads only the pipeline's contrasts. The server images carry it.
- **A change for the TREC numbers:** the overlay's rerun ran with `conserve` off and no
  library cut, the pipeline's contrasts with ampliseq's settings. Everything is now
  computed with them, so the added pairs and the merged option keep their estimates but
  count fewer significant taxa than the dashboard published before 25/11/2026 (Naples vs
  Barcelona, SILVA: 34 instead of 41). The TREC repository's R script was fixed the same
  day and now gives the same numbers.

### Joins and choices

Every join and every choice the merge and the comparisons make, in one place. The TREC
repository documents the same in `docs/decisions.md`, with two figures (the merge in detail; the ANCOM-BC options, settings and check).

Shares are mean relative abundance over the 85 samples.

| Join | Key | Kind | On the TREC run |
|---|---|---|---|
| SILVA run's ASVs to the PR2 run's taxonomy | ASV ID (md5 of the sequence, the same in both runs: same reads, same denoising) | left, from the SILVA run | all 127,845 found, same sequences. The PR2 run's 7,872 extra ASVs are those SILVA labels chloroplast or mitochondria, which the SILVA run filters out (`exclude_taxa`); they are dropped |
| Merged lineages to the run's `feature-table.tsv` (merged ANCOM-BC, merged MA) | ASV ID, then summed per merged `Kingdom;Phylum` | inner | lineages with no Kingdom or Phylum left out (about 2%) |
| Second run's slices to the SILVA run's | none: rows are stacked, labelled `pr2` | stack | PR2 read at level 4, where its Subdivision is |
| Samples to metadata | sample ID | as for one run | 85 samples everywhere |

| Choice | Rule | Why, and what it costs |
|---|---|---|
| Which database names an ASV | PR2 if its Domain starts with `Eukaryota` (organelles included), else SILVA if Bacteria or Archaea, else SILVA as it is (`fallback`) | Each database where it is strong. TREC: 57,520 / 69,852 / 473 ASVs |
| Confidence threshold on PR2's call | none | Domain disagreements are about 0.5% (317 ASVs Bacteria or Archaea for SILVA and nuclear Eukaryota for PR2, 0.29%, PR2 confidence median 0.63). Worth an option if another project shows more |
| PR2 ranks in SILVA's seven slots | `slot_ranks()`, above. Metazoa one rank deeper (`DEEPEN`) | Until 25/11/2026 Metazoa were read one slot off (Family held a genus, Genus a species): the Metazoa, 32.5% of TREC abundance, at genus and species level. Fixed here and in `build_trec_dualtax.py`; the tests pin the copepod lineage |
| What "Phylum" is per option | `silva`: SILVA Phylum; `pr2`: PR2 Subdivision (bacteria too, e.g. `Proteobacteria_X`); `merged`: SILVA Phylum for prokaryotes, PR2 Subdivision for eukaryotes, PR2 Class for Metazoa | Names compare across options only for eukaryotes (pr2, merged) or prokaryotes (silva, merged) |
| Organelles | ampliseq's default `--exclude_taxa mitochondria,chloroplast` matches SILVA labels only | PR2 run keeps them (9.9%, 20 of its 98 ANCOM-BC taxa at level 4); merged keeps PR2-labelled ones the SILVA run let through (0.26%) |
| Abundances of the merged view | the SILVA run's tables | consistent with that run's diversity results |
| ANCOM-BC settings | ampliseq 2.18.0 `conf/modules.config`: `prv_cut` 0.1, `lib_cut` 500, `conserve` on, Holm per contrast, q < 0.05, pseudocount 1, reference = the alphabetical first level | what the pipeline's own contrasts use; the recipe refuses to add comparisons if it does not reproduce them |
| MA plot A axis | mean log10(count + 1) over the samples where the taxon is present | zeros are not in the composition table. Rare taxa sit higher than a mean over all samples would put them |

### Versions

ampliseq 2.18.0 template 1.7.0 to 1.8.0 (pruning: a new DC option and a new order) then
2.0.0 (major: a new DC and new variables, so the project is ingested again). The shared recipes and the qiime2 catalog module (2.2.0) changed, so
ampliseq 2.14.0, 2.16.0, 3.1.0 and `init/catalog_conformance` take a minor bump: their
outputs are unchanged without the new DC.

### Tested on a local instance

`depictio local up` on this branch, with the TREC run:
- **Ingest:** the raw SILVA folder plus `PR2_RESULTS`, with no `TREE_FILE`, took 80 s. A second ingest with `--update-config` kept every ID.
- **Upgrade path:** a project built the old way on 1.24.0 (overlay folder and `TREE_FILE`) was re-ingested the new way. The two were compared table by table:
  - 20 tables and the tree are identical;
  - `ancombc_results` and `ma_canonical`: the `silva` rows (66 taxa) and the `pr2` rows (98
    taxa) are identical to the overlay's, every value, for the two contrasts ampliseq ran.
  - The pairs and the option the overlay got from its R rerun are back, computed at
    ingest: all three options (`silva`, `pr2`, `merged`) by all three contrasts, with the
    overlay's row counts and its estimates (log fold changes within 1e-8). Only their
    standard errors are wider (`conserve`, above), so fewer taxa are significant: Naples
    vs Barcelona 34 instead of 41 (SILVA), 32 instead of 34 (PR2); merged 39, 55 and 55
    instead of 46, 67 and 64. `ma_canonical`: 837 rows, the same intensities.
- **The TREC dashboard on the new project:** every tab renders. Differential abundance opens on the merged option and shows the three options and the three comparisons in the browser (volcano, cards, MA).
- **Render checker:** `scripts/check_deployment.py` reports three `DC_NOT_REGISTERED` on `matrix_dc_id`. Those are false positives, already there before this branch: the field is deprecated, the viewer does not read it, and the three heatmaps render in the browser.

### What is left (draft issues below)

- **A second-run option in the abstract.** The `*_alt` sources serve one extra run. Letting
  `SourceOverride.glob_pattern` take an absolute pattern resolved against its own folder
  would serve any number, and other two-run templates.
- **`taxonomy_composition`** reads QIIME2's barplot counts, which the merged table (relative
  abundances) does not carry. It stays SILVA's, as it was with the overlay.
- **A server-side ingest** (ingest worker, Data refresh) reads `PR2_RESULTS` only when the
  folder is one the server's data policy allows. A CLI ingest reads it as it is.
- If `merged_taxonomy` fails, the ingest reports it as failed, but its readers fall back to
  the SILVA tables (an optional `dc_ref` that cannot be read is `None`). Worth a stricter
  rule later: required when `PR2_RESULTS` is set.
- ampliseq 3.1.0 has the same tree DC and recipes; it gets neither `max_tips` nor the
  merge here (the brief was 2.18.0).

## 3. Extra tables on a template project (investigated, no code change)

TREC steps 2 and 9 add a CTD sensor table to the ampliseq project and use it in the
dashboard. Adding the table is no longer blocked in the app:

- Since v1.21.0 the project page's **Add data** button (`AddDataModal`) adds uploaded files,
  or the tables of a folder, to any project, template-built ones included, with link
  suggestions. Each lands in a workflow of its own.
- `PUT /projects/update` merges with the stored document (`merge_project_workflows`): a
  later `depictio ingest --update-config` keeps a workflow or DC the payload omits. A
  table added in the app survives re-ingestion of the template.

So the CTD table can be added to the TREC project today, and the dashboard edited in the app
to use it. What is still missing is a **scripted** route, kept in Git with the project:

- `depictio ingest --template` resolves only the template's collections; no CLI command
  adds a table to an existing project;
- a local template (`depictio template export`, then `--template <dir>`) works but forks
  the whole template, which then misses every later fix;
- a table added in the app must be added again whenever the project is created anew (a new
  instance, new IDs).

Smallest change: a local overlay template that extends a bundled one (draft issue 2).

## Draft issues (not filed)

### 1. [TASK] ampliseq: taxonomy_composition from the merged taxonomy

`taxonomy_composition` reads QIIME2's barplot (`level-N.csv`, counts plus metadata). With
`PR2_RESULTS` it stays SILVA's. Either collapse counts from the merged table (it would need
the SILVA run's count table, `qiime2/abundance_tables/feature-table.tsv`), or document that
this DC is per run and label its card in the base dashboard. Check first which dashboard
components read it.

### 2. [FEATURE] Extra collections on a template project, kept in a file

A template project takes extra tables in the app (Add data), but not from a file kept with
the project. Proposal: a local template that extends a bundled one:

```yaml
template:
  extends: nf-core/ampliseq/2.18.0
  template_id: local/trec-aml-2024
  version: 1.0.0
data_collections:      # appended to the base template's workflow
  - data_collection_tag: ctd_profiles
    config: {type: Table, scan: {mode: single, scan_parameters: {filename: "{CTD_FILE}"}}}
links: [...]           # appended to the base template's links
```

`resolve_template_config` loads the base, appends the collections and links, merges the
variables (the overlay's win), and resolves recipes and dashboards from the base. CLI only,
like `--template <dir>` today. Tags must not clash with the base template's.

Done when: `depictio ingest <dir> --template ./trec-template` creates the ampliseq project
with the CTD table and its links, and a second ingest with `--update-config` keeps both.

### 3. [TASK] ampliseq 3.1.0: tree pruning and the PR2 merge

Port `max_tips` (and the metadata-before-tree order) and the `merged_taxonomy` DC to the
3.1.0 template. ampliseq 3.x may name SILVA's top rank `Domain` (`with_kingdom` handles it
in the recipe) and adds per-rank `*_confidence` columns (left out of the merged table).
