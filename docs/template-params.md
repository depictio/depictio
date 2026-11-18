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

Detection is deterministic: the same two runs always give the same report.
Deciding what to do with a change the template does not cover yet (a new
output, a step redesigned) is still a person's call, or a model's; it is rare
in nf-core pipelines, and every change it has to judge is listed for it.

```bash
# Rules against the two schemas, no run needed
depictio template check nf-core/rnaseq/3.26.0 --against 3.27.0

# The template run on the run it was built on and on the release's run
python scripts/nfcore_drift.py --template nf-core/ampliseq/2.18.0 \
  --old s3://nf-core-awsmegatests/ampliseq/results-<pinned sha>/ \
  --new s3://nf-core-awsmegatests/ampliseq/results-<release sha>/   # or a local -profile test outdir
```

`nfcore_drift.py` resolves the template on both runs exactly as `depictio
ingest` does (auto-detection, `from_params` rules, conditionals), then builds
every collection: scans read, recipes run in dependency order with their
`dc_ref` inputs. It compares the two in five layers:

| Layer | What it reports | Example (ampliseq 2.18 → 3.1) |
|---|---|---|
| Files | a collection or a recipe source that found files and finds none, optional or not, with the release's closest new file | ❌ `rel-table-ASV_with-DADA2-tax.tsv` → likely `…DADA2-sbdi-gtdb-tax.tsv`; the recipe was silently using its fallback |
| Columns | columns removed (❌ when the recipe declares or names them), renamed in place, added (a family such as `*_confidence` is named); a header made of data (taxa, samples) is summarised | `Kingdom` → gone in the renamed table, 7 new `*_confidence` columns |
| Tables | a collection that built and now fails or loses a column (❌); rows, nulls, categories, a unit (scale ×100) and, on rows paired by their key across the two runs, values that anti-correlate (a flipped sign convention) | tip metadata: `Family` 14 % → 71 % null |
| Parameters | the two schemas (removed, renamed by description or close name, default or type changed; ❌ for a param a rule reads) and the two runs' own `params.json`, nested values included | `taxlevels` lost its `Kingdom`: the Phylum moved one level up |
| Outputs | folders of the release's run that the old run lacked and no collection reads | `summary_tables/` |

`nfcore_monitor.py report` runs it whenever the template pins a megatest run
and the release has one; a ❌ in it makes the verdict ❌ review needed. When the
release has no megatest run, run its `-profile test` (the
`nfcore-release-testrun` workflow keeps the outdir as an artifact) and pass the
outdir as `--new`; a test profile exercises fewer routes than a megatest, so
read a lost collection there against the profile's settings first.

The weekly `nfcore-release-monitor` workflow opens one wave PR (`nf-core wave:
…`), each pipeline with a verdict. Then `python scripts/bump_template_version.py
--pipeline <p> --new-version <v>` copies the template, and CI's `template check
--fetch-schema` holds each changed template to its own release's schema (every
template, weekly and when the checker changes).

On that pull request, the `template-drift` workflow runs `python
scripts/nfcore_monitor.py bump --target <p>/<v>`: the version it was copied from,
on its pinned run, against the new copy on the release's own run. A path the
copy already fixed is then no finding; what remains is posted as a comment, and
an error fails the check. Run the same command locally before pushing.

What a *new* flag removes from the outputs can be settled the same way: run the
pipeline's `-profile test` with and without it and pass both outdirs to
`nfcore_drift.py`: the collections that lose their files are the ones the
conditional must drop.
