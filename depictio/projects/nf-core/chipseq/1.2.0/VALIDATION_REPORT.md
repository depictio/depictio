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

Those counts are the state validated on the date above. The shipped YAML has since gained a
fifth tab and a top-pinned metadata section, and lost the four peak cards that opened the
MultiQC tab (CS-D11, CS-D12, CS-D13): five tabs, 97 components (24 cards, 23 text tiles, 15
interactive filters, 13 MultiQC panels, 12 advanced visualisations, 7 tables and 3 figures),
49 of them carrying a `use:`. It has not been re-ingested against
the megatest since; it is model-validated by
`depictio/tests/models/test_shipped_dashboard_yamls.py`.

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
| ChIP enrichment over input (the fingerprint curve) | **MultiQC** (`use: multiqc/deeptools`) |
| Read distribution around genes | **Dedicated** (`deeptools/metagene_profile`), see CS-D11: MultiQC's "Read Distribution Profile after Annotation" plots the same `plotProfile` matrix as a bare curve |
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

The template's QC tab did not bind a General Statistics tile while that stood. It binds one
now (`cs-qc-general-stats`, the canonical `use: multiqc/general_stats` binding the other
templates carry) on the strength of the payload-builder fix landing alongside this change;
`general_stats` had stayed in the data collection's `modules` list throughout because the
underlying data was always present: 80 libraries by 26 metrics, MultiQC 1.35. The table
paginates at 50 rows, so this run's 80 libraries come out over two pages. If the API fix is
reverted, this tile is the first thing to unbind.

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

### CS-D11: the signal-level tiles moved off the MultiQC tab, and three of them were rebound

The MultiQC tab lost its `advanced_viz` tiles here; the card row that also read outside the
report stayed behind until CS-D13. The three `advanced_viz` tiles that read the
per-sample tables `preseq`, `plotFingerprint` and `plotProfile` write beside their curves
moved to a new **Signal** tab (`tab_order: 2`; `Peaks`, `Consensus` and `Differential
binding` shifted to 3, 4, 5). Four decisions came with the move:

* **`cs-qc-readdist` deleted.** MultiQC's deepTools "Read Distribution Profile after
  Annotation" renders the same `plotProfile` matrix as `cs-qc-av-metagene`, which adds the
  TSS marker, the scaled gene-body band, axis titles, the viz-settings panel and
  show-underlying-data. Only the richer of the two is kept. The intro copy that claimed
  "MultiQC has no panel for it" was false and is gone.

* **`cs-qc-av-fingerprint` rebound.** The catalog render's default axes (`auc` against
  `synthetic_js_distance`) measure the same thing twice (r = -0.868 across the 16 libraries
  of this run), so the cloud was a diagonal band. It is now `percent_genome_enriched`
  against `js_distance`, deepTools' own QC scatter, sized by `diff_enrichment` and coloured
  by `auc_ratio`. The cost is that those columns need `--JSDsample` and are therefore
  non-null for the 8 IP libraries only: the 8 inputs carry no point, because they are the
  reference each IP is compared against. That is stated in the tile's intro.

* **`cs-pk-fig-volcano` converted to an `advanced_viz` volcano.** It was a `mode: code`
  scatter over `macs2_peaks` (258 986 rows) that kept `sort().head(2000)`. Code mode skips
  column projection and aggregation pushdown, so the worker materialised the whole table
  whatever the figure drew, and the tile's badge read "258 986 / 258 986 pts". The `volcano`
  kind reduces at scan level and keeps the tail whole (`sampling.py`, `TAIL_ROLE["volcano"]`),
  which is what the `head(2000)` was reaching for. The component's `index` is unchanged
  (`cs-pk-fig-volcano`) so saved filters survive. Two things are lost and are deliberate:
  the volcano renderer emits no lasso cross-filter (the sibling Manhattan does, and the
  section intro now says so) and it colours by hit tier rather than by sample (the Manhattan
  colours by sample over the same frame, and `category_col: sample` keeps the sample in the
  show-underlying-data table).

* **Analysis-mode grouping opt-in.** After the conversion, `cs-pk-fig-tss` is the template's
  only `mode: code` figure. Its frame is per-peak, not per-sample, and its colour axis is the
  HOMER feature class; the per-sample reading of the same distances is the `cs-pk-av-tss`
  advanced_viz directly below it. It therefore does not name `depictio_group_kwargs` /
  `depictio_group_by` and stays out of grouping on purpose.

### CS-D12: the design sheet is pinned to the top of every tab

Every template in the family carries its metadata / samplesheet collection in a
`persistent: true, pin: top, collapsed: true` grid section, so the cohort is one click away
wherever the viewer lands. chipseq's `design` table used to sit inside the bottom-pinned
`Reference tables` next to the peak QC summary. It now has its own top-pinned **ChIP design**
section (icon `mdi:table-account`, teal) with an intro, four cards (ChIP samples split by
antibody, the antibodies themselves, the input controls, and the share of ChIPs whose
antibody is replicated) and the full-width table. `Reference tables` keeps the peak QC
summary alone and its intro was narrowed to match.

### CS-D13: the MultiQC tab holds MultiQC panels only, and the four peak cards it opened with are gone

The tab named **MultiQC** is the reprocessed report and nothing else. Two exceptions are by
design and stay: text tiles and interactive filters, and the two `persistent: true` pinned
sections (`ChIP design` at the top, `Reference tables` at the bottom) that every tab carries.
Everything else on that tab now reads `multiqc_data`.

That left the `Run at a glance` card row, four cards on `macs2/peak_summary`. None of them
moved, because each already said what it says somewhere else, and the tab that owns MACS2
data already had a full four-card row of its own:

* **`cs-qc-card-peaks` (Peaks called)** = `cs-pk-card-count` (Peaks, `Peak yield`). The same
  number with the same top-3-by-sample breakdown; the Peaks-tab card counts the peak rows
  themselves, so it also follows the `Peak scope` sliders.
* **`cs-qc-card-width` (Median peak width)** = `cs-pk-card-width` (Peak width, `Peak yield`).
  The same box-plot statement, taken over the 258986 peak widths rather than over the eight
  per-sample medians.
* **`cs-qc-card-fold` (Median fold enrichment)** = `cs-pk-card-fold` (Fold enrichment,
  `Peak yield`). The same mean enrichment over input. The pass / warn threshold framing the
  deleted card carried is kept in that row by `cs-pk-card-qvalue`, which is a threshold card.
* **`cs-qc-card-frip` (FRiP score)** = `cs-qc-frip`, the `frip_score` MultiQC panel that stays
  on this tab in `ChIP enrichment` (CS-D6). The panel plots FRiP per sample, which is strictly
  more than the gauge's average of it, and the pinned `Peak QC summary` table carries the
  `frip_score` column on every tab, with a FRiP `RangeSlider` pinned beside it.

Moving the FRiP card to the Peaks tab instead was considered and rejected on two grounds: it
would have made that card row five wide, which is ragged at eight columns, and it reads
`macs2_peak_summary` while its neighbours read `macs2_peaks`, so it would have sat still while
the rest of the row responded to the `Peak scope` sliders.

With the cards gone, `Run at a glance` would have held its intro alone, which renders as an
empty box and is what `test_grid_sections_are_not_empty` catches. The section is instead
renamed **Run summary** (icon `mdi:view-dashboard-outline`, teal) and given MultiQC content:
`cs-qc-general-stats`, the General Statistics table, moved up into it from `Read quality`,
where it had always been a poor fit - it pools MACS2, Picard and phantompeakqualtools numbers
as well as the read-level ones. The tab therefore still opens on a one-row-per-library
summary, and `Read quality` now holds exactly the FastQC and Trim Galore panels its name
promises. Three layouts shifted with it: the two FastQC tiles from `y: 6` to `y: 1` and the
cutadapt tile from `y: 11` to `y: 6`. One consequence for CS-D3: the General Statistics tile
is now the only tile in `Run summary`, so if the payload-builder fix is ever reverted and the
tile has to be unbound, the section goes with it rather than being left holding its intro.

Two intros were rewritten for what is actually on screen. `cs-qc-intro` no longer announces
"four cards for the peak yield and signal-to-noise of the run" and now describes the general
statistics table and the panels under it; `cs-ref-intro` no longer calls the peak QC summary
the rows "behind the cards on every tab", because after this change no card reads it.

---

# 2026-09-22 remediation pass

**Date:** 2026-09-22
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2`, `feat/nfcore-templates-lot2`
**Validator:** local depictio-cli against the lot 2 docker stack (API `:8112`, viewer `:5612`,
Mongo `:27112`, config `~/.depictio/CLI.feat-nfcore-templates-lot2-112.yaml`), on the same
megatest data as the 2026-09-05 build.

## Why

The 2026-09 nf-core template audit measured this template against the real run rather than
against its own YAML, and found that the experiment it is built to show was not reachable from
the dashboard: the only exposed factor was `antibody`, one DESeq2 collection was bound by
thirteen tiles and reachable by no filter, the cards sat in a collapsed section with three of
four drawing the same breakdown, and every text tile was one grid row shorter than its body.
This pass fixes those and adds the interval-shaped views of the peak set that the Manhattan
plot cannot give.

## What changed

**The hub was rebuilt (CS-D14, CS-D15, CS-D16).** `design` is no longer a scan of
`pipeline_info/design_controls.csv`; it is a transformed collection produced by
`nf-core/chipseq/design_factors.py`. The sheet itself stays bound as `design_controls`.

**New / changed collections, with the shape read back from Delta after ingest:**

| Collection | Rows x cols | What it is |
|---|---|---|
| `design` (rebuilt) | 16 x 7 | one row per LIBRARY, with `role`, `antibody`, `condition`, `replicate` |
| `design_controls` (new) | 8 x 7 | the pipeline's own design sheet, unchanged |
| `deseq2_qc_pca` (new) | 8 x 6 | principal components of the count matrix, per antibody |
| `deseq2_qc_sample_dists` (new) | 8 x 9 | sample-to-sample distances on rlog values, per antibody |

The other fourteen collections are unchanged and were re-verified in the same ingest:
`macs2_peaks` 258986 x 11, `homer_annotated_peaks` 258986 x 13, `macs2_consensus_boolean`
153891 x 16, `deseq2_results` 153891 x 12, `deseq2_results_raw` 153891 x 31,
`preseq_ccurve_raw` 160000 x 7, `deeptools_plot_profile` 11200 x 5,
`preseq_complexity_curve` 2688 x 6, `homer_tss_distance_profile` 648 x 4,
`macs2_consensus_fc` 500 x 14, `deeptools_fingerprint_metrics` 16 x 13, `design_reads` 16 x 5,
`macs2_peak_summary` 8 x 10, and `multiqc_data` (a MultiQC collection, no Delta shape).

**Links.** Nine added: `design_reads -> multiqc_data` on the library name;
`design.antibody -> macs2_consensus_boolean / macs2_consensus_fc / deseq2_results /
deseq2_qc_pca` through the `wildcard` resolver; `macs2_consensus_boolean.interval_id <->
deseq2_results.gene_id` in both directions; and `design.sample_id -> deseq2_qc_pca /
deseq2_qc_sample_dists`.

**Catalog.** `macs2_peaks` gained three renders (`peak_genome_view`, `peak_coverage_track`,
`peak_volcano`). Four MultiQC panel stubs were added for the pipeline's own custom content:
`frip_score`, `nsc_coefficient`, `rsc_coefficient`, `strand_shift_correlation`.

**Dashboard.** Five tabs, 112 components. 62 of the 65 panel tiles carry a `use:` (95%); the
three that do not read the `design` hub, which is a pipeline-local recipe with no catalog
module. Every tab now opens on a four-card glance strip, every tab carries both the pinned
persistent filter section and a tab-local one, every text tile is `h: 2`, and every grid row
sums to 8.

## Commands run

```
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k chipseq
    8 passed, 2 failed (both catalog-dependent; see CS-D26)
uv run pytest depictio/tests/models/test_catalog.py -q
    92 passed, 7 failed (none naming macs2 or the new multiqc stubs; see CS-D26)
uv run python -m depictio.cli run --template nf-core/chipseq/1.2.0 \
  --data-root ~/Data/depictio-nfcore/chipseq/1.2.0/megatest --dry-run
    8/8 steps
uv run python -m depictio.cli run --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot2-112.yaml \
  --template nf-core/chipseq/1.2.0 --data-root ~/Data/depictio-nfcore/chipseq/1.2.0/megatest
    8/8 steps, 18 data collections, dashboard 6ab2aa14fbe776a1a573e22f, 5 tabs
uv run ruff format / check on the two new recipes
    clean
```

Every recipe was also run directly against the real files before the ingest, through the same
glob and read options the collection declares, and its output frame compared to
`EXPECTED_SCHEMA`.

---

### CS-D14: the 1.2.0 pin is stale, and staying

chipseq 2.x is the current line. The template stays on 1.2.0 in this pass, deliberately: 2.x is
not a version bump of this template but a rewrite. `design_controls.csv` is gone (2.x takes an
nf-core samplesheet and derives no control sheet), `macs` became `macs3`, and `mergedLibrary`
became `merged_library`, so every scan regex, every recipe glob and the hub recipe would change
together. The 2.x megatest prefix on `s3://nf-core-awsmegatests/chipseq/` is empty, so there is
no run to validate that rewrite against and no way to tell which of the guesses is right. Until
a 2.x megatest exists, a 2.x template would be authored blind. Recorded here rather than fixed.

### CS-D15: the conditions the run exists to compare were not filterable

The megatest is two experiments: EZH2 in NTKO against TKO cells, and FOXA1 in E2-treated
against vehicle-treated cells. Neither comparison was a column. `design_controls.csv` carries
`sample_id`, `control_id`, `antibody`, `replicatesExist` and `multipleGroups`, and the
conditions appear only inside the sample names (`EZH2_IP_NTKO_R1`). The dashboard exposed
`antibody`, which has two values and separates the two experiments but not the arms inside
them, so the reader could compare EZH2 against FOXA1 and nothing else.

`nf-core/chipseq/design_factors.py` parses the names token by token: the replicate is a trailing
`_R<digits>`, and the condition is what is left after the leading antibody token and an optional
`IP` / `ChIP` marker. On this run it yields `condition` with 4 distinct values (E2, NTKO, TKO,
VEH) and `replicate` with 2 (R1, R2), both inside the 2..6 band a factor filter needs, checked
against the ingested collection rather than assumed. Both are now persistent filters beside the
library and antibody ones.

The parse is name-shaped, and that is a real limit: a run whose samples are named on another
convention gets a `condition` that is whatever is left of the name. The recipe emits the column
either way and the dashboard filter then shows one value per sample, which is visibly useless
rather than silently wrong.

### CS-D16: the input control libraries were in no row of the hub

`design_controls.csv` has one row per ChIP, so the eight INPUT libraries appeared only as values
of `control_id`. They are sequenced libraries and they carry rows in preseq, plotFingerprint,
plotProfile, samtools and the MultiQC report, so the sample filter offered eight of the sixteen
libraries the reader can see, and an input could never be selected. A ChIP QC comparison is a
comparison against those inputs.

The recipe recovers them from `control_id` and carries them as rows of their own, labelled by
`role` (ChIP / input control) and given the antibody of their own name prefix (INPUT). The hub
is 16 rows now, and `antibody` has 3 values instead of 2.

### CS-D17: `replicatesExist` and `multipleGroups` were dead columns

Both are 1 on every row of this run, by construction: the pipeline writes them per antibody and
this design has replicates and groups for both antibodies. They backed a `gauge` card
("Replicated share", pinned at 100% forever) and would back a filter that can never narrow
anything. Dropped from the hub; the card is gone with them.

### CS-D18: `deseq2_results` was bound by thirteen tiles and reachable by no filter

The Differential binding tab reads `deseq2_results` for every one of its panels, and the
collection appeared in no `links:` entry, so nothing the reader picked anywhere else reached it.
Two links fix it at two grains.

Per interval: a DESeq2 row scores one consensus interval, and `gene_id` there is `interval_id`
in `macs2_consensus_boolean`. Both directions are now linked, so a row ticked on the Consensus
tab carries to its differential binding row and back.

Per antibody: the contrast ids are `EZH2_IP_NTKOvsEZH2_IP_TKO` and `FOXA1_IP_E2vsFOXA1_IP_VEH`,
which start with the antibody, so the `wildcard` resolver (prefix match) carries the persistent
antibody filter into the contrast column. The same resolver carries it into `consensus_set` on
the two consensus collections, whose labels are `EZH2_IP` and `FOXA1_IP`. A per-SAMPLE link
into any of those three is not possible and is not a gap in the template: a consensus set and a
contrast are aggregates over samples and have no sample column by construction.

The interval link inherits CS-D9: `Interval_1` exists in both consensus sets, so the join is
exact only once a single antibody or contrast is in view. The antibody link is what makes that
the normal reading state rather than something the reader has to remember.

### CS-D19: there was no glance strip, and three of the four cards drew the same breakdown

The four cards the dashboard opened with sat inside `ChIP design`, a section that is
`collapsed: true`, so the default view of every tab opened on a text tile and a MultiQC panel.
Three of the four broke down by `antibody` (ChIP samples split by antibody, antibodies by
antibody, input controls by antibody) and the fourth was the dead gauge of CS-D17.

`Cohort at a glance` is a new pinned persistent grid section, not collapsed, carrying four cards
at `x` 0/2/4/6, `w: 2`, `h: 2`, with four different breakdowns: libraries by role (donut),
conditions as a top-4, peaks called with a top-3 by sample, and the FRiP score as a Tukey box
plot. Being persistent and pinned is also what makes it legal on the MultiQC tab, which
`test_multiqc_tabs_hold_only_multiqc_panels` otherwise restricts to report panels.

Two per-tab strips were rebalanced for the same reason: the Consensus fourth card broke down by
`consensus_set`, which the first card already did, and now draws the reproducibility tiers of
the strongest intervals; the Differential binding first card broke down by `direction`, which
the second card already did, and now breaks down by contrast.

### CS-D20: 23 text tiles were one grid row short of their body

Every text tile in the file was `h: 1` and every one had a body over 120 rendered characters,
between 136 and 276, against the ~300 characters a full-width row fits. `TextRenderer` applies
no `maxHeight`, no `overflow` and no line clamp, so the overflow is drawn over the tile below.
All 23 are `h: 2`, and the `y` of every tile under them was recomputed section by section (the
grid is per section, so the arithmetic is local to each). Guarded from here by
`test_text_tiles_are_tall_enough_for_their_body`.

### CS-D21: a megatest-only directory was anchored in a glob (lint F7)

`homer_annotated_peaks` overrides the recipe's glob to keep the merged-library level only, and
the override read `bwa/mergedLibrary/macs/*/*_peaks.annotatePeaks.txt`. The `bwa/` prefix exists
because this megatest aligned with BWA; chipseq 1.2.0 writes `bowtie2/`, `star/` or `hisat2/`
for its other aligners, and the collection would have come back empty for all of them. The glob
is now `**/mergedLibrary/macs/*/*_peaks.annotatePeaks.txt`: `mergedLibrary` is the aggregation
level every 1.2.0 run publishes and is exactly the thing the override exists to pin, so it
stays. Verified to match the same 8 files as before.

`(?:.*/)?` is the portable form for a REGEX, and the same pass applied it to the MultiQC scan,
which is now the shared
`(?:.*/)?multiqc(?:/[^/]+)?/multiqc_data/multiqc\.parquet$` every template uses; it matches the
one parquet on disk and would also match the `multiqc/<peak route>/multiqc_data/` layout a run
publishes without the reprocess. The HOMER override is a GLOB and not a regex, so it takes
`**/` instead.

### CS-D22: four MultiQC panels had no catalog stub, and now do

FRiP, NSC, RSC and the strand cross-correlation are MultiQC custom content the pipeline writes
itself, so they had no `depictio/catalog/multiqc/<module>.yaml` and their four tiles were the
only MultiQC tiles in the file with no `use:` (the original CS-D6). They are written
identically by chipseq, atacseq and cutandrun, which makes them catalog material rather than a
template specific: `multiqc/frip_score`, `multiqc/nsc_coefficient`, `multiqc/rsc_coefficient`
and `multiqc/strand_shift_correlation` now exist and the four tiles carry a badge.

The section names were read off the run's own parquet with `multiqc.list_plots()` before
writing them (`frip_score-section`, `nsc_coefficient-section`, `rsc_coefficient-section`,
`strand_shift_correlation-section`), not copied from the published HTML report.

`peak_count` and `peak_annotation` are the same kind of custom content and deliberately have no
stub: both duplicate a panel the Peaks tab draws from the peak tables directly. The DESeq2 PCA
and clustering sections carry a per-antibody numeric suffix the run assigns itself
(`deseq2_pca_1`, `deseq2_pca_2`, `deseq2_clustering_1`, `deseq2_clustering_2`), which is not a
portable module name; they are bound as data instead, see CS-D24.

### CS-D23: the peak set had no interval-shaped view

Every view of the peaks placed them at a point: the Manhattan at the summit, the volcano at
(enrichment, significance), the histogram at the width. A MACS2 call is an interval, and the
question "what does the binding look like along this locus" had no panel.

`Peak landscape` is a new section on the Peaks tab with two tiles over `macs2_peaks`:
`use: macs2/peak_genome_view` (`genome_view`, `mark: rect`, `end_col` on the peak end) draws one
rectangle per call on a chromosome-aware locus axis with a region brush, and
`use: macs2/peak_coverage_track` draws the same intervals in plain Plotly with fold enrichment
on a log axis. The second is deliberate redundancy per the wave's contract for coordinate
tracks: same rows, no external renderer, so the section still says something if the GenomeSpy
view is unavailable. It is unavailable right now, see CS-D27.

Neither smooths. `smoothing_window: 0` is set explicitly on the coverage track because peaks are
not evenly spaced bins and the default rolling mean would average across gaps of megabases.

### CS-D24: the shared DESeq2 QC PCA recipe mis-maps a per-antibody run

`pca.vals_mqc.tsv` and `sample.dists_mqc.tsv` were on disk and bound by nothing. The
`deseq2/qc_pca` and `deseq2/qc_sample_dists` catalog outputs landed during this wave, and both
recipes need their glob repointed at the `_mqc.tsv` flavour chipseq publishes (their own glob
wants the plain `.txt` a single-matrix pipeline writes); that is a `source_overrides` entry in
this template and works.

`qc_sample_dists` is then correct. The matrix comes back block diagonal, 8 rows by 8 sample
columns with the cross-antibody pairs empty, which is honest: the two matrices were never
compared. The heatmap is captioned to say so.

`qc_pca` is NOT correct on this run, and it is a shape problem rather than a parse failure.
chipseq publishes one count matrix per antibody, so there are two PCA files, and each spells the
variance it explains into its own header (`"PC1: 63% variance"` against `"PC1: 91% variance"`).
The glob loader concatenates diagonally, those headers do not collide, and the two matrices land
in four columns rather than two. `qc_pca.py` then maps columns to roles by position on the
concatenated frame: the output has EZH2's PC1 and PC2 as `dim_1` and `dim_2`, FOXA1's PC1 as
`dim_3`, all four FOXA1 rows null on `dim_1` and `dim_2`, and `dim_1_percent` = 63 for all eight
rows. An embedding bound to it plots four of the eight libraries.

`depictio/catalog/deseq2/**` is another agent's partition this wave and was not edited. The
template uses a pipeline-local recipe, `nf-core/chipseq/deseq2_qc_pca.py`, which keeps the
catalog output's column names (so the tile still binds `use: deseq2/qc_pca_embedding`) and
resolves the components per matrix: it recognises a matrix by which component columns its rows
populate, which is exactly what the diagonal concat encodes, and labels it by the longest common
prefix of its samples, the same rule `macs2/consensus_boolean.py` uses for `consensus_set`. The
result is 8 rows, every library on its own matrix's PC1 and PC2, with the per-set variance
(EZH2_IP 63 / 34, FOXA1_IP 91 / 7).

The general fix belongs upstream: `deseq2/qc_pca.py` should resolve its components per source
file rather than per concatenated frame, which would make it correct for any pipeline that runs
DESeq2 more than once. Recorded here for whoever owns that output.

The gauge card the catalog output offers (`dim_1_percent`, `coverage_max: 100`) is not bound.
It would be the only card in its section, and the wave's layout rule is that a strip is four
cards or none.

### CS-D25: every tab now carries both kinds of filter

The audit's rule is that a tab has the pinned persistent section AND a tab-local,
non-persistent one on its own collections. Three tabs had no tab-local section at all.

| Tab | Tab-local filter section | On |
|---|---|---|
| MultiQC | `Library scope` (new) | `design_reads.sample_id`, the `<sample>_T<n>` grain the FastQC and Trim Galore panels are keyed on |
| Signal | `Signal scope` (new) | `deeptools_fingerprint_metrics.percent_genome_enriched`, `preseq_complexity_curve.total_reads` |
| Peaks | `Peak scope`, `Annotation scope` | q-value, fold enrichment, width, and a chromosome multi-select (new) |
| Consensus | `Consensus scope` | consensus set, samples per interval, and a chromosome multi-select (new) |
| Differential binding | `Contrast` | contrast, direction, log2 fold change, -log10 padj |

`Library scope` needed a link of its own (`design_reads -> multiqc_data`, `sample_mapping`):
the read-level panels are keyed on the library and the rest of the dashboard on the merged
sample, so the library sheet reaches the report on its own key rather than through the hub.

### CS-D26: the catalog is all-or-nothing, and it was red for other reasons during this pass

`load_catalog_entries()` raises on the first invalid tool directory and returns nothing, so a
half-written directory anywhere under `depictio/catalog/` blanks every `use:` in every template
at once. Thirteen other agents were writing into that tree during this pass, and it was red on
`gtdbtk` (a `sankey` render with no `roles.steps`) and `mag` throughout.

That is what makes `test_shipped_dashboard_yamls.py -k chipseq` report 2 failures and
`test_catalog.py` 7. Neither set names `macs2`, the four new `multiqc` stubs or this template:
the catalog failures are `gtdbtk`, `mag`, `cooltools`, `funcscan` and four scrnaseq tools, plus
two `*.schema.json` files that are now behind a model change. Verified by loading every tool
directory individually and patching the loader with the result: with `gtdbtk` and `mag` skipped,
all 16 `advanced_viz` tiles of this dashboard resolve and none degrades to a dict. The ingest
above ran against the live API, whose catalog cache predates those edits, and every `use:`
expanded.

### CS-D27: the kind is `genome_view`, and its renderer does not build right now

The wave brief names the GenomeSpy kind `genomespy_track`. No such kind is registered: the
merged spike calls it `genome_view` in `depictio/models/components/types.py`, with exactly the
roles and config keys the brief describes (`chr`, `pos`, `score` required, `feature`, `end`,
`sample`, `category` optional; `mark: point|rect|bar`, `end_col` required by `rect`). The
catalog render and the tile bind `genome_view`; binding the name in the brief would have failed
`use:` expansion.

The renderer landed during this wave and the dev viewer of this stack cannot serve it yet.
`packages/depictio-react-core/src/components/advanced_viz/genomespy/useGenomeSpy.ts` imports
`@genome-spy/core/genome/genomes.js`. The dependency is declared (`@genome-spy/core: 0.88.1`, in
`packages/depictio-react-core/package.json` and `depictio/viewer/package.json`) and present in
this worktree's own `node_modules`, so this is not a missing dependency: the viewer container's
install predates it, and the fix is an image rebuild rather than a code change. It affects every
dashboard on this stack, not this template.

Two consequences, both environmental. Vite raises a full-page HMR overlay, which a screenshot
can pre-empt by claiming the `vite-error-overlay` custom element name before Vite defines it.
Worse, the failed dynamic import rejects the lazy chunk ALL `advanced_viz` tiles are loaded
from, so the viewer's error boundary replaces the whole tab, not the one tile. Any tab holding
an `advanced_viz` tile is therefore unrenderable on this stack until the rebuild, which is four
of the five here; the MultiQC tab holds none and renders, and its screenshot is the evidence
that the new glance strip, the four filter groups and the report panels are correct.

Validated through the API instead: every collection's shape was read back from
`/deltatables/shape/{dc_id}` after the ingest, and the dashboard and its five tabs from
`/dashboards/list?include_child_tabs=true`. The remaining four tabs want a screenshot pass once
the viewer image is rebuilt.

None of this is why CS-D23 keeps a `coverage_track` beside the GenomeSpy tile: that redundancy
is the wave's contract for coordinate tracks and holds after the rebuild too.

## 2026-09-22 review fixes

Pinned `Role` multi-select added on `design.role` (two values on the reference run: ChIP or
input control), grouped with the other experimental factors. Not done: rebinding the
tab-local `Library scope` (`design_reads.sample_id`). The MultiQC tab renders only the
report plus the pinned `design` and `macs2_peak_summary` tables, which already carry the
persistent and threshold filters; the `design_reads -> multiqc_data` link is what makes the
library control narrow the read-level panels, so the binding is functional as declared.

## 2026-09-23 wave 2b (PR #1102)

### What changed

- New `Locus` tab (tab_order 4; Consensus and Differential binding move to 5 and 6). A
  `genome_view` navigator on `macs2_peaks` (`use: macs2/peak_genome_view`, `mark: rect`, one
  lane per library, `controls_placement: header`, `assembly: hg19`, `default_region:
  chr21:43,600,000-44,000,000`) drives a `coverage_track` on `macs2_consensus_boolean` (one
  lane per consensus set, height = supporting libraries) and a following `genome_view` on
  `homer_annotated_peaks` (feature class, nearest gene on hover). Two `region` links in
  `template.yaml` (`macs2_peaks` -> `macs2_consensus_boolean`, -> `homer_annotated_peaks`).
  Glance strip of four region cards, tab-local `Locus scope` (chromosome, q-value, consensus
  support, feature class).
- Peaks tab: the `Peak landscape` section (genome_view + coverage_track, both on
  `macs2_peaks`) is gone, which clears this template's `test_no_double_track_binding` hit
  (CS-D28). New `Around the summits` section on the new catalog output
  `macs2/summit_profile` (CS-D29). FRiP bar per sample (`use: macs2/peak_summary`). Peak
  volcano restricted to `views: [volcano]`. Annotation bar turned into a percentage
  composition (`barnorm: percent`).
- Differential binding: volcano, MA and QQ merged into one `volcano` tile with `views:
  [volcano, ma, qq]` and header controls; the `ma` and `qq` tiles are removed. PCA embedding
  gets `controls_placement: header`.
- `show_histogram: true` on every range slider (11 tiles).
- New DC `macs2_summit_profile` + design -> summit profile sample link.

### CS-D28: the default region is hg19 and has no gene lane

The run was aligned to hg19 (HOMER puts a TFF1 promoter peak at chr21:43,786,569, -173 bp
from the hg19 TSS). The bundled gene lane and the gene-symbol search exist for hg38 and mm10
only, so the navigator draws no gene lane and its locus field takes coordinates only. The
HOMER nearest-gene track stands in. The region was picked from the data: every one of the
8 IP libraries has 2 to 18 peaks in it, both consensus sets hold intervals (EZH2 33, FOXA1 18).

### CS-D29: no read-coverage signal is published, so the summit profile aggregates calls

`computeMatrix` output is not published as a table and no bigWig is in the megatest mirror
(the `test/` profile mirror has `bigwig/`, the megatest does not), so neither a summit-centred
metagene nor an `indexed_file` bigWig track can be built from this run. `macs2/summit_profile`
aggregates the narrowPeak calls on a +/-2 kb summit-centred grid instead: the share of a
sample's calls covering each offset, and the other samples' summits per anchor per kb. On
this run FOXA1 replicates show a central spike of about 20 summits/kb against 0.15 in the
flanks; EZH2 about 6.5 against 1.5. The text tiles say it is not read coverage.

### Commands and results

    uv run pytest -q depictio/tests/models/test_shipped_dashboard_yamls.py -k chipseq   10 passed
    uv run pytest -q depictio/tests/models/test_catalog.py                              99 passed
    uv run pytest -q depictio/tests/recipes/test_macs2_summit_profile.py                4 passed
    test_no_double_track_binding --runxfail: chipseq no longer listed
    depictio run --template nf-core/chipseq/1.2.0 ... --dry-run                         8/8 steps
    wipe + re-ingest (project 6ab3cadd4da14702f8f30336): 8/8 steps; macs2_summit_profile 648
    rows, macs2_peaks 258986, homer_annotated_peaks 258986, macs2_consensus_boolean 153891,
    every Delta DC non-empty.

Live: the Locus tab opened with the navigator's two filters set to chr21 43600000-44000000
and the region cards recounted to 89 peaks and 8 nearest genes. The brush / locus-entry walk
could not be completed: the stack stopped answering mid-validation (see the wave report).
