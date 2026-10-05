# nf-core/airrflow 5.1.0: template ingestion validation report

**Date:** 2026-09-05
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot1`
**Validator:** local depictio-cli (`depictio/cli/.venv`) against the local docker stack
(instance `feat-nfcore-templates-lot1`, API `:8101`, MinIO `:9101`,
config `~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml`).

## Goal

Build the airrflow 5.1.0 template plus the `enchantr` catalog tool it depends on, and drive
`depictio-cli run` against the real AWS megatest output end to end.

## Data used

AWS megatest run
`s3://nf-core-awsmegatests/airrflow/results-e69d49e3f23f11a3391755b5fb7aa4283c0a2471/`
(the 5.1.0 release tag; 5.1.1 has no megatest run). A ten-sample, two-subject multiple
sclerosis B cell study of cervical lymph node and brain lesion tissue, run in the default
`--mode fastq` UMI route with clonal analysis and both enchantR reports enabled.

```bash
python scripts/nfcore_megatest.py fetch --pipeline airrflow --version 5.1.0 \
  --dest ~/Data/depictio-nfcore/airrflow/5.1.0/megatest
# or, equivalently:
bash depictio/projects/nf-core/airrflow/5.1.0/download_test_data.sh
```

The manifest (`megatest.yaml`) fetches 13 keys: the validated samplesheet, the params and
software-versions files, the MultiQC parquet, the four enchantR repertoire-report tables, the
threshold summary, the two V-usage tables and the two sequence-count logs.

## Ingestion result: 12 / 12 data collections processed, exit 0

```bash
depictio/cli/.venv/bin/python -m depictio.cli run \
  --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml \
  --template nf-core/airrflow/5.1.0 \
  --data-root ~/Data/depictio-nfcore/airrflow/5.1.0/megatest
```

The final validated run left `--project-name` off, so the project carries the name the
template declares. That matters only for a later standalone `depictio dashboard import`,
which resolves the dashboard's `project_tag` by name; `run` itself accepts any project
name because step 8 passes the id of the project it just created.

Delta tables read back from MinIO after the run:

| Data collection | Rows | Columns |
|---|---|---|
| `multiqc_data` | 1 report, 4 modules, 21 sample ids | (MultiQC parquet, not Delta) |
| `samplesheet` | 10 | 15 |
| `sequence_counts` | 10 | 17 |
| `sequence_fates` | 80 | 11 |
| `repertoire_summary` | 10 | 20 |
| `clonal_diversity` | 369 | 10 |
| `clone_sizes` | 67770 | 7 |
| `clone_sets` | 45149 | 14 |
| `clonal_overlap` | 10 | 12 |
| `v_gene_usage` | 490 | 9 |
| `v_gene_matrix` | 10 | 59 |
| `threshold_summary` | 2 | 9 |

All four dashboard tabs imported (`Quality control` + `Sequence processing` + `Repertoire` +
`Clonal analysis`, 76 components). Every tile was then executed against those frames: the five
code-mode figures each return a plotly `Figure` with the expected trace count (10 / 7 / 2 / 18 /
10), all sixteen cards compute a non-null value with their secondary strip through
`bulk_compute_cards`, the eight advanced visualisations bind only columns the collection
actually has, and every MultiQC tile names a module and plot MultiQC's own `list_plots()`
reports for this parquet.

The persistent `Subject` filter was exercised end to end (`subject_id = M4` through
`bulk_compute_cards` on all four tabs): `filter_applied` is true on every tab and the card
values narrow as expected. Four medians are unchanged under the filter (rarefied richness,
evenness, mean clone size, retention); each was checked against the frame and is a genuine
coincidence of this ten-sample study, where M4's values straddle the same centre as the whole
cohort. No FILTER MISMATCH, no 4xx and no 5xx.

## Decisions

### AF-D1: `clonal_abundance.tsv` is 17 MB of a 20 MB download and is not fetched

alakazam writes a bootstrapped rank-abundance curve with confidence bounds for all 238651
clone observations. `clone_sizes_table.tsv` already carries the rank and the frequency per
clone, which is what the dashboard's rank-abundance panel plots, so the manifest omits the
curve. This takes the download from 20 MB to about 3 MB.

The cost is the confidence ribbon on the rank-abundance panel: the plotted curve is the point
estimate only. Listed in the gap report.

### AF-D2: twelve draft recipes consolidated to ten outputs

An earlier draft shipped `clonal_overlap` and `clonal_overlap_matrix` (one long, one wide),
`clone_counts` and `diversity_summary` (both per sample), and `v_family_usage` and a gene-level
sibling. Each pair fed one visualisation, so they were merged: `clonal_overlap` is now the wide
matrix, `repertoire_summary` carries the clone counts and the q = 0 / 1 / 2 Hill slices, and
`v_gene_usage` stacks both resolutions into one long table with a `rank` column.

### AF-D3: the overlap matrix diagonal is zeroed

A sample's overlap with itself is its whole repertoire, one to two orders of magnitude larger
than any real pairwise sharing. Left in, it flattens the colour scale to the point where the
off-diagonal cells are indistinguishable. `clonal_overlap.py` writes 0 on the diagonal and the
tile description says so.

### AF-D4: enchantR's own two tables disagree slightly on V family counts

`V_family_distribution_data.tsv` and `V_gene_distribution_by_sequence_data.tsv` are written by
the same Rmd from the same rearrangement table, but rolling the gene file up to family level
gives 72 (sample, family) pairs against the family file's 68, and 4 of the 68 shared pairs
differ by one or two sequences. `v_gene_usage.py` therefore reads the family rows from the
family file and the gene rows from the gene file rather than deriving one from the other; the
`v_family` column on gene rows is derived from the IMGT gene name only so the composition can be
coloured by family.

### AF-D5: SRR1383456 has no diversity numbers

The sample yielded 27 sequences, and enchantR excludes it from `clonal_diversity.tsv` (9 of 10
samples appear). `repertoire_summary` therefore carries null `richness`, `shannon`, `simpson`
and `evenness` for it while its clone counts are present. This is enchantR's own filtering,
not a recipe artefact, and the diversity panels simply draw nine curves.

### AF-D6: MultiQC labels airrflow's second FastQC run `fastqc-1`

airrflow runs FastQC twice, on the raw reads and again after assembly, so MultiQC's module id
for the second run is `fastqc-1` and its samples carry an `_ASSEMBLED` suffix (21 sample ids for
10 samples). The dashboard's FastQC tiles set `selected_module: fastqc-1` while still carrying
`use: multiqc/fastqc` for the catalog badge, and the template's MultiQC DC lists both `fastqc`
and `fastqc-1` so a run with a single FastQC invocation still binds.

### AF-D7: no GROUP_COL variable

Other templates expose a `GROUP_COL` for the metadata column to group by. airrflow's template
does not, because the CLI has no template-level default mechanism: `resolve_template` falls back
to the `__no_group__` sentinel for an unset `GROUP_COL`, and airrflow's samplesheet DC is
present on every route with no conditional to prune it, so a `{GROUP_COL}` placeholder would
bind a filter and a card to a column that does not exist on any run started without `--var`.
The dashboard groups on the columns airrflow's samplesheet schema guarantees instead:
`subject_id` (which is structural, since clones are defined within a subject), `tissue` and
`sex`.

In this megatest `tissue` reads `Baseline` for all ten samples and the lymph node against brain
lesion contrast is recorded in the non-schema `treatment` column, so the `Tissue` filter offers
one value here. That is a property of this run's samplesheet, not of the template.

### AF-D8: skipped, the per-sample AIRR rearrangement tables

`vdj_annotation/02-make-db/*_db-pass.tsv` (about 20 MB) would add V by J pairing, CDR3 length
and isotype panels. They are not fetched and no recipe reads them. Listed in the gap report.

## MultiQC overlap policy

| Signal | Decision |
|---|---|
| Read counts, quality, GC, length, duplication, adapters, status | **MultiQC** (`use: multiqc/fastp`, `use: multiqc/fastqc`), 11 tiles |
| Per-sample run totals | **MultiQC** general statistics table |
| pRESTO / Change-O sequence funnel | **Dedicated** (`enchantr/sequence_counts`, `enchantr/sequence_fates`): MultiQC has no module for the pipeline's own parsed logs |
| Clonal diversity, abundance, overlap, V usage, thresholds | **Dedicated**: MultiQC has no immune-repertoire module at all |

## Discrepancies

### AF-X1: `test_all_recipe_output_roles_resolve_against_the_recipe` cannot read list-valued roles

`depictio/tests/models/test_catalog.py::test_all_recipe_output_roles_resolve_against_the_recipe`
does `set(r.roles.values())`, which raises `TypeError: unhashable type: 'list'` on any render
whose role is a list. Those are exactly the roles `_LIST_ROLES` declares: sankey `steps`,
sunburst `ranks`, complex_heatmap `value_columns` / `row_annotation_cols`. Six shipped renders
across three tools now use them (`combgc`, `dbcan`, `hamronization` from the funcscan
workstream, `enchantr` here), and the first one the loader reaches makes the whole test error
out.

Every role in the catalog resolves once the lists are flattened. The test file is outside this
workstream's owned paths; another workstream in the same branch patched it to flatten the lists
while this run was in flight, and the assertion passes for all six renders.

### AF-X2: airrflow's route flags are not auto-detected

The template exposes `SKIP_CLONAL_ANALYSIS`, `SKIP_REPORT`, `SKIP_THRESHOLD_REPORT`,
`SKIP_MULTIQC` and `ASSEMBLED_MODE` so a run that skipped a step prunes the matching data
collections. `pipeline_info/params.json` already carries `skip_clonal_analysis`, `skip_report`,
`skip_report_threshold`, `skip_multiqc` and `mode`, but `_introspect_pipeline_params` in
`depictio/cli/cli/utils/templates.py` only maps the ampliseq and viralrecon flags, so these must
be passed by hand (`--var SKIP_CLONAL_ANALYSIS=true`). Every affected collection is
`optional: true` or is pruned by the conditional, so a run that omits the flag still ingests.

### AF-X3: recipe fixtures cannot be validated against a whole-catalog load while another
workstream's tool folder is incomplete

`load_catalog_entries()` is all-or-nothing: while `depictio/catalog/homer/` existed without a
`module.yaml`, every `use:` reference in every shipped dashboard was unresolvable and 28 catalog
tests plus the airrflow `advanced_viz` assertion failed on it. The folder was completed by its
own workstream during this run and the tests now pass; recorded here because the failure mode is
not obvious from the error, which names only the offending folder.

---

## 2026-09-22: lot 1 remediation pass

Filter semantics, the unbound rank-abundance file, the overlap ordination, table sizing and the
text-tile height convention, against the same megatest run.

### What changed

* **Dead filter removed.** `tissue` holds one value for every sample of this cohort, so the
  filter on it could never narrow anything. It is replaced by `treatment`, which is where the
  megatest submitters put the sampling site (lymph node against brain lesion): the only
  biological contrast that varies here. The filter is titled `Sampling site`, and
  `columns_description` now documents the values rather than trusting the column names. The
  `Subjects` card's `breakdown_col` moved from `tissue` to `treatment` for the same reason.
* **`clonal_abundance.tsv` is now ingested.** It was on disk and unbound: 238 651 rows,
  17 MB, alakazam's `estimateAbundance` output. New catalog output `enchantr/clonal_abundance`
  (`clonal_abundance.py` / `.yaml` / `.tsv`) casts it and decimates each sample onto a
  log-spaced rank grid: every rank up to 20 kept exactly, the tail thinned, 200 points per
  sample at most. 238 651 rows in, 1 296 out, 132 to 151 points per sample. It renders as a
  `profile` with the bootstrap interval as a ribbon (`enchantr/abundance_ribbon`), two cards and
  a table. The manifest key is added and the "deliberately NOT fetched" note removed.
* **Overlap MDS.** `enchantr/clonal_overlap` gained an `embedding` render (`overlap_mds`) bound
  to the existing wide matrix. The dashboard tile sets `compute_method: pcoa` with a
  Bray-Curtis distance, so the ordination is computed per request and follows the sample filter
  instead of freezing a layout at ingest.
* **Orphan DCs linked.** `clone_sets` and `threshold_summary` reached no filter before.
  `threshold_summary` is per subject, so it is now linked on `subject_id`. `clone_sets` has no
  `sample_id` column at all (its sample columns are the membership flags), so the link exists to
  carry the filter as far as `_narrow_wide_matrix_columns`, which mirrors it onto the column set
  by value. `clonal_abundance` is linked from both the samplesheet and the repertoire summary.
* **Half row filled.** `Clones and depth` had a lone `w: 4` figure. A new `scatter_xy` render
  on `enchantr/repertoire_summary` (`richness_evenness`) fills the other half: rarefied richness
  against evenness, sized by sequencing depth.
* **Tables resized to their real row counts.** samplesheet h5 to h4 (10 rows), repertoire
  summary h4 (10), sequence counts h4 (10), clonal overlap h4 (10), clonal threshold h4 to h3
  (2 rows).
* **Glance strip on every tab.** The four cohort cards moved out of the collapsed `Sample sheet`
  section into a new persistent, pinned, uncollapsed `Cohort at a glance` section, so a reader
  on any tab sees what the tiles are computed from. The samplesheet table stays collapsed below.
* **Text tiles.** Eleven intros whose rendered body exceeds 120 characters moved from `h: 1` to
  `h: 2`, and the `y` of every tile below them in the same section was recomputed so each grid
  row still sums to 8.

### Commands

```bash
# recipe on the real file
uv run python -c "...transform(...)"        # 238651 -> 1296 rows, 8 columns, dtypes match
uv run python <scratchpad>/audit.py .../airrflow/5.1.0/dashboards/base.yaml   # 0 problems
uv run python <scratchpad>/catcheck.py .../airrflow/5.1.0/dashboards/base.yaml # 11 advanced_viz, 0 invalid
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k airrflow
uv run python -m depictio.cli run --template nf-core/airrflow/5.1.0 \
  --data-root ~/Data/depictio-nfcore/airrflow/5.1.0/megatest --dry-run   # 8/8 steps
```

### Discrepancies

#### AF-D9: alakazam drops a sample from the abundance table

`clonal_abundance.tsv` has nine of the ten samples. SRR1383456 contributed 27 sequences in 24
clones, below what `estimateAbundance` will bootstrap, so it has no row. This is the same reason
it has no diversity numbers (AF-D5). The DC is declared `optional: true` and the profile simply
has one curve fewer; no tile fails.

#### AF-D10: AF-D1 is reversed

AF-D1 argued `clonal_abundance.tsv` was not worth 17 MB of a 20 MB download because
`clone_sizes_table.tsv` already carries rank and frequency. That is true of the point estimates
and false of the confidence band, which is the only thing on this template that says whether a
difference in clonal expansion is supported by the sequences behind it. The decimation keeps the
cost at ingest: the download grows, the delta table does not.

#### AF-D11: the whole-catalog test is red for reasons outside this template

`test_advanced_viz_components_validate` and `test_advanced_viz_survives_the_component_union`
fail on every template while other agents of this wave are mid-write in `depictio/catalog/`
(`ascat` without output files, `cooltools` still naming the pre-rename `genomespy_track` kind).
Catalog loading is all-or-nothing, so the failure is unrelated to airrflow. Validated instead
against a catalog copy restricted to the tool dirs this dashboard uses (`enchantr`, `multiqc`):
11 advanced_viz components, 0 invalid. This is AF-X3 recurring, and it is the argument for that
issue's proposed per-tool validation path.

## 2026-09-22 review fixes

MultiQC scan regex brought to the mandated form
(`(?:.*/)?multiqc(?:/[^/]+)?/multiqc_data/multiqc\.parquet$`). Not done: a pinned
`pcr_target_locus` factor. On the reference run (`pipeline_info/samplesheet.valid.tsv`,
10 rows) the column is constant (`IG` throughout), so a control on it could never narrow
anything and stays out per the dead-filter rule; `subject_id` (2), `treatment` (2) and
`sex` (2) already carry the varying factors.

## 2026-09-23: wave 2b (spectratype, V-J pairing, ribbon profile, header controls)

What changed:

- New optional collections `cdr3_spectratype` and `vj_usage_matrix`, built by two
  version-local recipes (`recipes/cdr3_spectratype.py`, `recipes/vj_usage_matrix.py`) from
  the AIRR rearrangement table `clonal_analysis/.../repertoires/All_samples__repertoire-pass.tsv`
  (now a `megatest.yaml` key, 308 MB, 130,232 rows, IGH only). The recipes read six and
  seven of its 74 columns through `read_kwargs.columns` (0.06 s), so the raw table never
  reaches Delta. Links: `sample_id` to the spectratype, `subject_id` to the V-J grid.
- Repertoire tab: sections `CDR3 spectratype` (text + faceted bar figure, one panel per
  sample, coloured by donor) and `V-J pairing` (text + `complex_heatmap`, rows donor and V
  gene, columns IGHJ1 to IGHJ6, subject row annotation); a `CDR3 length (aa)` slider with
  histogram in `Repertoire scope`.
- Clonal analysis: the hand-written Plotly ribbon figure (own palette, `code_content`) is
  replaced by a `profile` tile with `lower_col: d_lower`, `upper_col: d_upper`.
- `controls_placement: header` on the V gene composition, richness against evenness and
  overlap MDS; `show_histogram: true` on four threshold sliders.

Discrepancies:

- AF-D12: the spectratype and V-J tiles bind no catalog render (`use:`): the collections are
  version-local recipes, and `enchantr` is not in this pass's partition. Promoting them to
  `depictio/catalog/enchantr/{cdr3_spectratype,vj_usage}.yaml` would restore the `use:` ratio.
- AF-D13: the diversity ribbon tile is a direct `viz_kind: profile` for the same reason.
- AF-D14: SRR1383456 has 27 sequences in the repertoire table, so its spectratype panel is a
  handful of bars; it is kept (filtering is the reader's call through the sample filter).

Commands and results:

| command | result |
| --- | --- |
| recipes on the real table (`resolve_sources` + `transform` + `validate_schema`) | spectratype 259 x 6, V-J 103 x 10 |
| `uv run pytest -q depictio/tests/models/test_shipped_dashboard_yamls.py -k airrflow` | 10 passed |
| `depictio.cli run --template nf-core/airrflow/5.1.0 ... --dry-run` | 8/8 steps |
| delete + re-ingest | project `6ab3cc7c81d2d7032d3ff302`, dashboard `6ab3ccdce8b8ace33d32c9f6`; cdr3_spectratype 259 rows, vj_usage_matrix 103 rows |
| Playwright, 1600x1000 | `/tmp/shots-airrflow/` (tabs + `verify-repertoire-*.png`, `verify-rep2-*`, `verify-clonal-*`) |

## Wave 3 (sc-immune family rework)

Applied from `review-sc-immune.md` and the consolidated review, in the order P0 genericity,
blockers, redundancies, conventions.

What changed:

- Genericity: new `GROUP_COL` (default `treatment`) and `GROUP_COL_DISPLAY` (default
  "Condition") template variables, ampliseq 2.18.0 convention, also set in `reference.vars`.
  The "Sampling site" filter is now `airr-filter-group` on `{GROUP_COL}`; the subject card
  breaks down by `{GROUP_COL}`. No IGHJ4, no CDR3 "12 to 16" range, no shazam threshold stated
  as a fact; the UMI wording is gone from the MultiQC and funnel intros. `megatest.yaml` gets a
  `forbidden_terms:` list (sample ids, subject ids, sampling sites, provider, IGHJ4, "12 to 16").
- Blockers: `airr-clone-div-cibars` now reads a new `diversity_orders` collection (catalog
  output `enchantr/diversity_orders`, q = 0, 1, 2 labelled) filtered by a Select
  (`airr-clone-filter-order`, `default_value: q = 1, Shannon`); the q RangeSlider is gone, so the
  profile ribbons keep every order. `airr-seq-card-retention`: median with `box_plot`, no gauge.
  `airr-rep-filter-rank` and `airr-rep-fig-family` deleted. Clone size card: "Median clone
  size", `box_plot`, no threshold. `airr-clone-card-threshold`: no verdict (P17), median with
  per-subject `top_n`.
- Redundancies removed: `airr-clone-div-profile`, `airr-clone-fig-rank`,
  `airr-clone-overlap-mds`, `airr-rep-table-summary`, `airr-rep-card-samples`,
  `airr-clone-card-sizeclass` (the sunburst carries size classes), `airr-tables-intro`.
- Conventions: Repertoire = gene usage only, with 4 new cards (V families, V genes, largest V
  family share, productive sequences). `Clones and depth` and the clones / clone size / evenness
  cards moved to the top of Clonal analysis; `airr-rep-filter-clones` moved to `Clonal scope`.
  Two pinned tables (samplesheet, repertoire summary); sequence counts, threshold and overlap
  tables moved collapsed to the tab that reads them. All tab-local filter sections open. Intros
  at most 2 sentences. Overlap heatmap colourscale `Blues`. Target loci card without the
  subject composition strip. `SKIP_MULTIQC` description corrected.

Verification (offline):

| command | result |
| --- | --- |
| `uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py depictio/tests/models/test_template_conventions.py -q -rxX -k airrflow` | 13 passed, 3 xpassed (all KNOWN_VIOLATIONS entries now pass) |
| `execute_recipe("enchantr/diversity_orders.py", ...)` on megatest and test runs | 27 x 7 and 9 x 7, three orders each |
| `depictio.cli run --template nf-core/airrflow/5.1.0 --dry-run` on megatest, test, test_tcr | configuration validation passed |

Still open:

- The CLI resolver sets `GROUP_COL=__no_group__` before declared variable defaults are applied,
  so on the CLI path the `treatment` default is shadowed until the resolver is patched (reference
  seeding is unaffected thanks to `reference.vars`).
- A samplesheet without the `GROUP_COL` column (the nf-core `test` and `test_tcr` profiles have
  no `treatment`) leaves the condition filter empty and the subject card without breakdown; pass
  `--var GROUP_COL=<column>`.
- Not re-ingested or checked live (no stack in this wave). Seeds, kinds and conformance for the
  new `diversity_orders` output are regenerated by the main session.
- No record_card "detail" section and no isotype or SHM angle yet (lot 3 candidates).
