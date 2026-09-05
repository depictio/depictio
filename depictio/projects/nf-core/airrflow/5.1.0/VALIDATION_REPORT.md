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
