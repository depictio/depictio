# Enriched catalog fixtures

A catalog fixture is a small sample of an output's real table, and the catalog previews
every render on it. Taken from one run, many fixtures held one sample or one category: a
stacked bar per sample drew one bar, a PCA one point, a per-sample profile one line, a
top-N card one value. The fixtures below were grown so each preview shows what its
component does.

How they were grown:

- The real rows are kept, unchanged and first in the file (one exception: the real
  `cuppa/classifier_matrix.tsv` rows get the `TUMOR1 | <type>` label the recipe writes
  once a table holds several tumours).
- New samples continue the real naming scheme, or reuse sample names a sibling fixture of
  the same module already holds, so the fixtures of one module still join.
- Values derive from the real rows: one shift per new sample and column, plus per-row
  noise (`scripts/enrich_catalog_fixture.py`), or module-specific code where columns are
  linked (counts and percentages, compositions summing to 100, monotone curves such as
  preseq complexity, coverage survival or rarefaction, start below end, ranks).
- Columns, column order, dtypes and separator are those of the real table.

This file, not a comment in each output's YAML, records it: the YAML is part of a
module's hashed version, the fixture is not.

## Synthetic content worth knowing

These parts are not derived from a real row and should not be read as real results:

- `purple/drivers.tsv`, `purple/somatic_variants.tsv`: added variants and drivers sit on
  real cancer genes at approximate hg38 positions; HGVS strings follow the effect.
- `arriba/fusions.tsv`, `linx/fusion_structure.tsv`, `linx/svs.tsv`: well-known fusions
  and structural variants with approximate breakpoints, exon counts and domains.
- `epitopeprediction/*`: added HLA typings and mutant peptides from known hotspots
  (KRAS G12D, TP53 R175H, IDH1 R132H, BRAF V600E, PIK3CA E545K); IC50 values derived.
- `tidk/search_windows.tsv`: some added sequence lengths are invented.
- `taxpasta/profiles.tsv`, `gtdbtk/*`, `sylph/profile.tsv`, `metaphlan/profile.tsv`:
  higher-rank rows are sums of the species rows; some added taxids were written from
  memory.
- `bambu/*`, `snpeff/*`, `neo/neoepitopes.tsv`, `last/synteny_links.tsv`,
  `hmmer/hmmalign_hits.tsv`, `fcsgx/actions.tsv`, `ctatsplicing/cancer_introns.tsv`:
  added identifiers, accessions and coordinates are synthetic.
- `gsea/report.tsv`: the opposite pole of each contrast (real GSEA reports both) holds
  Hallmark sets with approximate sizes.
- `crisprseq/substitutions.tsv`: the real rows hold no substitution; the added samples
  carry small synthetic substitution rates.

## Outputs left as they are, by design

- `happy_summary`: hap.py reports SNP and INDEL only, both shown, pooled across samples.
- `optitype` `hla_class`: class I only.
- `fusioninspector_protein_domains`, the viralmetagenome contig class card and the
  orthofinder copy-class card: binary vocabularies, both values shown.
- `homer_tss_distance_profile` holds only bins upstream of the TSS; the profile's centre
  is not in the real sample.

## Fixtures

| output | fixture | real rows | rows now |
|---|---|---|---|
| agat_statistics | `agat/statistics.tsv` | 24 | 48 |
| arriba_fusions | `arriba/fusions.tsv` | 15 | 21 |
| ascat_cnv_segments | `ascat/cnv_segments.tsv` | 4 | 36 |
| ascat_purity_ploidy | `ascat/purity_ploidy.tsv` | 2 | 6 |
| bambu_counts_gene_long | `bambu/counts_gene_long.tsv` | 72 | 96 |
| bambu_counts_transcript_long | `bambu/counts_transcript_long.tsv` | 72 | 96 |
| bcftools_stats_summary | `bcftools/stats_summary.tsv` | 10 | 30 |
| bcftools_stats_tstv | `bcftools/stats_tstv.tsv` | 10 | 30 |
| bcl2fastq_unknown_barcodes | `bcl2fastq/unknown_barcodes.tsv` | 15 | 60 |
| bclconvert_demux_stats | `bclconvert/demux_stats.tsv` | 8 | 28 |
| bedtools_strand_bins | `bedtools/strand_bins.tsv` | 8 | 72 |
| cellranger_cell_qc | `cellranger/cell_qc.tsv` | 25 | 25 |
| cellranger_cluster_summary | `cellranger/cluster_summary.tsv` | 42 | 84 |
| cellranger_library_metrics_long | `cellranger/library_metrics_long.tsv` | 4 | 24 |
| cellranger_pca_variance | `cellranger/pca_variance.tsv` | 30 | 60 |
| cnvkit_cnv_profile | `cnvkit/cnv_profile.tsv` | 18 | 103 |
| combgc_region_track | `combgc/region_track.tsv` | 16 | 30 |
| combgc_tool_overlap | `combgc/tool_overlap.tsv` | 25 | 28 |
| cooltools_domains | `cooltools/domains.tsv` | 54 | 234 |
| cooltools_eigenvector | `cooltools/eigenvector.tsv` | 15 | 414 |
| crisprseq_edit_outcomes | `crisprseq/edit_outcomes.tsv` | 14 | 42 |
| crisprseq_indel_sizes | `crisprseq/indel_sizes.tsv` | 13 | 53 |
| crisprseq_substitutions | `crisprseq/substitutions.tsv` | 18 | 54 |
| ctatsplicing_cancer_introns | `ctatsplicing/cancer_introns.tsv` | 3 | 10 |
| cuppa_classifier_matrix | `cuppa/classifier_matrix.tsv` | 16 | 42 |
| cutandrun_samples | `cutandrun/samples.tsv` | 6 | 13 |
| damageprofiler_lgdistribution | `damageprofiler/lgdistribution.tsv` | 8 | 16 |
| enchantr_clonal_abundance | `enchantr/clonal_abundance.tsv` | 18 | 54 |
| enchantr_clonal_diversity | `enchantr/clonal_diversity.tsv` | 45 | 60 |
| enchantr_clonal_overlap | `enchantr/clonal_overlap.tsv` | 10 | 13 |
| enchantr_clone_sizes | `enchantr/clone_sizes.tsv` | 50 | 65 |
| enchantr_repertoire_summary | `enchantr/repertoire_summary.tsv` | 10 | 13 |
| enchantr_v_gene_matrix | `enchantr/v_gene_matrix.tsv` | 10 | 13 |
| epitopeprediction_allele_summary | `epitopeprediction/allele_summary.tsv` | 4 | 15 |
| epitopeprediction_peptides | `epitopeprediction/peptides.tsv` | 14 | 47 |
| epitopeprediction_predictions | `epitopeprediction/predictions.tsv` | 20 | 120 |
| epitopeprediction_predictor_agreement | `epitopeprediction/predictor_agreement.tsv` | 4 | 46 |
| epitopeprediction_predictor_summary | `epitopeprediction/predictor_summary.tsv` | 5 | 14 |
| fcsgx_actions | `fcsgx/actions.tsv` | 8 | 18 |
| funcscan_software_versions | `funcscan/software_versions.tsv` | 18 | 33 |
| gsea_report | `gsea/report.tsv` | 36 | 62 |
| gtdbtk_rank_composition | `gtdbtk/rank_composition.tsv` | 15 | 203 |
| gtdbtk_summary | `gtdbtk/summary.tsv` | 15 | 26 |
| gtf_transcripts | `gtf/transcripts.tsv` | 20 | 60 |
| hamronization_gene_presence | `hamronization/gene_presence.tsv` | 33 | 116 |
| hmf_bamtools_coverage_profile | `hmf_bamtools/coverage_profile.tsv` | 16 | 48 |
| hmf_bamtools_fragment_length | `hmf_bamtools/fragment_length.tsv` | 16 | 48 |
| hmf_bamtools_summary | `hmf_bamtools/summary.tsv` | 2 | 6 |
| hmmer_hmmalign_hits | `hmmer/hmmalign_hits.tsv` | 12 | 36 |
| homer_tss_distance_profile | `homer/tss_distance_profile.tsv` | 48 | 144 |
| last_synteny_links | `last/synteny_links.tsv` | 15 | 39 |
| linx_fusion_structure | `linx/fusion_structure.tsv` | 16 | 60 |
| linx_svs | `linx/svs.tsv` | 16 | 127 |
| macs2_broad_peaks | `macs2/broad_peaks.tsv` | 36 | 72 |
| macs2_summit_profile | `macs2/summit_profile.tsv` | 18 | 54 |
| mcquant_cells | `mcquant/cells.tsv` | 8 | 108 |
| mcquant_segmentation_summary | `mcquant/segmentation_summary.tsv` | 4 | 18 |
| mcquant_segmenter_agreement | `mcquant/segmenter_agreement.tsv` | 4 | 36 |
| merqury_copy_number_composition | `merqury/copy_number_composition.tsv` | 12 | 36 |
| merqury_sequence_qv | `merqury/sequence_qv.tsv` | 18 | 24 |
| metaphlan_profile | `metaphlan/profile.tsv` | 55 | 330 |
| mhcquant_fragment_ions | `mhcquant/fragment_ions.tsv` | 16 | 48 |
| mhcquant_length_distribution | `mhcquant/length_distribution.tsv` | 10 | 30 |
| mhcquant_motif_matrix | `mhcquant/motif_matrix.tsv` | 18 | 54 |
| mhcquant_peptide_composition | `mhcquant/peptide_composition.tsv` | 18 | 54 |
| mhcquant_peptides | `mhcquant/peptides.tsv` | 16 | 48 |
| mhcquant_replicate_detection | `mhcquant/replicate_detection.tsv` | 16 | 48 |
| mhcquant_replicate_intensity | `mhcquant/replicate_intensity.tsv` | 16 | 48 |
| mhcquant_replicate_pairs | `mhcquant/replicate_pairs.tsv` | 48 | 144 |
| mhcquant_sample_summary | `mhcquant/sample_summary.tsv` | 2 | 6 |
| mhcquant_source_proteins | `mhcquant/source_proteins.tsv` | 16 | 48 |
| mirdeep2_score_summary | `mirdeep2/score_summary.tsv` | 22 | 66 |
| mirtop_isomir_composition | `mirtop/isomir_composition.tsv` | 17 | 102 |
| mosdepth_per_base_bins | `mosdepth/per_base_bins.tsv` | 16 | 56 |
| mosdepth_regions | `mosdepth/regions.tsv` | 16 | 144 |
| nanoplot_nanostats_quality | `nanoplot/nanostats_quality.tsv` | 15 | 30 |
| neo_neoepitopes | `neo/neoepitopes.tsv` | 48 | 63 |
| nonpareil_summary | `nonpareil/summary.tsv` | 4 | 12 |
| orthofinder_orthogroup_matrix | `orthofinder/orthogroup_matrix.tsv` | 16 | 30 |
| preseq_complexity_curve | `preseq/complexity_curve.tsv` | 48 | 144 |
| proteinfamilies_cluster_size_distribution | `proteinfamilies/cluster_size_distribution.tsv` | 13 | 46 |
| proteinfamilies_family_metadata | `proteinfamilies/family_metadata.tsv` | 13 | 37 |
| purple_drivers | `purple/drivers.tsv` | 16 | 50 |
| purple_somatic_variants | `purple/somatic_variants.tsv` | 16 | 94 |
| qiime2_rarefaction_canonical | `qiime2/rarefaction_canonical.tsv` | 6 | 108 |
| qiime2_stacked_taxonomy_canonical | `qiime2/stacked_taxonomy_canonical.tsv` | 6 | 123 |
| qualimap_coverage_across_reference | `qualimap/coverage_across_reference.tsv` | 16 | 48 |
| qualimap_coverage_histogram | `qualimap/coverage_histogram.tsv` | 16 | 48 |
| qualimap_coverage_per_contig | `qualimap/coverage_per_contig.tsv` | 16 | 48 |
| qualimap_genome_fraction_coverage | `qualimap/genome_fraction_coverage.tsv` | 16 | 48 |
| repeatmasker_repeat_classes | `repeatmasker/repeat_classes.tsv` | 30 | 180 |
| ribowaltz_frames | `ribowaltz/frames.tsv` | 18 | 54 |
| rseqc_read_distribution | `rseqc/read_distribution.tsv` | 16 | 96 |
| samtools_flagstat | `samtools/flagstat.tsv` | 4 | 12 |
| samtools_idxstats | `samtools/idxstats.tsv` | 18 | 54 |
| samtools_stats_sections | `samtools/stats_sections.tsv` | 14 | 78 |
| seacr_consensus_peaks | `seacr/consensus_peaks.tsv` | 40 | 47 |
| seacr_frags_profile | `seacr/frags_profile.tsv` | 16 | 60 |
| seacr_peak_summary | `seacr/peak_summary.tsv` | 4 | 6 |
| seqtk_cutn_gap_lengths | `seqtk/cutn_gap_lengths.tsv` | 27 | 52 |
| snpeff_genes | `snpeff/genes.tsv` | 45 | 63 |
| snpeff_protein_lollipop | `snpeff/protein_lollipop.tsv` | 15 | 79 |
| stableexpression_stable_gene_values | `stableexpression/stable_gene_values.tsv` | 12 | 76 |
| star_log_final | `star/log_final.tsv` | 4 | 10 |
| svanalyzer_svbenchmark | `svanalyzer/svbenchmark.tsv` | 2 | 6 |
| sylph_profile | `sylph/profile.tsv` | 30 | 496 |
| tama_category_composition | `tama/category_composition.tsv` | 14 | 84 |
| tama_transcript_blocks | `tama/transcript_blocks.tsv` | 16 | 63 |
| taxpasta_profiles | `taxpasta/profiles.tsv` | 32 | 128 |
| tidk_search_windows | `tidk/search_windows.tsv` | 15 | 69 |
| vcf_filter_breakdown | `vcf/filter_breakdown.tsv` | 16 | 48 |
| vcf_substitution_spectrum | `vcf/substitution_spectrum.tsv` | 12 | 36 |
| vcf_variant_density | `vcf/variant_density.tsv` | 454 | 1362 |
| viralmetagenome_contig_classes | `viralmetagenome/contig_classes.tsv` | 14 | 60 |
| viralmetagenome_samples_overview | `viralmetagenome/samples_overview.tsv` | 4 | 8 |
| wittyer_summary | `wittyer/summary.tsv` | 4 | 12 |
