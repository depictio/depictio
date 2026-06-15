# nf-core Template Validation Scenarios

Scenarios identified for `generate_validation_runs.sh` extension, plus runs already
executed on the EMBL cluster for this branch.

Derived analytically from template YAML data collections and pipeline option space.
Priority order at the bottom.

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

## Priority additions to `generate_validation_runs.sh`

In order of value-per-effort:

1. **A2** — ampliseq, no-metadata: exercises `if_var_absent` conditional; trivial (just omit METADATA_FILE)
2. **S4** — viralrecon, skip-snpeff: hits `variants_long` recipe column logic directly; one flag
3. **A4** — ampliseq, 16S-multi + ANCOM-BC: validates full 6-dashboard path; needs metadata TSV
4. **S1** — viralrecon, skip-kraken2: tests optional module absence in MultiQC parquet; one flag
5. **A3** — ampliseq, Greengenes2: stresses taxonomy string parsing; one flag

## MultiQC version compatibility note

viralrecon 3.0.0 ships MultiQC **1.31**; ampliseq 2.16.0 and 2.17.0 ship **1.33**.
If a depictio template reads MultiQC parquet, verify that column names and schema are
stable across those two minor versions before assuming cross-pipeline portability.
