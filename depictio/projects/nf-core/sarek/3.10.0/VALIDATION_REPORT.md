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

---

# Remediation pass, 2026-09-22

**Date:** 2026-09-22
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2` (`feat/nfcore-templates-lot2`)
**Validator:** local depictio-cli dry run + recipe execution against the real megatest data +
`pytest` + **a live ingestion and per-tab screenshots against a running stack** (API
`http://localhost:8112`, viewer `http://localhost:5612`, Mongo `localhost:27112`). Unlike the
2026-09-17 pass, this one did cover a live server.

## What changed

The 2026-09-17 pass shipped 2 tabs and 45 components, with the variant-level panels blocked on
the megatest manifest deliberately not fetching any VCF. This pass fetched the VCFs and built
the variant-level half of the template.

**Fetched (20 files, 44 MB), added to `megatest.yaml`:** per-sample per-caller
`variant_calling/deepvariant/*/*.deepvariant.vcf.gz`, `variant_calling/*/*/*.filtered.vcf.gz`,
`variant_calling/manta/*/*.diploid_sv.vcf.gz`, `variant_calling/strelka/*/*.variants.vcf.gz`,
and `annotation/*/*/*_snpEff.ann.vcf.gz`. Deliberately still not fetched: `*.g.vcf.gz` and
`*.genome.vcf.gz` (gVCF, one record per reference block, no value in a call-level view) and
`*_VEP.ann.vcf.gz` (SnpEff's annotation already covers the annotated-call panels; VEP's own
summary is on the MultiQC tab). The full manifest dry run now reports 196 files / 104.3 MB.

**New shared library:** `depictio/recipes/lib/vcf.py`, a pure-Polars VCF reader. bgzip is
gzip-compatible, so `pl.scan_csv` reads a `.vcf.gz` with no new dependency: 286,633 plain
records scan in 0.1 s, 371,068 annotated records in 0.2 s. `vcf_to_long()` returns one row per
variant (sample, caller, chrom, pos, variant_key, ref, alt, variant_type, qual, filter_status,
is_pass, gt, dp, vaf), and with `with_annotation=True` also splits SnpEff's first `ANN` entry
into gene, gene_id, impact, consequence, hgvs_p and aa_pos.

**New catalog outputs (15 across 5 tool dirs):**

| Tool dir | Outputs added |
| --- | --- |
| `depictio/catalog/vcf/` (new) | `variants` |
| `depictio/catalog/snpeff/` (new) | `ann_variants`, `variant_upset`, `protein_lollipop`, `csv_stats`, `genes`, `gene_upset`, `gene_heatmap`, `oncoplot` |
| `depictio/catalog/vcftools/` (new) | `filter_summary`, `tstv_qual` |
| `depictio/catalog/mosdepth/` | `regions`, `summary`, `xy_sex_check` (`amplicon_coverage` untouched) |
| `depictio/catalog/bcftools/` | `stats_sections` |

**template.yaml:** 6 data collections and 4 links became 33 and 24, including four
`optional: true` somatic collections (`ascat_segments`, `cnvkit_segments`,
`msisensorpro_summary`, `ngscheckmate_matches`) carrying their real output globs so a somatic
`test_full` run lights them up without a template change. `samples.py` gained a
`read_depth_label` string column (`75M reads` / `200M reads`), because the Int64
`read_depth_millions` can only drive a slider, never a MultiSelect.

**dashboards/base.yaml:** 2 tabs / 45 components became 6 tabs / 131 components, 80 tiles of
which 77 carry a `use:` (96%). Every tab has a 4-card glance strip, an intro text tile and its
own tab-local filters; box-plot cards went from 0/5 to present on every distribution tab.

## Live validation performed

```bash
depictio-cli run --template nf-core/sarek/3.10.0 --data-root <megatest> --dry-run
# -> 8/8 steps passed, 0 errors, 0 warnings

# project lot2-sarek wiped first (DELETE /projects/delete), then ingested once:
uv run python -m depictio.cli run --template nf-core/sarek/3.10.0 \
  --data-root ~/Data/depictio-nfcore/sarek/3.10.0/megatest --project-name lot2-sarek
# -> 8/8 steps, 29 data collections processed, 4 optional skipped, no other error

uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -k sarek -q
# -> 10 passed
```

**Row counts, read back from `/deltatables/shape/{dc_id}` after the ingest.** All 29
non-optional collections have rows; the 4 optional ones have no Delta table, as intended.

| Collection | Rows x cols | Collection | Rows x cols |
| --- | --- | --- | --- |
| `samples` | 2 x 7 | `snpeff_ann_variants` | 371,068 x 20 |
| `samplesheet` | 2 x 8 | `snpeff_variant_upset` | 52,644 x 11 |
| `bcftools_stats_summary` | 10 x 12 | `snpeff_protein_lollipop` | 13,993 x 9 |
| `bcftools_stats_tstv` | 10 x 8 | `snpeff_csv_stats` | 510 x 6 |
| `bcftools_stats_sections` | 92,362 x 6 | `snpeff_genes` | 163,557 x 11 |
| `mosdepth_regions` | 10,836 x 8 | `snpeff_gene_upset` | 3,000 x 6 |
| `mosdepth_summary` | 204 x 9 | `snpeff_gene_heatmap` | 40 x 11 |
| `mosdepth_xy_sex_check` | 4 x 6 | `snpeff_oncoplot` | 253 x 4 |
| `vcftools_filter_summary` | 48 x 9 | `vcf_variants` | 286,631 x 14 |
| `vcftools_tstv_qual` | 1,757 x 7 | `multiqc_data` | 1 parquet file |

**Per-tab screenshots** (headless Chromium, 1600x1000): one per tab under
`/tmp/claude-502/shots-sarek/`, plus a tall variant capturing the whole scroll container.

## Discrepancies found in this pass

### SK-D1 (fixed): `sample_mapping` now carries explicit mappings

SK-D1 above described `sample_mapping`'s canonicalisation regex failing on sarek's dot-joined
per-tool MultiQC sample names. The resolver itself is shared code outside this template's edit
scope, but the link accepts an explicit `mappings: {canonical: [variants]}` block, which is.
The MultiQC link now lists the 20 MultiQC sample-name variants per sample read directly off the
run's `multiqc.parquet` (`-1`, `-1_1`, `-1_2`, `.md`, `.recal`, `.deepvariant`,
`.deepvariant_snpEff`, `.deepvariant_VEP.ann`, `.freebayes.filtered[...]`,
`.haplotypecaller.filtered[...]`, `.manta.diploid_sv[...]`, `.strelka.variants[...]`). The
underlying regex gap in `depictio/cli/cli/utils/sample_mapping.py` is unchanged and still worth
fixing for templates that cannot enumerate their variants.

### SK-D7: two FreeBayes VCFs in the bucket are Fusion symlink targets, not VCFs

`variant_calling/freebayes/NA12878_{75M,200M}/*.filtered.vcf.gz` are 196-byte ASCII files whose
entire content is a Fusion path (`/fusion/s3/nf-core-awsmegatests/work/sarek/work-8ccac7ad.../...`).
They are not gzip, so a reader that decompresses them raises `not in gzip format`. The raw-line
scan design absorbs this: each file contributes one junk line that the recipe's data-line regex
drops, rather than failing the whole collection. Practical effect: FreeBayes contributes 0 rows
to `vcf_variants` and is absent from the variant-level UpSet, while its SnpEff-annotated twins
(`annotation/freebayes/...*_snpEff.ann.vcf.gz`) are complete (42k and 43k calls) and do reach
`snpeff_ann_variants`. This is a publication defect in the megatest bucket, not a template or
pipeline issue.

### SK-D8: Manta's VCFs are real, correcting an earlier note

An earlier note recorded both FreeBayes and Manta VCFs as 0 bytes on S3. Manta's are in fact
complete (26 KB and 41 KB, 57 and 72 SV records), consistent with SK-D4's bcftools-stats
reading. Only FreeBayes' are defective, and not as zero-byte objects but as SK-D7's symlink
targets.

### SK-D9: `.md` and `.recal` mosdepth region files are byte-identical

`<sample>.md.regions.bed.gz` and `<sample>.recal.regions.bed.gz` have matching md5s on this
run: BQSR changes base qualities, not alignment positions, so per-target depth is unchanged.
`mosdepth_regions` therefore carries each window twice, once per pass, and the `mosdepth pass`
filter on the Cohort QC tab exists so a reader can collapse that duplication rather than
mistake it for two conditions. The `.recal` summaries are not identical: they drop chrM (50 rows
against `.md`'s 52).

### SK-D10: `bcftools stats` column offsets are not where the brief placed them

Building `bcftools_stats_sections` needed three corrections against the brief's field offsets:
the `DP` block's count is field 5 ("number of sites"), not field 4 (a fraction) and not field 3
(identically 0 unless bcftools ran with `-s`/`-S`); `SiS` keeps fields 3 and 6 (singleton SNPs,
singleton indels). `QUAL`, `AF` and `ST` matched. Also worth recording for any future panel: the
`quality` block alone is 97% of the collection's 92,362 rows, so a bar chart over all sections
pooled is unreadable and the section filter is load-bearing, not a convenience.

### SK-D11: `genomespy_track` is not a registered kind, `genome_view` superseded it

The brief asked for a `genomespy_track` tile beside the `coverage_track` one.
`AdvancedVizKind` in `depictio/models/components/types.py` has no such member: the spike's
single-track kind was replaced by the multi-track `genome_view`, which takes the same
`mark: rect` / `end_col` configuration plus per-sample lanes. Both the mosdepth regions tile and
the VCF call tile use `genome_view`.

### SK-D12: polars 1.43.2 `read_csv` has no `include_file_paths`

A `RecipeSource` that resolves a glob reads with `pl.read_csv`, which in the pinned polars
(1.43.2) does not accept `include_file_paths`; only `scan_csv` does. Any recipe that derives
`sample` or `caller` from a file name therefore cannot use a glob source and must go through a
raw-scan data collection with `dc_ref`. That is why every new collection here comes in raw plus
transformed pairs (`vcf_calls_raw` / `vcf_variants`, `snpeff_genes_raw` / `snpeff_genes`, and so
on) rather than a single glob-sourced recipe. `xy_sex_check` is the one glob-sourced recipe, and
it needs no file-name identity because it reads the already-keyed summary rows.

### SK-D5 (unchanged): catalog schema regen still owed, and four failures that are not this template's

Final run of the catalog suite in this pass:

```bash
uv run pytest depictio/tests/models/test_catalog.py -q
# -> 4 failed, 95 passed
```

None of the four belong to this template, and all four name another agent's tool directory or a
shared file outside every template agent's edit scope:

- `test_committed_json_schema_is_current[catalog.schema.json]` and `[output.schema.json]`: the
  two committed `*.schema.json` files are stale against the current `CatalogEntry` /
  `CatalogOutput` models, unchanged since 2026-09-17. Fixing needs
  `depictio dev catalog schema --model {entry,output} -o depictio/catalog/<file>`, and
  `depictio/catalog/*.schema.json` is a shared file this agent may not edit.
- `test_every_bundled_card_declares_a_secondary_strip`: six bare cards in `cellbender`,
  `kallisto`, `qcatch` and `simpleaf`.
- `test_cli_validate_exits_zero_on_bundled_catalog`: three non-numeric card aggregations in
  `cellranger`, `cooltools` and `gtdbtk`.

Catalog loading is all-or-nothing, so any test that resolves a `use:` transitively validates
every tool directory. The five this template owns were confirmed to load cleanly in isolation at
the end of the pass, and the catalog as a whole loads (75 entries):

```
vcf OK outputs=1 | snpeff OK outputs=8 | vcftools OK outputs=2
mosdepth OK outputs=6 | bcftools OK outputs=3
```

## Known gap in this pass: five of six tabs could not be screenshotted

Tab 1 (MultiQC) renders correctly and was captured (23 tiles, no error markers). Tabs 2 to 6
could not be: the shared viewer dev server on `localhost:5612` is failing to transform
`packages/depictio-react-core/.../advanced_viz/AdvancedVizDispatch.tsx`, with

```
[plugin:vite:import-analysis] Failed to resolve import "@genome-spy/core/genome/genomes.js"
  from ".../advanced_viz/genomespy/useGenomeSpy.ts"
```

which surfaces in the browser as `Failed to fetch dynamically imported module:
.../AdvancedVizDispatch.tsx` and renders 0 tiles on any tab holding an advanced-viz panel. All
five new tabs hold at least one, so all five are blocked; tab 1 is the only tab with no
advanced-viz tile, which is why it alone rendered.

**Root cause, and why it is not a host-side install problem.** `@genome-spy/core@0.88.1` is
installed on the host (`packages/depictio-react-core/node_modules/@genome-spy`, with
`dist/src/genome/genomes.js` present, and the package's `exports` map has `"./*":
"./dist/src/*"`), so the import path is correct and resolvable from a host-side build. The dev
server does not see it: `docker-compose.dev.yaml` bind-mounts only the `src/` directories into
`depictio-viewer-dev` ("Live source only, node_modules stay in the image, never masked"), so
every `node_modules` the container resolves against comes from the image, which was built before
this dependency was added. `docker logs` on the container confirms it resolving against
`/build/node_modules`. Installing on the host therefore cannot fix it and neither can a plain
restart: the viewer-dev image has to be rebuilt.

```bash
docker compose -f docker-compose.dev.yaml --env-file .env.instance build depictio-viewer-dev
docker compose -f docker-compose.dev.yaml --env-file .env.instance up -d depictio-viewer-dev
```

`packages/**` belongs to the GenomeSpy kind agent and docker commands are out of scope here, so
neither was run from this agent; the owning agent was sent the diagnosis. Re-shooting the five
tabs is the one outstanding validation step for this template. Everything those tabs depend on
(the ingest, the row counts, the links, the dashboard YAML and the catalog renders it resolves)
validated by the other means recorded above, and this failure mode is independent of the
template: it takes down every advanced-viz tile in the repo equally.

## 2026-09-22 review fixes

- `dashboards/base.yaml`: the four glance cards (`sk-glance-card-snps/indels/depth/tstv`,
  formerly `sk-sheet-card-*`) moved out of the collapsed `Sample sheet` section into
  `Run at a glance`, which is now `persistent: true, pin: top` so the strip is visible on first
  paint and rides every tab; the MultiQC intro and general statistics panel moved to a new
  `MultiQC general statistics` section. The sample hub table sits at `y: 2` under its intro.
- Tab-local, non-persistent `Glance scope` section on the main tab: a `Select` on
  `bcftools_stats_summary.caller`, which narrows the pinned strip and the pinned reference
  table (both rendered on that tab).
- Pinned `Sample filters` unchanged: `patient` equals `sample_id` on both reference rows, so
  a patient control would mirror the sample control one to one, and `status` is `0` for
  both rows, so a `status_label` filter would be dead. Both are worth adding on a run with
  several samples per patient or a tumour/normal design.
- `template.yaml`: new links `samples.sample_id -> snpeff_oncoplot.sample_id` (the `Genes`
  oncoplot is now reached by the persistent sample picker) and
  `bcftools_stats_summary.caller -> bcftools_stats_tstv.caller` (so the glance scope reaches
  the Ts/Tv card).
- `test_shipped_dashboard_yamls.py -k sarek` passes. `.db_seeds` not regenerated here.

## 2026-09-23 wave 2b

### What changed

- New pipeline-local recipes in `recipes/`: `mosdepth_targets` (per-target depth, primary
  contigs, 850,444 rows), `mosdepth_windows` (the 1 Mb windows renamed onto `chrom` / `pos` /
  `depth`, 10,836 rows), `substitution_spectrum` (48 rows) and `indel_spectrum` (318 rows) from
  the `bcftools stats` sections, and `callset_qc` (8 rows, one per SNV-calling callset). Unit
  tests in `depictio/tests/recipes/test_sarek_locus_recipes.py` (5 tests).
- New `indexed_file` collection `snpeff_vcf_files` (optional): the eight SNV/indel
  snpEff-annotated VCFs plus their `.tbi`, `max_file_size_mb: 32`, Manta and TIDDIT excluded.
  `megatest.yaml` now fetches `annotation/*/*/*_snpEff.ann.vcf.gz.tbi` (10 objects, 3 to 235 kB).
- Cohort QC: the `mosdepth_regions` double binding (a `coverage_track` and a `genome_view` on
  the same collection) is replaced by a locus section, `One locus, three tracks`, opening on
  `chr17:7,400,000-8,000,000`: a `genome_view` navigator on `mosdepth_windows` (header
  controls, region filter), a `coverage_track` on `mosdepth_targets`, a `genome_view` of
  `vcf_variants` per caller over the hg38 gene lane, and a `genome_view source: file` on
  `snpeff_vcf_files`. `test_no_double_track_binding` now XPASSes on sarek.
- Variant yield: `Mutation spectra` (figure bars of the six folded substitution classes and of
  indel length within 20 bp, as fractions per callset) and `Callset QC profile`
  (`parallel_coordinates` over `callset_qc`).
- Caller concordance: VAF against depth as `density: true`; manhattan in `mode: rainfall`;
  a `Depth at the call` RangeSlider with `show_histogram`; header controls on the dotplot,
  scatter and genome view.
- Consequences: a `record_card` on `snpeff_ann_variants` keyed on `variant_key`, fed by the
  impact scatter's selection, opening on `chr17:7676154:G:C` (TP53 Pro72Arg).
- MultiQC tab: the Ts/Tv RangeSlider draws its histogram.

### Validation performed

- `depictio-cli run --template nf-core/sarek/3.10.0 --data-root <megatest> --dry-run`: 8/8
  steps, after the last template edit.
- `pytest depictio/tests/recipes/test_sarek_locus_recipes.py` plus
  `test_shipped_dashboard_yamls.py -k "sarek or double_track"`: 15 passed, 1 xpassed.
- Live ingest into project `lot2-sarek` on the lot2 stack (before the `chrom` / `pos`
  restructure below): 34 collections processed, the 4 somatic optional ones skipped,
  `snpeff_vcf_files` uploaded 8 files and its manifest (`/files/indexed/{dc_id}`) returned
  presigned URLs that answer range requests (206) with CORS for the viewer origin. All five
  tabs loaded; the navigator echoed the default region and a typed locus
  (`chr1:1,000,000-1,600,000`) updated it; the per-caller calls tile held 329 rows there.
  Screenshots: `/tmp/claude-502/shots-sarek/tab0.png` to `tab5.png`, `tab1_chr1.png`.
- Offline, on the restructured recipes: at the default region there are 4 windows, 1,328
  targets in 4 lanes, and 42 to 83 records per annotated VCF (`tabix`).
- Re-ingest after the restructure (project `6ab3db839baf4b8c12f0d68f`, main dashboard
  `6ab3dbf430116ab0896e43ec`, tabs `...43ed` to `...43f1`): 35 collections processed, 4 somatic
  optional ones skipped. Shapes: `mosdepth_windows` 10,836, `mosdepth_targets` 850,444,
  substitution spectrum 48, indel spectrum 318, `callset_qc` 8, `vcf_variants` 286,631,
  `snpeff_ann_variants` 371,068; `snpeff_vcf_files` lists 8 files.
- Locus section, live: at the default region the per-target track draws 1,328 targets in four
  lanes, the calls track sits on chr17 over TP53, and the file track issues 24 MinIO requests
  (the `.tbi` and range reads of the `.vcf.gz`). Typing `chr1:1,000,000-1,600,000` moves all
  four tracks (per-target 968 rows, MinIO 32 requests). No `compute_coverage_track` 500.
- Other tabs, live: substitution and indel-length bars, the parallel coordinates (8 lines, 8
  axes), the density heatmap, the rainfall panel, the depth slider and the TP53 Pro72Arg record
  card (one card per callset, DeepVariant PASS at VAF 0.43, FreeBayes at 0.46) all render. The
  three Variant yield tiles that did not scroll into view sit in `Variant tables`, which is
  collapsed by design.
- Screenshots: `/tmp/claude-502/shots-sarek/tab0.png` to `tab5.png`, `tab1_chr1.png`, and per
  tile `cqc4_*` (default region), `cqc5_*` (chr1), `vy2_*`, `cc2_*`, `cs2_*`.

### Discrepancies found in this pass

- SK-D13. Cards ignore a `genome_selection` region: the two target cards stayed run-wide while
  the navigator narrowed the tracks. They are titled as run-wide figures.
- SK-D14. `follow_region_filter` zooms a follower only when the filter's column names equal the
  follower's own `chr_col` / `pos_col`; region links narrow the rows but not the view. On the
  first ingest the calls tile and the file track stayed genome-wide and MinIO saw no request.
  Fixed by naming every locus collection `chrom` / `pos` (`mosdepth_windows`, renamed
  `mosdepth_targets`); confirmed live on the re-ingest, all four tracks move together.
- SK-D15. `compute_coverage_track` returned 500 with `LinkResolutionError: Unknown resolver
  type: region`, on fresh containers too, so not stale code. Cause: the template also declared
  a `direct` stage link on the same pair (`mosdepth_windows` to `mosdepth_targets`). The
  multi-hop walker takes the direct link, but `/links/{project}/resolve` finds a link by its
  source and target collections and is answered with the region link, which it cannot resolve.
  Fixed in the template by dropping the stage link (the stage picker no longer reaches the
  per-target track); after the re-ingest, no 500. Platform follow-up: resolve by link id, or
  skip region links in the resolver's lookup.
- SK-D16. The file track is keyed on the VCF file name (`<sample>.<caller>`), so the sample
  picker does not reach it; `file_max_lanes: 8` shows all eight.
- SK-D17. `callset_qc` and the spectra are per callset (sample and caller), not per sample:
  with one individual at two depths, the sample is not a useful unit on its own. Manta has no
  SNV and is dropped from both.
- SK-D18. `mosdepth_summary` has no region link, yet live the per-contig bars and table show
  only the region's contig (chr17, then chr1). Not traced; harmless here, but the section text
  does not rely on it.
- SK-D19. The file track decodes one lane per locus and fails the other seven with `Loading
  failed: workerPool.decompressBlocks is not a function` (the viewer's `@gmod/bgzf-filehandle`
  6.6.0 worker pool under concurrent loads). The range reads themselves succeed. Viewer bug,
  outside the template.
- SK-D20. The calls track's row label reads `329 rows` at both regions while its marks move;
  the label looks computed once. The density tile draws from the same row sample as the scatter
  (about 10k of 286k calls), so its text and the docs no longer say it bins every call.
- SK-D6 (FreeBayes absent from `vcf_variants`) and SK-D9 (`md` and `recal` mosdepth lanes
  identical) still hold and show in the locus section. `cnv_profile` stays unbound: the run
  publishes no somatic profile.
