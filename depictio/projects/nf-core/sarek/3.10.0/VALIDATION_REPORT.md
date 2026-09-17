# nf-core/sarek 3.10.0: template ingestion validation report

**Date:** 2026-09-17
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2`
**Validator:** local depictio-cli dry run + recipe execution against the real megatest data +
`pytest`. No server was available in this session, so this report does **not** cover a live
ingestion (see "Not covered" below).

## Goal

Build the sarek 3.10.0 template and the `bcftools` catalog tool it owns
(`bcftools/stats_summary`, `bcftools/stats_tstv`), covering germline variant calling with five
callers side by side on the same two samples.

## Data used

AWS megatest run `results-8ccac7ad37b05dd792447763bf9671b719824587` (the 3.10.0 release tag),
`test_full_germline_ncbench_agilent/` profile: `~/Data/depictio-nfcore/sarek/3.10.0/megatest/`,
185 files. One patient row per sample (see SK-D2), two samples (`NA12878_75M`, `NA12878_200M`),
five germline callers (DeepVariant, FreeBayes, HaplotypeCaller, Manta, Strelka), both annotators
(SnpEff, VEP). `megatest.yaml` and `input/` were already refined before this agent started.

## template.yaml and dashboard structure

6 data collections: `samples` (hub, transformed via `nf-core/sarek/samples.py`), `samplesheet`
(scan), `multiqc_data` (native MultiQC 1.35, 10 modules), `bcftools_stats_raw` (scan, feeds the
next two via `dc_ref`), `bcftools_stats_summary` and `bcftools_stats_tstv` (both transformed via
the new `bcftools` catalog tool). 4 links: hub -> MultiQC (`sample_mapping`), hub -> both
bcftools-stats collections (`direct`), and a cross-link between the two bcftools-stats
collections.

2 dashboard tabs, 45 components across 9 sections (30 on MultiQC, 15 on Variant calling): 11
text tiles, 18 MultiQC panels, 3 interactive filters, 5 cards, 3 figures, 5 tables, 1 advanced
visualisation (a `dot_plot` over `bcftools/stats_summary`: log10(records) as colour, SNP
fraction as size, one dot per sample and caller). 28 of the 31 non-text/non-interactive tiles
carry a `use:` catalog reference (90.3 %); the 3 that do not are the `samples`-collection card
and table (no catalog owner, `samples` is a pipeline-local hub, matching every other template
in this repo) and one custom bar figure (`sk-vc-fig-indels`) that intentionally shares its
section's already-declared `n_indels` story rather than adding a second near-duplicate catalog
render.

## New catalog tool: `bcftools` (`stats_summary`, `stats_tstv`)

`depictio/catalog/bcftools/`: `module.yaml`, `stats_summary.{yaml,py,tsv}`,
`stats_tstv.{yaml,py,tsv}`. Both outputs read the same raw scan
(`bcftools_stats_raw`, `**/*.bcftools_stats.txt`) through `dc_ref`, because the caller and the
sample both live only in the directory path
(`reports/bcftools/<caller>/<sample>/<file>.bcftools_stats.txt`), never in the file's own
content. Pipeline-agnostic by design (matches the brief: "shared output... sarek owns");
any workflow running `bcftools stats` per caller per sample with the same path shape lands in
the same two collections.

`stats_summary` also carries two derived columns purely to give the caller-comparison dot plot
a natural (not contrived) binding: `snp_fraction` (already 0-1, `frac_expressing`) and
`log10_n_records` (`mean_expression`, so Manta's ~2-orders-of-magnitude-smaller record count
still reads on the same plane as the four SNP/indel callers).

Both recipes and `depictio/projects/nf-core/sarek/recipes/samples.py` were executed directly
against the real megatest files (not just unit-tested against the fixture) and their output was
hand-verified against a from-scratch Python re-implementation of the same bcftools-stats
parsing logic:

| Collection | Rows | Columns | Schema |
|---|---|---|---|
| `bcftools_stats_summary` | 10 (2 samples x 5 callers) | 12 | all match `EXPECTED_SCHEMA` |
| `bcftools_stats_tstv` | 10 | 8 | all match `EXPECTED_SCHEMA` |
| `samples` | 2 | 6 | all match `EXPECTED_SCHEMA` |

## New MultiQC panels: `gatk`, `vcftools`, `vep`

`depictio/catalog/multiqc/{gatk,vcftools,vep}.yaml`. sarek's megatest is the first pipeline in
this repo to need these three modules, so their `section:` plot titles were read directly off
`multiqc.list_plots()` run against this run's own `multiqc.parquet` (not copied from another
pipeline's report, which would have been a guess): `gatk -> ["Observed Quality Scores"
{sub-datasets}, "Reported Quality vs. Empirical Quality"]`, `vcftools -> ["TsTv by Count",
"TsTv by Qual"]`, `vep -> ["General Statistics", "Variant classes", "Consequences"
{sub-datasets}, "SIFT summary", "PolyPhen summary", "Variants by chromosome", "Position in
protein"]`. `bcftools`, `fastqc`, `fastp`, `samtools`, `mosdepth`, `picard`, `snpeff` panels
already existed in git and were reused as-is (not edited), after confirming their existing
`selected_module`/`selected_plot` convention against this run's own `list_plots()` output too
(all match).

Since no existing checked-in MultiQC parquet fixture in this repo carries `gatk`/`vcftools`/
`vep` (the shared `catalog_conformance` fixture the brief's `preseq.yaml` example points at does
not either), the three new panels got stub builders in
`catalog_conformance/scripts/multiqc_stubs.py` and their `fixture:` is the conformance parquet.

## Validation performed (no server available)

```bash
depictio/cli/.venv/bin/depictio-cli run --template nf-core/sarek/3.10.0 \
  --data-root ~/Data/depictio-nfcore/sarek/3.10.0/megatest --dry-run
# -> 8/8 steps passed: template resolved, DC scans matched real files, dashboard imported
```

```bash
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k sarek
# -> 10 passed
uv run pytest depictio/tests/models/test_catalog.py -q
# -> 97 passed, 2 failed (both pre-existing, unrelated to this pipeline, see SK-D5)
```

`ruff format` / `ruff check` / `pre-commit run --files` all pass clean on every file this agent
wrote.

### Not covered

No server was reachable from this session ("Do NOT ingest" per the brief), so this report does
not include: a live ingestion result, a post-ingest per-collection row/column table read back
from Delta Lake, card/figure/advanced-viz compute results against a running API, or the
`test_multiqc_tabs_hold_only_multiqc_panels` / section-icon / layout tests being exercised
against a real render. The dry run and the direct recipe execution above are the strongest
signal available without one.

## Discrepancies

### SK-D1: `sample_mapping` does not canonicalise sarek's per-tool MultiQC sample names

The hub's `sample_id` values are `NA12878_75M` / `NA12878_200M`. sarek's own MultiQC report
names the same sample differently per module: `NA12878_75M-1_1` (FastQC/fastp, lane + read
suffix), `NA12878_75M.md` / `NA12878_75M.recal` (samtools/picard/mosdepth, processing-stage
suffix), `NA12878_75M.deepvariant` / `NA12878_75M.freebayes.filtered` / `..._snpEff` /
`..._VEP.ann` (bcftools/snpeff/vep/vcftools, caller + annotator suffix). The
`sample_mapping` link resolver's canonicalisation regex
(`depictio/cli/cli/utils/sample_mapping.py::build_sample_mapping`,
`^([A-Za-z0-9_-]+?)(?:_[12])?(?:\s+-\s+.+)?$`) only strips a trailing `_1`/`_2` read suffix or a
`" - annotation"` suffix, it does not strip `.md`/`.recal`/`.deepvariant`/`.freebayes.filtered`
dot-joined suffixes, and it does not strip a `-1` lane marker either. Concretely: `NA12878_75M.
deepvariant` does not match the regex at all (dots aren't in the character class) and falls
back to being treated as its own canonical id, distinct from `NA12878_75M`. Practically, this
means the persistent `Sample filters` picker linked to `multiqc_data` via `sample_mapping` is
unlikely to actually narrow most of the MultiQC panels on this template when a single sample is
picked, even though the panels themselves render correctly with no filter applied. This is a
gap in the shared `sample_mapping.py`, not something a template can work around, flagged here
rather than fixed, since that file is outside this agent's edit scope (not a pipeline dir or a
catalog tool). The `direct` links to `bcftools_stats_summary`/`bcftools_stats_tstv` are
unaffected: those collections' `sample` column is derived by this template's own recipes off
the directory path, not off a MultiQC sample name, so it already matches the hub exactly.

### SK-D2: the megatest samplesheet's `patient` column is not a shared "NA12878"

The brief describes this megatest as "1 patient (NA12878), 2 samples". The samplesheet itself
(`input/NA12878_Agilent_full_test.csv`) instead has `patient == sample` on both rows
(`NA12878_200M,0,NA12878_200M,...` and `NA12878_75M,0,NA12878_75M,...`): the two read-depth
conditions are the same individual biologically, but the samplesheet structurally encodes them
as two distinct patients, not one patient with two samples. `samples.py` reflects the
samplesheet as published (`patient` column equals `sample_id` for both rows) rather than the
biological framing; `status` is `0` (normal) for both either way, since this is the germline
route. Noted in `docs/dashboards.md` so a reader does not expect a shared "NA12878" value to
filter both samples together on that column (the hub has no such column to filter on).

### SK-D3: `bcftools stats`' variable row width broke the first scan design, twice

`bcftools stats` writes `SN` rows (4 tab fields) before any `TSTV` row (8 fields), and
`has_header: false` infers the scanned CSV's column count from the file's first data row. A
first design using `new_columns: [c0..c7]` with `truncate_ragged_lines: true` failed at
`depictio-cli run --dry-run` time with `polars.exceptions.ShapeError: The length of the new
names list should be equal to or less than the original column length`: the SN row (4 fields)
sets the inferred width, and no `new_columns` list longer than that is ever accepted, so `TSTV`'s
columns 5-8 (`ts`, `tv`, `ts/tv`, ...) could never be read. Fixed by scanning with a separator
that never appears in the file (`\x1e`), so every full line lands in one `raw_line` text column
regardless of its internal tab count, and the two recipes split it themselves after filtering to
the record type they read. Caught only by actually running the dry run against real data, not
by the fixture-based unit shape, the fixture's 10 hand-picked rows do not exercise the
column-count-inference order dependency the real 92,462-row scan does.

### SK-D4: Manta's bcftools stats read as near-zero, which is correct

Manta is the one structural-variant caller among the five; its `bcftools stats` report has
`ts=0 tv=0 ts_tv=0.0` and `n_snps=0` for both samples (72 and 57 total records, almost all
landing in `n_others`, bcftools' bucket for symbolic/complex alleles). Every dashboard tile that
shows Manta alongside the four SNP/indel callers says so in its description; nothing was
filtered or special-cased in the recipes, since a caller reporting genuinely near-zero SNPs is
the correct output for a structural-variant caller, not a data gap.

### SK-D5: two catalog schema tests fail, pre-existing and outside this agent's scope

`test_catalog.py::test_committed_json_schema_is_current` fails for `catalog.schema.json` and
`output.schema.json` (both stale relative to the current `CatalogEntry`/`CatalogOutput`
Pydantic models). `git diff --stat` on `depictio/models/components/advanced_viz/{configs,
schemas}.py` confirms those models changed in this worktree (the lot-2 kinds work: `contact_map`,
`knee_plot`, `damage_profile`) while the two committed `*.schema.json` files did not. Fixing
this needs `depictio dev catalog schema --model ... -o depictio/catalog/*.schema.json`, which
touches files outside every agent's per-pipeline/per-catalog-tool edit scope in this lot, noted
here for whoever owns the kinds/schema regen step, not fixed.

### SK-D6 (transient, self-resolved): catalog-wide validation briefly broke on another pipeline's WIP file

Mid-session, `test_advanced_viz_components_validate[...sarek.../base.yaml]` failed three times
in a row with three different errors, each pointing at a different **other** pipeline's catalog
tool folder under active edit by a parallel agent (`depictio/catalog/cellbender`: invalid
`nf_core_url`; then `depictio/catalog/cellranger`: a `bool` where a `str` was expected in
`dict_kwargs`; then a render-id collision in the same folder). Catalog loading is all-or-nothing
(`load_catalog_entries()` walks every tool directory and raises on the first invalid one), so
any test that resolves a `use:` reference transitively validates the *entire* catalog, not just
this template's own tool. Each failure disappeared on the next run without this agent touching
anything, confirming the cause was concurrent edits elsewhere, not this template. `bcftools` and
the three new `multiqc/*.yaml` panels were also verified to load cleanly in isolation via
`_load_tool_dir()` at every point during this session, independent of the rest of the catalog's
state.
