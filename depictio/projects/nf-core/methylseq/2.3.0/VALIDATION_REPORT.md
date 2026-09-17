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
