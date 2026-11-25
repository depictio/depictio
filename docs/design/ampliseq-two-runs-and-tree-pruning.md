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

## 2. A second run with another reference database (done for the taxonomy views)

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
  (Supergroup, Division). The merged lineage keeps SILVA's seven slots: Kingdom = PR2
  Domain, Phylum = `EUK_PHYLUM_RANK` (Subdivision, PR2 level 4), then the next PR2 ranks.
  Metazoa read one rank deeper (Arthropoda, Mollusca ...). The merged Phylum is therefore
  always at collapse level 2, and PR2's own collapsed outputs (ANCOM-BC slices,
  barplots) must be read at level 4 to match it (`pr2_level()`).
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
  rank and confidence, the rel-tables at levels 2 to 6 are identical, and the five
  consumers produce the same frames from the new DC as from the overlay folder.

### Versions

ampliseq 2.18.0 template 1.7.0 to 1.8.0 (pruning: a new DC option and a new order) then
2.0.0 (major: a new DC and new variables, so the project is ingested again). The shared recipes and the qiime2 catalog module (2.2.0) changed, so
ampliseq 2.14.0, 2.16.0, 3.1.0 and `init/catalog_conformance` take a minor bump: their
outputs are unchanged without the new DC.

### What is left (draft issues below)

- **ANCOM-BC and the MA plot keep the DATA_ROOT run's results.** The TREC dashboard offers
  "SILVA" and "PR2" options, read from slices the overlay labelled `.silva.csv` /
  `.pr2.csv`. The ANCOM-BC recipe reads its slices with globs, and a recipe glob cannot
  leave the data root (`Path.glob` refuses an absolute pattern), so the PR2 run's slices
  are out of reach today.
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

Smallest change: a local overlay template that extends a bundled one (draft issue 3).

## Draft issues (not filed)

### 1. [FEATURE] ampliseq: ANCOM-BC and MA plot per reference database with PR2_RESULTS

When `PR2_RESULTS` is set, `ancombc_results` and `ma_canonical` still read only the
DATA_ROOT (SILVA) run. Projects that merged SILVA and PR2 by hand showed both runs' results
side by side, tagged `taxonomy = silva | pr2`, from slices renamed `lfc_slice.silva.csv` /
`lfc_slice.pr2.csv`.

Proposal:
- `qiime2/ancombc.py`: five optional *path* sources for a second run (`lfc_alt` ...; paths,
  not globs: a recipe glob cannot leave the data root) and params `label` / `alt_label`
  (default unset, so other templates are unchanged).
- ampliseq 2.18.0: when `PR2_RESULTS` is set, point them at
  `{PR2_RESULTS}/qiime2/ancombc/differentials/Category-{GROUP_COL}-level-{PR2_PHYLUM_LEVEL}/`,
  with `PR2_PHYLUM_LEVEL` derived from `EUK_PHYLUM_RANK` (`pr2_level()`: Subdivision = 4),
  labels `silva` / `pr2`.
- `ma_canonical`: the PR2 run's `qiime2/barplot/level-{PR2_PHYLUM_LEVEL}.csv` as the
  labelled barplot for the `pr2` rows.
- Alternative: let `SourceOverride.glob_pattern` take an absolute pattern resolved against
  its own folder, which would also serve other two-run templates.

Done when: a project ingested with `PR2_RESULTS` shows both databases' ANCOM-BC results,
with the same taxa and log fold changes as each run's own slices.

### 2. [TASK] ampliseq: taxonomy_composition from the merged taxonomy

`taxonomy_composition` reads QIIME2's barplot (`level-N.csv`, counts plus metadata). With
`PR2_RESULTS` it stays SILVA's. Either collapse counts from the merged table (it would need
the SILVA run's count table, `qiime2/abundance_tables/feature-table.tsv`), or document that
this DC is per run and label its card in the base dashboard. Check first which dashboard
components read it.

### 3. [FEATURE] Extra collections on a template project, kept in a file

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

### 4. [TASK] ampliseq 3.1.0: tree pruning and the PR2 merge

Port `max_tips` (and the metadata-before-tree order) and the `merged_taxonomy` DC to the
3.1.0 template. ampliseq 3.x may name SILVA's top rank `Domain` (`with_kingdom` handles it
in the recipe) and adds per-rank `*_confidence` columns (left out of the merged table).
