# nf-core/viralmetagenome 1.2.0: validation report

Offline validation against the AWS megatest run
`s3://nf-core-awsmegatests/viralmetagenome/results-74064a43f4b00c163c22bcfc9cf1d84a2a69e988/`
(the 1.2.0 release tag, `test_full` profile: four paired-end metagenomic libraries of one virus,
three from cell culture and one clinical sample; MEGAHIT assembly, CD-HIT-EST clustering with the
reference pool, one refinement cycle, iVar variants and consensus, and three mapping constraints,
two named references and one picked by Mash from a pool). No server, no ingestion, no
screenshots: the live check (RULES section 15) is still to do, item by item below.

## Data

- Fetched with `python scripts/nfcore_megatest.py fetch --pipeline viralmetagenome --version 1.2.0 --max-file-mb 20`
  (`bash download_test_data.sh`, which also copies the vendored metadata): 580 files, 42 MB of a
  320 MB, 994-object run. BAM, BAI, FASTQ, mpileup, bwa-mem2 indices, Mash sketches and Picard
  PDFs are skipped: no tile reads them.
- Every file name carries the run's `--global_prefix` (`test_20260916_1.2.0_<run name>-`),
  including the MultiQC data folder, so every glob matches on the suffix.
- The run wrote MultiQC 1.27 (`multiqc/<prefix>-multiqc_data/`, no parquet). The parquet was
  rebuilt with `python -m depictio.dev_scripts.multiqc_reprocess --src <dest> --dest <dest> --exclude '*_mqc.tsv'`
  (MultiQC 1.35): modules bcftools, fastp, fastqc, kraken, mosdepth, picard, prokka, samtools,
  1248 parquet rows. The per-sample cluster summaries (`*.summary_mqc.tsv`) are excluded: alone
  they turn into one custom-content section per sample named after the run prefix. The
  pipeline's other custom-content sections (contig completeness, contig taxonomy, failed contig
  quality) are built in the work directory and are not published. QUAST's per-consensus
  `*.tsv` files are published as one-line pointers (`<id>/report.tsv`), not reports; the QUAST
  numbers come from the overview tables instead.
- The pipeline does not publish the `--metadata` table it merged into its samples overview.
  `input/metadata.tsv` is the nf-core/test-datasets `metadata_testfull.tsv` reduced to five
  columns, with one design column added for the demo, `specimen` (`Cell culture` for the three
  cultured isolates, `Clinical sample` for the swab), read off `sample_alias`.
  `input/samplesheet.csv` and `input/mapping_constraints.csv` are the run's sheets, vendored for
  reference; no recipe reads them.

## Recipe runs on the megatest

Run with `execute_recipe` in the order the template declares them, with the template's source
overrides, with the vendored metadata.

| Collection | Rows |
| --- | --- |
| `metadata` (scan) | 4 |
| `multiqc_data` (scan) | 1 parquet, 8 modules |
| `vmg_samples_overview` | 4 |
| `samples` | 4 |
| `read_funnel` | 12 |
| `vmg_contig_classes` | 81 (27 contigs and 54 reference-pool sequences) |
| `vmg_clusters` | 9 |
| `vmg_contigs` | 27 |
| `vmg_contigs_overview` | 4 |
| `vmg_contig_iterations` | 10 |
| `vmg_mapping_overview` | 7 |
| `checkv_quality` | 17 |
| `genomes` | 11 (4 de novo, 7 constraint) |
| `ivar_variants` | 2342 |
| `coverage_bins` | 5983 (10 mappings, 50 bp bins) |
| `coverage_cumulative` | 1011 |

What the data says, so the tiles are read against it: 369 to 10,092 raw read pairs per sample,
0.02 % to 5.7 % host, 94 % to 100 % of the pairs retained, Q30 above 99.5 % everywhere. The three
cultured isolates assemble into one to three contigs and one cluster each; the clinical sample
into 22 contigs (2.1 kb N50) and six clusters, five filtered out. Eleven consensus genomes: the
cultured ones at 0.45 % to 1.54 % N, 97.9 % to 100 % identity to the closest reference and 96 % to
99 % breadth at 10X; the clinical ones at 35 % and 92 % N and 1 % to 6 % breadth. iVar writes 2342
calls, 81 of them PASS (40 fixed, 5 major, 36 minor; 73 SNVs, 8 deletions) across 10 genomes; 2294
calls sit under half frequency, almost all filtered. CheckV ran on the minimal test database:
every consensus is `Not-determined` and completeness is null.

## Checks run

- `python -m depictio.cli dashboard validate dashboards/base.yaml --offline`: passes.
- `python -m depictio.cli run --template nf-core/viralmetagenome/1.2.0 --data-root <megatest> --dry-run`:
  the dry-run preview lists 16 collections, all `ok`, 0 empty, 0 missing sources, with the
  metadata table and without passing it (the CLI then finds `input/metadata.tsv` under the data
  root). Steps 1 to 8 need a server and stop at step 1 here.
- `pytest depictio/tests/models/test_template_conventions.py depictio/tests/models/test_shipped_dashboard_yamls.py depictio/tests/models/test_template_dc_order.py -k viralmetagenome`:
  22 passed. Eight warn-level notes of `test_no_mean_of_percentages_warn_only` (median of a
  per-sample or per-genome percentage: host, Q30, duplicates, N, identity, breadth); each is a
  per-entity measure, not a share to be pooled.
- `pytest depictio/tests/recipes/test_viralmetagenome_recipes.py depictio/tests/recipes/test_viralmetagenome_project_recipes.py`:
  29 passed.
- `pytest depictio/tests/models depictio/tests/recipes depictio/tests/cli/utils/test_compose.py`:
  4339 passed, 2 failures in `test_s3_access.py` (botocore client defaults of this environment,
  unrelated).
- `depictio dev catalog validate`: 122 tools valid. `pytest depictio/tests/models/test_catalog.py`:
  106 passed. `pytest depictio/tests/catalog depictio/tests/models/test_advanced_viz_config_alignment.py`:
  112 passed, 4 failures in `test_conformance_project.py`: the conformance project is a
  generated artefact, regenerated once at integration for the 11 new catalog outputs.
- Every column a tile names exists in the table of its data collection, checked against the
  recipe outputs above, with the metadata table (`specimen`) and without it (`__no_group__`).
- Row budget (open sections, stored `h`): Overview 21 of 24; MultiQC 17, Samples 13, Contigs 13,
  Consensus 16, Mapping 15, Variants 15 of 20. Text tiles checked against `text_layout`.
- Pruning simulated route by route with the import's rules (a tile on an absent optional
  collection goes, a values line citing one goes, a tab left without a filter or a non-metadata
  tile goes, a highlight whose source went goes):
  - the full run and no `METADATA_FILE`: nothing is pruned;
  - `--skip_assembly`: the Contigs tab, the refinement profile on Consensus, the contigs
    highlight, steps 2 and 3 and the first findings row go; Consensus, Mapping and Variants keep the
    constraint genomes;
  - no `--mapping_constraints`: nothing is pruned, the genome hub holds the de novo genomes;
  - `--skip_precluster`: nothing is pruned, every contig reads `Not classified`;
  - `--skip_checkv`: the CheckV table goes; the CheckV card reads the tier from the overview;
  - `--skip_variant_calling`: the Variants tab, its highlight, step 6 and the last findings row go.

## Scenarios

**Megatest:** `s3://nf-core-awsmegatests/viralmetagenome/results-74064a43f4b00c163c22bcfc9cf1d84a2a69e988/`
(tag 1.2.0, run_root `.`, manifest megatest.yaml; tables-only fetch, 42 MB of 320 MB)

**MultiQC:** run wrote 1.27 -> reprocessed with 1.35 (`--exclude '*_mqc.tsv'`)

**Template requirements:**
- Always: the samples overview (`vmg_samples_overview`, `samples`, `read_funnel`), the genome hub
  (`genomes`, from either overview) and `multiqc_data`
- Optional: `metadata` (`--var METADATA_FILE`, the `--metadata` table, vendored as
  `input/metadata.tsv`); `GROUP_COL` is its first factor column (`specimen` on the reference)
- Every route-dependent collection (contigs, clusters, classification, both genome overviews,
  CheckV, iVar, mosdepth) is `optional: true`; no route flag is needed

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| VM1 | **test_full megatest (validated offline)** | `--var METADATA_FILE=<data root>/input/metadata.tsv` | none | Every recipe runs on the real files; dry-run preview 16/16 collections. |
| VM2 | **no metadata table** | omit `METADATA_FILE` | `metadata` pruned | The hub carries `__no_group__` and the overview's factor columns; every tile renders with one group. |
| VM3 | **constraint route only** | `--skip_assembly` | no contigs, clusters or de novo consensus | Contigs tab, refinement profile, contigs highlight and their Overview lines pruned (simulated). |
| VM4 | **de novo route only** | no `--mapping_constraints` | no `mapping_overview.tsv`, no Mash screen | The genome hub holds de novo genomes only; the Mash columns of the mapping table are empty. |
| VM5 | **several assemblers** | `--assemblers spades,megahit,trinity` | one idxstats and one QUAST block per assembler | `assembler` gains values; the samples overview reads the longest assembly. Not seen on data. |
| VM6 | **several viruses or segments** | a metagenome with more than one virus, or a segmented one | several clusters refined per sample, several annotations | `virus` gains values (the colours, the Virus filter); the genome view lists more references. Not seen on data. |
| VM7 | **bcftools caller** | `--variant_caller bcftools` | no raw iVar tables | `ivar_variants` is empty and the Variants tab is pruned; the bcftools VCFs are not read yet. |
| VM8 | **no global prefix** | `--prefix` unset | file names without the run prefix | The globs match on the suffix and the prefix strip is a no-op; not seen on data. |
| VM9 | **full CheckV database** | `--checkv_db` the full release | completeness estimated | The CheckV tier and completeness fill in; validated on a fixture only. |

**Ranking by template stress:** VM6 > VM7 > VM3 > VM5 > VM9 > VM4 > VM2 > VM8 > VM1

## Not verified (pending live check, RULES section 15)

Each item of section 15 needs a running stack with the template ingested from the megatest:

- pending live check: the Overview fits in about two screens, values fill in, highlights draw,
  `tab:` links open;
- pending live check: controls dock right on full-width viz and on top of the w4 and w5 ones
  (depth against breadth, cumulative coverage, identity against ambiguity);
- pending live check: no tile shows an empty band or a cut body; no tick label is cut, no legend
  scrolls or overlaps (the depth profile and the cumulative curves carry ten series);
- pending live check: no map in this template (nothing to draw);
- pending live check: each dock shows a few controls and "More options"; no view switch here;
- pending live check: the group has the same colour on the sample scatter, the Samples card and
  the filter chips;
- pending live check: every child tab opens on its intro; every KPI card draws its secondary and
  its caption, no bar reads about 1 %, each icon shows in its own colour;
- pending live check: the Guide's demos are not empty (group filter and Samples card on
  `samples`, boxed KPI strips, selectable scatters, tab links);
- pending live check: each conditional route still renders without a broken highlight or a stray
  `{VAR}` (simulated offline above);
- pending live check: a sample picked in the left panel moves every card of a child tab
  (through the `samples` links, MultiQC through `sample_mapping` on prefixed report rows); the
  Variants genome view opens on data (`default_region: first`).

Other open points:

- Genome browser. The filtered VCFs are published next to the index of the sorted VCF they were
  filtered from, so no published VCF has its own index: an `indexed_file` collection and a
  file-backed `genome_view` are not possible on this release. The calls are drawn from the table
  collection instead (`TODO(jbrowse)` in base.yaml). With several references in a run the view's
  axis lists each reference; each lane holds its calls on its own reference.
- MultiQC report rows carry the run prefix (`<prefix>-<sample>_<reference>...`); the link relies
  on `sample_mapping` attaching a name to the hub sample it holds as a whole token
  (`canonicalize_to_hub`, rule 4). Checked offline on the reprocessed parquet: 78 of its 99 row
  names attach to one of the four samples; the 21 left are FastQC's overrepresented sequences and
  one header row. Not yet seen narrowing a panel on a stack.
- The reprocessed MultiQC report lacks the pipeline's custom-content sections; the MultiQC tab
  pins tool modules only.
