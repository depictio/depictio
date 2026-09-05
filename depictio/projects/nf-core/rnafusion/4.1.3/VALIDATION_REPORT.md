# nf-core/rnafusion 4.1.3: template ingestion validation report

**Date:** 2026-09-05
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot1`
**Validator:** local depictio-cli (`depictio/cli/.venv`) against the local docker stack
(instance `feat-nfcore-templates-lot1`, API `:8101`, MinIO `:9101`,
config `~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml`).

## Goal

Build the rnafusion 4.1.3 template plus the six catalog tools it depends on
(`fusionreport`, `arriba`, `starfusion`, `fusioncatcher`, `fusioninspector`,
`ctatsplicing`) and the two shared MultiQC entries it needs (`multiqc/star`,
`multiqc/picard`), then drive `depictio-cli run` against the real AWS megatest output
end to end and ground every dashboard tile on the Delta tables the run produced.

## Data used

AWS megatest run
`s3://nf-core-awsmegatests/rnafusion/results-76ad76e7c39b2ba9edc35aa3602e3dc454d842ec/`
(the 4.1.3 release tag). It is the pipeline's own test profile: **one sample, `test`**, a
synthetic library spiked with twelve well known cancer fusions, run with all three callers
(Arriba, STAR-Fusion, FusionCatcher), FusionInspector validation and CTAT-splicing.

```bash
python scripts/nfcore_megatest.py fetch --pipeline rnafusion --version 4.1.3 \
  --dest ~/Data/depictio-nfcore/rnafusion/4.1.3/megatest
# or, equivalently:
bash depictio/projects/nf-core/rnafusion/4.1.3/download_test_data.sh
```

The manifest (`megatest.yaml`) fetches **20 files, 3.9 MB**: the params and
software-versions files, the MultiQC parquet, the fusion-report consensus CSV, the three
caller tables, the FusionInspector abridged table, the two CTAT-splicing intron files, and
the raw STAR / Picard / samtools / fastp metric files that a later MultiQC reprocess would
need. Everything large is excluded on purpose (stringtie is about 415 MB on its own); the
manifest header lists each exclusion.

The run does not publish its samplesheet. `pipeline_info/params.json` points `input` at
`nf-core/test-datasets`, so the manifest's `post_fetch_help` carries the exact `curl` line
and the template ships a copy at `input/samplesheet.csv` so it is self-describing.

## Ingestion result: 10 / 11 data collections populated, 1 optional skipped, exit 0

```bash
depictio/cli/.venv/bin/python -m depictio.cli run \
  --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml \
  --template nf-core/rnafusion/4.1.3 \
  --data-root ~/Data/depictio-nfcore/rnafusion/4.1.3/megatest
```

`--project-name` was left off, so the project carries the name the template declares.
Project **RNAfusion Gene Fusion Detection**, id `6a9c2f3ca6d18491fedaf546`, dashboard
`nf-core/rnafusion` id `6a9c2f4430851b3fe1718187` plus its three child tabs.

Delta tables read back from MinIO after the run:

| Data collection | Rows | Columns | Note |
|---|---|---|---|
| `multiqc_data` | 1 report, 5 sample ids | (MultiQC 1.33 parquet, not Delta) | binds `fastqc`, `fastqc-1`, `fastp`, `star`, `picard`; the parquet also carries the two `nf-core-rnafusion-*` summary sections |
| `samplesheet` | 1 | 6 | 4 declared plus `depictio_run_id`, `aggregation_time` |
| `fusion_consensus` | 20 | 13 | the hub, one row per fusion |
| `caller_evidence` | 45 | 9 | 20 fusions across 3 callers |
| `arriba_fusions` | 15 | 18 | 14 distinct fusions |
| `starfusion_fusions` | 15 | 14 | 14 distinct fusions |
| `fusioncatcher_fusions` | 23 | 16 | 17 distinct fusions |
| `fusioninspector_fusions` | 17 | 22 | 14 distinct fusions |
| `fusion_protein_domains` | 184 | 9 | 12 fusions, both partners |
| `splice_junctions` | 200 | 13 | 14 chromosomes, 28 genes |
| `cancer_introns` | skipped | | source file is header only, see RF-D3 |

The CLI reports the skip explicitly:
`⊘ Skipped optional data collection 'cancer_introns': all 1 matched files were empty`.

## What was verified

All four tabs imported with every component: **74 / 74 stored components** (main
`nf-core/rnafusion` 23, `Fusion calls` 12, `Evidence` 17, `FusionInspector and splicing`
22), nothing dropped, no 4xx and no 5xx.

Every tile was then grounded on the Delta table the viewer would read, not on a locally
recomputed frame:

- **3 code-mode figures** executed against their real frames with the viewer's scope
  (`df`, `pl`, `px`, `go`, `pd`, `np`, `depictio_group_by`, `depictio_group_kwargs`) and
  each returned a plotly `Figure`: the caller cross plot (1 trace), the fusion allelic
  ratio scatter (3 traces), the protein domain track (2 traces). 6 traces in total.
- **59 bound column references** checked against the ingested columns and all present:
  16 card `column_name` plus their `breakdown_col`, 14 interactive `column_name`, 2
  figure `selection_column`, 9 table `row_selection_column`, the `dict_kwargs` of the one
  ui-mode figure, and every column named inside an `advanced_viz` `config:` block
  (`set_columns`, `effect_col`, `feature_col`, `selection_column`).
- **42 `use:` handles** resolved in the catalog. The 9 that name an advanced-viz render id
  resolved to a kind whose declared roles bind only columns the collection has
  (`upset_plot`, `lollipop` x2, `dot_plot` x5, `manhattan`). The other 33 resolved to a
  catalog output (cards, tables, MultiQC tiles).
- **9 MultiQC tiles** name a module and a plot the parquet really carries, checked against
  `extract_multiqc_metadata`. `general_stats` is exempt by construction.
- **16 cards** computed server side through `bulk_compute_cards`, every one non-null, 14
  with their secondary strip (`__breakdown__`, `box_plot_stats`, `__threshold__`,
  `__histogram__`).
- **Filters were exercised**, not just declared. On each tab the tab's own MultiSelect and
  the persistent `Fusion scope` filter were applied through `bulk_compute_cards`:
  `fusion_consensus.fusion = AKAP9--BRAF` moves 3 of 4 cards on `Fusion calls`,
  `caller_evidence.caller = fusioncatcher` moves 4 of 4 on `Evidence`,
  `fusioninspector_fusions.prot_fusion_type = INFRAME` moves 4 of 8 on
  `FusionInspector and splicing`. `filter_applied` is true in every case.
- **Cross-DC propagation through the template links** was measured. Picking one fusion in
  the persistent filter narrows `caller_evidence` from 20 to 1 and
  `fusioninspector_fusions` from 14 to 1 through the links, while the four
  `splice_junctions` cards stay at their unfiltered values, which is correct: the junction
  collections are deliberately unlinked because CTAT-splicing keys on the intron, not on
  the fusion.

### Link overlap, measured on the ingested tables

No FILTER MISMATCH. Every link has a real, partial overlap rather than zero or everything:

| Link | Source keys | Target keys | Shared | One pick matches |
|---|---|---|---|---|
| `fusion_consensus.fusion` to `caller_evidence` | 20 | 20 | 20 | 3 rows |
| `fusion_consensus.fusion` to `arriba_fusions` | 20 | 14 | 14 | 1 row |
| `fusion_consensus.fusion` to `starfusion_fusions` | 20 | 14 | 14 | 1 row |
| `fusion_consensus.fusion` to `fusioncatcher_fusions` | 20 | 17 | 17 | 1 row |
| `fusion_consensus.fusion` to `fusioninspector_fusions` | 20 | 14 | 14 | 1 row |
| `fusion_consensus.fusion` to `fusion_protein_domains` | 20 | 12 | 12 | 6 rows |
| `fusioninspector_fusions.fusion` to `fusion_protein_domains` | 14 | 12 | 12 | 6 rows |
| `fusioninspector_fusions.fusion` to `caller_evidence` | 14 | 20 | 14 | 3 rows |
| `samplesheet.sample` to `multiqc_data` | 1 | 5 report ids | see RF-D2 | 3 of 5 |

The consensus is a superset of every caller, as it should be: 20 fusions, of which Arriba
and STAR-Fusion each report 14 and FusionCatcher 17. The last row is the one link that
loses rows silently, which RF-D2 covers.

Each link was also driven through the server's own resolver
(`POST /depictio/api/v1/links/{project}/resolve`). All nine resolve, none returns an
`unmapped_values` entry.

## MultiQC overlap policy

| Signal | Decision |
|---|---|
| Read counts, base quality, GC, length, duplication, adapters, status | **MultiQC** (`use: multiqc/fastqc`, both the raw and the `fastqc-1` trimmed run) |
| Reads kept by trimming, insert sizes, per read quality | **MultiQC** (`use: multiqc/fastp`) |
| Alignment rates and gene count assignment | **MultiQC** (`use: multiqc/star`, new shared entry) |
| Duplication, insert size distribution, transcript region assignment, gene body coverage | **MultiQC** (`use: multiqc/picard`, new shared entry) |
| Per sample run totals | **MultiQC** general statistics table |
| Caller consensus, per caller evidence, in silico validation, protein domains, splice junctions | **Dedicated**: MultiQC has no fusion module at all, and none of these tables reaches the report |

Nine of the main tab's tiles are MultiQC panels. Two new shared entries were added under
`depictio/catalog/multiqc/` following `fastqc.yaml`'s shape; the `multiqc_stubs.py`
builders that let the conformance project cover them were written and proved by running
MultiQC 1.35 over the stubs (all four Picard anchors and both STAR anchors appear in
`multiqc_data/multiqc.parquet`).

## Design decisions

### RF-C1: the fusion is the unit of analysis, not the sample

rnafusion writes one file per tool per sample and **none of those files carries a sample
column**. The recipe harness concatenates the globbed files without their path, so a sample
cannot be recovered from them (RF-D5). Every fusion table is therefore keyed on the fusion
name, the links fan a fusion selection out across the callers, and the samplesheet only
drives the MultiQC panels. On this validation run the choice costs nothing, because the
megatest is a single sample and every cross sample panel would be degenerate anyway.

### RF-C2: `cancer_introns` is optional and no tile depends on it

CTAT-splicing writes `test.cancer.introns` with a header and no rows on this run: nothing
survived the cancer intron annotation filter. The collection is declared `optional: true`,
the recipe exists so a run that does produce candidates ingests them, and no dashboard tile
reads it. The `*.cancer.introns.prelim` candidate file is fetched alongside it purely to
document that the filter, not the pipeline, is what emptied the table.

### RF-C3: route flags are declared but not auto-detected

The template exposes `SKIP_ARRIBA`, `SKIP_STARFUSION`, `SKIP_FUSIONCATCHER`,
`SKIP_FUSIONINSPECTOR`, `SKIP_CTATSPLICING` and `SKIP_QC`, each naming the `params.json`
field it mirrors. `_introspect_pipeline_params` in `depictio/cli/cli/utils/templates.py`
only maps the ampliseq and viralrecon flags, so a run that skipped a caller needs the
matching `--var`. This is the same gap airrflow recorded; it is listed here so the two
reports agree rather than as a new finding.

## Discrepancies

### RF-D1: the API caches the catalog at process start, so a `use:` handle for a tool added later degrades silently

This is the significant one. `AdvancedVizLiteComponent._expand_catalog_use` turns
`use: <tool>/<render>` into `viz_kind` plus a full per-kind `config`, and
`DashboardDataLite.to_full()` derives `catalog_source` from the same handle. The expansion
calls `load_catalog_entries()`, whose result is cached in the process. The API process on
this stack was started before `depictio/catalog/fusionreport/` and the other five rnafusion
tools existed, so for that process they do not exist.

When the expansion raises `unknown catalog tool`, the component **does not fail the
import**: the lite component union falls back to keeping the raw dict, `validate_schema_online`
skips dicts with an explicit `# Pydantic already caught these`, and the import reports
success. The tile is then stored with `viz_kind: null`, `catalog_source: null` and the raw
YAML `config`, and `AdvancedVizDispatch.tsx` dispatches strictly on `metadata.viz_kind`, so
the viewer draws `Unknown advanced viz kind: ""` where the figure should be.

Reproduced deliberately, two single-tile dashboards imported back to back into the same
project through the same endpoint, then deleted:

| Probe | `use:` | Stored `viz_kind` | Stored `config` | `catalog_source` |
|---|---|---|---|---|
| 1 | `fusionreport/caller_upset` (added today) | `null` | `{}` | `null` |
| 2 | `hamronization/arg_upset` (present at API start) | `upset_plot` | 14 keys with defaults | set |

So the YAML is right and the catalog is right: `DashboardDataLite.from_yaml(...).to_full()`
run in the worktree expands `fusionreport/caller_upset` to `viz_kind: upset_plot` with a
14 key config. It is the running API process that cannot see the tool.

Consequences, in order of severity:

1. **A silent failure, not an error.** An unresolvable `use:` handle should fail the import
   loudly. Instead the dashboard imports, the component count is right, every other check
   passes, and the defect is only visible in a browser. Every check in this report passes on
   the current server state and none of them would have caught it; it was found by comparing
   the stored `viz_kind` against the other pipelines' projects.
2. **It affects every workstream on this branch, not this template.** Counting the stored
   advanced viz components across the whole stack: ampliseq 11/11 with a kind, viralrecon
   9/9, funcscan 9/9, airrflow 8/8, but rnafusion 0/9, rnaseq 0/2, taxprofiler 0/8 and
   chipseq 3/7. The split is exactly whether the tool folder existed when the API process
   last started.
3. **The fix is a restart, not a YAML change.** Restarting the API container and re-running
   `depictio-cli run` for the affected pipelines populates `viz_kind`, `config` defaults and
   `catalog_source`. Adding a redundant `viz_kind:` next to every `use:` would mask the bug
   and would still store a config without the kind's defaults and without the catalog badge,
   so the template YAML was deliberately left alone.

Worth fixing upstream in two places: make `load_catalog_entries()` invalidate on a change
to the catalog directory (or expose a refresh), and make a `use:` handle that fails to
expand an import error rather than a silent downgrade to a raw dict.

### RF-D2: `sample_mapping` cannot reach a MultiQC sample that the pipeline renamed between stages

`build_sample_mapping` canonicalises a MultiQC sample id with
`^([A-Za-z0-9_-]+?)(?:_[12])?(?:\s+-\s+.+)?$`, which strips only a `_1` / `_2` read suffix
and MultiQC's own ` - ` annotation. rnafusion runs FastQC twice, before and after trimming,
and names the second pass's inputs `test_trimmed_1` and `test_trimmed_2`. Those canonicalise
to `test_trimmed`, a **second canonical id the samplesheet's `test` can never reach**.

Measured on this run: the parquet holds 5 sample ids over 2 canonical ids, and
`POST /links/{project}/resolve` with `samplesheet.sample = ["test"]` returns
`["test", "test_1", "test_2"]` with an **empty `unmapped_values`**. Nothing signals a loss,
because the source value did map; the rows that vanish are on the target side.

The visible effect: picking the only sample in the persistent `Sample filters` empties the
`Trimmed read quality` tile (module `fastqc-1`, whose only samples are `test_trimmed_1` and
`test_trimmed_2`) and silently halves the raw FastQC tiles, whose plots carry all four ids.
Per plot, the ids are `test` for fastp, STAR and Picard, `test_1`/`test_2`/`test_trimmed_1`/
`test_trimmed_2` for the `fastqc` anchors, and `test_trimmed_1`/`test_trimmed_2` only for
the `fastqc-1` anchors.

For the infrastructure: any pipeline that renames its samples between stages, with a
`_trimmed`, `_filtered`, `_dedup` or `_ASSEMBLED` style suffix, hits this. The resolver
should either report the target ids it could not cover, or canonicalise against the
samplesheet's known sample list (longest prefix match) rather than against a fixed suffix
pattern. airrflow's AF-D6 is the same root cause with a milder outcome, so it is worth one
fix rather than a per template workaround.

### RF-D3: an optional data collection with an empty source is registered without a Delta table

`cancer_introns` is correctly skipped at ingest, with a clear CLI message. But the
collection is still written into the project's `data_collections` list, so it appears
wherever data collections are listed while every read of it fails:

```
GET /deltatables/get/6a9c2f...    404  No DeltaTableAggregated found for Data Collection ID ...
GET /deltatables/specs/6a9c2f...  404  No DeltaTable found for data collection ...
GET /deltatables/shape/6a9c2f...  404  No DeltaTable found for Data Collection ID ...
```

The bucket prefix for that id holds zero objects, so `pl.read_delta` raises
`TableNotFoundError: No files in log segment` rather than returning an empty frame.

For the infrastructure: nothing at the API distinguishes "declared optional and legitimately
empty" from "broken". A consumer that walks a project's collections has to treat a 404 as
normal, which then hides real breakage. Either prune skipped optional collections from the
project document, or mark them (an `ingested: false` / `skipped_reason` field) so the
distinction survives to the API.

### RF-D4: recipe-transformed collections carry no run provenance column

Only the scanned `samplesheet` gained `depictio_run_id` and `aggregation_time`. All nine
recipe-transformed collections carry exactly the recipe's own columns and nothing else.
Confirmed to be general, not an rnafusion quirk: on the same stack, airrflow's
`sequence_counts` and `sequence_fates` and funcscan's `hamronization_report` and
`hamronization_gene_presence` all lack it while their samplesheets have it.

For the infrastructure: a project with more than one run has no way to attribute a
transformed row to a run, and no way to scope a filter by run. It bites rnafusion hardest
because the caller tables have no sample column either (RF-D5), so a transformed row there
carries no provenance of any kind.

### RF-D5: rnafusion emits no sample column, and the recipe harness adds none

Arriba, STAR-Fusion, FusionCatcher, FusionInspector and CTAT-splicing each write one file
per sample, with the sample encoded **only in the file name**. `resolve_sources` globs the
matching files and concatenates their contents, discarding the path, so a recipe cannot
recover the sample even though the information is right there in the file name it read.

This is why the whole template is keyed on the fusion (RF-C1). It costs nothing on a single
sample megatest, but on a cohort run the caller tables silently pool every sample into one
table and the per caller panels become a pooled view rather than a per sample one. That is
documented in `docs/dashboards.md` so a user is not surprised by it.

For the infrastructure: a `source_column` or `source_path` option on `RecipeSource`, filled
with the matched file name, would fix this for every pipeline that publishes per sample
files without an in-file identifier. That is a common nf-core layout, not an rnafusion
peculiarity.

### RF-D6: the megatest is one sample of synthetic spiked-in fusions

Two limitations, one on each axis.

**One sample.** Everything that compares samples degenerates:

- the persistent `Sample filters` MultiSelect offers exactly one value, so it can only
  select all or nothing, and the `Read QC scope` strandedness filter the same;
- the `Run samplesheet` table is one row;
- every per sample MultiQC bar and line panel draws a single series: `Reads kept by fastp`,
  `STAR alignment scores`, `STAR gene-count assignment`, `Insert size distribution`,
  `Coverage along the gene body`, `Where the bases landed`. The general statistics table
  shows five rows, but they are one sample's read files, not five samples;
- the whole sample axis of the infrastructure goes unexercised, including any
  `sample_mapping` expansion beyond a single canonical id, which is part of why RF-D2 was
  only found by reading the resolver rather than by seeing a panel break.

The fusion tabs are not degenerate, because the fusion rather than the sample is the unit:
the UpSet compares callers, the dot plots compare callers, and every filter acts on fusion
attributes.

**Synthetic fusions.** The twelve spiked-in fusions are all textbook cancer fusions that all
three callers find and that two knowledge bases already list, so their Fusion Indication
Index is exactly 1.0. The other eight calls are one two-caller call and seven single-caller
IGH and DUX4 artefacts at 0.167. The result is a bimodal, saturated score: 12 fusions at
1.0, 1 at 0.833, 1 at 0.667, 7 at 0.167. So the FII lollipop reads as two flat plateaux
rather than a ranking, the FII box plot has its median at the maximum, and the caller UpSet
is dominated by one intersection of size 12. All three panels are correct and would be
informative on a real tumour run; they simply have little to show here.

One consequence worth recording so it is not read as a bug: the `Supporting reads` card on
the `Evidence` tab is 14.0 both unfiltered and under `fusion = AKAP9--BRAF`. Checked against
the frame, that fusion's three caller rows are 13, 25 and 14 reads, and 14 happens to be the
median of all 45 rows as well. A genuine coincidence of a 45 row table.

### RF-D7: a component's YAML `tag` never reaches the server, `index` does

A dashboard YAML component may carry both `tag` and `index`. Only `index` survives into
`stored_metadata`; `tag` is dropped, and when `index` is absent the model mints a UUID. In
this dashboard 14 of the 74 components set both and they differ, for example
`tag: rnaf-filter-sample` with `index: rnaf-sample-filter`.

For the infrastructure: any tooling that reads a shipped YAML and then addresses the stored
component by `tag` matches nothing, with no error, and simply reports zero components. This
was hit while writing the verification harness: a first pass that collected the persistent
filters by `tag` found an empty list and silently skipped the whole persistent filter test.
Either carry `tag` through as an alias, or reject a YAML that sets both to different values.
