# nf-core/eager 2.4.5: template ingestion validation report

**Date:** 2026-09-17
**Worktree / branch:** `feat-nfcore-templates-lot2` (`feat/nfcore-templates-lot2`)
**Validator:** `depictio/cli/.venv/bin/depictio-cli run --dry-run` against the local server
this worktree's config resolves; recipes also exercised directly against the real data with
`uv run python3` (no ingestion, see "Do NOT ingest" in the brief this was built against).

## Goal

Build the nf-core/eager 2.4.5 template: the ancient-DNA QC funnel from raw reads through
mapping, duplication and coverage to the DamageProfiler misincorporation signature that
authenticates the DNA as ancient, and the genotypes called from what survives. Own the
shared catalog outputs `samtools/flagstat` and `qualimap/bamqc_genome_results`, and bind a
DamageProfiler misincorporation recipe to the new `damage_profile` advanced-viz kind
(`sample, end, position, base_change, frequency`) the kinds workstream was adding in
parallel.

## Data used

`~/Data/depictio-nfcore/eager/2.4.5/megatest/`: already fetched and MultiQC-reprocessed to
the 1.35 parquet before this work started. Two Atlantic cod libraries, `COD076E1bL1` (three
lanes, ERR1943600/601/602) and `COD092E1bL1i69` (three lanes, ERR1943607/608/609), mapped
with BWA, deduplicated with Picard MarkDuplicates and damage-profiled with DamageProfiler.
`megatest.yaml` and `input/benchmarking_vikingfish.tsv` were refined before this task and
were not further edited.

```bash
bash depictio/projects/nf-core/eager/2.4.5/download_test_data.sh
```

fetches everything **except** the samplesheet, see the next section.

## The samplesheet is not part of the megatest fetch

Unlike ampliseq, rnaseq or cutandrun, eager's AWS test bucket carries no `input/` prefix and
no `pipeline_info/params.json` to recover the run's `--input` TSV from (eager 2.x predates
the nf-core params dump). `input/benchmarking_vikingfish.tsv` is therefore a
hand-reconstructed manifest against the six ENA runs the megatest fetched, it ships with
the template but is **not** copied into `DATA_ROOT` by `download_test_data.sh` or by the
megatest fetch. A real run needs it placed by hand:

```bash
mkdir -p "$DATA_ROOT/input"
cp depictio/projects/nf-core/eager/2.4.5/input/benchmarking_vikingfish.tsv "$DATA_ROOT/input/"
```

This was done against the local `~/Data/depictio-nfcore/eager/2.4.5/megatest/` copy before
running the commands below. **Discrepancy EA-D1** (see below).

Also unlike ampliseq/rnaseq, the samplesheet's `SAMPLESHEET_FILE` auto-detection
(`depictio/cli/cli/utils/templates.py`, `_auto_detect_metadata_columns` neighbourhood) only
recognises a filename containing the substring `samplesheet`: `benchmarking_vikingfish.tsv`
does not match it. The `samples` recipe therefore reads a **fixed** path
(`input/benchmarking_vikingfish.tsv`, matching the cutandrun `samples.py` convention of a
fixed `pipeline_info/samplesheet.valid.csv` rather than a `{SAMPLESHEET_FILE}` variable) so
no `--var` or auto-detection is needed, but this only works if the file keeps this exact
name. **Discrepancy EA-D2.**

## software_versions.csv, not .yml

eager 2.4.5 is DSL1: `pipeline_info/software_versions.csv` is a flat two-column
`tool<TAB>version` table (35 rows), not the DSL2 `CUSTOM_DUMPSOFTWAREVERSIONS` nested YAML
cutandrun's `pipeline_info/software_versions.yml` deliverable is. The bundled copy here keeps
the `.csv` name and the real layout; `template.yaml`'s `provenance.sources` reads it with
`format: "tsv"` (a 2-column key/value reader), which the model layer accepts natively, no
conversion needed. **Discrepancy EA-D3** against the brief's `pipeline_info/software_versions.yml`
deliverable name.

## Three raw-scan-plus-recipe two-step DCs, not the freeform-text norm

`samtools/flagstat.py` and `qualimap/bamqc_genome_results.py` read genuinely freeform text
reports (`samtools flagstat`'s twelve fixed-label lines; Qualimap's `key = value` sections)
that never name the sample inside the file, only the path does. Both follow the
`preseq/complexity_curve.py`-documented idiom (raw DC scan with `include_file_paths`, then a
`dc_ref` recipe) but had no tabular structure to scan, so the raw DC reads one LINE per row
(`separator` set to `\x1f`, the same trick `catalog/ataqv/metrics.py` uses for JSON) and the
recipe reassembles + regex-parses each file's lines. `damageprofiler/misincorporation.py`'s
raw file IS a real TSV (three `#`-prefixed comment lines then a header), so its DC is a plain
TSV scan with `comment_prefix: "#"`; only the sample (parent directory) and the read end
(filename) needed recipe-side parsing. All three verified against the real files (see
Commands run).

## preseq recipe override

`depictio/catalog/preseq/complexity_curve.py`'s sample-id helper
(`strip_stage_suffixes`) does not know eager's `<library>.filtered.preseq` naming (`filtered`
and `preseq` are not in its stage-token list), so it would return the whole file stem
unchanged. `depictio/projects/nf-core/eager/recipes/complexity_curve.py` is a pipeline-local
override with the identical output schema (`use: preseq/complexity_curve` in the dashboard
is unaffected); see `docs/dashboards.md` for the full rationale. eager's `lc_extrap` run also
wrote no bootstrap CI, so `lower_ci`/`upper_ci`/`ci_width` are present but always null.
**Discrepancy EA-D4** (not a bug, documents why the recipe path differs from the catalog's).

## damage_profile: a lot-2 kind

`damageprofiler/misincorporation.yaml` binds `kind: damage_profile`
(roles: `sample, end, position, base_change, frequency`). At the time this template was
built, `depictio/models/components/advanced_viz/{configs,schemas,types}.py` already declared
the kind, its `DamageProfileConfig` (default column names `sample`/`end`/`position`/
`base_change`/`frequency`, matching this recipe's output exactly, no `config:` overrides
needed on the dashboard tile) and its `ROLE_NAMES`/`CANONICAL_SCHEMAS`/`KIND_METADATA`
entries, the kinds workstream had landed its models before this template's validation pass.
`uv run pytest depictio/tests/models/test_catalog.py -q` and
`test_shipped_dashboard_yamls.py -q -k eager` both pass with the binding live; no fallback
or workaround was needed. If a future rebase reverts the kind ahead of this template's own
merge, the `use: damageprofiler/misincorporation` advanced-viz tile
(`ea-dmg-av-profile` in `dashboards/base.yaml`) is the one to watch, everything else on that
tab (the figure, the card, the table, the two MultiQC panels) is kind-independent.

## bcftools: referenced, not owned

nf-core/sarek owns `bcftools/stats_*` (its `depictio/catalog/bcftools/` was present,
mid-build, in this shared worktree throughout, not edited). The Genotyping tab therefore
binds only the `multiqc/bcftools` MultiQC panels (Substitution types, Variant quality, Indel
distribution, Variant depths); no `bcftools/stats_summary` or `_tstv` table is referenced
from this template, to avoid depending on an output that may not exist yet when this
template's own tests run standalone.

## Commands run

```bash
# Catalog validation (whole catalog was briefly broken mid-build by a concurrent
# agent's in-progress depictio/catalog/bcftools/; retried after it stabilised, see
# "Cross-agent worktree note" below)
uv run pytest depictio/tests/models/test_catalog.py -q
# 97 passed, 2 failed: test_committed_json_schema_is_current[catalog.schema.json/output.schema.json]
#, pre-existing, unrelated to this template (see Discrepancy EA-D5).

uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q
# 809 passed, 4 failed, all pre-existing/unrelated to eager:
#   test_advanced_viz_components_validate / _survives_the_component_union
#     [nf-core/nanoseq/3.0.0/dashboards/base.yaml]              (nanoseq workstream, in progress)
#   test_section_icons_and_colors_are_bundled
#     [projects/init/advanced_viz_showcase/dashboards/{contact_map,knee_plot}.yaml]
#                                                                  (kinds workstream, in progress)
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k eager
# 10 passed, 0 failed.

# Each recipe's transform() run directly against the real DATA_ROOT files (not through
# the CLI loader), schema + shape printed and spot-checked against the source reports:
#   samtools/flagstat.py            -> 4 rows (2 libraries x 2 stages)
#   qualimap/bamqc_genome_results.py -> 2 rows (one per library)
#   damageprofiler/misincorporation.py -> 180 rows (2 libraries x 2 ends x 15 positions x 3 classes)
#   nf-core/eager/recipes/samples.py -> 2 rows (one per library)
#   nf-core/eager/recipes/complexity_curve.py -> 399 rows total across both libraries, thinned

mkdir -p ~/Data/depictio-nfcore/eager/2.4.5/megatest/input
cp depictio/projects/nf-core/eager/2.4.5/input/benchmarking_vikingfish.tsv \
   ~/Data/depictio-nfcore/eager/2.4.5/megatest/input/

depictio/cli/.venv/bin/depictio-cli run --template nf-core/eager/2.4.5 \
  --data-root ~/Data/depictio-nfcore/eager/2.4.5/megatest --dry-run
# ✅ Depictio-CLI run completed successfully! (8/8 steps), server accessibility, S3, project
# validation, config sync, scan, process, joins and dashboard import all passed. No ingestion.

uv run ruff format <5 recipe .py files> && uv run ruff check <same>       # clean
pre-commit run --files <every file this template touched>                  # all hooks passed
```

## Cross-agent worktree note

`depictio/catalog/bcftools/` (nf-core/sarek's, untracked) briefly failed
`CatalogOutput` validation (`renders_as.0.title: Extra inputs are not permitted`) while that
agent's work was mid-flight in this shared worktree; it was not edited from here, and a later
retry of the full `test_catalog.py` run found it fixed. Flagging in case the timing differs
on a rebuild: a global `load_catalog_entries()` failure with `bcftools` in the traceback is
not this template's bug.

## `use:` coverage

36 of 38 dense (non-text, non-interactive) dashboard tiles carry a `use:`: 94.7%, above the
brief's ~90% target. The two without one are the library-hub card and table (no catalog
module owns a pipeline's own sample sheet, the convention every other nf-core template
here follows).

## Open questions

- Whether `EA-D2`'s fixed-path samplesheet convention should instead grow a
  `SAMPLESHEET_FILE` variable + auto-detection support for non-`samplesheet`-named files, so
  a future ancient-DNA template with a differently-named manifest does not need its own
  special case.
- Whether `endorS.py`'s endogenous-DNA percentage (currently reachable only through the
  MultiQC general-stats panel, since it is `generalstats`-only custom content with no
  dedicated MultiQC section) deserves a small dedicated `endorspy/` catalog tool and card ,
  out of scope for this pass since the brief only named `samtools/flagstat`,
  `qualimap/bamqc_genome_results` and the damage-profile binding.
