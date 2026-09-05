# nf-core/chipseq 1.2.0: template ingestion validation report

**Date:** 2026-09-05
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot1`
**Validator:** local depictio-cli (`depictio/cli/.venv`) against the local docker stack
(instance `feat-nfcore-templates-lot1`, API `:8101`, MinIO `:9101`,
config `~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml`).

## Goal

Build the chipseq 1.2.0 template plus the `macs2` and `homer` catalog tools it needs, reuse
the `deseq2` tool the differentialabundance workstream built, and drive `depictio-cli run`
against the real AWS megatest output end to end. chipseq is the one pipeline in this lot whose
MultiQC report predates the parquet era, so the run also had to prove the reprocess path.

## Data used

AWS megatest run
`s3://nf-core-awsmegatests/chipseq/results-048fd6854fcc85b355c61dfc2e21da0bcc6399ea/`
(the 1.2.0 release tag). Sixteen human libraries: EZH2 ChIP in NTKO and TKO cells and FOXA1
ChIP in E2 and VEH treated cells, two replicates each, every ChIP against its own input
control. Eight ChIP samples reach the peak collections, all sixteen reach the read QC panels.

```bash
python scripts/nfcore_megatest.py fetch --pipeline chipseq --version 1.2.0 \
  --dest ~/Data/depictio-nfcore/chipseq/1.2.0/megatest
# or, equivalently:
bash depictio/projects/nf-core/chipseq/1.2.0/download_test_data.sh
```

The manifest (`megatest.yaml`) fetches 399 files, 212.8 MB: the design sheets, the software
versions, the original MultiQC 1.9 report's provenance files, every raw MultiQC input of the
narrowPeak main path (FastQC zips, Trim Galore reports, samtools stats/flagstat/idxstats,
Picard metrics, preseq curves, phantompeakqualtools spp.out and custom content, deepTools
fingerprint and profile tables, featureCounts summaries, all `*_mqc.tsv`), the MACS2 narrow
peak calls and their HOMER annotation, the per-antibody consensus boolean matrices and the
two DESeq2 result tables. No BAM, no FASTQ, no bigWig. The broadPeak twin of the tree is left
out on purpose (CS-D8).

## MultiQC was reprocessed: 1.9 to 1.35

This is the one template in the lot whose QC tab does **not** read the MultiQC report the
pipeline published. It reads one this repository generated.

**Source version and how it was detected.** chipseq 1.2.0 is a DSL1 pipeline and this run
shipped MultiQC 1.9, which writes `multiqc_data.json` and no parquet at all; Depictio's
MultiQC data collection reads only `multiqc.parquet` (MultiQC 1.31 and later). Two of
`detect_source_multiqc_version()`'s four probes answer for this run, and they agree:

| Probe | Answer |
|---|---|
| `_version_from_data_json` (`config_version` in `multiqc/narrowPeak/multiqc_data/multiqc_data.json`) | `1.9` |
| `_version_from_log` (`This is MultiQC v...` banner in `multiqc.log`) | `1.9` |
| `_version_from_software_versions` (DSL1 tab-separated `pipeline_info/software_versions.csv`, row `MultiQC\tv1.9`) | `1.9` |

This settles the plan's open question about `config_version`: the key **is** present in a
MultiQC 1.9 `multiqc_data.json` and the json probe answers before the log banner is needed.
The manifest therefore fetches both `multiqc.log` and `multiqc_data.json` from the original
report, purely as provenance, and `megatest.yaml` records `multiqc: {version: "1.9",
reprocess: true}`.

**The reprocess command.**

```bash
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/chipseq/1.2.0/megatest \
  --dest ~/Data/depictio-nfcore/chipseq/1.2.0/megatest
```

It stages every raw tool output under `--src` (skipping every `multiqc*/` directory, so the
1.9 report is never re-parsed as input), runs the pinned MultiQC 1.35 over the staging dir,
pins the creation date for a reproducible parquet, and writes
`multiqc/multiqc_data/multiqc.parquet` next to a `REPROCESSED.json` recording both versions.
399 inputs were staged.

**What came back.** `REPROCESSED.json` records `source_version 1.9`, `reprocessed_with 1.35`
and 20 module anchors. The parquet holds 161 sample ids and, read back through
`multiqc.parse_logs()` + `multiqc.list_plots()`, 19 modules carrying 37 plots:

| Module | Plots | Module | Plots |
|---|---|---|---|
| `fastqc` | 9 | `peak_count` | 1 |
| `picard` | 6 | `peak_annotation` | 1 |
| `samtools` | 6 | `frip_score` | 1 |
| `cutadapt` | 2 | `nsc_coefficient` | 1 |
| `deepTools` | 2 | `rsc_coefficient` | 1 |
| `preseq` | 1 | `strand_shift_correlation` | 1 |
| `featurecounts` | 1 | `deseq2_pca_1` / `deseq2_pca_2` | 1 each |
| `macs` | 0 (general stats only) | `deseq2_clustering_1` / `deseq2_clustering_2` | 1 each |
| `phantompeakqualtools` | 0 (general stats only) | | |

**What a consumer must know.** The anchors and plot names above are MultiQC 1.35's, and they
are *not* the ones the 1.9 report wrote. `template.yaml`'s `dc_specific_properties.modules`
and `plots` and every `selected_module` / `selected_plot` in `dashboards/base.yaml` are
authored against this list and were verified against it, not against the published report.
Consequences:

* Never assert byte equality, plot names or anchors across MultiQC versions here. If the
  pinned MultiQC moves, re-run the reprocess and re-read `list_plots()` before trusting an
  anchor.
* The custom-content sections chipseq writes as `*_mqc.tsv` (`frip_score`, `peak_count`,
  `peak_annotation`, `nsc_coefficient`, `rsc_coefficient`, `strand_shift_correlation`, the
  four `deseq2_*` sections) keep MultiQC's `<id>-section` plot naming. Those names come from
  the pipeline's own `_mqc.tsv` headers, so they are stable across MultiQC versions in a way
  the tool-module plot titles are not.
* `macs` and `phantompeakqualtools` are parsed and contribute general-statistics columns, but
  expose no plot in 1.35, so no tile can bind them (CS-D5).
* The reprocess is not idempotent with respect to version detection (CS-D7).

## Ingestion result: 10 / 10 data collections processed, exit 0

```bash
depictio/cli/.venv/bin/python -m depictio.cli run \
  --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml \
  --template nf-core/chipseq/1.2.0 \
  --data-root ~/Data/depictio-nfcore/chipseq/1.2.0/megatest
```

`--project-name` was deliberately left off, so the project carries the name the template
declares (`ChIP-seq Peak Analysis`, id `6a9c2fe97d658c751f4fa03c`, dashboard
`6a9c2ff530851b3fe17181a7`). That matters for a later standalone `depictio dashboard import`,
which resolves the dashboard's `project_tag` by name. The run went green 8/8 on the first
attempt and was then repeated twice on the dashboard edits this validation produced (the
General Statistics tile removed, CS-D3; three tab subtitles rewritten without em dashes).
Because re-ingesting accumulates dashboards, each repeat deleted the project first through
`DELETE /depictio/api/v1/projects/delete`, so the final state is one clean 8/8 run of exactly
the YAML that ships.

Delta tables read back from MinIO after the run:

| Data collection | Rows | Columns |
|---|---|---|
| `multiqc_data` | 1 report, 19 modules, 37 plots, 161 sample ids | (MultiQC parquet, not Delta) |
| `design` | 8 | 7 |
| `design_reads` | 16 | 5 |
| `macs2_peaks` | 258986 | 11 |
| `macs2_peak_summary` | 8 | 10 |
| `homer_annotated_peaks` | 258986 | 13 |
| `macs2_consensus_boolean` | 153891 | 16 |
| `macs2_consensus_fc` | 500 | 14 |
| `deseq2_results_raw` | 153891 | 31 |
| `deseq2_results` | 153891 | 12 |

`deseq2_results_raw` exists only so `deseq2_results` can read it back through `dc_ref`: the
contrast id lives in the file NAME and only a scan carries the path into the frame. The
referenced collection is therefore declared **before** the collection that reads it and
ingestion stays sequential; reordering the two breaks the run.

All four dashboard tabs imported (`Sequencing QC` + `Peaks` + `Consensus` +
`Differential binding`, 28 + 24 + 14 + 17 = 83 components: 20 cards, 17 text tiles, 15
interactive filters, 13 MultiQC panels, 7 tables, 7 advanced visualisations and 4 figures).
43 of those tiles carry a `use:` catalog reference that resolved
(`macs2/*` 20, `deseq2/*` 9, `homer/annotated_peaks` 5, `multiqc/*` 9).

## Post-ingest verification

Every collection was read back from its Delta table in MinIO and every tile grounded against
the real frame. No FILTER MISMATCH, no 4xx, no 5xx.

**Code-mode figures (2/2).** Both exec against their frame with the viewer's scope
(`df, pl, px, go, pd, np, depictio_group_by, depictio_group_kwargs`) and return a plotly
`Figure`: `Enrichment against significance` 8 traces / 2000 points (one trace per sample after
the top-2000 q-value cut), `Distance to the nearest TSS` 5 traces / 77735 points (one per
annotation class, inside the 10 kb window).

**Column bindings.** All 20 card `column_name` / `breakdown_col`, all 15 interactive
`column_name`, both `selection_column`s, all 5 `row_selection_column`s and all 38 advanced_viz
column bindings (3 manhattan, 8 UpSet `set_columns`, 10 heatmap `value_columns` +
`row_annotation_cols`, 5 volcano, 5 MA, 3 QQ, 4 DA barplot) exist in the bound collection. No
interactive filter sits on a constant column.

**Cards.** `bulk_compute_cards` returns a non-null value for all 20 cards across the four
tabs, with 19 secondary strips (the FRiP gauge has no strip by design): 258986 peaks, FRiP
0.0536, median width 179 bp, median fold enrichment 5.32, 20492 genes touched, 153891
consensus intervals, 1.56 samples per interval, 97238 tested intervals, strongest -log10 padj
13.05.

**Links (8/8).** Replayed as real joins between the Delta frames:

| Link | Source keys hit | Target rows matched |
|---|---|---|
| `design.sample_id` -> `multiqc_data` (sample_mapping) | 8 / 8 | 82 MultiQC sample names in the report |
| `design.sample_id` -> `macs2_peaks.sample` | 8 / 8 | 258986 / 258986 |
| `design.sample_id` -> `macs2_peak_summary.sample` | 8 / 8 | 8 / 8 |
| `design.sample_id` -> `homer_annotated_peaks.sample` | 8 / 8 | 258986 / 258986 |
| `macs2_peaks.peak_id` -> `homer_annotated_peaks.peak_id` | 258986 / 258986 | 258986 / 258986 |
| `homer_annotated_peaks.peak_id` -> `macs2_peaks.peak_id` | 258986 / 258986 | 258986 / 258986 |
| `macs2_consensus_boolean.peak_id` -> `macs2_consensus_fc.peak_id` | 500 / 153891 | 500 / 500 |
| `macs2_consensus_fc.peak_id` -> `macs2_consensus_boolean.peak_id` | 500 / 500 | 500 / 153891 |

The last two are asymmetric by construction, not by accident: `macs2_consensus_fc` keeps only
the 250 most strongly bound intervals of each consensus set (CS-D4).

**MultiQC tiles (13/13).** Every tile names a module and a plot that
`multiqc.list_plots()` reports for the reprocessed parquet, and every one of them also renders
server-side through `POST /dashboards/render_multiqc`: FastQC sequence counts 2 traces,
FastQC quality histograms 16, cutadapt filtered reads 1, samtools percent mapped 3, Picard
duplication 3, preseq complexity 18 traces / 8004 points, featureCounts assignments 3,
deepTools fingerprint 16 traces / 1600 points, deepTools read distribution 16 / 1600, FRiP 8,
strand cross-correlation 16 / 6416, NSC 16, RSC 16.

**Tables and advanced visualisations.** All 7 tables render a non-empty first page through
`POST /dashboards/render_table`. All 7 advanced_viz tiles project their bound columns through
`POST /advanced_viz/data`: manhattan 10117 of 258986 rows (sampled), UpSet 153891 of 153891
(not sampled, as the kind demands), complex heatmap 500 of 500, volcano 9641, MA 9658, QQ
9620 (all sampled with the tail kept), DA barplot 153891 of 153891 (not sampled).

**Unit tests.** `depictio/tests/models/test_catalog.py` and
`depictio/tests/models/test_shipped_dashboard_yamls.py`: 535 passed.
`python -m depictio.cli dev catalog validate`: 31 catalog tools valid.

## MultiQC overlap policy

| Signal | Decision |
|---|---|
| Read counts, quality, GC, length, duplication, adapters | **MultiQC** (`use: multiqc/fastqc`, `use: multiqc/cutadapt`) |
| Alignment, duplication, insert size, library complexity | **MultiQC** (`use: multiqc/samtools`, `use: multiqc/picard`, `use: multiqc/preseq`) |
| ChIP enrichment over input, read distribution around genes | **MultiQC** (`use: multiqc/deeptools`) |
| Reads assigned to consensus peaks | **MultiQC** (`use: multiqc/featurecounts`) |
| FRiP, peak count, NSC / RSC, strand cross-correlation | **MultiQC**, pipeline custom content, no catalog entry (CS-D6) |
| Per-peak coordinates, width, enrichment, significance | **Dedicated** (`macs2/peaks`, `macs2/peak_summary`): the MultiQC `macs` module exposes no plot, only general-statistics columns |
| Consensus peak overlap and per-sample signal | **Dedicated** (`macs2/consensus_boolean`, `macs2/consensus_fc`): MultiQC has no set-intersection or signal-matrix view |
| Peak annotation against gene structure | **Dedicated** (`homer/annotate_peaks`): the `peak_annotation` custom-content bar has no per-peak detail, no distance to TSS and no gene |
| Differential binding | **Dedicated** (`deseq2/*`, reused from the differentialabundance workstream): the `deseq2_pca_*` / `deseq2_clustering_*` custom content is sample-level only |

New MultiQC catalog entries created here: `multiqc/preseq.yaml` and `multiqc/deeptools.yaml`.
`multiqc/featurecounts.yaml` and `multiqc/picard.yaml` already existed and are used as is.

## Discrepancies

### CS-D1: no `pipeline_info/params.json`, so nothing is auto-detected from the run

chipseq 1.2.0 is DSL1 and writes no `params*.json`; the run's parameters survive only inside
`execution_report.html`. `_introspect_pipeline_params` therefore sets no template variable
from this run and the template exposes `DATA_ROOT` alone. Provenance is collected from the
tab-separated `pipeline_info/software_versions.csv` (`format: tsv`, a two-column
`tool<TAB>version` table, not the YAML later releases write) and nothing else, so the Settings
drawer shows a Software versions group and no parameters group. Nothing degrades: there is no
conditional data collection in this template that would need a flag.

### CS-D2: the samplesheet is an output, not an input

There is no `samplesheet.valid.csv` to curl from GitHub. The pipeline derives
`pipeline_info/design_reads.csv` (16 libraries) and `pipeline_info/design_controls.csv`
(8 ChIP samples with their input control and antibody) and publishes both, so the manifest
fetches them and the template scans them in place. Copies live in the template's `input/`
directory so the template is self-describing. `design_controls.csv` is the hub every link
starts from; `design_reads.csv` is library-level, one row per `<sample>_T<n>` technical
replicate, and is bound only as a reference table.

### CS-D3: the MultiQC General Statistics table cannot be rendered for this run (API bug)

`POST /dashboards/render_multiqc_general_stats` answers **500** with
`arg must be a list, tuple, 1-d array, or Series` for this parquet. Root cause, reproduced
locally against `depictio/api/v1/services/multiqc/general_stats_payload.py`:

chipseq runs `samtools stats` and `samtools flagstat` over the same BAMs, so the general-stats
table carries two different metrics (`reads_mapped` from stats, `mapped_passed` from flagstat)
whose MultiQC column **title** is the same, `Reads mapped`. In `_process_multiqc_data`,
`column_mapping` maps both pivot columns onto that one display title, and the de-duplication
loop right after it keys `sanitized_columns` on the display name:

```python
for col in df_multiqc_real.columns:  # sees "Reads mapped (M)" twice
    sanitized = _sanitize_column_name(col)
    while sanitized in sanitized_columns.values():
        sanitized = f"{original_sanitized}_{counter}"
    sanitized_columns[col] = sanitized  # second pass OVERWRITES the first entry
```

Because the dict key is the same for both, the second pass overwrites the first mapping and
`rename()` gives **both** columns the name `Reads mapped (M)_1`. `df[column]` then returns a
DataFrame instead of a Series and `pd.to_numeric` raises inside
`_multiqc_data_bars_colormap`.

This is not chipseq-specific. Sweeping every megatest parquet on this machine through
`_process_multiqc_data`, `rnaseq/3.26.0` collides too (`Reads mapped (M)_1` **and**
`M Aligned (M)_1`); `airrflow/5.1.0` is clean. The fix belongs in
`depictio/api/v1/services/multiqc/general_stats_payload.py` (build the sanitized names
positionally rather than through a dict keyed on the display title, and disambiguate the
display title itself by section key), which is outside this workstream's owned paths.

Until it lands, the template's QC tab does not bind a General Statistics tile. Its slot is
taken by the RSC coefficient and the deepTools read-distribution panels, which read the same
report; `general_stats` stays in the data collection's `modules` list because the underlying
data is present and the tile becomes usable again as soon as the API is fixed.

### CS-D4: `macs2_consensus_fc` is a top-N view, so its link back is 500 of 153891

`macs2/consensus_fc.py` keeps the 250 most strongly bound intervals of each consensus set
(500 rows for the two antibodies here) because the complex heatmap plots one row per interval
and 153891 rows is not a heatmap. The `macs2_consensus_boolean` -> `macs2_consensus_fc` link
therefore matches 500 of 153891 source keys. That is the intended behaviour, not a mismatch:
selecting an interval on the overlap panels narrows the heatmap when the interval is in the
top set and clears it otherwise, and the reverse link matches 500 of 500.

### CS-D5: `macs` and `phantompeakqualtools` parse but expose no plot

Both modules are recognised by MultiQC 1.35 and contribute general-statistics columns
(`Number of Peaks`, `NSC`, `RSC`, `Frag Length`), but `list_plots()` reports zero plots for
either. They stay in the data collection's `modules` list so their general-statistics columns
survive, and no tile binds them. That is also why no `multiqc/macs.yaml` or
`multiqc/phantompeakqualtools.yaml` catalog entry was created: a catalog MultiQC entry exists
to give a plot tile its `use:` badge, and there is no plot to bind. The plan listed both as
candidates; they are dropped, with the peak-level story carried by the dedicated `macs2` tool
instead.

### CS-D6: four MultiQC tiles carry no `use:` badge

`frip_score`, `nsc_coefficient`, `rsc_coefficient` and `strand_shift_correlation` are
chipseq's own custom content, written by the pipeline as `*_mqc.tsv`, not MultiQC tool
modules. A `depictio/catalog/multiqc/<module>.yaml` entry describes a *tool* module that
recurs across pipelines, so creating one for a chipseq-only section would put a pipeline
specific into the catalog. The four tiles are therefore plain MultiQC components with no
catalog reference. The same reasoning covers `peak_count`, `peak_annotation` and the four
`deseq2_*` custom-content sections, which are not bound at all because the dedicated `macs2`,
`homer` and `deseq2` collections say the same thing with per-peak detail.

### CS-D7: the reprocess is not idempotent for source-version detection

`detect_source_multiqc_version()` probes the parquet first, then `multiqc_data.json`. Once the
reprocess has written `multiqc/multiqc_data/multiqc.parquet` (and, with `--keep-json`, a
1.35 `multiqc_data.json` beside it), a second run over the same `--src` reports
`source MultiQC: 1.35` instead of 1.9 and would overwrite `REPROCESSED.json` with that wrong
source version. The staged inputs are unaffected, because `plan_inputs()` skips every
`multiqc*/` directory, so the parquet itself is identical; only the provenance record
degrades. Keep the first `REPROCESSED.json`, or delete `multiqc/multiqc_data/` before
re-running. The command in `megatest.yaml`'s `post_fetch_help` deliberately does not pass
`--keep-json`, so a fresh reproduction leaves only the parquet and the provenance file.

### CS-D8: only the narrowPeak route is bound

The run publishes a complete `macs/broadPeak/` twin of the whole MACS2 tree. It is neither
fetched nor bound, for two reasons: `*_peaks.broadPeak` is BED6+3 with no summit column, so it
needs its own catalog output rather than an alternate glob on `macs2/peaks`; and both trees
carry the same sample names, so a single MultiQC report over both would collide sample ids.
The broadPeak route is deferred, consistent with the lot's "main pipeline path first"
decision. Everything in the template matches on file NAME, never on the
`bwa/mergedLibrary/macs/narrowPeak/` prefix, so a run aligned with a different aligner lands
in the same collections unchanged.

### CS-D9: `deseq2_results.gene_id` is unique only within a contrast

DESeq2 scores consensus intervals named `Interval_1 ... Interval_N`, and the numbering
restarts in each consensus set. Across the two contrasts the frame holds 153891 rows but only
97238 distinct `gene_id` values; `(contrast, gene_id)` is unique at 153891. Consequences: the
DESeq2 table's `row_selection_column: gene_id` and the volcano's `label_col: gene_id` identify
an interval only in combination with the selected contrast, which is why the `Contrast` filter
is a single-choice `Select` and the tab's text tiles tell the reader to pick one first. It is
also why no link is declared between `deseq2_results` and the consensus collections:
`macs2_consensus_boolean.peak_id` is `<consensus set>:<interval id>` precisely so it stays
unique, and joining it to a bare `Interval_N` would silently cross the two antibodies. Making
that link possible needs a `consensus_set`-aware key in `deseq2/results_long.py`, which is
owned by the differentialabundance workstream; see the note below.

### CS-D10: the DESeq2 tables of this run are LF-terminated, not CR-terminated

The lot brief flagged chipseq's `*.deseq2.results.txt` as CR-terminated and required the
recipe to handle `\r`. Checked byte by byte on all four result files of this megatest
(`EZH2_IP_NTKOvsEZH2_IP_TKO` and `FOXA1_IP_E2vsFOXA1_IP_VEH`, full and FDR 0.05 subsets):
zero CRLF, zero lone CR, LF throughout. Every other table in the run is LF too. No recipe
change was needed and none was made: `deseq2/results_long.py` already documents CR/CRLF
tolerance and strips stray `\r` from string columns, so a run that does write CR would still
ingest. Recorded so the assumption is not carried forward untested.
