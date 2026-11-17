# Your pipeline's parameters and its Depictio template

A Depictio template (`depictio/projects/nf-core/<pipeline>/<release>/template.yaml`)
lists the files of your `--outdir` it reads (data collections, each with a tag)
and the dashboards built on them. A run made with `--skip_alignment`, `--tools
arriba` or `--skip_multiqc` writes other files, so the template has **routes**:
variables whose presence drops or repoints collections. The template reads which
route a run took from the run itself, `pipeline_info/params_<timestamp>.json`.
Nobody passes a flag.

![from params_<ts>.json to the dashboard](images/template-params/schema_from_params.png)

## Check your pipeline in three commands

```bash
pip install depictio        # the CLI alone; no server needed for any of this

# 1. The template against your release's nextflow_schema.json (fetched from GitHub)
depictio template check nf-core/rnaseq/3.26.0 --fetch-schema

# 2. What one run turns on (template auto-detected from pipeline_info/)
depictio template check --run results/

# 3. Which files each collection finds in that run, before ingesting anything
depictio ingest results/ --dry-run
```

`depictio template check nf-core/rnaseq/3.26.0 --fetch-schema --run results/`
on a `--skip_alignment` run:

```text
variable                   set by                              default run  this run  when set → template
DATA_ROOT                  auto: the results directory                       set      in paths only
PSEUDOALIGNER_ONLY         {param: skip_alignment}                  –        set      set → drops tracks; repoints sample_overview,
                                                                                        expression_heatmap, gene_expression, gene_summary,
                                                                                        gene_counts, deseq2_qc_pca, deseq2_qc_dists
SKIP_MULTIQC               {param: skip_multiqc}                    –         –       set → drops multiqc_data, general_stats
SKIP_QUANTIFICATION_MERGE  {param: skip_quantification_merge}       –         –       set → drops sample_overview, expression_heatmap, …
TRACKS_URI                 --var                                               –       set → repoints tracks
This run fires:
  • if_var_present: PSEUDOALIGNER_ONLY → drops tracks; repoints sample_overview, …
✓ every param a rule reads exists in this release
! skip_* params no rule reads, whose tool the template names: skip_bigwig, skip_deseq2_qc, skip_qc, …
```

- **set by**: a `from_params` rule, `auto` (found in the outputs), or `--var`
  (only a user knows it: a path, a bucket, a genome build).
- **default run**: the rule evaluated on the schema's defaults. `set` there
  means the route is taken by a default run: check that this is what you mean.
- **✗ … not a parameter of this release**: the rule reads a param your release
  does not have (renamed, misspelt), so it would never hold. The command exits
  1; CI runs it on every template change.
- **! skip_\***: `skip_*` flags of the release that no rule reads, but whose
  tool the template names (a tag, a path). A run with one of them may lack
  files a collection reads: run step 3, then add a rule and a conditional.

Also: `--params params.json` instead of `--run`, `--schema
nextflow_schema.json` for a local checkout (a release in progress), `--var K=V`
as you would pass it to `depictio ingest`, `--all` for every bundled template.

## Adding a route

A variable with a `from_params` rule, and a conditional on it:

```yaml
template:
  variables:
    - name: SKIP_ARRIBA                       # rnafusion 4.1.3
      description: "arriba not among --tools"
      from_params: {all: [{param: tools, not_contains: arriba}, {param: tools, not_contains: all}]}
  conditional:
    - if_var_present: SKIP_ARRIBA             # no arriba/ directory
      remove_dc_tags: [arriba_fusions, arriba_fusion_links]
    - if_var_present: PSEUDOALIGNER_ONLY      # rnaseq: the same files, under salmon/
      override_dcs:
        - data_collection_tag: gene_counts
          scan_filename: "{DATA_ROOT}/salmon/salmon.merged.gene_counts.tsv"
```

| Rule | Holds when the param is… |
|---|---|
| `{param: p}` | on: `true`, `"true"`, a non-empty string, a non-zero number, a non-empty list |
| `{param: p, is: false}` | off: `false`, `"false"`, `"null"`, empty, or absent |
| `{param: p, equals: v}` / `not_equals: v` | `v`, any case (`not_equals` also holds when absent) |
| `{param: p, contains: v}` / `not_contains: v` | a list, or a comma-separated string, holding `v` |
| `{any: [...]}` / `{all: [...]}` | one / every nested rule holds |

- A rule that holds sets the variable to `"true"`; one that does not sets
  nothing, so the variable is optional (`required: true` is refused).
- An explicit `--var` always wins. `--var X=false` (or `0`, `null`, empty)
  unsets a rule's variable: the way to overrule a rule that misfires.
- Unknown keys (`from_param:`, `equal:`) are a load error, not a rule that
  never holds.
- Read the param's meaning in the release's code, not only its name: in
  rnaseq 3.26.0, `--skip_qc` skips every QC step *except* MultiQC.

**Which params file.** The newest `pipeline_info/params_<timestamp>.json` (a
resumed run leaves one per attempt). `nf-params.json` holds only what the user
overrode, so an absent default would read as off: it is never used for rules.
For a root of `run_*/` directories, the first run's file, with a warning. No
file: no rule fires, and the template is used as is.

## Coverage of the 57 bundled templates

| | Templates | Why |
|---|---|---|
| Routes set by rules | 18: airrflow (×3), ampliseq 2.16 / 2.18, crisprseq, demultiplex, differentialabundance, epitopeprediction, funcscan, mhcquant, pairgenomealign, proteinannotator, rnafusion, rnaseq, smrnaseq, stableexpression, viralrecon | 51 rules, each read against the release's schema and workflow code |
| Routes by inputs only | 24 (atacseq, chipseq, cutandrun, sarek, ampliseq 2.14, …) | their conditionals test inputs, not flags: `TRACKS_URI` (where the BAMs and bigWigs live), `METADATA_FILE` (found in `input/`), `GENOME` (a UCSC build; the run's `--genome` is an iGenomes key) |
| No route | 15 (eager, hic, mag, scrnaseq, taxprofiler, …) | one layout, whatever the params |
| `--var` on purpose | mcmicro `SINGLE_SEGMENTER`, epitopeprediction `SINGLE_PREDICTOR` / `NO_VARIANT_INPUT`, chipseq `PRESEQ_RAN`, isoseq 3.0.1 `SKIP_MULTIQC`, cutandrun `MULTIQC_REPROCESSED` | no param says it: a list's length or the samplesheet's content, a default against the template's design, a param the release lacks, a report re-made after the run |

**Not covered yet.** `depictio template check --all --fetch-schema` names, for
29 templates, `skip_*` flags whose tool the template reads and that no rule
handles (rnaseq `skip_bigwig`, `skip_deseq2_qc`; ampliseq `skip_multiqc`; …).
Each one is a route to verify against the release's code before adding it.

## When a new release ships

Everything here is deterministic: two `nextflow_schema.json`, the template, and
the release's megatest run. No step needs a model.

```bash
depictio template check nf-core/rnaseq/3.26.0 --against 3.27.0
```

| Change in the release | Found by | What to do |
|---|---|---|
| A param a rule reads is gone or renamed | `--against`: ✗, with the closest new names | fix the rule in the new version's template |
| A param's default flips a rule on a default run | `--against`: ✗ | check the release's code, adjust the rule |
| A new `skip_*` flag | `--against`: ➕ | a route to verify (below) |
| A file the template reads moved | `nfcore_monitor.py` (megatest paths, recipes run on the release's data) | repoint the collection |

The weekly `nfcore-release-monitor` workflow runs both for every release and
opens one wave PR (`nf-core wave: …`), each pipeline with a verdict; a broken
rule is ❌ review needed even when the release has no megatest run yet. Then
`python scripts/bump_template_version.py --pipeline <p> --new-version <v>`
copies the template, rules included; CI's `template check --all
--fetch-schema` holds the new version to its own schema.

What stays a person's call is what a *new* flag removes from the outputs. It
can be settled without one, by running the pipeline's `-profile test` with and
without the flag and comparing `depictio ingest <outdir> --dry-run`: the
collections that lose their files are the ones the conditional must drop.
