# nf-core Template Validation Scenarios

Scenarios identified for `generate_validation_runs.sh` extension, plus runs already
executed on the EMBL cluster for this branch.

Derived analytically from template YAML data collections and pipeline option space.
Priority order at the bottom.

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
  `depictio/cli/cli/utils/templates.py` maps only the ampliseq and viralrecon flags, so a
  run that skipped a step needs the matching `--var`. Every affected collection is either
  optional or pruned by its conditional, so a run that omits the flag still ingests.

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
  the ampliseq and viralrecon flags, so `SKIP_ARRIBA`, `SKIP_STARFUSION`,
  `SKIP_FUSIONCATCHER`, `SKIP_FUSIONINSPECTOR`, `SKIP_CTATSPLICING` and `SKIP_QC` must be
  passed by hand as `--var`. `SAMPLESHEET_FILE` overrides where the sheet is looked for
- The fusion, not the sample, is the key of every collection. rnafusion writes one file per
  tool per sample with the sample encoded only in the file name, and `resolve_sources`
  concatenates the globbed files without their path, so no caller table can carry a sample
  column. The samplesheet therefore reaches only the MultiQC panels
- Observed on this megatest (the pipeline's own test profile, one synthetic sample `test`
  with all three callers, FusionInspector and CTAT-splicing enabled): 20 consensus fusions
  over 45 caller-evidence rows, Arriba and STAR-Fusion reporting 14 distinct fusions each
  and FusionCatcher 17, FusionInspector validating 14, 184 Pfam domain rows over 12 fusions,
  200 scored junctions over 14 chromosomes, and `cancer_introns` header-only

### Further scenarios (analytical, not yet run)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| F1 | **multi-sample cohort** | any samplesheet with more than one row | Each caller writes one file per sample, all matched by the same glob | The highest-stress scenario and the one this megatest cannot reach. `resolve_sources` drops the path, so every caller table silently pools the cohort into one frame with no sample column and no `depictio_run_id` (transformed collections never get one). Counts stay arithmetically correct but stop being per sample, and the same fusion called in two samples collapses to rows that cannot be told apart. Also the only way to exercise the sample axis at all: the persistent `Sample filters` MultiSelect, the `sample_mapping` fan-out and every per-sample MultiQC panel are single-valued here. Needs a run before the template is claimed cohort-safe. |
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

**Scenarios:**

| Scenario | Flags | Expected effect |
|---|---|---|
| narrowPeak default (validated) | none | all 10 DCs populated |
| broad peaks | `--broad_peak` | `macs/broadPeak/*_peaks.broadPeak` is BED6+3 with no summit column: `macs2_peaks` finds nothing. Needs a dedicated `macs2/broad_peaks` output, deferred |
| single replicate per antibody | design with one replicate | no consensus peak set is built; `macs2_consensus_*` and both `deseq2_*` DCs empty |
| single condition per antibody | design with one group | consensus built, DESeq2 not run; both `deseq2_*` DCs empty |
| `--skip_peak_annotation` | flag | `homer_annotated_peaks` and `homer_tss_distance_profile` empty; the Peaks tab loses its annotation section |
| `--skip_preseq` | flag | `preseq_ccurve_raw` finds nothing, so `preseq_complexity_curve` is empty and the complexity ribbon tile has no data. The MultiQC preseq panel goes with it |
| `--skip_plot_profile` / `--skip_plot_fingerprint` | flags | `deeptools_plot_profile` / `deeptools_fingerprint_metrics` empty; the two ChIP-enrichment tiles below the MultiQC panels lose their data |
| `--skip_consensus_peaks` / `--skip_diff_analysis` | flags | Consensus and Differential binding tabs lose their data |
| MultiQC not reprocessed | (omit the reprocess step) | `multiqc_data` finds no parquet; the whole QC tab is empty. This is the pipeline's normal state: the reprocess is mandatory, not optional |

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

## Priority additions to `generate_validation_runs.sh`

In order of value-per-effort:

1. **A2** — ampliseq, no-metadata: exercises `if_var_absent` conditional; trivial (just omit METADATA_FILE)
2. **S4** — viralrecon, skip-snpeff: hits `variants_long` recipe column logic directly; one flag
3. **A4** — ampliseq, 16S-multi + ANCOM-BC: validates full 6-dashboard path; needs metadata TSV
4. **S1** — viralrecon, skip-kraken2: tests optional module absence in MultiQC parquet; one flag
5. **A3** — ampliseq, Greengenes2: stresses taxonomy string parsing; one flag
