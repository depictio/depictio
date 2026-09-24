# nf-core Template Validation Scenarios

Scenarios identified for `generate_validation_runs.sh` extension, plus runs already
executed on the EMBL cluster for this branch.

Derived analytically from template YAML data collections and pipeline option space.
Priority order at the bottom.

The scenarios below are what a template *should* be stressed with. `TEST_DATASETS.md`
lists what nf-core actually ships to stress it with: every `test*` profile of every
pinned pipeline, its dataset, and whether the 1.10.0 Nextflow trigger can ingest it.

## Conventions

Each pipeline section opens with two header lines that pin what the template was
validated against (see `MEGATEST_STATUS.md` for the survey behind them):

- `**Megatest:** <prefix> (tag <tag>, run_root <root>, manifest megatest.yaml)`
  where `<prefix>` is `s3://nf-core-awsmegatests/<pipeline>/results-<tag_sha>/`
  (`tag_sha` of the release in <https://nf-co.re/pipelines.json>), `<root>` is the
  sub-directory used as `DATA_ROOT` (`.` when it is the prefix root, e.g. rnaseq
  `aligner_star_salmon/`), and the manifest is
  `depictio/projects/nf-core/<pipeline>/<version>/megatest.yaml`, fetched with
  `python scripts/nfcore_megatest.py fetch --pipeline <pipeline> --version <version>`.
- `**MultiQC:** run wrote <version> -> used as-is` or
  `**MultiQC:** run wrote <version> -> reprocessed with 1.35`.

The viralrecon 3.0.0 and ampliseq 2.16.0 sections predate this convention and document
runs executed on the EMBL cluster rather than a megatest, so they carry only the pinned
MultiQC version. Their megatest status is in `MEGATEST_STATUS.md`.

MultiQC floor: depictio reads only `multiqc.parquet`, the MultiQC >= 1.31 name
(1.30 wrote `BETA-multiqc.parquet`, older releases wrote no parquet at all). The
template's MultiQC scan regex is the only gate, so a run from an older MultiQC
surfaces as a missing `multiqc_data` DC and must be reprocessed with the pinned
MultiQC 1.35 (`multiqc.reprocess: true` in the manifest) before the template can
be validated against it. The shipped templates were validated against MultiQC 1.31
(viralrecon 3.0.0), 1.33 (ampliseq 2.16.0 and 2.17.0) and 1.34 (ampliseq 2.18.0);
the 1.35 reader accepts all of them, but column and schema uniformity is only
checked per data collection, never across pipelines.

---

## viralrecon 3.0.0

**MultiQC version pinned:** 1.31

**Template requirements:**
- Always: `multiqc_data` (parquet), `summary_metrics`, mosdepth TSVs
- ivar amplicon: `variants_long`, `mosdepth_amplicon_coverage`, `mosdepth_amplicon_heatmap`
- SARS-CoV-2 specific: `pangolin_lineages`, `nextclade_results`

### Runs executed on EMBL cluster (this branch)

| Run dir | Profile / Samplesheet | Protocol | Notes |
|---------|----------------------|----------|-------|
| `run_illumina_amplicon` | `-profile test,singularity` | amplicon/ivar | baseline; custom samplesheet `samplesheet_test_illumina_amplicon.csv` |
| `run_nanopore` | `-profile test_nanopore,singularity` | nanopore/artic | **used `--skip_variants_long_table`** — workaround for empty VCF on test data; `variants_long` DC absent; needs clean re-run without the flag |

### Runs launched (2 additional, based on v3.0 samplesheets)

| Run dir | Samplesheet | Reference | Protocol | Key flags |
|---------|-------------|-----------|----------|-----------|
| `run_hiv` | `samplesheet/v3.0/samplesheet_test_hiv.csv` | NC_001802.1 (HIV-1) | metagenomic/bcftools | `--skip_pangolin --skip_nextclade` |
| `run_ev` | `samplesheet/v3.0/samplesheet_test_EV.csv` | NC_002058.3 (Enterovirus) | metagenomic/bcftools | `--skip_pangolin --skip_nextclade` |

Both use GitHub-hosted references (no igenomes S3). These cover scenarios S2+S3 combined:
non-SARS pathogen (no lineage DBs) + metagenomic protocol (no ivar/amplicon mosdepth).

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| S1 | **illumina-amplicon-skip-kraken2** | `-profile test,docker` + `--skip_kraken2` | Kraken2 absent from MultiQC parquet | Template lists `kraken` in `modules:` — tests silent absence of optional module. |
| S2 | **illumina-amplicon-skip-pangolin-nextclade** | `-profile test,docker` + `--skip_pangolin --skip_nextclade` | No pangolin/nextclade CSVs | Simulates non-SARS pathogen. `pangolin_lineages` / `nextclade_results` DCs empty. *Covered by HIV/EV runs above.* |
| S3 | **illumina-metagenomic** | `-profile test,docker --protocol metagenomic` | No amplicon primer trimming | `mosdepth_amplicon_*` absent; bcftools variants. *Covered by HIV/EV runs above.* |
| S4 | **illumina-amplicon-skip-snpeff** | `-profile test,docker` + `--skip_snpeff` | ivar TSV missing GENE/AA/EFFECT/FUNCLASS columns | `variants_long` recipe column logic — highest-risk scenario for recipe failure. |
| S5 | **illumina-amplicon-freyja** | `-profile test,docker` (freyja runs by default) | Freyja rows in MultiQC parquet | Tests `freyja` module parsing. Wastewater surveillance use case. |

**Ranking by template stress:** S4 > S2/S3 (HIV/EV) > S5 > S1

---

## ampliseq 2.16.0

**MultiQC version pinned:** 1.33  *(ampliseq 2.17.0 also pins 1.33)*

**Template requirements:**
- Always: `multiqc_data` (cutadapt + fastqc), `samplesheet`
- With QIIME2: `taxonomy_composition`, `taxonomy_rel_abundance`, alpha diversity, rarefaction
- Conditional on `METADATA_FILE`: `metadata`, `ancombc_results` (full 6-dashboard mode)

### Runs executed on EMBL cluster (this branch)

| Run dir | Profile | Amplicon | Notes |
|---------|---------|----------|-------|
| `run_16s_multi` | `test_multi` | 16S multi-run | multiple sequencing runs merged |
| `run_its_pacbio` | `test_pacbio_its` | ITS / PacBio | divergent: `barplot/level-2.csv` may differ |

### Runs launched (2 additional, based on available samplesheets)

| Run dir | Profile | Samplesheet | Amplicon | Key features |
|---------|---------|-------------|----------|--------------|
| `run_iontorrent` | `test_iontorrent` | `Samplesheet_it_SE_ITS.tsv` | ITS (fungi) / IonTorrent SE | `sintax` taxonomy, `--iontorrent`, `skip_qiime`; tests non-Illumina platform + UNITE DB |
| `run_multiregion` | `test_multiregion` | `samplesheet_multiregion.tsv` | 16S multi-region (SIDLE) | SIDLE stitching of 5 hypervariable regions; Greengenes88 taxonomy; ANCOM enabled |

`run_multiregion` (SIDLE) is the closest available test to a **16S × 18S** combined analysis — SIDLE is designed to span marker genes across regions and could include 18S primers in a real deployment. No 18S-specific test data exists in nf-core/test-datasets at this time.

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| A1 | **16s-nanopore** | `-profile test_nanopore,singularity` | ONT reads; longer amplicons | DADA2/QIIME2 output identical; cutadapt SE-style. All DCs expected present. |
| A2 | **16s-pe-no-metadata** | `-profile test,docker` (no `METADATA_FILE`) | Conditional `if_var_absent: METADATA_FILE` fires | `metadata`, `alpha_rarefaction`, `ancombc_results` DCs dropped; 3-dashboard layout. Highest-value unrun scenario. |
| A3 | **16s-pe-greengenes2** | `-profile test,docker --dada_ref_taxonomy greengenes2=2022.10` | GG2 taxonomy strings vs SILVA | Tests recipe robustness to different taxon string format/separators. |
| A4 | **16s-multi-with-ancombc** | `-profile test_multi,docker` + `METADATA_FILE` + `GROUP_COL` | Full ANCOM-BC path enabled | Exercises `ancombc_results`, `ma_canonical`, `embedding_pcoa`, `alpha_diversity_multi_canonical`. Full 6-dashboard path. |
| A5 | **18s-illumina-pe** | Custom samplesheet, 18S primers (e.g. TAReuk454FWD1/TAReukREV3), PR2 DB | 18S microeukaryote amplicon | No built-in test profile or test data in nf-core/test-datasets; requires custom samplesheet + `--dada_ref_taxonomy pr2`. |

**Ranking by template stress:** A4 > A3 > A2 > A5 > A1

- A4 exercises the full ANCOM-BC path and GROUP_COL substitution logic
- A2 exercises the `if_var_absent` conditional DC removal (simple to run, high coverage)
- A5 (18S) has no test data available upstream — needs real data or a contributed test dataset

---

## differentialabundance 2.0.0

**Megatest:** `s3://nf-core-awsmegatests/differentialabundance/results-30ed7741fc392127156c2fb10cfa3d69d216b54b/` (tag 2.0.0, run_root `.`, manifest `megatest.yaml`)

**MultiQC:** the run writes none, by pipeline design, so the template declares no `multiqc_data` collection and the dashboard ships no QC tab.

**Template requirements:**
- Always: `samples` (hub), `deseq2_results_raw`, `deseq2_results`, `deseq2_vst_pca`,
  `deseq2_vst_heatmap`, `deseq2_sample_distance`
- Conditional on `--gtf`: `deseq2_results_annotated_raw` and `deseq2_results_annotated`,
  both `optional: true`. Without them the Expression and Genome view tabs have no data.
- The samplesheet and the contrasts file are not published under the results prefix.
  `pipeline_info/params.json` names them as public URLs and `post_fetch_help` in the
  manifest carries the two `curl` lines that mirror them into `<DATA_ROOT>/input/`.

### Run executed (this branch)

| Run | Source | Notes |
|---|---|---|
| megatest 2.0.0 | AWS megatest, tag_sha `30ed7741` | 24 mouse RNA-seq samples from a featureCounts matrix, two contrasts, DESeq2 route, 8/8 collections ingested |

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| D1 | **limma route** | `--differential_method limma` | writes `*.limma.results.tsv`, no DESeq2 tables and no `all.vst.tsv` | No conditional prunes the DESeq2 collections, so every one of them fails instead of being removed. Highest-value unrun scenario. |
| D2 | **no annotation** | omit `--gtf` | the annotated tables are never written | Exercises the two `optional: true` collections and the empty Expression / Genome view tabs. Cheapest scenario with real coverage. |
| D3 | **affy arrays** | `-profile test_affy` | matrix comes from CEL files, no variance-stabilising transform | The three VST-derived collections have no source file and fail; a route conditional would be needed. |
| D4 | **single contrast** | one row in the contrasts file | no second contrast | The contrast-versus-contrast scatter degenerates to a single group and the contrast MultiSelect has one option. |
| D5 | **enrichment enabled** | `--gsea_run` or gprofiler2 | publishes GSEA / g:Profiler tables under `tables/` | No collection binds them today, so the `enrichment` visualisation kind stays unused on this template. |

**Ranking by template stress:** D1 > D3 > D2 > D5 > D4

---

## funcscan 4.0.0

**Megatest:** `s3://nf-core-awsmegatests/funcscan/results-aee3dc965eb0c77267435544dda30da858763913/` (tag 4.0.0, run_root `.`, manifest `megatest.yaml`)

**MultiQC:** run wrote 1.34, used as-is. The parquet holds a single `run_metadata` row with no general-stats table and no module sections, because funcscan feeds MultiQC nothing but software versions. `multiqc_data` stays in the template as `optional: true` and the dashboard ships no QC tab.

**Template requirements:**
- Always: `screening_summary`, the hub, assembled through `dc_ref` from the four screening
  arms.
- Every other collection is `optional: true`, one group per screening arm: ARG
  (`hamronization_*`), AMP (`ampcombi_*`), BGC (`combgc_*`), CAZyme (`dbcan_*`).
- Conditionals `SKIP_ARG`, `SKIP_AMP`, `SKIP_BGC`, `SKIP_CAZYME` prune each group and its
  dashboard tab explicitly.
- Declaration order is load-bearing: `screening_summary` is declared last because a
  `dc_ref` source is resolved from the referenced collection's Delta table, which only
  exists once that collection has been processed.

### Run executed (this branch)

| Run | Source | Notes |
|---|---|---|
| megatest 4.0.0 | AWS megatest, tag_sha `aee3dc96` | 19 MGnify metagenome assemblies with all four screening arms enabled, 15/15 collections ingested |

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| F1 | **all screens skipped** | none of the four `--run_*_screening` flags | the four `dc_ref` sources of the hub are all absent | `screening_summary` is not optional, so the run fails rather than degrading. The clearest negative test the template has. |
| F2 | **one screen only** | `--run_arg_screening` alone | three arms produce nothing | Exercises three conditionals at once and the hub with a single input. |
| F3 | **taxonomic classification on** | `--run_taxa_classification` | MMseqs2 adds taxonomy columns to every screening report | Tests that the four recipes tolerate extra columns rather than pinning a column count. |
| F4 | **protein input** | `--input` with pre-called proteins | the annotation arm never runs | ARG and AMP reports keep their shape, contig-derived columns are absent. |
| F5 | **a release that feeds MultiQC** | any future funcscan with module sections | the parquet gains real modules | The optional `multiqc_data` collection would populate and the missing QC tab becomes a visible gap. |

**Ranking by template stress:** F1 > F3 > F2 > F4 > F5

---

## airrflow 5.1.0

**Megatest:** `s3://nf-core-awsmegatests/airrflow/results-e69d49e3f23f11a3391755b5fb7aa4283c0a2471/` (tag 5.1.0, run_root `.`, manifest `megatest.yaml`). 5.1.1 publishes no megatest run.

**MultiQC:** run wrote 1.34, used as-is (fastp plus FastQC on raw and post-assembly reads, four module sections).

**Template requirements:**
- Always: `multiqc_data`, `samplesheet` (hub), `sequence_counts`, `sequence_fates`,
  `repertoire_summary`, `clonal_diversity`, `clone_sizes`, `clone_sets`, `clonal_overlap`,
  `v_gene_usage`, `v_gene_matrix`
- `optional: true`: `threshold_summary`
- Conditionals: `SKIP_CLONAL_ANALYSIS`, `SKIP_REPORT`, `SKIP_THRESHOLD_REPORT`,
  `SKIP_MULTIQC`, `ASSEMBLED_MODE`
- None of those five flags is auto-detected. `_introspect_pipeline_params` in
  `depictio/cli/cli/utils/templates.py` maps only the ampliseq, viralrecon and demultiplex flags, so a
  run that skipped a step needs the matching `--var`. Every affected collection is either
  optional or pruned by its conditional, so a run that omits the flag still ingests.
- Wave 3: `GROUP_COL` (default `treatment`, the megatest's design column) drives the condition
  filter and the subject card breakdown. The nf-core CI samplesheets carry no such column, so
  `test` and `test_tcr` ingest with `--var GROUP_COL=<column>`; without it the condition filter
  is empty.

### Run executed (this branch)

| Run | Source | Notes |
|---|---|---|
| megatest 5.1.0 | AWS megatest, tag_sha `e69d49e3` | ten-sample, two-subject multiple sclerosis B cell study, default `--mode fastq` UMI route, 12/12 collections ingested |

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| A1 | **assembled input** | `--mode assembled` | pRESTO never runs, `parsed_logs/` is absent | Exercises `ASSEMBLED_MODE`: the two sequence-log collections and the Sequence processing funnel are pruned. |
| A2 | **TCR instead of BCR** | `--loci tr` | V, D and J gene names are TR, not IG | Tests that the V-usage recipes read the gene column rather than assuming an IGHV prefix. |
| A3 | **report skipped** | `--skip_report` | `repertoire_comparison/` is absent | Exercises `SKIP_REPORT`: the two V-gene collections go and the Repertoire tab loses its heatmap. |
| A4 | **fixed clonal threshold** | `--clonal_threshold 0.1` | no find-threshold fit is published | Exercises `SKIP_THRESHOLD_REPORT` and the one `optional: true` collection. |
| A5 | **single subject** | any one-subject samplesheet | one value in `subject_id` | The persistent Subject filter degenerates and the faceted diversity figure collapses to one panel. |
| A6 | **no UMIs** | `--library_generation_method specific_pcr` | different pRESTO stage set | `sequence_fates` carries a different stage vocabulary, so the funnel must not pin stage names. |

**Ranking by template stress:** A2 > A1 > A6 > A3 > A5 > A4

---

---

## rnafusion 4.1.3

**Megatest:** `s3://nf-core-awsmegatests/rnafusion/results-76ad76e7c39b2ba9edc35aa3602e3dc454d842ec/`
(tag `76ad76e7`, run_root `.`, manifest megatest.yaml)

**MultiQC:** run wrote 1.33 -> used as-is

**Template requirements:**
- Always: `multiqc_data` (parquet at `multiqc/multiqc_data/`), plus the two fusion-report
  collections `fusion_consensus` and `caller_evidence`. `fusion_consensus` is the hub every
  `links:` entry starts from, and both recipes read the same
  `fusionreport/*/*.fusions.csv`, so they stand or fall together
- Always: `samplesheet`, read from `{DATA_ROOT}/input/` because rnafusion never publishes
  the sheet into the results tree. `params.json` `input` points at a nf-core test-datasets
  URL, so the manifest `post_fetch_help` carries the curl line and the template ships a copy
- Per caller, pruned by conditional: `arriba_fusions` (`SKIP_ARRIBA`), `starfusion_fusions`
  (`SKIP_STARFUSION`), `fusioncatcher_fusions` (`SKIP_FUSIONCATCHER`)
- Per validation step: `fusioninspector_fusions` and `fusion_protein_domains`
  (`SKIP_FUSIONINSPECTOR`), both read from the same abridged table
- Per splicing step: `splice_junctions` and `cancer_introns` (`SKIP_CTATSPLICING`).
  `cancer_introns` is additionally `optional: true` and no tile depends on it
- Route flags are declared but not auto-detected: `_introspect_pipeline_params` maps only
  the ampliseq, viralrecon and demultiplex flags, so `SKIP_ARRIBA`, `SKIP_STARFUSION`,
  `SKIP_FUSIONCATCHER`, `SKIP_FUSIONINSPECTOR`, `SKIP_CTATSPLICING` and `SKIP_QC` must be
  passed by hand as `--var`. `SAMPLESHEET_FILE` overrides where the sheet is looked for
- The sample is derived from each file name. Since wave 3 every fusion recipe reads `sample`
  through `RecipeSource.source_path`, the template links `samplesheet.sample` to all ten fusion
  collections, and the fusion-report rank is computed per sample. Before that, the globbed
  files were concatenated without their path and every caller table pooled the cohort.
- Observed on this megatest (the pipeline's own test profile, one synthetic sample `test`
  with all three callers, FusionInspector and CTAT-splicing enabled): 20 consensus fusions
  over 45 caller-evidence rows, Arriba and STAR-Fusion reporting 14 distinct fusions each
  and FusionCatcher 17, FusionInspector validating 14, 184 Pfam domain rows over 12 fusions,
  200 scored junctions over 14 chromosomes, and `cancer_introns` header-only

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| F1 | **multi-sample cohort** | any samplesheet with more than one row | Each caller writes one file per sample, all matched by the same glob | The highest-stress scenario and the one this megatest cannot reach. Since wave 3 each caller table carries a path-derived `sample` column, and a synthetic two-sample cohort checked offline gives per-sample rows, per-sample ranks and a derived extra caller. A real cohort is still the only way to exercise the sample axis live: the persistent `Sample filters` MultiSelect, the `sample_mapping` fan-out and every per-sample MultiQC panel are single-valued here. |
| F2 | **single caller** | `--tools arriba` plus the matching `--var SKIP_STARFUSION=true --var SKIP_FUSIONCATCHER=true` | Only one caller directory is written | Two of the three caller collections pruned, so the `Evidence` tab loses two of its three per-caller dot plots and two of its three tables. `caller_evidence` keeps one row per fusion instead of up to three, so the evidence dot plot degenerates to a single column and `evidence_fraction` is 1.0 everywhere. The `Caller concordance` UpSet drops to one set with a single intersection, and `tool_support` becomes a constant, which also flattens the donut on the `Fusions called` card and the colour of the ranking lollipop. Tests conditional pruning and set-based rendering at once. |
| F3 | **no FusionInspector** | `--var SKIP_FUSIONINSPECTOR=true` | No `fusioninspector/` tree | `fusioninspector_fusions` and `fusion_protein_domains` pruned together, taking two of the three sections of the last tab: `Validated calls` (4 cards, dot plot, allelic-ratio scatter) and `Fusion protein domains` (domain track, lollipop, table). Also removes the tab's second hub, so the two `fusioninspector_fusions -> *` links vanish and only the fusion-consensus fan-out remains. The largest single-flag loss in the template. |
| F4 | **no CTAT-splicing** | `--var SKIP_CTATSPLICING=true` | No `ctatsplicing/` tree | `splice_junctions` and `cancer_introns` pruned, removing the `Splice junctions` section (4 cards, Manhattan, per-gene bar) and one pinned reference table. Low risk because both collections are deliberately unlinked, so nothing else on the dashboard changes; that is exactly what the scenario should confirm. |
| F5 | **cancer introns populated** | a run whose junctions survive the CTAT cancer-intron annotation filter | `*.cancer.introns` has rows rather than a bare header | The inverse of what was validated: here the file is header-only, the ingest skips the collection with a message, and the collection is still registered on the project with no Delta table at all, so `deltatables/get`, `/specs` and `/shape` all 404 and `pl.read_delta` raises `TableNotFoundError` rather than returning an empty frame. A run with real candidates is the only way to exercise `cancer_introns.py`, its `cancer_intron_manhattan` render and the TCGA and GTEx prevalence columns. Nothing at the API distinguishes "optional and legitimately empty" from "broken", so a consumer walking the project has to treat a 404 as normal. |
| F6 | **skip QC** | `--skip_qc` plus `--var SKIP_QC=true` | No FastQC, fastp, STAR or Picard sections reach MultiQC | `multiqc_data` pruned, which empties the whole main tab: 9 MultiQC tiles across three sections, plus the `samplesheet -> multiqc_data` link that is the samplesheet's only consumer. The fusion tabs are untouched, so this is the scenario that shows the funnel still works with its first step removed. |
| F7 | **real tumour library** | any non-synthetic RNA-seq input | Fusion Indication Index spreads instead of saturating | The megatest is a spike-in: 12 of 20 fusions are textbook cancer fusions that all three callers find and two knowledge bases list, so their index is exactly 1.0, while 7 single-caller IGH and DUX4 artefacts sit at 0.167 and one two-caller call at 0.833. The score is therefore bimodal and saturated, so the `fii_lollipop` reads as two flat plateaux rather than a ranking, the index box plot has its median at the maximum, and the UpSet is dominated by one intersection of size 12. All three panels are correct and simply have nothing to separate. A real library is needed to confirm the ranking, the box plot spread and the `fii` RangeSlider are usable. |
| F8 | **route flag omitted** | a run that skipped a caller but was ingested without the matching `--var` | The conditional never fires, so the collection stays declared | Because the flags are not read from `params.json`, the recipe runs against a directory that does not exist and the collection fails or empties while the dashboard still carries its tiles. The failure mode differs per collection: the three caller ones are not `optional: true`, so the ingest should stop, whereas `cancer_introns` is and would be skipped quietly. Worth a run that pins which of the two happens, since it is the most likely operator mistake with this template. |
| F9 | **MultiQC sample-id shapes** | any run where a stage renames its samples | Panel sample ids do not reduce to the samplesheet id | rnafusion runs FastQC twice and names the second pass `<sample>_trimmed_1` / `_trimmed_2`. `build_sample_mapping` strips only a `_1` / `_2` read suffix, so those canonicalise to a second id `test_trimmed` that the samplesheet's `test` can never reach. `resolve_link` returns `["test", "test_1", "test_2"]` with an empty `unmapped_values`, so nothing signals a loss: picking the only sample empties the `fastqc-1` tile and drops the post-trim series from the raw FastQC tiles. Not fixable from the template; the resolver has to report uncovered target ids or canonicalise against the samplesheet rather than a fixed suffix pattern. Any `_trimmed`, `_filtered`, `_dedup` or `_ASSEMBLED` suffix hits it. |
| F10 | **catalog added after the API started** | any ingest of a template whose catalog tools are newer than the running API process | `use:` handles fail to expand | `load_catalog_entries()` is cached per process, so a tool folder created after start-up does not exist for the API. `_expand_catalog_use` raises, the lite component union keeps the raw dict instead of failing, `validate_schema_online` skips dicts, and the import reports success while storing `viz_kind: null`, `catalog_source: null` and the raw YAML config. The viewer dispatches on `viz_kind` and draws `Unknown advanced viz kind: ""`, so all 9 advanced-viz tiles are blank until the API is restarted and the run repeated. Confirmed by two probe imports through the same endpoint: `fusionreport/caller_upset` stored null, `hamronization/arg_upset` stored `upset_plot` with a full 14-key config. Branch-wide, not rnafusion-specific: ampliseq 11/11, viralrecon 9/9, funcscan 9/9 and airrflow 8/8 have a kind, rnafusion 0/9, rnaseq 0/2, taxprofiler 0/8 and chipseq 3/7 do not. A platform fix, not a scenario run: invalidate the cache on a catalog change, and make a failed `use:` expansion an import error. |
| F11 | **component addressed by `tag`** | any tooling that reads a shipped dashboard YAML | Only `index` reaches `stored_metadata` | A YAML component may set both `tag` and `index`; `tag` is dropped at import and a missing `index` is replaced by a UUID. 14 of this dashboard's 74 components set both to different values, for example `tag: rnaf-filter-sample` with `index: rnaf-sample-filter`. Anything matching stored components by `tag` finds nothing and reports zero, with no error. Hit while building the tile-verification harness, where it silently skipped the whole persistent-filter test. Either alias `tag` through or reject a YAML that sets the two differently. |

**Ranking by template stress:** F1 > F2 > F3 > F8 > F5 > F7 > F4 > F6 > F9 > F10 > F11

---

## rnaseq 3.26.0

**Megatest:** `s3://nf-core-awsmegatests/rnaseq/results-e7ca46272c8f9d5ceee3f71759f4ba551d3217a4/`
(tag `e7ca4627`, run_root `aligner_star_salmon/`, manifest megatest.yaml)

**MultiQC:** run wrote 1.33 -> used as-is

**Template requirements:**
- Always: `multiqc_data` (parquet at the nested `multiqc/star_salmon/multiqc_report_data/`),
  `samplesheet` (project-local recipe, condition read off `<condition>_REP<n>`)
- STAR + Salmon route: `sample_overview`, `expression_heatmap`, `gene_expression`,
  `gene_counts`, all from `star_salmon/salmon.merged.gene_*.tsv` via `source_overrides`
- `PSEUDOALIGNER_ONLY`: the same four collections repointed at `salmon/`
- `SKIP_MULTIQC`: prunes `multiqc_data`
- `SKIP_QUANTIFICATION_MERGE`: prunes the whole expression chain, leaving the QC tab

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| R1 | **pseudoaligner-only** | `--skip_alignment --pseudo_aligner salmon` | No `star_salmon/`; matrices under `salmon/` | `PSEUDOALIGNER_ONLY` conditional undoes the STAR + Salmon repointing. The megatest already ships both trees, so this is testable on the fetched data by re-running with the flag. |
| R2 | **skip-quantification-merge** | `--skip_quantification_merge` | No merged `salmon.merged.gene_*.tsv` | All four expression DCs pruned; only the QC tab survives. Tests that a tab reduced below the minimum is dropped rather than half-rendered. |
| R3 | **skip-multiqc** | `--skip_multiqc` | No report at all | `multiqc_data` pruned; 19 tiles disappear and the QC tab must still meet the minimum. |
| R4 | **rsem route** | `--aligner star_rsem` | `aligner_star_rsem/` publishes `rsem.merged.gene_tpm.tsv`, not `salmon.merged.*` | Not covered: the salmon recipes match on file name. Would need an `rsem` catalog tool or a name-tolerant recipe. |
| R5 | **kallisto pseudo-aligner** | `--pseudo_aligner kallisto --skip_alignment` | Matrices under `kallisto/` | Same gap as R4: `PSEUDOALIGNER_ONLY` hardcodes `salmon/`. |
| R6 | **non-conventional sample names** | any run whose samplesheet is not `<condition>_REP<n>` | `samplesheet.py` yields one condition per sample | Degrades colouring and the condition cards; nothing errors. Worth a run to confirm. |

**Ranking by template stress:** R2 > R4/R5 > R1 > R3 > R6

---

## taxprofiler 2.0.1

**Megatest:** `s3://nf-core-awsmegatests/taxprofiler/results-70ecc15e49b4f1fcf79d876643b5d14b65c66178/`
(tag `70ecc15e`, run_root `.`, manifest megatest.yaml)

**MultiQC:** run wrote 1.34 -> used as-is

**Template requirements:**
- Always: `multiqc_data` (parquet at `multiqc/multiqc_data/`), plus the five taxpasta
  collections `taxpasta_profiles`, `taxpasta_matrix`, `taxpasta_embedding`,
  `taxpasta_presence`, `taxpasta_sample_summary`. The hub `taxpasta_profiles` melts every
  `taxpasta/*.tsv`; the other four read it back through `dc_ref`, so all five stand or fall
  with `--run_profile_standardisation`
- Optional, per profiler: `sylph_ani` and `sylph_profile` (`--run_sylph`, the profile also
  needs a sylph-tax taxonomy), `melon_ranks` (`--run_melon`, long reads only)
- Optional, per report format: `taxon_names`, a project-local recipe that harvests the
  taxid to name and rank lookup from the kraken2, krakenuniq and centrifuge reports
- Optional, per input: `samplesheet` and `database_sheet`, read from `{DATA_ROOT}/input/`
  because taxprofiler never publishes either sheet into the results tree
- No conditionals and no route flags: unlike rnaseq and airrflow, this template exposes only
  `DATA_ROOT` and `SAMPLESHEET_FILE`, and every profiler-specific collection is
  `optional: true` instead. A run with a different profiler set therefore ingests unchanged
  and simply shows fewer tiles, at the cost of never failing loudly when a profiler is missing
- Observed on this megatest (every `run_*` flag true): 10 profilers over 17 profiler and
  database combinations reach the hub, split 10 profilers / 14 combinations on Illumina
  against 3 (diamond, kaiju, mOTUs) / 6 on nanopore

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| T1 | **no standardisation** | `--run_profile_standardisation false` | Profilers run, `taxpasta/` is never written | All five non-optional collections go empty at once, so Profiles, Concordance and Confidence lose every taxpasta tile and only Read QC survives. The one scenario that breaks a collection the template declares mandatory; highest risk. |
| T2 | **long-read only** | nanopore samplesheet, `--run_melon --run_sylph` | No fastp, FastQC, bowtie2 or nonpareil; porechop_abi and nanoq instead | The comparison collapses from 10 profilers to 3, so `n_profilers` maxes at 3 rather than 9 and the UpSet degenerates to three sets. Six of the 14 MultiQC tiles lose their module (both FastQC runs, fastp, bowtie2, nonpareil). `melon_ranks` is populated here and nowhere else. |
| T3 | **short-read only** | Illumina samplesheet, no long-read route | No porechop_abi, nanoq or minimap2 host removal | `melon_ranks` empty: melon is a nanopore-only marker-gene profiler, so the Genome copies section has no tile. Tests that a collapsed section is dropped rather than half-rendered. |
| T4 | **input sheets absent** | any run where `{DATA_ROOT}/input/` was not populated | Neither sheet is in the results tree, so a fetch that only mirrors S3 misses both | `samplesheet` and `database_sheet` are skipped, which costs the persistent sample filter, the platform annotation the taxpasta recipes join on, both reference tables and the whole `samplesheet -> *` link fan-out. Silent, because both are `optional: true`. |
| T5 | **no sylph** | `--run_sylph false` | No `sylph/` tree | `sylph_ani` and `sylph_profile` pruned, taking the Confidence tab's Containment identity section and the Profiles tab's Containment composition section with them. The partial case is worth its own run: sylph without a sylph-tax taxonomy populates `sylph_ani` but leaves `sylph_profile` empty, so one tool's two collections disagree. |
| T6 | **smaller profiler set** | e.g. `--run_kraken2 --run_bracken` only | Fewer `taxpasta/*.tsv` files | Nothing is pruned, only rows: the hub narrows, `taxpasta_presence` loses set columns and the UpSet, the ordination and the concordance heatmap all shrink. Tests that an optional-DC template degrades gracefully where a conditional-based one would prune. |
| T7 | **no kraken-style reports** | a profiler set without kraken2, krakenuniq or centrifuge | Nothing writes `<profiler>/<db>/*.report.txt` | `taxon_names` empty, so every taxon keeps the `taxid <id>` fallback label in the composition tiles, the heatmap rows and the tables. Renders fine and reads as noise; the failure is legibility, not an error. |
| T8 | **profiler assigns nothing** | observed here with ganon | taxpasta writes a full table whose every count is zero | `profiles.py` drops zero-count rows, so the profiler vanishes from every tile with no warning. ganon ran in this megatest and is absent from the 10. Worth a run that asserts the ingest reports it rather than silently omitting it. |
| T9 | **skip preprocessing QC** | `--skip_preprocessing_qc` | No FastQC or fastp sections in the parquet | Four of the 14 MultiQC tiles lose their module, leaving the Read quality section empty while Host removal and Profiler panels still render. Tests silent absence of optional modules the template lists in `modules:`. |
| T10 | **MultiQC sample-id shapes** | any run whose profiler panels key on `<sample>_<db>.<tool>` | Panel sample ids do not reduce to the samplesheet id | The persistent sample filter reaches 20 of 78 ids on this megatest and leaves 58 orphans: the profiler top-taxa panels, the raw FastQC series and the porechop_abi rows keyed on the ENA run accession. Not fixable from the template, `resolve_link` passes `target_known_values=None` so `regex` and `wildcard` degrade to passthrough. Needs a platform fix, not a scenario run. |

**Ranking by template stress:** T1 > T2/T3 > T4 > T5 > T6 > T8 > T7 > T9 > T10

---

## chipseq 1.2.0

**Megatest:** `s3://nf-core-awsmegatests/chipseq/results-048fd6854fcc85b355c61dfc2e21da0bcc6399ea/`
(tag 1.2.0, run_root `.`, manifest megatest.yaml)

**MultiQC:** run wrote 1.9 -> reprocessed with 1.35

**Template requirements:**
- Always: `design`, `design_reads`, `multiqc_data` (REPROCESSED parquet), `macs2_peaks`,
  `macs2_peak_summary`, `homer_annotated_peaks`, `homer_tss_distance_profile` (dc_ref on
  `homer_annotated_peaks`)
- Signal QC route (present in every default run): `preseq_ccurve_raw` ->
  `preseq_complexity_curve` (dc_ref), `deeptools_fingerprint_metrics`,
  `deeptools_plot_profile`
- Consensus route (>= 2 replicates per antibody): `macs2_consensus_boolean`, `macs2_consensus_fc`
- Differential route (>= 2 conditions per antibody): `deseq2_results_raw` -> `deseq2_results` (dc_ref)
- Optional: `metadata` (`--var METADATA_FILE`; the megatest design is vendored as
  `input/sample_metadata.tsv`), joined into `design`: `condition` is the `GROUP_COL` factor,
  else the design group
- `GENOME` (default `hg38`) sets the Locus tab's genome axis. The megatest was aligned to hg19,
  so it is ingested with `--var GENOME=hg19`; `reference.vars` sets both for the bundled
  reference

**Scenarios:**

| Scenario | Flags | Expected effect |
|---|---|---|
| narrowPeak default (validated) | none | all 10 DCs populated |
| broad peaks | `--broad_peak` | `macs/broadPeak/*_peaks.broadPeak` is BED6+3 with no summit column, so `macs2_peaks` finds nothing and `macs2_broad_peaks` reads it instead. Both outputs ship, one glob each, so a run matches exactly one |
| single replicate per antibody | design with one replicate | no consensus peak set is built; `macs2_consensus_*` and both `deseq2_*` DCs empty |
| single condition per antibody | design with one group | consensus built, DESeq2 not run; both `deseq2_*` DCs empty |
| `--skip_peak_annotation` | flag | `homer_annotated_peaks` and `homer_tss_distance_profile` empty; the Peaks tab loses its annotation section |
| `--skip_preseq` | flag | `preseq_ccurve_raw` finds nothing, so `preseq_complexity_curve` is empty and the complexity ribbon tile has no data. The MultiQC preseq panel goes with it |
| `--skip_plot_profile` / `--skip_plot_fingerprint` | flags | `deeptools_plot_profile` / `deeptools_fingerprint_metrics` empty; the two ChIP-enrichment tiles below the MultiQC panels lose their data |
| `--skip_consensus_peaks` / `--skip_diff_analysis` | flags | Consensus and Differential binding tabs lose their data |
| MultiQC not reprocessed | (omit the reprocess step) | `multiqc_data` finds no parquet; the whole QC tab is empty. This is the pipeline's normal state: the reprocess is mandatory, not optional |
| no design table | omit `METADATA_FILE` | `metadata` pruned; `condition` falls back to the design group |
| `GENOME` left at its default | omit `--var GENOME=hg19` on an hg19 run | the Locus axis is laid out on the wrong assembly; a region typed on a contig that assembly does not list can fail the view |

**Known gap:** the MultiQC General Statistics table cannot be bound for this pipeline
(samtools stats + flagstat both emit a "Reads mapped" column; the API general-stats payload
collapses them and answers 500). See chipseq VALIDATION_REPORT.md CS-D3.

---

## atacseq 1.2.2

**Megatest:** `s3://nf-core-awsmegatests/atacseq/results-f327c86324427c64716be09c98634ae0bc8165f6/`
(tag 1.2.2, run_root `.`, manifest megatest.yaml)

**MultiQC:** run wrote 1.9 -> reprocessed with 1.35

**Template requirements:**
- Always: `sample_design`, `design_reads`, `multiqc_data` (REPROCESSED parquet, pinned by a
  literal scan regex so it cannot pick up the run's own 1.9 tree)
- ataqv route: `ataqv_metrics`, `ataqv_fragment_length`, `ataqv_tss_coverage`,
  `ataqv_chromosome_counts`
- Signal QC route (present in every default run): `preseq_ccurve_raw` ->
  `preseq_complexity_curve` (dc_ref), `deeptools_fingerprint_metrics`,
  `deeptools_plot_profile`
- Peak route: `macs2_peak_summary`, `macs2_broad_peaks`, `homer_annotated_peaks`,
  `homer_tss_distance_profile` (dc_ref on `homer_annotated_peaks`)
- Consensus route (>= 2 replicates per group): `macs2_consensus_boolean`, `macs2_consensus_fc`
- Differential route (>= 2 conditions): `deseq2_results_raw` -> `deseq2_results` (dc_ref)
- `GENOME` (default `hg38`) sets the Locus tab's genome axis. The megatest was aligned to hg19,
  so it is ingested with `--var GENOME=hg19`; `reference.vars` sets it for the bundled reference

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| K1 | **MultiQC not reprocessed** | omit the reprocess step | No parquet at all, since 1.9 predates it | `multiqc_data` finds nothing and the whole QC tab is empty. This is the pipeline's normal state, so the reprocess is mandatory rather than optional. Highest stress. |
| K2 | **narrowPeak route** | default, no `--narrow_peak false` | `macs2/narrowPeak/` instead of `broadPeak/`, and the file gains a summit column | `macs2_broad_peaks` finds nothing: the recipe reads the BED6+3 broad shape. Release 1.2.1 is the narrowPeak twin of this same run, so this is directly testable. The `broadPeak/` nesting also moves the MultiQC report, which the literal scan regex pins. |
| K3 | **single replicate per group** | design with one replicate | No consensus peak set is built | `macs2_consensus_*` and both `deseq2_*` empty; the Consensus and Differential tabs lose their data. |
| K4 | **single condition** | design with one group | Consensus built, DESeq2 not run | Both `deseq2_*` empty while the consensus tiles still render. |
| K5 | **`--skip_peak_annotation`** | flag | No HOMER output | `homer_annotated_peaks` and `homer_tss_distance_profile` empty; the Peaks tab loses its annotation section. |
| K8 | **`--skip_preseq` / `--skip_plot_profile` / `--skip_plot_fingerprint`** | flags | The signal-QC tables are not written | `preseq_complexity_curve`, `deeptools_plot_profile` and `deeptools_fingerprint_metrics` empty one for one; each loses exactly its own tile, the MultiQC panels above them go at the same time. |
| K6 | **ataqv not run** | older config or `--skip_ataqv` | No `ataqv/` tree | All four ataqv collections empty at once, which is the whole library-quality tab. They are declared required, so this is the second scenario that breaks a mandatory collection. |
| K7 | **mitochondrial contig named differently** | a genome whose MT contig is not `chrM` | `ataqv_chromosome_counts` still populates but the MT fraction card keys on a name that is absent | Renders, reads as zero mitochondrial signal, which is wrong rather than empty. Worth a run. |

**Ranking by template stress:** K1 > K6 > K2 > K3/K4 > K5 > K7

---

## cutandrun 3.1

**Megatest:** `s3://nf-core-awsmegatests/cutandrun/results-42502fb44975e930eec865353c5481f472bcf766/`
(tag 3.1, run_root `.`, manifest megatest.yaml)

**MultiQC:** run wrote 1.14 -> reprocessed with 1.35

**Template requirements:**
- Always: `samples`, `samplesheet`, `multiqc_data` (REPROCESSED parquet)
- deepTools QC route (present in every default run): `deeptools_fingerprint_metrics`,
  `deeptools_sample_pca`, `deeptools_correlation_matrix`
- SEACR route: `seacr_peaks_raw` -> `seacr_peaks` (dc_ref), `seacr_peak_summary`,
  `seacr_consensus_peaks`, `seacr_fragment_lengths_raw` -> `seacr_fragment_lengths` (dc_ref)
- `caller_agreement` joins the two callers per sample, so it needs both
- `macs2_peaks` is the only `optional: true` collection: a SEACR-only run keeps every
  other tile and simply loses the comparison
- `GENOME` (default `hg38`, the megatest's build) feeds the Locus tab's navigator, tracks and
  gene lane since wave 3

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| C1 | **MultiQC not reprocessed** | omit the reprocess step | 1.14 wrote no `multiqc.parquet` | `multiqc_data` finds nothing and the QC tab is empty. Mandatory, not optional, as for chipseq and atacseq. |
| C2 | **SEACR only** | `--peakcaller seacr` | No `macs2/` tree | `macs2_peaks` pruned, and `caller_agreement` degrades to one caller: the agreement tile is the one that reads wrong rather than empty, since a single caller trivially agrees with itself. The optional flag covers the collection but not the derived comparison. |
| C3 | **MACS2 only** | `--peakcaller macs2` | No SEACR output | Six required collections empty at once, which is most of the dashboard. The template is SEACR-first by design and this is the scenario that breaks it. |
| C4 | **both callers, different order** | `--peakcaller seacr,macs2` vs the reverse | cutandrun writes the primary caller's peaks to the consensus path | `seacr_consensus_peaks` may hold MACS2 intervals while the tile says SEACR. Worth a run: the failure is a mislabel, not an error. |
| C5 | **single replicate per target** | samplesheet with one replicate | No consensus peak set per target | `seacr_consensus_peaks` empty; the Consensus tab loses its data. |
| C6 | **IgG control absent** | `--igg_control false` | SEACR runs against a numeric threshold rather than the control | The peaks still populate but `seacr_peak_summary`'s control-normalised columns are absent or null. |
| C7 | **numbered stage directories renamed** | a future release reorganising `01_prealign/` .. `04_reporting/` | Every scan path shifts | All recursive scans miss. This megatest's numbered layout is pinned in `megatest.yaml`, so a 3.2+ run is the thing to check before bumping the template. |

**Ranking by template stress:** C3 > C1 > C7 > C2 > C5 > C4 > C6

## sarek 3.10.0

**Megatest:** `s3://nf-core-awsmegatests/sarek/results-8ccac7ad37b05dd792447763bf9671b719824587/`
(tag 3.10.0, run_root `test_full_germline_ncbench_agilent/`, manifest megatest.yaml)

**MultiQC:** run wrote 1.35 -> used as-is

**Template requirements:**
- Always: `samples` (hub, pipeline-local; since wave 3 built from the `csv/` files sarek
  publishes, with no samplesheet collection), `multiqc_data` (native 1.35 parquet,
  10 modules), `bcftools_stats_raw` (scan, feeds the next two via `dc_ref`),
  `bcftools_stats_summary`, `bcftools_stats_tstv` (the new `bcftools` catalog tool)
- Germline-only route: 5 callers (DeepVariant, FreeBayes, HaplotypeCaller, Manta, Strelka) x
  2 samples, both annotators (SnpEff, VEP)
- No somatic profile is published by this megatest, so ASCAT / ControlFREEC / MSIsensor
  outputs never appear

**2026-09-22 remediation:** the template now declares 33 collections (24 links): the 38 VCFs
of the pinned run are fetched (20 files, 44 MB, gVCF and VEP duplicates excluded) and read by a
pure-Polars reader (`depictio/recipes/lib/vcf.py`, catalog `vcf/variants` and
`snpeff/ann_variants`), plus mosdepth regions / summary / XY sex check, vcftools FILTER and
Ts/Tv-by-quality summaries, the bcftools stats sections and the snpEff CSV and genes tables.
The dashboard went from 2 to 6 tabs (MultiQC, Cohort QC, Variant yield, Caller concordance,
Consequences, Genes), 131 components, 96 percent of tiles on `use:`. Four somatic collections
(ASCAT, CNVkit, MSIsensor-pro, NGSCheckMate) are declared `optional: true` for a future
`test_full` somatic run. SK2 is closed for this template by an explicit `mappings:` block on
the MultiQC link (20 name variants per sample); the resolver gap itself is TEMPLATE_BOTTLENECKS
16. Both FreeBayes `variant_calling/` VCFs on S3 are 196-byte symlink targets (SK-D7), so
FreeBayes contributes no rows to `vcf_variants`; its snpEff twins are complete. Manta's VCFs are
real (SK-D8).

**2026-09-23 wave 3:** the template no longer depends on the validation run. The hub is built
from `csv/recalibrated.csv`, `csv/markduplicates*.csv` and `csv/variantcalled.csv`, the first one
present winning, with no name parsing; the MultiQC link uses the hub-aware `sample_mapping`
resolver and the `mappings:` table is gone. A `GENOME` variable (default `hg38`) drives the genome
tracks, the calls-track gene lane and the annotated VCF collection. Every `vcftools_*` and
`snpeff_*` collection and the XY sex check are optional, and `callset_qc` falls back to the raw
calls when the annotated VCFs are absent. mosdepth reads one pass per sample.

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| SK1 | **germline NCBench Agilent (validated)** | `test_full_germline_ncbench_agilent` | none | 29 of 33 DCs populate (the 4 somatic ones are `optional: true`): 286,631 `vcf_variants` rows, 371,068 `snpeff_ann_variants`, 163,557 `snpeff_genes`, 10 `bcftools_stats_*` rows (2 samples x 5 callers). |
| SK2 | **`sample_mapping` canonicalisation gap (closed in wave 3)** | any run | sarek's per-tool MultiQC sample names carry stage/caller/annotator suffixes (`.md`, `.recal`, `.deepvariant`, `.freebayes.filtered`, ...) | SK-D1 is closed: the resolver now attaches each MultiQC name to its hub id (TEMPLATE_BOTTLENECKS 16), so the hub's Sample filter narrows the MultiQC panels without a hand-written `mappings:` block. Worth a live run to confirm on a caller set other than the megatest's. |
| SK3 | **single caller** | `--tools haplotypecaller` | Four callers' `bcftools stats` reports absent | `bcftools_stats_summary`/`_tstv` narrow to 2 rows (1 caller x 2 samples); the caller-comparison `dot_plot` degenerates to two points. |
| SK4 | **annotation skipped** | `--skip_tools snpeff,vep` | No SnpEff/VEP output | `gatk`, `vcftools` and `vep` MultiQC panels empty; the Annotation portion of the MultiQC tab loses its data. |
| SK5 | **somatic pairs (tumor/normal)** | a tumor/normal design | ASCAT / ControlFREEC / MSIsensor outputs would appear for the first time in this repo | Not published by this megatest, so untestable against it; no somatic-specific catalog output exists yet either: the germline-only `bcftools_stats_*` binding (SN-record based) would still apply to whatever callers run. |
| SK6 | **Manta's near-zero SNP counts** | present in the validated run | Manta is the one structural-variant caller among the five | SK-D4: `ts=0 tv=0 n_snps=0` for both samples is correct behaviour, not a data gap, easy to misdiagnose as broken without the dashboard's own caller-labelled description. |

**Ranking by template stress:** SK1 > SK2 > SK5 > SK4 > SK3 > SK6

---

## scrnaseq 4.2.0

**Megatest:** `s3://nf-core-awsmegatests/scrnaseq/results-3fc17b4f971a89e47c88337de71d0e777ffad8cc/aligner_cellranger/`
(tag 4.2.0, run_root `aligner_cellranger/`, manifest megatest.yaml)

**MultiQC:** run wrote 1.35 -> used as-is

**Template requirements:**
- Always: `samples` (hub), `cellranger_metrics_summary`, `cellranger_barcode_rank` (`knee_plot`
  kind), `cellranger_embedding` (three `embedding`-kind renders sharing one table: UMAP, t-SNE,
  PCA), `cellranger_diffexp` (`da_barplot` kind), `cellranger_pca_variance` (code-mode scree
  figure), `cellbender_metrics`, `multiqc_data` (native 1.35)
- One 10x Genomics v2 lane, `pbmc8k`, GRCh38 (8,767 cells out of 499,387 raw barcodes); Cell
  Ranger route only

**2026-09-22 remediation:** every scan regex and provenance glob lost its `aligner_cellranger/`
anchor (`(?:.*/)?`, route disambiguated by `cellranger/` | `simpleaf/` | `kallisto/` in the
path), so SC2 now degrades per route instead of emptying every collection. New `cellranger`
outputs: a wide cell x marker-gene matrix (`cell_expression`, 8,767 x 127, which puts every
gene in the embedding's Colour-by menu), its long form, `hvg_dispersion`, `cell_cycle`
(Tirosh S / G2M scores), `cell_funnel` (attrition card), `diffexp` widened to every k-means
resolution, and `aligner_summary` / `cell_calls_by_method` promoted from pipeline-local
recipes. 56 collections, 9 tabs (a Compare selections tab on `group_compare` is new), 0 bare
cards, 0 partial grid rows, a tab-local filter section on every tab.

**2026-09-23 wave 3:** no tissue panel is hardcoded any more. `MARKER_PANEL`, an optional comma
list passed to the two per-cell expression recipes through their `params`, puts the reader's
genes first; without it the recipes fall back on the top markers per cluster and the most
dispersed genes, so a run on another tissue or organism ingests. CellBender metrics are read per
route from each aligner's own scan. No gene, sample or cluster label is named in any text or
default.

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| SC1 | **Cell Ranger route, single lane (validated)** | `aligner_cellranger` | none | 56 DCs declared; `knee_plot`, the `embedding` renders, `da_barplot` and the `group_compare` tab all resolve. |
| SC2 | **STARsolo / kallisto / simpleaf route** | `--aligner star\|kallisto\|simpleaf` | None of the `cellranger`/`cellbender` file-name patterns match another aligner's output | Every `cellranger_*`/`cellbender_*` collection empty; `aligner_star` also publishes no MultiQC at all for this run. |
| SC3 | **CellBender not run** | older config / CellBender skipped | No CellBender metrics | `cellbender_metrics` empty; CellBender is documented as pass-through provenance here, so nothing else degrades. |
| SC4 | **multi-lane run** | a samplesheet with more than one 10x lane | More than one `sample` value | `cellranger_diffexp`'s top-100-genes-per-cluster cap (open question 2 in the report) would need revisiting for more clusters; `barcode_rank`/`embedding` just gain rows. |
| SC5 | **MultiQC's own barcode-rank export used instead of the raw-matrix recipe** | hypothetical | MultiQC packs `(rank, count)` tuples as strings inside table cells | SC-D3: not a table a recipe can read cleanly; the fresh streaming sum off the raw matrix is what is actually bound, with the MultiQC panel kept alongside it, labelled as Cell Ranger's own rendering. |

| SC6 | **custom marker panel** | `--var MARKER_PANEL=<gene>,<gene>,...` | none | The panel genes lead the expression matrix and the long table; genes absent from the run are dropped quietly. Not exercised on a live ingest yet. |

**Ranking by template stress:** SC1 > SC2 > SC4 > SC6 > SC3 > SC5

---

## mag 5.5.0

**Megatest:** `s3://nf-core-awsmegatests/mag/results-171cf36971499cea4c9bccac4536cccbfc540e14/`
(release candidate of 5.5.0, not a tag sha: `manifest.version = '5.5.0'` four days before the
tag; run_root `.`, manifest megatest.yaml). The 5.4.2 prefix (`5dabb015`) is a truncated sync
that dropped every object under about 8 MB, and the tagged 5.5.0 run (`56abab5b`) crashed after
read QC, so the release candidate is the only complete run of this configuration.

**MultiQC:** run published no `multiqc/` -> reprocessed with 1.35 (8 modules)

**Template requirements:**
- Always: `samples` (hub, pipeline-local), `multiqc_data` (REPROCESSED parquet), the QUAST
  assembly report and length ladder (`quast/assembly_report`, `quast/length_ladder`), contig
  depths (`mag/contig_depths`), per-bin QUAST (`quast/bins_summary`), CheckM2
  (`checkm2/quality_report`), GTDB-Tk (`gtdbtk/summary`, `gtdbtk/rank_composition`), Prokka
  (`prokka/summary`, `prokka/gene_track`) and the joined `mag/bin_summary` with MIMAG tiers
- Three CAPES samples, hybrid short+long read, four assemblers x five binners; 479 bins after
  refinement, 150 placed by GTDB-Tk
- No `GenomeBinning/depths/bins/` and no contig-to-bin map are published on this prefix, so
  there is no bin x sample depth heatmap and no binner UpSet; only METAMDBG's Prokka GFFs are
  fetched (all 449 would be 1.1 GB), so the locus map covers METAMDBG bins only

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| MG1 | **default megatest (validated offline)** | none | none | 19 DCs populate: 479 bins in `bin_summary` (9 high / 154 medium / 248 low / 16 contaminated / 52 unknown MIMAG), 150 GTDB-Tk placements, 449 Prokka summaries, 222,165 contig depth rows; the phylum filter has more than one value. |
| MG2 | **a run publishing `GenomeBinning/depths/bins/` and a contig-to-bin map** | 5.4.2-style output with a complete sync | Per-bin depth table and the map exist | Would re-enable the bin x sample depth heatmap and the binner UpSet that MG-D6 dropped; the catalog outputs exist, only the manifest keys are missing. |
| MG3 | **all Prokka GFFs fetched** | a larger fetch | 449 GFFs instead of METAMDBG's 44 | `prokka/gene_track` covers every bin; the Bin detail tab's locus map stops naming METAMDBG as its scope. |
| MG4 | **fewer binners run** | e.g. `--skip_maxbin2` / `--skip_metabat2` | Fewer binner rows everywhere | `bin_summary`, `checkm2_quality_report` and `quast_bins_summary` lose their per-binner rows one for one; the Binning scope filter narrows. |
| MG5 | **GTDB-Tk skipped** | `--skip_gtdbtk` | No classification | `gtdbtk_summary` and `gtdbtk_rank_composition` empty, `bin_summary.sources_present` drops by one, the Taxonomy tab keeps only its MultiQC panel. |
| MG6 | **Prokka skipped** | `--skip_prokka` | No annotation | `prokka_summary` and `prokka_gene_track` empty, the Annotation tab's cards and the Bin detail locus map disappear. |

**Ranking by template stress:** MG1 > MG2 > MG5 > MG6 > MG4 > MG3

---

## nanoseq 3.0.0

**Megatest:** `s3://nf-core-awsmegatests/nanoseq/results-1e60482a2c4621234393a6eef8e9a104309c20ae/`
(tag 3.0.0, run_root `.`, manifest megatest.yaml)

**MultiQC:** run wrote 1.11 -> reprocessed with 1.35

**Template requirements:**
- Always: `samples` (hub), `multiqc_data` (REPROCESSED parquet: `fastqc`, `nanostat`,
  `samtools`), the long Bambu counts, `deseq2_results_raw` -> `deseq2_results` (`dc_ref`,
  `volcano`/`ma`/`qq`), `dexseq_results` (`volcano`/`qq`). The wide Bambu matrices are no longer
  declared (wave 3)
- Optional: `metadata` (`--var METADATA_FILE`; the megatest design is vendored as
  `input/sample_metadata.tsv`). The hub reads `condition` from `GROUP_COL` and protocol, source
  replicate and run id from the table, never from the FASTQ names
- SG-NEx A549 and K562 cell lines, direct-cDNA and cDNA Nanopore RNA-seq, 3 replicates each (6
  samples)
- This run publishes no pycoQC, no featureCounts, no JAFFAL fusion calls and no
  `variant_calling/` output for its parameter set

**2026-09-22 remediation:** Bambu's wide matrices are melted to long (`bambu/counts_gene_long`,
`counts_transcript_long`), which carries `sample` into every downstream collection and takes
the funnel from 1 link to 11; `bambu/sample_pca`, `sample_correlation` and
`top_variable_genes` feed a sample-structure tab; NanoStats (`nanoplot/nanostats`,
`nanostats_quality`) and samtools stats sections (`samtools/stats_sections`) give a read-QC
tab. The sample recipe splits `input_file` into `protocol` (cDNA vs direct cDNA),
`source_replicate` and `run_id`: the six libraries are one cDNA plus two direct-cDNA per cell
line off three flow cells, not three replicates. 7 tabs; the pinned reference table is cut to
the 200 best-measured genes; `gtf/transcripts` is bound `optional: true` for a run that
publishes `bambu/extended_annotations.gtf` (NS4 gains an isoform panel). The live ingest must
run from the repo venv (TEMPLATE_BOTTLENECKS 17).

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| NS1 | **default direct-cDNA/cDNA megatest (validated)** | none | none | 18 of 21 collections populate (the GTF pair and its raw scan are `optional: true`); every kind-bound `advanced_viz` tile resolves. |
| NS2 | **MultiQC not reprocessed** | omit the reprocess step | 1.11 wrote no parquet | `multiqc_data` finds nothing, whole QC tab empty, mandatory as for chipseq/atacseq/cutandrun. |
| NS3 | **pycoQC enabled** | an older/differently-configured run | Not produced by this run | Would add a pycoQC panel; NS-D1 removed the dead manifest key rather than binding one, since this run's parameter set never produces it. |
| NS4 | **fusion detection or variant calling enabled** | `is_transcripts`, `nanopolish_fast5` set | Not this run's parameters | JAFFAL fusion calls and `variant_calling/` would appear; NS-D3 removed the corresponding manifest keys since neither is triggered here. |
| NS5 | **Bambu row-id granularity on a richer reference GTF** | a non-minimal test GTF | This megatest's minimal GTF makes Bambu's `gene_id` an exon-granular GTF-attribute string, not a clean `ENSG…` id | NS-D5: only the `bambu` recipes' own regex extraction is unaffected; the reused `deseq2_results` collection keeps the raw descriptor string verbatim, so hover labels on the Differential expression tab are long strings rather than clean gene ids. |

| NS6 | **no design table** | omit `METADATA_FILE` | `metadata` pruned | `condition` is the samplesheet group; the protocol, source replicate and run id filters and donuts read `unknown`. |

**Ranking by template stress:** NS1 > NS2 > NS6 > NS5 > NS3 > NS4

---

## eager 2.4.5

**Megatest:** `s3://nf-core-awsmegatests/eager/results-42c9d5f8602e5e88fdcec28f194d2cd4cff61c75/`
(tag 2.4.5, run_root `.`, manifest megatest.yaml)

**MultiQC:** run wrote 1.13.dev0 -> reprocessed with 1.35

**Template requirements:**
- Always: `samples` (hub, fixed-path samplesheet, EA-D2), `samtools_flagstat`,
  `qualimap_bamqc_genome_results`, `damageprofiler_misincorporation` (`damage_profile` kind),
  `preseq_complexity_curve` (`profile` kind, pipeline-local override recipe, EA-D4),
  `multiqc_data` (REPROCESSED parquet)
- Two Atlantic cod libraries (`COD076E1bL1`, `COD092E1bL1i69`), BWA mapping, Picard
  MarkDuplicates (not DeDup), DamageProfiler, GATK HaplotypeCaller genotyping
- `bcftools/stats_*` is referenced from sarek, not owned here; only the MultiQC `bcftools`
  panels are bound

**2026-09-22 remediation:** the bcftools stats reports are bound (`bcftools/stats_summary`,
`stats_tstv`, keyed on `Sample_Name`), and the files the run already published now reach
tiles: endorS.py endogenous DNA (`endorspy/endogenous`), Picard MarkDuplicates metrics
(`picard/markduplicates_metrics`), AdapterRemoval per-lane settings
(`adapterremoval/settings`), four Qualimap raw tables (coverage across the reference as a
`coverage_track` and a `genome_view`, depth histogram, genome fraction, per-contig depth) and
DamageProfiler fragment lengths plus a 5' C-to-T versus mean-length authenticity plane. A
five-stage read-fate sankey chains AdapterRemoval to the flagstat totals to the read. 8 tabs,
151 components, every tab with a glance strip and a local filter section; the four one-valued
filters (UDG, organism, seq type, strandedness) are gone, lane (4 values) and run accession (6)
replace them. EA5's five collections are declared `optional: true` with globs from the eager
docs, still unexercised.

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| EA1 | **default megatest (validated)** | none | none | 30 of 36 collections populate (5 gated optional ones plus the MultiQC collection carry no Delta table); all 13 `advanced_viz` tiles resolve. |
| EA2 | **MultiQC not reprocessed** | omit the reprocess step | 1.13.dev0 wrote no parquet (pre-parquet MultiQC era, like cutandrun/nanoseq) | `multiqc_data` finds nothing, whole QC tab empty. |
| EA3 | **samplesheet not placed by hand** | default fetch only | EA-D1: eager's AWS bucket carries no `input/` prefix and no `params.json` to recover `--input` from | The hand-reconstructed `input/benchmarking_vikingfish.tsv` must be copied into `DATA_ROOT` manually or the `samples` hub is empty. |
| EA4 | **samplesheet renamed** | any filename not containing `samplesheet` | EA-D2 is closed in wave 3: `samples.py` and `lane_stats.py` glob `input/*.tsv` instead of the megatest file name | A renamed sheet still reaches the hub as long as it is the only TSV under `input/`. |
| EA5 | **sex determination / MTNucRatio / mapDamage / bedtools enabled** | not this run's config | None of those directories exist in the validated run | No catalog output binds them yet; enabling them on a future run needs new template work, not just new data. |
| EA6 | **DeDup instead of Picard MarkDuplicates** | `--dedupper dedup` | Deduplication tool's report shape changes | Not exercised: this megatest used Picard. |

| EA7 | **short-fragment cut-off changed** | `--var SHORT_FRAGMENT_BP=<bp>` | none | Since wave 3 the value reaches the `damageprofiler/authenticity` recipe through its `params`, so the short-fragment share is recomputed, not only relabelled; the output column keeps its fixed name. |

**Ranking by template stress:** EA1 > EA2 > EA3 > EA4 > EA7 > EA5 > EA6

---

## methylseq 2.3.0

**Megatest:** `s3://nf-core-awsmegatests/methylseq/results-93bc5811603c287c766a0ff7e03b5b41f4483895/bismark/`
(tag 2.3.0, run_root `bismark/`, manifest megatest.yaml)

**MultiQC:** run wrote 1.13 -> reprocessed with 1.35

**Template requirements:**
- Always: `samples` (hub, `input/*.csv`, MS-D1), `bismark_alignment_summary`,
  `bismark_deduplication_summary`, `bismark_methylation_context_summary`,
  `bismark_mbias_curve` (`profile` kind, CpG context only), `multiqc_data` (REPROCESSED
  parquet); the Coverage section references the existing `multiqc/qualimap.yaml` panel rather
  than a new recipe
- Seven E-MTAB-6511 hESC samples (MShef11 x3 low-oxygen replicates, MShef4 bulk + 3
  passage/differentiation conditions), Bismark route only
- This run has no usable Preseq output (`PRESEQ_LCEXTRAP` FAILED for 6 of 7 samples) and no
  `picard_metrics/`

**2026-09-22 remediation:** MS5 is built. The per-CpG bedGraphs (756 MB, 8 to 46 M rows per
sample) are streamed through `depictio/recipes/lib/genomic_bins.py` behind a one-row-per-file
index collection into 10 kb windows (`bismark/binned_methylation`, 19,350 windows x 7
libraries), from which `methylation_density`, `window_pca`, `window_correlation`,
`top_variable_windows` and `window_group_compare` (pooled t on the arcsine-sqrt transform,
Benjamini-Hochberg, no SciPy in the CLI venv) are derived; `bismark_summary_report` and all
M-bias contexts are read; the Qualimap outputs eager added are bound on this layout. `condition`
is split into `treatment` and `replicate` (MS-D8: cell line and oxygen condition are the same
split, stated on the dashboard). 28 collections, 14 links, 8 tabs; the `_bismark_bt2_` infix is
gone from every pattern (`bismark_[a-z0-9]+`), so MS3's hisat route parses. The group
comparison calls one window on 3 versus 4 libraries without coverage weights (MS-D7), stated
in prose on the tab.

**2026-09-23 wave 3:** the design is no longer parsed from the sample names. The hub is the
samplesheet joined to an optional design table declared through `METADATA_FILE` (the megatest
design is vendored as `input/sample_metadata.tsv`, copied into `{DATA_ROOT}/input/` before the
ingest); `GROUP_COL` drives the filters, the glance donut and the colours, and the group
comparison tests the `GROUP_COL` factor when it has two levels. Without a design table
`metadata` and `bismark_window_group_compare` are pruned. `window_group_compare` now tests every
eligible window, not the drawing stride; on the megatest no window clears padj 0.05. A `GENOME`
variable (default `hg38`) feeds the three locus tracks. 6 tabs.

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| MS1 | **Bismark route, both cell lines (validated)** | none | none | Every one of the 28 collections populates (135,450 binned-methylation rows), dashboard funnel intact across 8 tabs. |
| MS2 | **single cell line** | Sample filter narrowed to one value of the design column | none | MultiQC panels, alignment/dedup/methylation tables and the M-bias curve all narrow together through the project links. The group comparison is computed at ingest, so it keeps both groups. |
| MS3 | **`bismark_hisat` / `bwameth` route** | `--aligner bismark_hisat` or `--aligner bwameth` | Out of scope for this template (Bismark route only) | `bismark/` file-name patterns would not match either alternate route's output names, so ingestion reports 0 rows for every Bismark-tagged collection rather than erroring. |
| MS4 | **Preseq succeeds for every sample** | a future/different run | MS-D2: this run's `PRESEQ_LCEXTRAP` failed for 6 of 7 samples, so no Preseq collection is declared | The existing `preseq/complexity_curve.py` recipe would bind directly with no pipeline-specific change if a future run succeeds for every sample. |
| MS5 | **deduplicated bedGraph read as a `coverage_track`** | not built | MS-D4: `*.deduplicated.bedGraph.gz` is fetched but unread | A natural `coverage_track` fit (per-base methylation), left out to keep this lot's Bismark tool to the four report-derived summaries the brief named. |

| MS6 | **no design table** | omit `METADATA_FILE` | `metadata` and `bismark_window_group_compare` pruned | The Group comparison tab loses its test; `GROUP_COL` stays `__no_group__`, so the tiles bound to it depend on import-time pruning. |

**Ranking by template stress:** MS1 > MS6 > MS2 > MS4 > MS5 > MS3

---

## hic 2.0.0

**Megatest:** `s3://nf-core-awsmegatests/hic/results-b4d89cfacf97a5835fba804887cf0fc7e0449e8d/`
(tag 2.0.0, run_root `.`, manifest megatest.yaml)

**MultiQC:** run wrote 1.13 -> reprocessed with 1.35

**Template requirements:**
- Always: `samples`/`samplesheet` (hub), `multiqc_data` (REPROCESSED parquet: `fastqc`,
  `hicpro`), `contact_matrix` (`contact_map` kind), `eigenvector`/`eigenvalues`
  (compartments), `insulation` (`coverage_track` kind, TADs), `distance_decay` (`profile`
  kind, hicexplorer)
- One mouse ES-cell sample (`HIC_ES_4`), three FASTQ pairs HiC-Pro merges before mapping
- Contact maps fetched at the two coarsest resolutions only (the `contact_map` tile
  downsamples further)

**2026-09-22 remediation:** HiC-Pro's `stats/*.{mmapstat,mpairstat,mRSstat,mergestat}` are read
(`hicpro/pair_stats`, `hicpro/pair_flow`: attrition card, sankey raw to mapped to valid to
cis / trans, donuts), P(s) is recomputed from the contact triplet (`cooltools/distance_profile`,
40 log bins per chromosome and pooled, slope panel), TAD intervals are derived from consecutive
boundary bins per arm (`cooltools/domains`, 43,775 rows, mappability-filtered) and the
eigenvector carries an A / B `compartment` column. Three locus tracks bind `genome_view`; the
contact map gained `display: triangle`. 7 tabs (MultiQC, Run QC, Library shape, Contact maps,
Compartments, TADs and boundaries, Compare samples), 102 components, 64 on `use:`. HC4 is the
gating scenario for the Compare samples tab. Saddle plot, HiCRep, APA and the brush from a
locus track into the contact map remain undone (HC-D10 to HC-D15).

**2026-09-23 wave 3:** 7 tabs to 5 (MultiQC, Run QC, Library shape, Contact maps, Domains and
compartments); the Compare samples tab is gone. E1 is phased per sample, resolution and
chromosome so it correlates positively with bin coverage. A `GENOME` variable (default `hg38`)
feeds every track and gene lane; the bundled reference sets `GENOME: mm10`.

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| HC1 | **default megatest (validated)** | none | none | All 4 dedicated tabs populate and every `advanced_viz` tile resolves its kind; wave 3 added a domain-size box and histogram figures beside them. Re-checked offline after wave 3, not live. |
| HC2 | **MultiQC not reprocessed** | omit the reprocess step | 1.13 wrote `mqc_*.txt` only | `multiqc_data` finds nothing, QC tab empty. |
| HC3 | **finer contact-map resolution fetched** | a fetch with more resolutions | Only the two coarsest resolutions were fetched here | The `contact_map` tile's own downsampling would need re-checking against a denser bin count; not exercised. |
| HC4 | **multi-sample HiC run** | a samplesheet with more than one sample | Every dedicated-tab collection currently keys off `HIC_ES_4` alone | The hub-driven sample filter would need re-validating against more than one value, and a sample comparison tab would need adding back: wave 3 removed it for lack of a second sample. |
| HC5 | **two-resolution window mismatch in insulation** | present in the validated run (20 kb vs 40 kb windows) | HC-D8: the two resolution files scan different, only partially-overlapping window sizes | The recipe discovers windows dynamically from `df.columns` rather than assuming a fixed 3-window tuple, exactly to survive this. |
| HC6 | **pipeline-local HiCExplorer module cited by `source_url`, not `nf_core_url`** | present in the validated run | HC-D5: `_check_identity_urls()` only enforces the nf-core/modules authority on `nf_core_url` | A pipeline-local module (`HIC_PLOT_DIST_VS_COUNTS`) needs `source_url` instead, a modelling constraint rather than a data-availability scenario. |

**Ranking by template stress:** HC1 > HC2 > HC5 > HC4 > HC3 > HC6

---

## riboseq 2.0.0

**Megatest:** `s3://nf-core-awsmegatests/riboseq/results-11d66a3b8ae1f41f9c385af36bd431c35bf015ab/`
(tag 2.0.0, run_root `.`, manifest megatest.yaml)

**MultiQC:** run wrote 1.33 -> used as-is (parquet at `multiqc/star/multiqc_report_data/`)

**Template requirements:**
- Always: the samplesheet, read from `{DATA_ROOT}/input/` because the pipeline does not publish
  it (vendored with the template, copied by `download_test_data.sh`), and the riboWaltz, anota2seq,
  Ribo-TISH and RiboCode tables. 14 of the 18 collections are `optional: true`
- Optional: `metadata` (`--var METADATA_FILE`; the megatest design is vendored as
  `input/metadata.tsv`). `GROUP_COL` has no template default and is set only by metadata
  auto-detection, so a run without a design table has no group filter
- Paired Ribo-seq and RNA-seq libraries; translational efficiency and ORF overlap are computed by
  pipeline-local recipes; ORFs from the two callers are matched on a `chrom:strand:stop` key

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| RB1 | **megatest with design table (validated offline)** | `--var METADATA_FILE=<DATA_ROOT>/input/metadata.tsv` | none | 18 collections and 35 links resolve; every recipe runs on the real files; CLI dry run 8/8. Live ingestion and rendering still pending. |
| RB2 | **no design table** | omit `METADATA_FILE` | `metadata` pruned | 17 collections and 23 links; the design table and the group filter disappear. Deriving `GROUP_COL` from the contrasts file would keep the filter (TEMPLATE_BOTTLENECKS 30). |
| RB3 | **one ORF caller** | a run with Ribo-TISH or RiboCode switched off | one ORF table absent | The ORF overlap collapses to one set; the per-caller collections are optional, so the ingest continues. |

**Ranking by template stress:** RB2 > RB1 > RB3

---

## smrnaseq 2.4.1

**Megatest:** `s3://nf-core-awsmegatests/smrnaseq/results-cb0af579b24cb8d5a3accd87b2f14ea93fe04832/`
(tag 2.4.1, run_root `.`, manifest megatest.yaml)

**MultiQC:** run wrote 1.33 -> used as-is

**Template requirements:**
- Always: the mirtop joined isomiR table (the source of the expression, isomiR and design views,
  since this run publishes no mature or hairpin count matrix and no edgeR tables), the miRDeep2
  `result_*.csv` tables at the run root, and `multiqc_data`
- Optional: `metadata` (`--var METADATA_FILE`; the megatest design is vendored as
  `input/sample_metadata.tsv`), with `GROUP_COL` naming the factor for colours, strips and the
  group test
- `GENOME` (default `hg38`) names the UCSC assembly of the precursor links; the megatest was
  aligned to hg19
- Conditionals: `SKIP_MIRDEEP` drops the four miRDeep2 collections, `SKIP_MULTIQC` the MultiQC
  and miRTrace ones

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| SM1 | **megatest with design table (validated offline)** | `--var METADATA_FILE=<DATA_ROOT>/input/sample_metadata.tsv --var GROUP_COL=condition --var GENOME=hg19` | none | 17 collections; the design adds its factors to the counts and the hub. CLI dry run 8/8. |
| SM2 | **no design table** | omit `METADATA_FILE` | `metadata` pruned | The counts and the hub lose their design columns; the group comparison has no factor to test and its tiles rely on import-time pruning. Dry run 8/8. |
| SM3 | **miRDeep2 skipped** | `--skip_mirdeep` plus `--var SKIP_MIRDEEP=true` | no `result_*.csv` | The four miRDeep2 collections are pruned, and the novel-miRNA tiles with them. |
| SM4 | **assembly without a `chr` prefix** | a run on a build whose contigs are not `chr`-prefixed | precursor coordinates | The UCSC links open on a locus the browser does not know. |

**Ranking by template stress:** SM2 > SM1 > SM3 > SM4

---

## genomeassembler 2.0.0

**Megatest:** `s3://nf-core-awsmegatests/genomeassembler/results-a72d47d9cdb50f21b97882dfb2abf4af8f4c74ad/`
(tag 2.0.0, run_root `.`, manifest megatest.yaml; selective fetch, about 8.6 MB of a 961 GB prefix)

**MultiQC:** the run writes none; the template declares no `multiqc_data` collection and opens on
an Overview tab instead

**Template requirements:**
- Always: `samplesheet` (`METADATA_FILE`, default `{DATA_ROOT}/input/samplesheet.csv`, vendored),
  `GROUP_COL` (default `strategy`) for the filters and the parallel coordinates
- Every tool collection (QUAST, BUSCO, Merqury, GenomeScope, jellyfish, samtools idxstats) is
  `optional: true` and every join is a left join, so a sample a tool never reached is a null, not
  an error. 20 of 24 collections are optional

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| GA1 | **partial megatest (validated offline)** | none | one failed task aborted the assembly QC of half the samples | Every recipe runs; the samples without assembly QC stay in `sample_status` as `No assembly QC`. CLI dry run 8/8 with and without `METADATA_FILE`. |
| GA2 | **complete run** | cluster re-run with the failing step's errors ignored | every sample reaches assembly QC | The first time every tile carries all samples; submitted, not back yet. |
| GA3 | **polishing enabled** | medaka, dorado or pilon | polished stages appear | The polishing tiles are bound by file name and have never seen data. |
| GA4 | **Hi-C scaffolding** | YaHS | scaffolded stage appears | Same as GA3. |
| GA5 | **another design column** | a samplesheet whose design column is not `strategy` | none | `--var GROUP_COL=<column>`; without it the filters read an absent column. |

**Ranking by template stress:** GA2 > GA3 > GA4 > GA1 > GA5

---

## mhcquant 3.2.0

**Megatest:** `s3://nf-core-awsmegatests/mhcquant/results-6ec12c97f7889a3e1f09ab89930723045c6bac68/`
(tag 3.2.0, run_root `.`, manifest megatest.yaml, `test_full` profile)

**MultiQC:** run wrote 1.33 -> used as-is (mhcquant custom content only; general stats is
`stats_table`)

**Template requirements:**
- Always: `samples` (`METADATA_FILE`, default `{DATA_ROOT}/input/samplesheet.tsv`; the pipeline
  does not publish its samplesheet, so it is vendored and copied by `download_test_data.sh`),
  the final peptide tables, the Comet PSM tables and `multiqc_data`
- `GROUP_COL` defaults to `Condition`; since the CLI now applies declared defaults before its
  generic sentinels, no `--var` is needed for a sheet that has that column
- Conditionals set by hand, not read from `params.json`: `NO_QUANTIFICATION` prunes the replicate
  collections, `NO_ION_ANNOTATION` the fragment-ion collection
- The replicate index of each intensity column is inferred from the samplesheet id order,
  because the peptide table does not name the raw file behind it

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| MQ1 | **test_full megatest (validated offline)** | none | none | Every recipe runs on the real files; CLI dry run 8/8. |
| MQ2 | **no quantification** | `--quantify false` plus `--var NO_QUANTIFICATION=1` | no per-replicate intensities | Replicate collections pruned with their tiles. The flag is not read from `params.json` (`quantify`), so the operator must pass it. |
| MQ3 | **no ion annotation** | `--annotate_ions false` plus `--var NO_ION_ANNOTATION=1` | no fragment-ion table | The fragment-ion collection is pruned. |
| MQ4 | **replicate order differs from the samplesheet** | a run whose raw files were processed in another order | none visible | Replicate tiles attribute intensities to the wrong raw file, silently. Only a run with known replicates can detect it. |
| MQ5 | **several samples per condition** | a larger cohort | the sharing view gains depth | With one sample per condition the peptide-sharing tiles compare two samples; a cohort is needed to read them as a condition effect. |

**Ranking by template stress:** MQ4 > MQ2 > MQ5 > MQ3 > MQ1

---

## demultiplex 1.8.0

**Megatest:** `s3://nf-core-awsmegatests/demultiplex/results-daade37c4a75a4c1709ccf12434deb3424141319/`
(tag 1.8.0, run_root `.`, manifest megatest.yaml; FASTQ not fetched)

**MultiQC:** run wrote 1.35 -> used as-is. The run-level `multiqcsav/` report holds no SAV section

**Template requirements:**
- bcl2fastq route: `demux_stats`, `lane_summary`, `read_quality`, `unknown_barcodes`. With
  `IS_BCLCONVERT`, read from the run's `demultiplexer` parameter, the same four collections are
  repointed at the BCL Convert reports. 13 of 18 collections are `optional: true`, so either
  layout ingests
- Per-library hub `libraries`, fastp and Falco QC, CheckQC verdicts
- Optional: `metadata` (`--var METADATA_FILE`; the library design is vendored in the template
  directory as `input/library_metadata.tsv`); `GROUP_COL` picks the design column, else one group
- InterOp metrics need an `interop_summary --csv=1` table that the pipeline does not write

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| DM1 | **bcl2fastq megatest with design (validated offline)** | `--var METADATA_FILE=<template dir>/input/library_metadata.tsv` | none | Every recipe runs on the real files; CLI dry run 8/8. |
| DM2 | **another design column** | DM1 plus `--var GROUP_COL=<column>` | none | The tiles regroup on the chosen factor. |
| DM3 | **no design table** | omit `METADATA_FILE` | `metadata` pruned | The hub carries a single `__no_group__` group and every tile still renders. |
| DM4 | **BCL Convert route** | `--demultiplexer bclconvert` | `Reports/*.csv` instead of `Stats/Stats.json` | Validated on MultiQC test data only; a real nf-core BCL Convert run is the missing check. |
| DM5 | **multi-lane flowcell** | more than one lane | one FASTQ stem per lane | The hub's `fastq_id` holds the first lane's stem, so the MultiQC fastp and Falco rows of other lanes are not narrowed by the library filter. |
| DM6 | **InterOp summary provided** | a run with an `interop_summary --csv=1` table | sequencer metrics readable | The SAV section, validated on a fixture only, would populate. |

**Ranking by template stress:** DM4 > DM5 > DM3 > DM1 > DM6 > DM2

---

## rnasplice 1.0.4 (pending)

**Megatest:** `s3://nf-core-awsmegatests/rnasplice/results-1d0494ae3402d1a46e0adadad24f81a0ff855c77/`
is not usable: 494 objects, only 80 of them with data, no MultiQC and none of the differential
splicing output.

**Status:** the template waits for an EMBL cluster `test_full` run (two-condition design). If that
run fails twice, seqinspector 1.1.2 takes its place: its megatest
(`results-6aa08aabb00cdbb0f5b62adf2749b472e794ba04`) is complete, with a global and a per-group
MultiQC parquet, and the reason is recorded in its report.

---

## Priority additions to `generate_validation_runs.sh`

In order of value-per-effort:

1. **A2** — ampliseq, no-metadata: exercises `if_var_absent` conditional; trivial (just omit METADATA_FILE)
2. **S4** — viralrecon, skip-snpeff: hits `variants_long` recipe column logic directly; one flag
3. **A4** — ampliseq, 16S-multi + ANCOM-BC: validates full 6-dashboard path; needs metadata TSV
4. **S1** — viralrecon, skip-kraken2: tests optional module absence in MultiQC parquet; one flag
5. **A3** — ampliseq, Greengenes2: stresses taxonomy string parsing; one flag
