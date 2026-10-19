# nf-core/genomeqc 1.0.1 template validation report

Validated offline against the AWS megatest of the 1.0.1 release,
`results-bce44e5b558e21b38d4dd2b6521302246b4dae6d` (`test_full`, software_versions.yml:
`nf-core/genomeqc: v1.0.1-gbce44e5`, Nextflow 26.04.6): three RefSeq assemblies with their
annotations, BUSCO on the hymenoptera_odb10 lineage, FCS-GX on NCBI's test-only database,
RepeatMasker with a RepeatModeler library, tidk, OrthoFinder v3. The run is 54,093 objects / 1.2 GB,
53,910 of them OrthoFinder internals; the fetched subset is 105 files, 7.9 MB
(`bash download_test_data.sh`), plus the vendored design table.

**Megatest:** `s3://nf-core-awsmegatests/genomeqc/results-bce44e5b558e21b38d4dd2b6521302246b4dae6d/`
(tag 1.0.1, run_root `.`, manifest megatest.yaml)

**MultiQC:** run wrote 1.35 -> used as-is (QUAST only: Assembly Statistics, Number of Contigs, and
the general statistics)

## What was verified offline

| Check | Result |
| --- | --- |
| `depictio dashboard validate --offline dashboards/base.yaml` | pass |
| `test_template_conventions.py`, `test_shipped_dashboard_yamls.py`, `test_template_dc_order.py` with `-k genomeqc` | 22 passed; six warn-only "median of a percentage" notices, see Open issues |
| `test_advanced_viz_config_alignment.py`, `test_catalog.py` | pass |
| `depictio/tests/recipes/test_genomeqc_recipes.py` (catalog: BUSCO mode, tidk, AGAT, RepeatMasker, OrthoFinder, FCS-GX, FCS-adaptor, Tiara) and `test_genomeqc_project_recipes.py` (karyotype, gene overlaps, hub) | 24 passed |
| `depictio/tests/catalog/` and `depictio/tests/recipes/` (the BUSCO change touches genomeassembler's recipes) | 726 passed; 4 `test_conformance_project.py` failures, see GQ-D9 |
| `depictio dev catalog validate` | pass (131 tools) |
| Every recipe of the template over the mirrored megatest (`execute_recipe`, input and output schemas, in declaration order) | pass, row counts below |
| `depictio ingest --template nf-core/genomeqc/1.0.1 --dry-run` on the megatest with `METADATA_FILE` | 24 of 24 collections ingest, 0 empty, 0 missing sources |
| Five route variants of the mirror (genome-only, `--skip_tidk`, no decontamination, no `--te`, `--skip_busco`) and no design table | every required collection and the hub build; the route's collections fail as optional, see Routes |

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| metadata | 3 (vendored: family, subfamily, accession) |
| multiqc_data | 1 report (module quast) |
| quast_assembly_raw | 3 |
| quast_assembly_report | 3 |
| quast_length_ladder | 18 (3 assemblies x 6 minimum lengths) |
| busco_batch_raw | 6 (3 genome-mode + 3 proteins-mode summaries) |
| busco_batch_summary | 6 |
| busco_composition | 24 (6 runs x 4 classes) |
| tidk_search_windows | 75,704 (10 kb windows over 9,473 sequences) |
| busco_karyotype | 698 (19, 275 and 404 sequences holding a complete BUSCO) |
| agat_statistics | 1,487 |
| agat_gene_models | 22 (10, 8 and 4 transcript types) |
| gene_overlaps | 3 |
| orthofinder_species_stats | 3 |
| orthofinder_orthogroup_matrix | 9,543 orthogroups |
| orthofinder_orthologue_matrix | 3 x 3 |
| ortho_seq_count | 3 |
| fcsgx_contamination | 3 |
| fcsgx_actions | 3 (1 EXCLUDE range, 2 clean assemblies as `none`) |
| fcsadaptor_actions | 3 (1 TRIM range, 2 `none`) |
| tiara_classifications | 3,120 (the raw assemblies; 174, 1,052 and 1,894 sequences of 3 kb or more) |
| repeatmasker_repeat_classes | 90 (30 lines per assembly) |
| repeatmasker_masking_summary | 3 |
| genomes | 3 (47 columns with the design) |

## Routes (RULES section 13)

Simulated by removing each route's outputs from a copy of the mirror and running every collection in
declaration order, then reading the importer's gates (`_component_has_data`,
`_prune_unresolved_text_values`, `_tab_meets_minimum`, orphaned highlights) against what each
component binds; the live import is pending (section 15 below).

| Route | Result |
| --- | --- |
| Full run (the megatest) | nothing dropped |
| Genome-only (no GFF) | `agat_*`, `gene_overlaps`, `orthofinder_*` and `ortho_seq_count` fail as optional (no files); the Annotation and Orthology tabs, the Annotate and Compare steps, the orthology findings row and two highlights go; the karyotype reads `busco/genome/<a>/ideogram/` (simulated, 698 rows). The proteins card prints a dash and the genome-against-annotation scatter has no points (GQ-D6) |
| `--skip_tidk` | `tidk_search_windows` and, through its dc_ref, `busco_karyotype` fail as optional: the Karyotype tab and the karyotype findings row go |
| No FCS-GX database | the four decontamination collections fail as optional: the Contamination tab and the Screen step go |
| No `--te` (or `--te hite`) | both RepeatMasker collections fail as optional: the Repeats tab and the Mask step go |
| `--skip_busco` | the BUSCO collections and the karyotype fail as optional: the Completeness and Karyotype tabs, the Complete step, two findings rows and one highlight go; the BUSCO key figure prints a dash |
| No design table | `metadata` is dropped; the hub carries `__no_group__` ("All genomes") |

## Open rows per tab (stored heights)

| Tab | Open rows | Open sections |
| --- | --- | --- |
| Overview | 21 of 24 | hero 1, about 3, pipeline 3, key figures 2, findings 10, how to read 2 |
| MultiQC | 13 | 1 (the intro is 1 of them) |
| Assembly | 15 | strip + 2 (contiguity 6, length ladder 6; tables collapsed) |
| Contamination | 7 | strip + 1 (foreign share and Tiara classes 4; tables collapsed) |
| Completeness | 14 | strip + 2 (BUSCO classes 5, genome against annotation 6; table collapsed) |
| Karyotype | 15 | strip + 2 (BUSCO ideogram 6, telomeric repeat ideogram 6; table collapsed) |
| Repeats | 8 | strip + 1 (repeat classes 5; tables collapsed) |
| Annotation | 13 | strip + 2 (gene models 6, genes and overlaps 4; tables collapsed) |
| Orthology | 13 | strip + 2 (UpSet 5, one-to-one heatmap 5; tables collapsed) |

## Findings on the megatest

- **Contiguity.** One chromosome-level assembly (177 sequences, N50 13.6 Mb, L50 7) and two
  scaffold-level ones (2,506 and 3,836 sequences above QUAST's 500 bp floor, N50 1.41 Mb and 522 kb,
  L50 53 and 103). N bases per 100 kb: 583, 1,981 and 6,689.
- **Completeness.** Complete BUSCOs 99.3%, 99.2% and 97.6% in the assemblies, 98.8%, 99.0% and 97.7%
  in their proteins: the annotations keep almost every conserved gene the assemblies hold.
  Duplicated BUSCOs stay at or below 0.5%.
- **Karyotype.** The complete BUSCOs sit on 19, 275 and 404 sequences; on the chromosome-level
  assembly the busiest sequence holds 12.7% of them, on the scaffold-level ones at most 2.1%. That
  is genomeqc's "sequences above x BUSCOs" signal, drawn to scale.
- **Telomeres (GQ-D3).** The run gave no `--repeat`, and `tidk explore` picked three units that are
  simple repeats rather than an insect telomere (an A run with a G, an 8-mer and a 7-mer, none of
  them TTAGG). The repeat ideogram is drawn as the run computed it; the intro tells the reader to
  check the unit first.
- **Contamination.** genomeqc's FCS-GX table puts 0.15% to 0.31% of each assembly as foreign, on
  the test-only database (GQ-D4). FCS-GX flags a single 2.1 kb scaffold for exclusion; FCS-adaptor
  one 25 bp adaptor to trim. Tiara calls 26 to 148 sequences per assembly bacterial and 67 to 253
  unknown, nearly all short scaffolds: a lead, not a verdict, as the intro says.
- **Repeats.** RepeatMasker masks 17.3%, 21.4% and 29.3% of the assemblies; unclassified repeats
  are the largest class in all three (7.5% to 12.4%), then DNA transposons.
- **Annotation.** 9,934, 10,632 and 9,876 protein-coding genes, 7.2 to 7.5 exons per mRNA on the
  longest isoform, 2.9% to 3.8% single-exon genes; 24% to 40% of the genes overlap another.
- **Orthology.** 9,543 orthogroups: 8,542 reach all three genomes (8,034 of them single-copy), 949
  two, 52 one; 95.8% to 96.9% of each genome's genes are placed. One-to-one orthologues between pairs
  run from 8,111 to 8,421.

## Decisions and defects

- **GQ-D1** genomeqc publishes neither BUSCO's full table nor a sequence-length table. The
  karyotype (`recipes/busco_karyotype.py`) reads genomeqc's IDEOGRAM CSV (complete BUSCOs per
  sequence) and takes the lengths from tidk (catalog `tidk/search_windows`, the last window of a
  sequence ends at its length), so it shades whole sequences by BUSCO density instead of placing
  single genes coloured by status. A run with `--skip_tidk` has no karyotype. The IDEOGRAM CSV is a
  genomeqc file shape, not a BUSCO one, so its recipe is pipeline-keyed; the catalog output carrying
  `renders_as: ideogram` is `tidk/search_windows` (`telomere_karyotype`).
- **GQ-D2** QUAST and MultiQC label an assembly after its FASTA (`GCF_..._genomic`), every other tool
  after the samplesheet name. The hub keys on the QUAST report's directory and keeps the FASTA label
  as `assembly_label` for the links to the QUAST tables and MultiQC; the length-ladder curves are
  named after the FASTA (the catalog `quast/*` recipes are unchanged).
- **GQ-D3** the tidk units of this run are simple repeats (above); nothing in the template assumes a
  telomere.
- **GQ-D4** the megatest's FCS-GX database is NCBI's test-only build (3,042 sequences, 0.28 Gbp):
  the contamination numbers exercise the tiles, they do not screen the assemblies.
- **GQ-D5** catalog `busco/batch_summary` gained `busco_mode`: genomeqc names its runs
  `<assembly>-<lineage>-<mode>-busco`, and without the mode the genome and protein runs of one
  assembly collapsed into one row. `busco/composition` carries it and adds `run_id` (one bar per
  run) with a new render `class_composition_by_run`; a summary without the mode keeps `busco_mode`
  null and `run_id` = the assembly (genomeassembler unchanged, its tests pass). The proteins-mode
  batch summary has 8 header fields and 13 on its row, so the raw scan sets
  `truncate_ragged_lines`.
- **GQ-D6** on a genome-only run the Completeness tab keeps two tiles that read the proteins mode
  (the "Complete in the proteins" card and the genome-against-annotation scatter), which then show a
  dash and no points instead of being pruned; the Overview's completeness row prints a dash for
  the protein value.
- **GQ-D7** Tiara is read on the raw assemblies only (`tiara/raw/`, `source_overrides`); genomeqc's
  second pass on the cleaned assemblies is left out.
- **GQ-D8** OrthoFinder's tens of thousands of per-orthogroup files are never fetched; the three
  summary tables are. The species tree (`Species_Tree/`, `tree/genome_anno/tree.nw`) is fetched but
  not drawn: with three tips it says nothing the UpSet does not.
- **GQ-D9** the catalog gained 11 outputs (`tidk/search_windows`, `agat/statistics`,
  `agat/gene_models`, `repeatmasker/repeat_classes`, `repeatmasker/masking_summary`,
  `orthofinder/species_stats`, `orthofinder/orthogroup_matrix`, `orthofinder/orthologue_matrix`,
  `fcsgx/actions`, `fcsadaptor/actions`, `tiara/classifications`) and two BUSCO fixtures changed;
  `depictio/projects/init/catalog_conformance` (shared, not edited here) must be regenerated
  (`python -m depictio.projects.init.catalog_conformance.scripts.generate_project`) for
  `test_conformance_project.py` to pass again.

## Section 15 live check (pending, no stack in this environment)

Every item below is **pending live check**; nothing here has been seen rendered.

| Item | Status |
| --- | --- |
| The Overview fits in about two screens, values fill in, highlights draw, `tab:` links open | pending live check |
| Controls dock right on full-width viz and on top of narrower ones | pending live check |
| No tile shows an empty band or a cut body; no tick label cut, no legend scrolling over ticks | pending live check |
| The map draws its tiles and points | not applicable (no map) |
| Each dock shows a few controls and "More options"; every view switch draws (the repeat-class rank switch, the ideogram mode switch) | pending live check |
| The group has the same colour on figures, advanced viz and the filter chips | pending live check |
| Every child tab opens on its intro; every KPI card draws its secondary and caption, no bar reads about 1%, each icon in its own colour | pending live check |
| The Guide's demos are not empty | pending live check |
| Each conditional route renders without a broken highlight or a stray `{VAR}` | pending live check |
| A genome picked in the left panel moves every card of a child tab; both karyotypes open on data | pending live check |

## Open issues

- Six cards take the median of a `*_pct` column (lint rule f, warn only): each row is one assembly,
  so the median is the intended reading.
- The orthogroup UpSet and the one-to-one heatmap have one column per genome; the persistent genome
  filter narrows the heatmap's rows but not the UpSet's sets (an orthogroup row carries no genome).
- The karyotype ideograms keep each genome's 24 longest sequences (`max_chromosomes: 24`); a draft
  assembly's hundreds of scaffolds are counted on the cards but not all drawn.
- `tidk_search_windows` is 75,704 rows, served whole to the ideogram (its sampling policy is
  `none`); not measured live.
- Not read: HiTE output (`--te hite`), Merqury (only with reads), the genomeqc tree summary plot.

## Validation scenarios

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| GQ1 | **test_full megatest (validated offline)** | `test_full`, release run `bce44e5b` | none | 24 of 24 collections populate: 3 genomes, 698 karyotype sequences, 75,704 tidk windows, 9,543 orthogroups; CLI dry run 24/24. |
| GQ2 | **genome-only** | a samplesheet without GFF | no AGAT, overlaps, OrthoFinder, protein BUSCO; ideogram under `busco/genome/` | Annotation and Orthology tabs pruned (simulated); the proteins tiles of Completeness show a dash (GQ-D6). The `<a>_<lineage>.csv` ideogram name is inferred from the docs, unseen on a real run. |
| GQ3 | **skip tidk** | `--skip_tidk` | no tidk | No sequence lengths: the Karyotype tab is pruned with tidk (simulated). |
| GQ4 | **known telomere** | `--repeat TTAGG` | `tidk/<a>/search/apriori/<repeat>/` | The a priori search wins over the a posteriori one (unit-tested); the repeat ideogram then reads as a telomere map. Unseen on a real run. |
| GQ5 | **no decontamination** | `--gxdb` and `--gxdb_manifest` unset | no `decontamination/`, `fcsgx/` | Contamination tab pruned (simulated). |
| GQ6 | **HiTE instead of RepeatMasker** | `--te hite` | `hite/<a>/` instead of `repeatmasker/` | No recipe reads HiTE: the Repeats tab is pruned. |
| GQ7 | **OrthoFinder v2** | `--ortho_version v2` | `orthofinder/v2/...`, no hierarchical orthogroups | The three summary tables keep their names; the recipes' globs do not name the version. Unseen. |
| GQ8 | **real FCS-GX database** | `--gxdb` on the full GX database | real contamination calls | The flagged-range tiles and the foreign-share threshold read real calls for the first time. |
| GQ9 | **no design table** | omit `METADATA_FILE` | none | `metadata` pruned, one constant group. |

**Ranking by template stress:** GQ2 > GQ8 > GQ4 > GQ7 > GQ3 > GQ5 > GQ6 > GQ1 > GQ9
