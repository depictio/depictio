# nf-core/methylseq 2.3.0: template validation report

**Date:** 2026-09-17
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2`
**Validator:** unit tests + `depictio-cli run --dry-run` (no server ingestion; no `docker` commands run).

## Goal

Build the methylseq 2.3.0 template (Bismark route) plus the `bismark` catalog tool it needs,
fixing the manifest's `keys:` list against the real fetched layout. Bismark is the pipeline's
core: alignment, deduplication and per-context methylation extraction (with M-bias curves),
on top of the reprocessed MultiQC report and a Qualimap coverage panel shared with
nf-core/eager.

## Data used

AWS megatest run
`s3://nf-core-awsmegatests/methylseq/results-93bc5811603c287c766a0ff7e03b5b41f4483895/bismark/`
(the 2.3.0 release tag, Bismark route). Seven samples from E-MTAB-6511: two hESC lines,
MShef11 under three low-oxygen replicates (Q1-Q3) and MShef4 across a bulk sample and three
passage/differentiation conditions (J1-J3). Already fetched and MultiQC-reprocessed to the
1.35 parquet at `~/Data/depictio-nfcore/methylseq/2.3.0/megatest/` before this session started.

```bash
python scripts/nfcore_megatest.py fetch --pipeline methylseq --version 2.3.0 \
  --dest ~/Data/depictio-nfcore/methylseq/2.3.0/megatest
# or, equivalently:
bash depictio/projects/nf-core/methylseq/2.3.0/download_test_data.sh
```

215 files on disk. No BAM, no FASTQ, no bedGraph payload read (the `.bedGraph.gz` files are
fetched for provenance but no collection or recipe reads them, see MS-D4).

## megatest.yaml: keys fixed against the real layout

Only `megatest.yaml` existed at the start of this task; its `keys:` list was checked file by
file against the fetched tree and fixed:

- **Added** `input/*.csv`: the pre-pipeline samplesheet (`input/samplesheet_full.csv`) was
  not fetched by any existing key, but it is the one file whose `sample` column matches every
  Bismark output file name directly. `pipeline_info/samplesheet.valid.csv` (already fetched by
  `pipeline_info/*.csv`) instead appends a `_T1` technical-replicate suffix that matches
  nothing, so it is not usable as the hub source.
- **Removed** `bismark/reports/*.txt`: dead key. `bismark/reports/` holds only
  `*_PE_report.html` (3 MB each); the `.txt` variant of the same report lives at
  `bismark/alignments/logs/*_PE_report.txt`, already covered by
  `bismark/alignments/logs/*`. `bismark/reports/*.html` (kept) covers the HTML.
- **Removed** `preseq/*.txt` and `picard_metrics/*.txt` / `picard_metrics/*_metrics`: genuinely
  absent from this run, not a manifest bug caught by a bad glob:
  `pipeline_info/execution_trace_2022-12-17_00-46-10.txt` shows `PRESEQ_LCEXTRAP` FAILED for 6
  of the 7 samples (only `SRR7961103` completed), so there is no usable per-sample Preseq
  output to build a collection on; `picard_metrics/` does not exist on disk at all and the trace
  has zero `PICARD` entries, Picard never runs on the Bismark route.
- **Verified, not changed:** `fastqc/*.zip`, `trimgalore/*.txt`, `trimgalore/*.zip` and
  `qualimap/*.txt` all look directory-mismatched against the real tree at a glance
  (`fastqc/zips/*.zip`, `trimgalore/logs/*.txt`, `trimgalore/fastqc/zips/*.zip`,
  `qualimap/<sample>/genome_results.txt` and `qualimap/<sample>/raw_data_qualimapReport/*.txt`)
, but the manifest matcher is `fnmatch.fnmatchcase`, not `glob`, and fnmatch's `*` crosses
  `/` freely, so all four already reach the nested files. Verified with a one-line fnmatch
  check against real paths before leaving them alone; see the comment now in `megatest.yaml`.

## Catalog: the `bismark` tool (4 outputs, new) + 1 MultiQC panel (new)

No `depictio/catalog/bismark/` existed anywhere in git or in any other agent's in-flight work,
so this is a new tool, matched purely on file name (no directory-prefix assumption):

| Output | Source file(s) | Renders |
|---|---|---|
| `bismark_alignment_summary` | `*_bismark_bt2_{PE,SE}_report.txt` | figure(bar), 3 cards (box_plot / threshold / top_n / histogram, 4 total), table |
| `bismark_deduplication_summary` | `*.deduplication_report.txt` | figure(bar), 4 cards, table |
| `bismark_methylation_context_summary` | `*_splitting_report.txt` ("Final Cytosine Methylation Report") | figure(bar), 4 cards, table |
| `bismark_mbias_curve` | `*.M-bias.txt` (CpG context, R1+R2 only) | `advanced_viz` `profile` (id `mbias_cpg_profile`), card, table |

`depictio/catalog/multiqc/bismark.yaml` (new, `section: bismark`) surfaces Bismark's own
Alignment Rates / Deduplication / Strand Alignment / Cytosine Methylation / M-Bias plots as
MultiQC panels, alongside the exact-count recipes above (the MultiQC plots are pictures; the
recipes are the numbers under them).

**Why raw-text parsing, not `columns:`.** All four Bismark reports are prose mixed with
`Key:\tValue` lines (the M-bias file additionally packs six differently-shaped tables into one
file). No single tabular read fits any of them, so each output uses the raw-scan + recipe
two-step (`<x>_raw` -> `<x>` via `dc_ref`, per the brief's own idiom for "sample name lives
only in the file name"), with the raw DC reading one LINE per row: `separator: "|"` (a byte
verified absent from all four report types, `grep -Fl` came back empty), `has_header: false`,
`new_columns: ["line"]`, `include_file_paths: source_path`. The recipe re-joins the lines per
`source_path`, regexes out the fields it needs, and strips a Bismark/TrimGalore-specific
filename suffix with a local regex, **not** `depictio.recipes.lib.sample_ids`, whose
`STRIP_STAGE_TOKENS` list does not cover `deduplicated`/`M-bias`/`splitting_report` and which
this brief's edit scope does not include; extending it would have meant editing a shared file.
All four recipes were run against the real 7-sample megatest data before being committed (see
Recipe dry-runs below): zero nulls, sample ids extracted cleanly for every file.

**Why CpG only for M-bias, not all 3 contexts.** The M-bias file holds 6 tables (CpG/CHG/CHH x
R1/R2); the `profile` kind binds one `series` column with no facet role, so one output can
show one coherent group of curves. CpG is the context nf-core/methylseq's default human/mouse
references report on and the one Bismark's own `--ignore` trim advice is normally read from.
CHG and CHH are not lost: `multiqc/bismark`'s `M-Bias` plot (with its 6-way dataset picker)
covers them.

**Coverage is referenced, not rebuilt.** `qualimap/bamqc_genome_results` is listed in the brief
as nf-core/eager's to own; this template's Coverage section binds the existing
`multiqc/qualimap.yaml` panel (`section: qualimap`) instead of building a second per-sample
Qualimap recipe. (Note: `depictio/catalog/qualimap/` now exists as an untracked directory in
this shared worktree, presumably eager's agent landing mid-session, but nothing in this
template depends on it, so its final shape does not affect this template either way.)

## Validation run

```bash
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k methylseq   # 10 passed
uv run pytest depictio/tests/models/test_catalog.py -q -k "bismark or multiqc or fixture or recipe"  # 20 passed
depictio/cli/.venv/bin/depictio-cli run --template nf-core/methylseq/2.3.0 \
  --data-root ~/Data/depictio-nfcore/methylseq/2.3.0/megatest --dry-run   # 8/8 steps, exit 0
uv run ruff format <5 recipe .py files>   # 1 reformatted, 4 unchanged
uv run ruff check <5 recipe .py files>    # all checks passed
pre-commit run --files <all new/changed files>   # all hooks passed
```

Two bugs the tests caught and this session fixed before landing:

1. **Unquoted `%` at the start of a YAML scalar** (`description: % methylation and coverage
   ...`), YAML reserves a leading `%` for directives; `yaml.scanner.ScannerError`. Fixed by
   quoting the string.
2. **`config.profile.color_col` on the M-bias `advanced_viz` tile**: `ProfileConfig` (unlike
   `scatter_xy`/`embedding`) has no `color_col`; the `series` role already IS the colour split,
   and its default `series_col` name (`"series"`) already matches the recipe's own `series`
   column, so the key was simply dropped rather than renamed.
3. Two narrow (`w: 4`) reference tables and one overflowing intro text tile, both caught by
   `test_shipped_dashboard_yamls.py`, fixed by widening to `w: 8` and trimming the body.

The full (unfiltered) run of both test files shows 5 remaining failures, all in
`nanoseq/3.0.0`, `eager/2.4.5` and `init/advanced_viz_showcase`: other agents' in-flight work
in this shared worktree, not touched by and not caused by this template. `test_catalog.py`'s
full run also shows 2 stale-schema failures (`catalog.schema.json` / `output.schema.json`
out of date against the current `CatalogEntry`/`CatalogOutput` models) unrelated to any
pipeline's content.

### Recipe dry-runs against the real megatest data

Each recipe's `transform()` was run directly against the real 7-sample data (raw scan
simulated in Python: one row per line, `source_path` set to the real file path) before the TSV
fixtures were cut from the output:

| Recipe | Rows | Nulls | Notable value |
|---|---|---|---|
| `alignment_summary.py` | 7 | 0 | mapping efficiency 77.1%-82.6% |
| `deduplication_summary.py` | 7 | 0 | duplication 0.72%-0.77% for 6 samples, **36.49%** for the MShef4 bulk sample |
| `methylation_context_summary.py` | 21 (7 x 3 contexts) | 0 | CpG 82.4%-87.3%, CHG/CHH <=1.7% |
| `mbias_curve.py` | 1736 (7 x 2 reads x ~124 positions) | 0 | none |
| `samples.py` (pipeline-local) | 7 | 0 | cell_line/condition parsed for all 7 |

### Dashboard `use:` coverage

53 components across 3 tabs / 12 sections. Excluding `text` (10) and `interactive` (5) tiles,
which never carry `use:` by design: **36 / 38 data-bearing tiles (94.7%) carry a `use:`.** The
2 without: the `samples` hub table and its donut card, which read a pipeline-local recipe
(`nf-core/methylseq/samples.py`), not a catalog tool, the same gap cutandrun's own `samples`
table has, for the same reason.

Kinds bound: `profile` (1, `bismark/mbias_cpg_profile`). No lot-2 kind was needed for this
template; nothing here is blocked on the kinds agent.

## Discrepancies

### MS-D1: `input/*.csv` was the missing megatest key

Described above under "megatest.yaml". Worth flagging on its own: without it, the only
fetchable samplesheet is `pipeline_info/samplesheet.valid.csv`, whose `_T1`-suffixed sample ids
do not match any Bismark output file name, so the hub recipe would need a second id-mangling
step it does not otherwise need. `input/samplesheet_full.csv`'s ids match directly.

### MS-D2: PRESEQ_LCEXTRAP mostly failed on this megatest run

6 of 7 samples' `PRESEQ_LCEXTRAP` process FAILED per the execution trace (only
`SRR7961103_GSM3415667_MShef11_low_oxygen_Q2` completed), even though
`pipeline_info/software_versions.yml` lists `preseq: 3.1.1` as a tool the run used. No Preseq
collection is declared here. `depictio/catalog/preseq/complexity_curve.py` already exists
(built for another pipeline) and would bind directly if a future methylseq megatest run
succeeds for every sample, nothing pipeline-specific would need to change in that recipe.

### MS-D3: no `params.json`, so nothing is auto-detected from the run

Same shape as cutandrun's CR-D8: `pipeline_info/` carries only `software_versions.yml` (no
`params*.json`, no `local_versions.yml`), so provenance is one source and the template exposes
`DATA_ROOT` alone as its only variable. Nothing degrades: there is no metadata-gated
conditional in this template.

### MS-D4: the deduplicated bedGraph is fetched but not read

`bismark/methylation_calls/bedGraph/*.deduplicated.bedGraph.gz` (per-sample, gzipped) is in the
manifest and on disk, but no data collection or recipe reads it. It is a
chromosome-position-level methylation track (`chrom, start, end, pct_methylated`), a natural
fit for the `coverage_track` kind used elsewhere in this catalog (see
`depictio/catalog/mosdepth/amplicon_coverage.yaml`), left out here to keep this lot's Bismark
tool to the four report-derived summaries the brief named explicitly (alignment, deduplication,
per-context methylation, M-bias). A `bismark_bedgraph` / `coverage_track` output reading these
gzipped per-base tracks (potentially large per sample; would need decimation like
`preseq/complexity_curve.py`'s) is the natural next addition to this tool.

### MS-D5: one sample's dedup rate is a real outlier, not a template bug

`SRR7961150_GSM3415714_MShef4_bulk` shows 36.49% PCR duplication against 0.72%-0.77% for the
other six samples (see the recipe dry-run table above). This is the megatest's own data, not
an artefact of the recipe or the template; the `Deduplication ceiling` card (`threshold_value:
20.0`) is set to catch exactly this on the Alignment & deduplication tab.

## Snippets for shared files (not applied, see brief's hard rules)

**`multiqc_stubs.py`**: no `bismark` builder exists yet, so
`depictio/catalog/multiqc/bismark.yaml`'s fixture is the shared conformance parquet (matching
`preseq.yaml`'s own approach), which carries no `bismark` section. `test_every_fixture_reads_
and_grounds_its_renders` still passes because the `multiqc` component declares no `roles:` (no
bound columns to check against); coverage-exemption tooling would need to key a `bismark`
stub off `section.name` values from `multiqc.list_plots()` on the real parquet ("Alignment
Rates", "Deduplication", "Strand Alignment", "Cytosine Methylation", and a 6-dataset "M-Bias"
plot keyed `{"M-Bias": ["CpG R1", "CHG R1", "CHH R1", "CpG R2", "CHG R2", "CHH R2"]}`).
A parser-valid stub needs, per sample: a Bismark alignment report
(`<sample>_bismark_bt2_PE_report.txt`), a deduplication report
(`<sample>_bismark_bt2_pe.deduplication_report.txt`), a splitting report
(`<sample>_bismark_bt2_pe.deduplicated_splitting_report.txt`) and an M-bias file
(`<sample>_bismark_bt2_pe.deduplicated.M-bias.txt`, all 6 sections), the four real-file
excerpts in `depictio/catalog/bismark/*.py`'s docstrings are ready-made templates for the four
builder functions.

**`.gitignore`**: no new lines needed; nothing this template writes falls outside the existing
patterns (no BAM/FASTQ/bedGraph is committed).

**`TEMPLATE_BOTTLENECKS.md` §10 row:**
`| methylseq | 2.3.0 | Bismark | bismark (4 outputs, new) | multiqc/bismark (new) | Bismark reports are prose + Key:Value, not tables: raw-scan-as-lines + regex idiom used for all 4 outputs |`

**`MEGATEST_STATUS.md` row:**
`| methylseq | 2.3.0 | bismark | fetched, MultiQC-reprocessed to 1.35, template + dashboard built, dry-run validated | preseq mostly failed on this run (6/7 samples); no picard_metrics |`

**`VALIDATION_SCENARIOS.md` section (draft):**
```
## nf-core/methylseq 2.3.0

- **M1 (default).** Bismark route, both cell lines present. Every collection populated,
  dashboard funnel intact.
- **M2 (single cell line).** Sample filter narrowed to one cell_line value: MultiQC panels,
  alignment/dedup/methylation tables and the M-bias curve all narrow together through the
  project links; no tile empties (no collection is `optional: true` in this template).
- **M3 (bismark_hisat / bwameth route).** Out of scope for this template (see docs/
  dashboards.md's "Bismark route only" note), `bismark/` file-name patterns would not match
  a HISAT2 or bwa-meth route's output names, and ingestion would report 0 rows for every
  Bismark-tagged collection rather than erroring.
```

**`nfcore_showcase.py` Scenario (draft):**
```python
(
    Scenario(
        pipeline="methylseq",
        version="2.3.0",
        data_root="~/Data/depictio-nfcore/methylseq/2.3.0/megatest",
        description="Bismark bisulfite alignment, dedup and per-context methylation, 2 hESC lines",
    ),
)
```

## Open questions

1. Should a fifth catalog output read the per-sample deduplicated bedGraph
   (`coverage_track` kind) in a follow-up, per MS-D4?
2. Should a future megatest re-fetch re-add `preseq/*.txt` once a run exists where
   `PRESEQ_LCEXTRAP` succeeds for every sample (MS-D2)?
3. `depictio/catalog/qualimap/` appeared mid-session as another agent's untracked work; if it
   lands with a `bamqc_genome_results`-style per-sample output before this PR merges, the
   Coverage section's 4 MultiQC-only tiles could gain a 5th, recipe-backed coverage-depth tile
   referencing it, not attempted here per the brief's "reference, don't create" rule for tools
   another pipeline owns.

---

# 2026-09-22: lot 2 remediation, 3 tabs to 8

Second pass over the same megatest run. The first pass shipped the tables the run
publishes as tables; this one reads the file the run publishes as a methylome and
builds the tabs that file makes possible.

## What changed

**New shared helper.** `depictio/recipes/lib/genomic_bins.py`: streaming binning of any
chrom / pos / value frame into fixed windows. `bin_coordinate_frame` (a `LazyFrame` in,
a binned `DataFrame` out), `bin_delimited_file` (a delimited file on disk, `scan_csv`
lazy, transparent `.gz`), `window_id_expr` (`chr1:10000-20000`) and `window_matrix`
(long to sample-by-window wide). Returns `chrom, start, end, mean, n`. It exists
because three methylseq recipes needed it and every future coverage or signal track
will too; recipes cannot import one another, so a shared lib is the only place it fits.

**The index-DC idiom.** `pl.read_csv` takes no `include_file_paths`, and a `glob_pattern`
`RecipeSource` reads every matched file eagerly, which for 756 MB of bedGraph is not an
option. The CLI's scan path uses `pl.scan_csv`, which is lazy and does take
`include_file_paths`, so `bismark_bedgraph_index` is a scan DC with `n_rows: 1`: one row
per file, carrying its absolute `source_path`. The recipes then stream those files
themselves and 300 million rows never enter Delta. Reusable by any template with a file
too large to ingest.

**8 new bismark catalog outputs** (4 to 12), all recipe-backed:

| Output | Rows on this run | What it is |
| --- | --- | --- |
| `bismark_summary_report` | 7 | `bismark2summary`'s table plus the derived ratios, including `conversion_efficiency_pct = 100 - %CHH` |
| `bismark_mbias_all_contexts` | 5,208 | all six M-bias tables, context and read as columns |
| `bismark_binned_methylation` | 135,450 | 19,350 windows x 7 libraries, 10 kb, complete in every library |
| `bismark_methylation_density` | 350 | per-CpG methylation histogram, 50 buckets per library |
| `bismark_window_pca` | 7 | numpy SVD over the window matrix, 3 components |
| `bismark_window_correlation` | 7 | Pearson between libraries, square |
| `bismark_top_variable_windows` | 150 | the windows with the highest cross-library variance |
| `bismark_window_group_compare` | 19,350 | every window tested between the design's two arms |

**9 new qualimap DCs** bound from `depictio/catalog/qualimap/`, which nf-core/eager owns:
`bamqc_genome_results` (7), `coverage_across_reference` (4,158), `coverage_histogram`
(30,655), `genome_fraction_coverage` (357), each with its raw scan. Referenced, not
recreated.

**Template**: 11 DCs to 28, 5 links to 14. **Dashboard**: 2 tabs to 8, 39 components on
the MultiQC tab and 105 across the other seven.

## Statistics, written out because they are not imported

`window_group_compare` evaluates the Student t tail itself. The slim CLI environment
(`depictio/cli/.venv`) ships numpy and polars and no SciPy, so a recipe that imported
SciPy would fail at ingestion time on a machine where the tests pass.

- pooled two-sample t on the **arcsine square-root transform** of the window's
  methylation proportion (the classical variance-stabilising map for a proportion bounded
  at 0 and 1, which is what stops a window at 97 % being called for being near the
  ceiling). The effect size reported back is the untransformed difference in percentage
  points, because that is the quantity a reader can judge;
- two-sided p from the regularised incomplete beta, `I_{df/(df+t^2)}(df/2, 1/2)`,
  evaluated with a Lentz continued fraction on `math.lgamma`, numpy-vectorised;
- Benjamini-Hochberg by sort plus reverse cumulative minimum.

Validated against `scipy.stats.t.sf` in a scratch environment: 4e-15 relative error in
the tail, 7.6e-10 absolute overall. `depictio/tests/recipes/test_bismark_methylome.py`
pins four reference points of the t tail, the tail's symmetry and monotonicity, and BH's
monotonicity and its cap at 1.

## Decimation policy, stated because it changes what the panels mean

287,394 windows binned. Windows with fewer than 20 CpGs in a library are dropped (a mean
over three CpGs is not that window's methylation); only windows surviving that cut in
**every** library are kept, so the PCA, the correlation and the t-test read the same rows
rather than each imputing its own holes (174,150 left); contigs with fewer than 50
windows go, which removes the unplaced scaffolds and the mitochondrion without naming an
assembly (24 contigs left, chr1-22, X, Y); what remains is strided **uniformly** over the
genome-ordered windows down to 20,000 per library, leaving 19,350.

The stride is uniform on purpose. Keeping the CpG-densest windows instead would have been
the obvious decimation and would have quietly turned every downstream panel into a
CpG-island panel.

## Validation run

```
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k methylseq
  -> 10 passed
uv run pytest depictio/tests/recipes/test_bismark_methylome.py -q
  -> 16 passed
uv run pytest depictio/tests/models/test_catalog.py -q
  -> 93 passed, 6 failed; none in bismark or qualimap (cellbender/kallisto/qcatch/
     simpleaf cards, cooltools and gtdbtk aggregations, and the two *.schema.json
     files, all other agents' in-flight work on this branch)
python -m depictio.cli run --template nf-core/methylseq/2.3.0 \
  --data-root ~/Data/depictio-nfcore/methylseq/2.3.0/megatest \
  --project-name lot2-methylseq --dry-run
  -> 8/8 steps
```

Project `lot2-methylseq` was deleted and re-ingested once. Every recipe wrote rows; the
16 bismark and qualimap recipes together added about 20 seconds over a tables-only
template, streaming 756 MB on the way through. All eight tabs imported
(39/15/16/14/20/16/14/10 components).

Every `use:` in the dashboard was resolved against the live catalog: 90 references, 29
distinct, all resolve. Every `data_collection_tag` in the dashboard exists in the
template; the ten template DCs with no tile are the nine raw scans and the index, which
are recipe inputs and not meant to have one.

## Discrepancies

### MS-D6: `genomespy_track` no longer exists, the tiles bind `genome_view`

The brief asked for a `genomespy_track` per sample. A concurrent kind agent superseded
that kind with `genome_view` while this work was in flight. The tile is bound to
`genome_view` with roles `chr / pos / score / end / sample` and
`facet_by_sample: true`, which is the same panel under the new name. Nothing was lost;
the name in the brief is stale.

### MS-D7: only one window clears the screen, and that is the honest answer

19,350 windows tested, 1 called (Hypomethylated, min padj 0.0134, largest absolute
difference 38.5 points), 19,349 Not significant. Three libraries against four, with no
per-CpG coverage weights, is a low-powered screen by construction. The tab says so in
prose rather than hiding the count. `methylation_coverage/*.cov.gz` would allow a
beta-binomial model instead; this run does not publish it.

### MS-D8: cell line and oxygen condition are the same split

MShef11 is exactly the low-oxygen arm and MShef4 exactly the normoxic one, so the
comparison cannot attribute a difference to either. `samples.py` now emits `treatment`
and `replicate` separately instead of one `condition` that was 1:1 with the sample, and
`group` is documented as the cell line for that reason. The sample-sheet intro on the
dashboard states the confound.

### MS-D9: `_bismark_bt2_` was pinned in five places

`template.yaml`'s alignment scan regex and four recipes matched the literal `bismark_bt2`
infix, so every sample id on the `bismark_hisat` route would have kept the aligner glued
to it. All five now match `bismark_[a-z0-9]+`, and the test suite pins both spellings.
MS-D4 is closed by `bismark_binned_methylation`: the deduplicated bedGraph is now read.

### MS-D10: screenshots are deferred, the dev viewer needs an image rebuild

The lot 2 dev viewer on :5612 predates the `@genome-spy/core` install, so every
`advanced_viz` tile fails with "Failed to fetch dynamically imported module" and the
dashboard shell reports SERVER OFFLINE. It affects every tab of every project on this
instance, not this template, and clearing it needs a viewer image rebuild that only the
instance owner can run. The eight tabs were validated through the API instead: schema,
bindings, `use:` resolution, per-collection row and column shapes, and the statistics
above. Screenshots are the main session's to take after the rebuild; the tab ids are in
the table below.

## Snippets for shared files (not applied, see brief's hard rules)

**`multiqc_stubs.py`**: no `bismark` builder exists yet, so
`depictio/catalog/multiqc/bismark.yaml`'s fixture is the shared conformance parquet (matching
`preseq.yaml`'s own approach), which carries no `bismark` section. `test_every_fixture_reads_
and_grounds_its_renders` still passes because the `multiqc` component declares no `roles:` (no
bound columns to check against); coverage-exemption tooling would need to key a `bismark`
stub off `section.name` values from `multiqc.list_plots()` on the real parquet ("Alignment
Rates", "Deduplication", "Strand Alignment", "Cytosine Methylation", and a 6-dataset "M-Bias"
plot keyed `{"M-Bias": ["CpG R1", "CHG R1", "CHH R1", "CpG R2", "CHG R2", "CHH R2"]}`).
A parser-valid stub needs, per sample: a Bismark alignment report
(`<sample>_bismark_bt2_PE_report.txt`), a deduplication report
(`<sample>_bismark_bt2_pe.deduplication_report.txt`), a splitting report
(`<sample>_bismark_bt2_pe.deduplicated_splitting_report.txt`) and an M-bias file
(`<sample>_bismark_bt2_pe.deduplicated.M-bias.txt`, all 6 sections), the four real-file
excerpts in `depictio/catalog/bismark/*.py`'s docstrings are ready-made templates for the four
builder functions.

**`.gitignore`**: no new lines needed; nothing this template writes falls outside the existing
patterns (no BAM/FASTQ/bedGraph is committed).

**`TEMPLATE_BOTTLENECKS.md` §10 row:**
`| methylseq | 2.3.0 | Bismark | bismark (4 outputs, new) | multiqc/bismark (new) | Bismark reports are prose + Key:Value, not tables: raw-scan-as-lines + regex idiom used for all 4 outputs |`

**`MEGATEST_STATUS.md` row:**
`| methylseq | 2.3.0 | bismark | fetched, MultiQC-reprocessed to 1.35, template + dashboard built, dry-run validated | preseq mostly failed on this run (6/7 samples); no picard_metrics |`

**`VALIDATION_SCENARIOS.md` section (draft):**
```
## nf-core/methylseq 2.3.0

- **M1 (default).** Bismark route, both cell lines present. Every collection populated,
  dashboard funnel intact.
- **M2 (single cell line).** Sample filter narrowed to one cell_line value: MultiQC panels,
  alignment/dedup/methylation tables and the M-bias curve all narrow together through the
  project links; no tile empties (no collection is `optional: true` in this template).
- **M3 (bismark_hisat / bwameth route).** Out of scope for this template (see docs/
  dashboards.md's "Bismark route only" note), `bismark/` file-name patterns would not match
  a HISAT2 or bwa-meth route's output names, and ingestion would report 0 rows for every
  Bismark-tagged collection rather than erroring.
```

**`nfcore_showcase.py` Scenario (draft):**
```python
(
    Scenario(
        pipeline="methylseq",
        version="2.3.0",
        data_root="~/Data/depictio-nfcore/methylseq/2.3.0/megatest",
        description="Bismark bisulfite alignment, dedup and per-context methylation, 2 hESC lines",
    ),
)
```

## Open questions

1. Should a fifth catalog output read the per-sample deduplicated bedGraph
   (`coverage_track` kind) in a follow-up, per MS-D4?
2. Should a future megatest re-fetch re-add `preseq/*.txt` once a run exists where
   `PRESEQ_LCEXTRAP` succeeds for every sample (MS-D2)?
3. `depictio/catalog/qualimap/` appeared mid-session as another agent's untracked work; if it
   lands with a `bamqc_genome_results`-style per-sample output before this PR merges, the
   Coverage section's 4 MultiQC-only tiles could gain a 5th, recipe-backed coverage-depth tile
   referencing it, not attempted here per the brief's "reference, don't create" rule for tools
   another pipeline owns.

---

# 2026-09-22: lot 2 remediation, 3 tabs to 8

Second pass over the same megatest run. The first pass shipped the tables the run
publishes as tables; this one reads the file the run publishes as a methylome and
builds the tabs that file makes possible.

## What changed

**New shared helper.** `depictio/recipes/lib/genomic_bins.py`: streaming binning of any
chrom / pos / value frame into fixed windows. `bin_coordinate_frame` (a `LazyFrame` in,
a binned `DataFrame` out), `bin_delimited_file` (a delimited file on disk, `scan_csv`
lazy, transparent `.gz`), `window_id_expr` (`chr1:10000-20000`) and `window_matrix`
(long to sample-by-window wide). Returns `chrom, start, end, mean, n`. It exists
because three methylseq recipes needed it and every future coverage or signal track
will too; recipes cannot import one another, so a shared lib is the only place it fits.

**The index-DC idiom.** `pl.read_csv` takes no `include_file_paths`, and a `glob_pattern`
`RecipeSource` reads every matched file eagerly, which for 756 MB of bedGraph is not an
option. The CLI's scan path uses `pl.scan_csv`, which is lazy and does take
`include_file_paths`, so `bismark_bedgraph_index` is a scan DC with `n_rows: 1`: one row
per file, carrying its absolute `source_path`. The recipes then stream those files
themselves and 300 million rows never enter Delta. Reusable by any template with a file
too large to ingest.

**8 new bismark catalog outputs** (4 to 12), all recipe-backed:

| Output | Rows on this run | What it is |
| --- | --- | --- |
| `bismark_summary_report` | 7 | `bismark2summary`'s table plus the derived ratios, including `conversion_efficiency_pct = 100 - %CHH` |
| `bismark_mbias_all_contexts` | 5,208 | all six M-bias tables, context and read as columns |
| `bismark_binned_methylation` | 135,450 | 19,350 windows x 7 libraries, 10 kb, complete in every library |
| `bismark_methylation_density` | 350 | per-CpG methylation histogram, 50 buckets per library |
| `bismark_window_pca` | 7 | numpy SVD over the window matrix, 3 components |
| `bismark_window_correlation` | 7 | Pearson between libraries, square |
| `bismark_top_variable_windows` | 150 | the windows with the highest cross-library variance |
| `bismark_window_group_compare` | 19,350 | every window tested between the design's two arms |

**9 new qualimap DCs** bound from `depictio/catalog/qualimap/`, which nf-core/eager owns:
`bamqc_genome_results` (7), `coverage_across_reference` (4,158), `coverage_histogram`
(30,655), `genome_fraction_coverage` (357), each with its raw scan. Referenced, not
recreated.

**Template**: 11 DCs to 28, 5 links to 14. **Dashboard**: 2 tabs to 8, 39 components on
the MultiQC tab and 105 across the other seven.

## Statistics, written out because they are not imported

`window_group_compare` evaluates the Student t tail itself. The slim CLI environment
(`depictio/cli/.venv`) ships numpy and polars and no SciPy, so a recipe that imported
SciPy would fail at ingestion time on a machine where the tests pass.

- pooled two-sample t on the **arcsine square-root transform** of the window's
  methylation proportion (the classical variance-stabilising map for a proportion bounded
  at 0 and 1, which is what stops a window at 97 % being called for being near the
  ceiling). The effect size reported back is the untransformed difference in percentage
  points, because that is the quantity a reader can judge;
- two-sided p from the regularised incomplete beta, `I_{df/(df+t^2)}(df/2, 1/2)`,
  evaluated with a Lentz continued fraction on `math.lgamma`, numpy-vectorised;
- Benjamini-Hochberg by sort plus reverse cumulative minimum.

Validated against `scipy.stats.t.sf` in a scratch environment: 4e-15 relative error in
the tail, 7.6e-10 absolute overall. `depictio/tests/recipes/test_bismark_methylome.py`
pins four reference points of the t tail, the tail's symmetry and monotonicity, and BH's
monotonicity and its cap at 1.

## Decimation policy, stated because it changes what the panels mean

287,394 windows binned. Windows with fewer than 20 CpGs in a library are dropped (a mean
over three CpGs is not that window's methylation); only windows surviving that cut in
**every** library are kept, so the PCA, the correlation and the t-test read the same rows
rather than each imputing its own holes (174,150 left); contigs with fewer than 50
windows go, which removes the unplaced scaffolds and the mitochondrion without naming an
assembly (24 contigs left, chr1-22, X, Y); what remains is strided **uniformly** over the
genome-ordered windows down to 20,000 per library, leaving 19,350.

The stride is uniform on purpose. Keeping the CpG-densest windows instead would have been
the obvious decimation and would have quietly turned every downstream panel into a
CpG-island panel.

## Validation run

```
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k methylseq
  -> 10 passed
uv run pytest depictio/tests/recipes/test_bismark_methylome.py -q
  -> 16 passed
uv run pytest depictio/tests/models/test_catalog.py -q
  -> 93 passed, 6 failed; none in bismark or qualimap (cellbender/kallisto/qcatch/
     simpleaf cards, cooltools and gtdbtk aggregations, and the two *.schema.json
     files, all other agents' in-flight work on this branch)
python -m depictio.cli run --template nf-core/methylseq/2.3.0 \
  --data-root ~/Data/depictio-nfcore/methylseq/2.3.0/megatest \
  --project-name lot2-methylseq --dry-run
  -> 8/8 steps
```

Project `lot2-methylseq` was deleted and re-ingested once. Every recipe wrote rows; the
16 bismark and qualimap recipes together added about 20 seconds over a tables-only
template, streaming 756 MB on the way through. All eight tabs imported
(39/15/16/14/20/16/14/10 components).

Every `use:` in the dashboard was resolved against the live catalog: 90 references, 29
distinct, all resolve. Every `data_collection_tag` in the dashboard exists in the
template; the ten template DCs with no tile are the nine raw scans and the index, which
are recipe inputs and not meant to have one.

## Discrepancies

### MS-D6: `genomespy_track` no longer exists, the tiles bind `genome_view`

The brief asked for a `genomespy_track` per sample. A concurrent kind agent superseded
that kind with `genome_view` while this work was in flight. The tile is bound to
`genome_view` with roles `chr / pos / score / end / sample` and
`facet_by_sample: true`, which is the same panel under the new name. Nothing was lost;
the name in the brief is stale.

### MS-D7: only one window clears the screen, and that is the honest answer

19,350 windows tested, 1 called (Hypomethylated, min padj 0.0134, largest absolute
difference 38.5 points), 19,349 Not significant. Three libraries against four, with no
per-CpG coverage weights, is a low-powered screen by construction. The tab says so in
prose rather than hiding the count. `methylation_coverage/*.cov.gz` would allow a
beta-binomial model instead; this run does not publish it.

### MS-D8: cell line and oxygen condition are the same split

MShef11 is exactly the low-oxygen arm and MShef4 exactly the normoxic one, so the
comparison cannot attribute a difference to either. `samples.py` now emits `treatment`
and `replicate` separately instead of one `condition` that was 1:1 with the sample, and
`group` is documented as the cell line for that reason. The sample-sheet intro on the
dashboard states the confound.

### MS-D9: `_bismark_bt2_` was pinned in five places

`template.yaml`'s alignment scan regex and four recipes matched the literal `bismark_bt2`
infix, so every sample id on the `bismark_hisat` route would have kept the aligner glued
to it. All five now match `bismark_[a-z0-9]+`, and the test suite pins both spellings.
MS-D4 is closed by `bismark_binned_methylation`: the deduplicated bedGraph is now read.

### MS-D10: screenshots are blocked by the shared dev viewer, not by this template

`packages/depictio-react-core/node_modules/@genome-spy/core` holds only `LICENSE`,
`package.json` and `README.md`: its `dist/` is absent from the pnpm store, so Vite fails
`Failed to resolve import "@genome-spy/core/genome/genomes.js"` and the dev viewer at
:5612 renders its shell and then reports SERVER OFFLINE. This predates and is independent
of this template, it affects every tab of every project on this instance, and fixing it
needs a `pnpm install`, which this session is not permitted to run. The eight tabs were
validated offline instead: schema, bindings, `use:` resolution, row counts and the
statistics above. Re-run
`scripts/../shots_methylseq.py`-style capture once the install lands.

## Snippets for shared files (not applied, see brief's hard rules)

**`TEMPLATE_BOTTLENECKS.md`**, methylseq entry, replacement text:

> **methylseq 2.3.0 - resolved.** The per-CpG bedGraph (7 files, 756 MB, 8-46 M rows
> each) was fetched but unread. It is now streamed through
> `depictio/recipes/lib/genomic_bins.py` into 10 kb windows behind a one-row-per-file
> index DC, which keeps 300 M rows out of Delta and costs about 20 s at ingestion.
> Remaining gap: no CpG-island or TSS annotation is bundled at any version, so the
> feature tab stratifies by CpG-density tertile and names the proxy as one.

**`MEGATEST_STATUS.md`**, methylseq row: `megatest.yaml` needs no change; its existing
`bismark/methylation_calls/bedGraph/*`, `bismark/summary/*` and `qualimap/*.txt` keys
already fetch everything the eight tabs read.

**`VALIDATION_SCENARIOS.md`**, methylseq scenario: unchanged apart from the tab count,
3 to 8.

## 2026-09-22 review fixes

- `dashboards/base.yaml`: the main tab now opens with a four-card glance strip in
  `Run at a glance` (`persistent: true, pin: top`, so it is legal on the MultiQC tab and rides
  every tab): mapping efficiency (`bismark/alignment_summary`, box plot), CpG methylation and
  bisulfite conversion efficiency (`bismark/summary_report`, box plot and gauge), and the
  samples-by-cell-line donut moved from `Sample sheet` (`ms-glance-card-cellline`). The MultiQC
  intro and general statistics panel moved to a new `MultiQC general statistics` section; the
  sample-sheet intro widened to `w: 8`.
- Tab-local, non-persistent `Glance scope` on the main tab: a `RangeSlider` on
  `bismark_summary_report.pct_cpg_methylation`, a DC the strip renders.
- `template.yaml`: new link `samples.sample_id -> bismark_window_correlation.sample` (the
  DC's own column name), so the correlation matrix follows the persistent sample picker.
- `test_shipped_dashboard_yamls.py -k methylseq` passes. `.db_seeds` not regenerated here.

## 2026-09-23 wave 2b: locus section, header controls, new kinds

What changed:

- `Global methylome`, section `Methylation along the genome`, is now a locus section (plan
  C.5). Navigator: a `genome_view` on `bismark_window_group_compare` with score
  `neg_log10_padj`, category `direction`, `score_threshold: 1.3`, `controls_placement: header`,
  `annotation: hg38`, `region_filter_enabled`, `default_region: "chr14:35,500,000-37,500,000"`.
  Followers (`follow_region_filter: true`): `bismark/methylation_genome_view` on
  `bismark_binned_methylation` (one lane per library) and a `genome_view` of
  `delta_methylation` on the group-comparison windows. The Manhattan stays on the Group
  comparison tab. The `coverage_track` that shared `bismark_binned_methylation` with the
  genome_view is removed, which clears this template from `test_no_double_track_binding`.
- `template.yaml`: region link `bismark_window_group_compare -> bismark_binned_methylation`
  (`resolver: region`, `columns: {chrom: chromosome, pos: position}`).
- Default region: chr14:35.5-37.5 Mb around NKX2-1 holds the only window of the run with padj
  under 0.05 (chr14:36,490,000-36,500,000, delta -24.3 points, MShef11 about 55 % against MShef4
  about 80 %); the region has 16 shared windows, so every lane and both tracks draw.
- Glance strip on `Global methylome`: card 3 now reads `bismark/summary_report`
  `pct_cpg_methylation` (genome-wide, unaffected by the region); card 4 (binned median gauge)
  is retitled "Median window level, locus region" because the navigator's region narrows it.
- `Run QC`: new section `Library QC profile` with a `parallel_coordinates` tile on
  `bismark_summary_report` (8 metrics, `group_col: cell_line`, `scale: minmax`, header).
- `Bias and context`: a faceted line figure (`facet_col: context`, `facet_row: read`) under
  the filtered M-bias profile, the per-context M-bias layout of Bismark's report.
- `Cohort structure`: `controls_placement: header` on the PCA embedding.
- `Group comparison`: the volcano spells `view: volcano`, `views: [volcano, qq]` with
  `p_value_col: p_value` and header controls.
- `show_histogram: true` on all 13 RangeSliders (coverage depth threshold included).

Discrepancies:

- MS-D11: the per-context M-bias `profile` cannot facet (ProfileConfig has no facet field and
  advanced_viz tiles take no per-tile `filter_expr`), so the profile stays one tile driven by
  the context and read filters and the per-context panels are a `figure` line with facets.
- MS-D12: `parallel_coordinates` and the two group-comparison `genome_view` tiles are bound by `viz_kind` +
  explicit roles, not `use:`: the `bismark` catalog module is not in this wave's partition, so
  no render id was added for them. Catalog renders would restore the `use:` ratio.
- MS-D14: a navigator never narrows its own fetch by its own region (by design, so a brush can
  widen again), so it loads its whole collection sampled to `figure_max_points` (10,000).
  Three layouts were tried live:
  1. Navigator on the 135,450-row binned collection: 9,626 sampled rows, about 8 of the 112
     windows of the default region drawn.
  2. Navigator on the 19,350-row group-comparison windows, score `delta_methylation`: 9,996
     sampled rows, and the one significant window (36.49 Mb) was sampled away, at the default
     region and at a typed chr14:36.2-36.8 Mb.
  3. Shipped: same collection, score `neg_log10_padj` with `score_threshold: 1.3`, which makes
     the server keep every row above the threshold whole (tail-preserving sampling). Live
     (project 6ab3d98bdb3fc8c8d7b62f3d): 9,759 rows, and the 36.49 Mb hit is drawn above the
     padj line at both regions. The followers are narrowed to the region and complete: 112
     binned rows and 16 difference rows at the default region; 35 and 5 at chr14:36.2-36.8 Mb.
  A platform fix would narrow a navigator's fetch to a window around its current view.
- MS-D13: qualimap `coverage_across_reference` is not on the locus section: its bins are about
  5 Mb (594 per library genome-wide), coarser than the 2 Mb default region, so it would draw one
  point or none.

Commands: `pytest test_shipped_dashboard_yamls.py -k methylseq` 10 passed; the double-track
lint no longer lists methylseq; `test_catalog.py` 99 passed; `test_filter_links_region.py` 12
passed; dry run 8/8; project wiped and re-ingested as `lot2-methylseq`, every DC has rows
(binned 135,450, group compare 19,350, summary 7, M-bias all contexts 5,208).

Live, 2026-09-23 after the stack restart (project 6ab3d98bdb3fc8c8d7b62f3d, main dashboard
6ab3da8430116ab0896e42eb, Global methylome 6ab3da8530116ab0896e42f0): ingest 8/8 with the same
shapes as above. Typing chr14:36,200,000-36,800,000 in the navigator's locus field moved the
navigator, the lanes (35 rows) and the difference track (5 rows). The parallel_coordinates tile
(7 lines, 8 axes, header controls) and the faceted M-bias figure (CpG, CHG, CHH by R1 and R2)
render. A mouse brush was not exercised; the locus field emits the same filter pair.
Screenshots: /tmp/claude-502/shots-methylseq/.
