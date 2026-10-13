# Binding `phylogenetic` to a catalog output: investigation

Question asked: the `phylogenetic` advanced-viz kind exists end to end (Pydantic
config, canonical schema, React renderer, API endpoint) but no catalog output
declares it, so it is only reachable by hand-writing dashboard YAML. What would
it take to bind it to a real catalog output from the nf-core templates in this
lot (airrflow 5.1.0, taxprofiler 2.0.1)?

**Verdict up front: neither candidate is viable. Do not bind the kind in this
lot.** Details, evidence and the structural blocker are below.

Everything marked *unverified* was not opened with a command on this machine.

---

## 1. The kind's real data contract

### 1.1 It is two data collections, not one

`PhylogeneticConfig` (`depictio/models/components/advanced_viz/configs.py:598`):

| field | required | meaning |
| --- | --- | --- |
| `tree_wf_id` | yes | workflow id of the **phylogeny** DC |
| `tree_dc_id` | yes | data-collection id of the **phylogeny** DC |
| `tree_dc_tag` | no | portable alternative, rewritten to ids at import |
| `metadata_wf_id` / `metadata_dc_id` / `metadata_dc_tag` | no | the **table** DC holding tip annotations |
| `taxon_col` | default `"taxon"` | metadata column that joins to tip labels |
| `color_col`, `label_col`, `extra_color_cols`, `category_palettes` | no | tip colouring / labelling |
| `default_layout`, `ladderize`, `show_metadata_strip`, `show_branch_lengths`, `show_internal_labels` | no | display defaults |

`tree_wf_id` and `tree_dc_id` are `Field(...)`: mandatory, no default.

### 1.2 A Newick file, not a tidy edge/node table

The tree half is a **file**, ingested as a DC of `type: "phylogeny"`
(`depictio/models/models/data_collections_types/phylogeny.py:20`, `DCPhylogenyConfig`):
`format: newick | nexus`, `ladderize`, `metadata_dc_tag`, `metadata_taxon_column`,
`tip_label_strategy`. There is no column schema, because there is no table.

It is served as raw text by
`GET /depictio/api/v1/advanced_viz/phylogeny/{data_collection_id}/newick`
(`depictio/api/v1/endpoints/advanced_viz_endpoints/routes.py:1414`, returns
`PlainTextResponse`). The endpoint resolves the file from `files_collection`,
falling back to the project document's
`config.scan.scan_parameters.filename`, then to the `/app` container rewrite.

`CANONICAL_SCHEMAS["phylogenetic"]` (`schemas.py:115`) is therefore
`{"taxon": _STRING}` and nothing else, with the comment saying so explicitly:
it validates the *metadata* DC only. `schemas.py:737` adds the hard structural
gate `_KIND_REQUIRES_DC_TYPE = {"phylogenetic": "phylogeny"}`, so the runtime
suggester will not recommend the kind for anything that is not a phylogeny DC.

### 1.3 What the renderer actually consumes

`packages/depictio-react-core/src/components/advanced_viz/PhylogeneticRenderer.tsx`
(2196 lines). Two independent fetches, neither of which is the component's own
bound DC:

1. `fetchPhylogenyNewick(config.tree_dc_id)` (line 279), raw Newick text, parsed
   client-side by `./phylo/newick`. Guarded at line 269:
   `if (!config.tree_dc_id) { setError('Phylogenetic: missing tree DC binding') }`.
2. `fetchAdvancedVizData({ wfId: config.metadata_wf_id, dcId: config.metadata_dc_id, columns: [...] })`,
   only when **both** metadata ids are present (line ~296). Columns projected are
   `taxon_col`, `color_col`, `label_col` and every entry of `extra_color_cols`.
   `fetchUniqueValues(config.metadata_dc_id, colorCol)` is called separately to
   pin a stable colour universe.

So: a Newick string plus a tip-keyed table. Never an edge list, never a node
table, never a nested JSON tree.

---

## 2. How the existing phylogeny is wired today

Two places in the repo, both wired by hand in project/template YAML plus
dashboard YAML. Neither goes through the catalog.

### 2.1 `init/advanced_viz_showcase` (synthetic demo)

- `depictio/projects/init/advanced_viz_showcase/project.yaml:423` declares DC
  `bacterial_tree`, `config.type: "phylogeny"`, `scan.mode: single`,
  `filename: .../data/bacterial_tree.nwk`,
  `dc_specific_properties: {format: newick, ladderize: true, metadata_dc_tag: bacterial_metadata, metadata_taxon_column: taxon}`.
- Sibling DC `bacterial_metadata` (`:439`) is a plain `type: "Table"` TSV with
  `taxon / group / habitat / genome_size_mb / resistance_profile`.
- The file exists: `depictio/projects/init/advanced_viz_showcase/data/bacterial_tree.nwk`,
  703 bytes, first bytes
  `(((((Escherichia_coli:0.02,Salmonella_enterica:0.03):0.04,Klebsiella_pneumoniae:0.05):0.02,…`.
- The tile is declared in `dashboards/phylogeny.yaml:43` with
  `viz_kind: 'phylogenetic'` and an explicit `config:` block.

### 2.2 nf-core/ampliseq (the real precedent)

- Tree DC, `depictio/projects/nf-core/ampliseq/2.18.0/template.yaml:626`
  (2.16.0 has the twin at `:600`): tag `phylogenetic_tree_canonical`,
  `optional: true`, `type: "phylogeny"`, `scan.mode: single`,
  `filename: "{DATA_ROOT}/qiime2/phylogenetic_tree/tree.nwk"`,
  `format: newick`, `metadata_dc_tag: phylogenetic_tree_metadata_canonical`,
  `metadata_taxon_column: taxon`.
- Metadata DC, same file, tag `phylogenetic_tree_metadata_canonical`:
  a `type: "Table"`, `source: "transformed"` DC produced by recipe
  `nf-core/ampliseq/tree_metadata_canonical.py`. Its declared output schema is
  `taxon` (ASV hash matching tip names), `Kingdom … Species`, `confidence`,
  `label`, `dominant_habitat`.
- Because the QIIME2 tree can be far larger than the renderer tolerates,
  `depictio/projects/nf-core/ampliseq/scripts/prune_newick.py` cuts `tree.nwk`
  to the ASVs the metadata recipe keeps, and the run passes
  `--var TREE_FILE=<pruned>`. Tips and metadata rows are kept in step by a
  selection function shared between the recipe and the pruner.
- The tile lives in `depictio/projects/nf-core/ampliseq/2.18.0/dashboards/base.yaml:2346`:
  `viz_kind: phylogenetic`, `data_collection_tag: phylogenetic_tree_canonical`,
  and a config block naming both DCs by tag plus
  `taxon_col: taxon`, `color_col: Phylum`, `default_layout: circular`,
  `extra_color_cols: [Kingdom … Species, dominant_habitat]`.
- Real evidence the tree exists for that pipeline:
  `~/Data/depictio-nfcore/ampliseq/2.16.0/run_16s_pe/qiime2/phylogenetic_tree/tree.nwk`,
  2522 bytes, first bytes
  `((1304d0f9dc2397bbf02e61577a2f5adc:0.275247608,((906a06fc904a9a11c50b0a100467961b:0.144882998,…`
  (ASV hashes as tip labels, real branch lengths, bootstrap supports on internal nodes).

### 2.3 What the catalog has today

`depictio/catalog/qiime2/tree_metadata.yaml` is the **metadata half only**:
`find: { path_glob: "**/qiime2/taxonomy/taxonomy.tsv" }`,
`recipe: nf-core/ampliseq/tree_metadata_canonical.py`, fixture `tree_metadata.tsv`,
and `renders_as` of two cards plus a table. It deliberately does **not** declare
a `phylogenetic` render. Nothing anywhere in `depictio/catalog/` declares
`kind: phylogenetic`; the only occurrences of the word are the enum in
`output.schema.json:89` / `catalog.schema.json:225` and a prose mention in
`SCHEMA.md:137`.

---

## 3. The structural blocker (applies to every candidate)

Even given a perfect Newick file, the catalog **cannot express this binding
today**. Three independent reasons:

1. **A catalog render binds exactly one DC.** `CatalogOutput` is one file, one
   optional recipe, one fixture, and a list of `Render`s whose only column
   handle is `roles`. There is no field for a second data collection, so there
   is nowhere to put the tree DC when the render is authored on the metadata
   table, and nowhere to put the metadata DC when the render is authored on the
   tree.
2. **The config blob builder has no notion of the tree fields.** Backend:
   `depictio/catalog/payload.py:237 _advanced_viz_config_and_data` builds
   `{"viz_kind": kind}` plus one `<role>_col` per declared role, and nothing
   else. Frontend: `depictio/viewer/src/builder/advanced_viz/configBlob.ts`
   `buildAdvancedVizConfigBlob` does the same; grepping the whole builder tree
   for `tree_dc_id` / `tree_wf_id` returns zero hits. So a catalog-composed
   `phylogenetic` component would persist a config with no `tree_dc_id`, and the
   renderer would hit its line-269 guard and print
   "Phylogenetic: missing tree DC binding".
3. **The picker would not offer it on the right DC anyway.** DC-to-output
   matching (`depictio/api/v1/endpoints/catalog_endpoints/routes.py:60-104`) has
   a raw lane (fnmatch on basename / path glob) and a recipe lane
   (`recipe == output.recipe`). A `find: { filename: "tree.nwk" }` output would
   match the phylogeny DC in the raw lane, so the offer could appear, but the
   render it offers is the one that cannot be configured (point 2), and
   `CatalogOutput` would have to carry no `columns`, no `recipe` and no
   `fixture` (allowed only for binding-less renders, `catalog.py:504`), which
   also means `catalog validate` and the offline preview can ground nothing.

Any real binding therefore needs a model change first: a way for a `Render` to
name a companion DC (by tag), plus config-blob support for `tree_dc_tag` /
`metadata_dc_tag` on both the Python and TS sides. That is a separate,
cross-cutting PR touching `catalog.py`, `output.schema.json`, `payload.py` and
`configBlob.ts`. It is out of scope for a lot that adds renderers.

---

## 4. Candidate A: airrflow 5.1.0 clonal lineage trees

### Verdict: NOT VIABLE. The data is not on disk.

Full inventory of `~/Data/depictio-nfcore/airrflow/5.1.0/megatest/`: **36 files,
all TSV/JSON/YAML/parquet.** Zero `.nwk`, `.newick`, `.tre`, `.tree`, `.nex`,
`.graphml`. A `find` across the entire `~/Data/depictio-nfcore` tree for those
extensions returns only ampliseq's QIIME2 trees, taxprofiler's ganon reports,
viralrecon lineage databases and pynndescent numba caches. Nothing from airrflow.

Everything under `clonal_analysis/`, with real sizes:

| path (relative to `megatest/`) | bytes |
| --- | --- |
| `clonal_analysis/find_threshold/all_reps_dist_report/tables/all_reps_threshold-mean.tsv` | 10 |
| `clonal_analysis/find_threshold/all_reps_dist_report/tables/all_reps_threshold-summary.tsv` | 290 |
| `clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables/clonal_abundance.tsv` | 17 477 913 |
| `clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables/clonal_diversity.tsv` | 51 031 |
| `clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables/clonal_overlap.tsv` | 201 122 |
| `clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables/clone_sizes_table.tsv` | 2 872 646 |
| `clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables/num_clones_table.tsv` | 577 |

Their headers (first line, verbatim):

- `clonal_diversity.tsv`: `sample_id  q  d  d_sd  d_lower  d_upper  e  e_lower  e_upper  subject_id`
- `num_clones_table.tsv`: `sample_id  subject_id  sequences  number_of_clones  clone_size_count_min  clone_size_freq_min  clone_size_count_median  clone_size_freq_median  clone_size_count_max  clone_size_freq_max`
- `clonal_overlap.tsv`: `subject_id  sampleA  sampleB  overlap_clone_id`
- `all_reps_threshold-summary.tsv`: `fields  model  cutoff  loglk  threshold  sensitivity  specificity  pvalue  mean_threshold`

None of these is a tree. `clonal_overlap.tsv` is a pairwise sample overlap
count, not an edge list of a lineage.

### Was a tree ever built?

Yes, but it was never fetched.

- `megatest/pipeline_info/params.json` has `lineage_trees: true`,
  `lineage_tree_builder: "raxml"`, `lineage_tree_exec: "/usr/local/bin/raxml-ng"`.
- `depictio/projects/nf-core/airrflow/5.1.0/pipeline_info/software_versions.yml:25`
  records `DOWSER_LINEAGES: {dowser: "2.4.1", enchantr: "0.1.25"}`, so the
  lineage-building process really ran in that megatest.
- The local mirror is a deliberate subset. `depictio/projects/nf-core/airrflow/5.1.0/megatest.yaml`
  describes itself as "the tables-only subset of it that the template recipes
  and MultiQC need" and its `keys:` list contains no tree path. Its
  "Deliberately NOT fetched" note names `clonal_abundance.tsv`,
  `Table_sequences_assembly.tsv`, `parsed_logs/Table_all_details_*`,
  `report_file_size/` and `vdj_annotation/*/*_db-pass.tsv`. Lineage trees are
  not mentioned at all, in either list.
- `VALIDATION_REPORT.md` for airrflow mentions no lineage output either.

**Unverified:** whether `s3://nf-core-awsmegatests/airrflow/results-e69d49e3…/`
publishes Dowser's trees, under what path, and in what format (Dowser's own
output is an R object; airrflow's published artefacts for it were not inspected
and nothing was downloaded). Confirming that would need a bucket listing, which
this investigation did not perform.

### Even if the file were fetched

Airrflow lineage trees are *per clone*: one small tree per clonal lineage, and a
megatest repertoire has thousands of clones. The kind renders **one** tree per
tile with **one** tip-metadata table. A per-clone corpus needs either a clone
picker inside the tile (the renderer has no such control) or one tile per clone
(absurd at this scale). So this is not just a missing file: the shape does not
match the kind's one-tree contract either.

---

## 5. Candidate B: taxprofiler 2.0.1 taxonomy

### Verdict: NOT VIABLE, and it would be a misuse of the kind.

Two separate objections. Either alone is disqualifying.

### 5.1 The data does not carry a lineage

The premise that "taxpasta output carries taxonomy_id and lineage" is **false
for this run**. Every file in `megatest/taxpasta/` is a wide
`taxonomy_id` + one count column per sample table, with no name, rank or lineage
column. Parsed with Python (tab-split), `taxpasta/kraken2_kraken2-db.tsv`
(6102 bytes) is 4 columns:

```
['taxonomy_id',
 'MOCK_002_Illumina_Hiseq_3000_kraken2-db.kraken2.kraken2.report',
 'MOCK_001_Illumina_Hiseq_3000_kraken2-db.kraken2.kraken2.report',
 'MOCK_003_Illumina_Hiseq_3000_kraken2-db.kraken2.kraken2.report']
['0', '19891', '16028', '51984']
['1', '0', '0', '0']
['131567', '0', '0', '1']
```

`metaphlan_metaphlan3-db.tsv` (6472 bytes) and `bracken_bracken-db.tsv` are the
same shape. The repo already knows this: `depictio/catalog/taxpasta/profiles.py`
says in its docstring "taxpasta only emits `name` / `rank` columns when the
pipeline passed `--add-name` / `--add-rank`; when it did not, an optional
`names` source … fills them in", and
`depictio/projects/nf-core/taxprofiler/recipes/taxon_names.py` exists precisely
to harvest `taxonomy_id → (name, rank)` back out of the kraken2 / krakenuniq /
centrifuge `*.report.txt` files (9 such files present on disk). Rank, not
lineage, and no branch lengths anywhere.

The one file that does carry a lineage path is ganon's report, and it is not
Newick despite the extension:
`megatest/ganon/ganon-db/MOCK_001_Illumina_Hiseq_3000_ganon-db.ganon_report.tre`,
22 811 bytes, tab-separated, first lines:

```
unclassified	-	-	unclassified	0	0	0	25477	5.60923
root	1	1	root	0	0	428721	428721	94.39077
superkingdom	2	1|2	Bacteria	0	0	334347	334347	73.61261
superkingdom	2157	1|2157	Archaea	0	0	94374	94374	20.77816
phylum	28890	1|2157|28890	Euryarchaeota	0	0	82168	82168	18.09079
```

Columns are rank, taxid, pipe-delimited taxid lineage, name, then counts. It is
a taxonomy report table. Building Newick from it would mean the repo writing a
tree serialiser for a structure that has no branch lengths.

### 5.2 A taxonomy is not a phylogeny

Even with a perfectly reconstructed NCBI lineage, every branch length would be
1, or arbitrary, or absent. The renderer's whole point is metric structure:
`show_branch_lengths` defaults to `true`, `BRANCH_LABEL_MAX = 20` ranks branches
by length to decide which to annotate, and the radial / diagonal layouts place
tips by cumulative branch length. Feeding it a rank hierarchy produces a
uniform comb that says nothing the existing views do not already say better.

And those views already exist and are already bound in the catalog:

- `depictio/catalog/taxpasta/profiles.yaml` binds `kind: stacked_taxonomy` with
  `roles: {sample_id: sample, taxon: name, rank: rank, abundance: rel_abundance}`.
- `depictio/catalog/qiime2/sunburst_canonical.yaml` is the hierarchical view for
  rank columns.
- `depictio/catalog/taxpasta/matrix.yaml` binds `complex_heatmap`,
  `presence.yaml` binds `upset_plot`, `embedding.yaml` binds `embedding`.

Binding `phylogenetic` here would add a worse duplicate of `sunburst`, on
fabricated branch lengths, and would put a "Phylogenetic tree" label on
something that is not a phylogeny. That is the misuse the question asked about,
and the answer is yes, it would be one.

---

## 6. Recommendation

**Do not bind `phylogenetic` to a catalog output in this lot.** No recipe spec
and no `renders_as` block are given, because neither candidate earns one and
writing a plausible-looking spec against absent data would be exactly the
fabrication this investigation was asked to avoid.

If the kind is to gain a catalog binding later, the honest order of work is:

1. **Unblock the model.** A `Render` needs a way to name a companion DC by tag
   (the two-DC problem, section 3.1), and both config-blob builders need to emit
   `tree_dc_tag` / `metadata_dc_tag` (section 3.2). Until then no catalog
   binding of this kind can render, whatever the data.
2. **Bind the pipeline that already has a real tree.** ampliseq is the only
   template in the repo with a genuine phylogeny on disk and a working
   hand-wired tile. The catalog already carries the metadata half
   (`qiime2/tree_metadata.yaml`); the missing piece is a tree-side output
   whose `find` is `**/qiime2/phylogenetic_tree/tree.nwk` and whose render
   names `qiime2_tree_metadata` as its companion. That becomes writable the
   moment step 1 lands, and it needs no new data.
3. **Revisit airrflow only after a bucket listing** confirms what, if anything,
   `DOWSER_LINEAGES` publishes, and after deciding how a per-clone corpus of
   trees would be presented in a single tile. Both are open questions, not
   details.

Candidate B should not be revisited at all: taxprofiler's data is a taxonomy,
and the taxonomy kinds it is already bound to are the correct ones.
