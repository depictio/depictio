# nf-core/oncoanalyser 3.0.0: validation report

Offline validation against the AWS megatest run
`s3://nf-core-awsmegatests/oncoanalyser/results-7c74c87a43749952b38c9a18915947570f0595a0/`
(the 3.0.0 release, `test_full` profile). No server, no ingestion, no screenshots: the live
check (RULES section 15) is still to do.

## Data

- Fetched with `python scripts/nfcore_megatest.py fetch --pipeline oncoanalyser --version 3.0.0
  --max-file-mb 100`: 29 tables and small VCFs, 32.7 MB of a 272 GB run (604 files, almost all
  BAMs). The manifest names the PURPLE, LINX, BamTools, QSEE, CHORD, CUPPA, SIGS, LILAC, TEAL and
  Neo tables and the PURPLE somatic VCF; the PAVE and SAGE twins of that VCF, AMBER, COBALT,
  ESVEE, Isofox and the plot inputs are left out.
- One WGTS subject in one analysis group: a tumor/normal DNA pair and a tumor RNA sample. Every
  tumor-level table has a single row per gene, SV or call of that tumor; BamTools and TEAL have
  one row per DNA sample. Cohort-level behaviour (group colours, boxes over several tumors) is
  checked on the recipes' synthetic tests, not on this run.
- The run publishes no reported fusion and no MultiQC report parquet.
- The samplesheet is not published: `input/samplesheet.csv` is the test-datasets sheet, one row
  per input file, collapsed by the `samples` recipe to one row per sample.
- `pipeline_info/params.json` is the run's own file without the three reference-bundle tables
  (`genomes`, `hmf_data_paths`, `panel_data_paths`), which the template's provenance excludes.

## Recipe runs on the megatest

Run through `execute_recipe` on the fetched tree, in the order the template declares them.

| Collection | Shape |
| --- | --- |
| `samples` | 3 x 8 |
| `purple_purity` | 1 x 31 |
| `purple_cnv_segments` | 2755 x 12 |
| `purple_gene_copy_number` | 39072 x 15 (150 genes gained or lost, 22813 with LOH) |
| `purple_drivers` | 410 x 22 |
| `purple_somatic_variants` | 43040 x 32 |
| `purple_protein_changes` | 478 x 19 |
| `purple_protein_genes` | 458 x 10 |
| `linx_svs` | 1421 x 24 |
| `linx_fusions` | 139 x 27 |
| `linx_fusion_structure` | 554 x 11 |
| `cuppa_predictions`, `cuppa_classifier_matrix` | 320 x 7, 40 x 11 |
| `sigs_allocation` | 13 x 5 |
| `chord_prediction`, `teal_telomere_length` | scans: 1 and 2 rows |
| `lilac_alleles` | 14 x 16 |
| `neo_neoepitopes` | 566 x 16 |
| `hmf_bamtools_summary`, `_coverage_profile`, `_fragment_length` | 2 x 29, 502 x 5, 352 x 4 |
| `qsee_status` | 29 x 9 |

Every column a component names (card and filter columns, table columns, record card sections,
figure kwargs, advanced viz roles, text values and their filter expressions) was checked against
these tables: all resolve. Every `use:` handle resolves in the catalog.

## Checks run

- `python -m depictio.cli dashboard validate --offline dashboards/base.yaml`: passes.
- `python -m depictio.cli run <data root> --template nf-core/oncoanalyser/3.0.0 --dry-run`: 22
  collections, all sources found. On a copy without CUPPA, SIGS, CHORD, LILAC, TEAL, Neo and
  QSEE the dry run lists their six recipe collections as missing and the two scans as empty,
  and ingests the other 14.
- `pytest depictio/tests -k "oncoanalyser or template_conventions or shipped_dashboard or
  template_dc_order or nfcore"`: 1702 passed, 4 skipped, no failure (including
  `test_oncoanalyser_recipes.py` and the catalog tests of the hmftools tools).
- The catalog conformance project was regenerated in a scratch copy and its tests pass with the
  ten oncoanalyser tools; the regenerated files are not committed.
- Row budget (open sections, stored `h`): Overview 23 of 24; Sequencing QC 13, Tumor profile 19,
  Copy number 16, Structural variants 15, Drivers 13, Small variants 13, Protein changes 14,
  Immune context 15 of 20. Text tiles checked against `text_layout`.
- A scratch lint of the RULES points no unit test covers: tab family (groups, order, subtitles),
  KPI strips (four cards, one icon and colour each), section icons and colours against
  `sectionIcons.ts`, section descriptions at 90 characters, banned keys (`controls_placement`,
  `icon_style`, `title_font_size`, `color_discrete_map`), hex colours outside `category_colors`,
  em dashes, megatest forbidden terms, highlight sources, tab links.
- Pruning simulated with the import's rules (`_prune_unresolved_text_values`, orphaned sections,
  the tab minimum) for four routes:
  - no optional tool: the Immune context tab goes (every visualisation binds LILAC, Neo or TEAL);
    Sequencing QC loses the QC verdicts section, Tumor profile the Tissue of origin and Mutational
    processes sections; the signature finding and its highlight, and the Classify and Type steps,
    lose their lines; the four Key figures stay.
  - no QSEE: only the QC verdicts and QC reference tables sections go.
  - no LILAC, Neo and TEAL: the Immune context tab and the Type step go.
  - no CUPPA and SIGS: the Tissue of origin section, the signature finding, its highlight and the
    Classify step go; the HRD card stays.

## Not verified

- Ingestion, rendering and the live Guide on a running stack.
- The structure resolver (`DEPICTIO_STRUCTURE_RESOLVER_ENABLED=true`): the Protein changes tab
  was written for it; with it off the structure tile says so and the rest of the tab works.
- Highlights of the copy-number profile, the signature bars and the chord diagram at w4 on the
  Overview, and the chord diagram and the resolved-event bar at w4 on their tab.
- The oncoplot and the gene scatter of this run have a single tumor column and 150 gained or
  lost genes: whether they read well on a cohort is untested.
- A cohort or a panel run: the recipes are tested on synthetic outputs, but only the test_full
  WGTS layout has been fetched.
