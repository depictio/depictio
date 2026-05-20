/**
 * Genome annotation registry for the CoverageTrack renderer.
 *
 * Each entry is keyed by *any* chromosome / contig name a project may use to
 * refer to the underlying sequence (RefSeq accession, GenBank accession,
 * unversioned, ``chr``-prefixed, …). The renderer matches the bound DC's
 * chromosome value against this table and, on a hit, draws a labelled gene
 * strip across the bottom of the coverage track.
 *
 * Entries are derived from canonical RefSeq GFFs (bundled alongside this
 * module for provenance — e.g. ``MN908947.3.gff``). Coordinates are
 * 1-based inclusive (GFF convention). Adding a new organism = (1) drop the
 * RefSeq GFF next to this file, (2) extract genes via
 * ``awk -F'\t' '$3 == "gene"' …``, (3) append to ``ANNOTATIONS_BY_ID`` and
 * register every common chromosome alias in ``ANNOTATIONS_BY_ALIAS``.
 *
 * Auto-detection only works when the bound DC's chromosome value matches one
 * of the registered aliases. For data with non-standard chromosome names,
 * dashboards can pin an explicit ``annotation_id`` in the viz config — that
 * wins over chromosome-name auto-detection.
 */
export interface GenomeFeature {
  /** Display label (gene symbol, ORF name). */
  name: string;
  /** 1-based inclusive start. */
  start: number;
  /** 1-based inclusive end. */
  end: number;
  /** Strand ('+' / '-' / '.'). Not currently rendered, but kept for future arrows. */
  strand?: '+' | '-' | '.';
}

export interface GenomeAnnotation {
  /** Stable identifier used by ``CoverageTrackConfig.annotation_id`` overrides. */
  id: string;
  /** Display name for the assembly (shown in tooltips / UI hints). */
  displayName: string;
  /** Reference sequence length (used to clamp / sanity-check the x-axis). */
  length: number;
  /** Source URL / citation for the underlying GFF. */
  source: string;
  /** Ordered list of gene features along the sequence. */
  features: GenomeFeature[];
}

/** SARS-CoV-2 Wuhan-Hu-1 (RefSeq NC_045512.2 / GenBank MN908947.3). */
const SARS_COV_2: GenomeAnnotation = {
  id: 'sars_cov_2',
  displayName: 'SARS-CoV-2 (Wuhan-Hu-1)',
  length: 29903,
  source: 'NCBI RefSeq NC_045512.2 (= GenBank MN908947.3)',
  features: [
    { name: 'ORF1ab', start: 266, end: 21555, strand: '+' },
    { name: 'S', start: 21563, end: 25384, strand: '+' },
    { name: 'ORF3a', start: 25393, end: 26220, strand: '+' },
    { name: 'E', start: 26245, end: 26472, strand: '+' },
    { name: 'M', start: 26523, end: 27191, strand: '+' },
    { name: 'ORF6', start: 27202, end: 27387, strand: '+' },
    { name: 'ORF7a', start: 27394, end: 27759, strand: '+' },
    { name: 'ORF7b', start: 27756, end: 27887, strand: '+' },
    { name: 'ORF8', start: 27894, end: 28259, strand: '+' },
    { name: 'N', start: 28274, end: 29533, strand: '+' },
    { name: 'ORF10', start: 29558, end: 29674, strand: '+' },
  ],
};

/** Respiratory syncytial virus A (RefSeq NC_038235.1). */
const RSV_A: GenomeAnnotation = {
  id: 'rsv_a',
  displayName: 'RSV-A',
  length: 15222,
  source: 'NCBI RefSeq NC_038235.1',
  features: [
    { name: 'NS1', start: 45, end: 576, strand: '+' },
    { name: 'NS2', start: 596, end: 1098, strand: '+' },
    { name: 'N', start: 1125, end: 2327, strand: '+' },
    { name: 'P', start: 2329, end: 3242, strand: '+' },
    { name: 'M', start: 3252, end: 4209, strand: '+' },
    { name: 'SH', start: 4219, end: 4628, strand: '+' },
    { name: 'G', start: 4673, end: 5595, strand: '+' },
    { name: 'F', start: 5648, end: 7550, strand: '+' },
    { name: 'M2', start: 7597, end: 8557, strand: '+' },
    { name: 'L', start: 8489, end: 15067, strand: '+' },
  ],
};

/** HIV-1 reference (RefSeq NC_001802.1).
 *  Overlapping reading frames are intrinsic to the virus — the strip will draw
 *  them stacked at the same y; that's biologically accurate. */
const HIV_1: GenomeAnnotation = {
  id: 'hiv_1',
  displayName: 'HIV-1',
  length: 9181,
  source: 'NCBI RefSeq NC_001802.1',
  features: [
    { name: 'gag-pol', start: 336, end: 4642, strand: '+' },
    { name: 'gag', start: 336, end: 1838, strand: '+' },
    { name: 'vif', start: 4587, end: 5165, strand: '+' },
    { name: 'vpr', start: 5105, end: 5396, strand: '+' },
    { name: 'tat', start: 5377, end: 7970, strand: '+' },
    { name: 'rev', start: 5516, end: 8199, strand: '+' },
    { name: 'vpu', start: 5608, end: 5856, strand: '+' },
    { name: 'env', start: 5771, end: 8341, strand: '+' },
    { name: 'nef', start: 8343, end: 8963, strand: '+' },
  ],
};

/** Hepatitis B virus (RefSeq NC_003977.2). Circular genome — annotation
 *  shown linearly. */
const HBV: GenomeAnnotation = {
  id: 'hbv',
  displayName: 'Hepatitis B virus',
  length: 3182,
  source: 'NCBI RefSeq NC_003977.2 (circular genome, shown linearly)',
  features: [
    { name: 'X', start: 1376, end: 1840, strand: '+' },
    { name: 'C', start: 1816, end: 2454, strand: '+' },
    { name: 'P', start: 2309, end: 4807, strand: '+' },
    { name: 'S', start: 2850, end: 4019, strand: '+' },
  ],
};

/** Registry of all bundled annotations, keyed by stable ``id``. */
const ANNOTATIONS_BY_ID: Record<string, GenomeAnnotation> = {
  sars_cov_2: SARS_COV_2,
  rsv_a: RSV_A,
  hiv_1: HIV_1,
  hbv: HBV,
};

/** Lookup table: any chromosome alias a project may use → its annotation. */
const ANNOTATIONS_BY_ALIAS: Record<string, GenomeAnnotation> = {
  // SARS-CoV-2
  'MN908947.3': SARS_COV_2,
  MN908947: SARS_COV_2,
  'NC_045512.2': SARS_COV_2,
  NC_045512: SARS_COV_2,
  // RSV-A
  'NC_038235.1': RSV_A,
  NC_038235: RSV_A,
  // HIV-1
  'NC_001802.1': HIV_1,
  NC_001802: HIV_1,
  // HBV
  'NC_003977.2': HBV,
  NC_003977: HBV,
};

/** All available annotation ids — useful for builder UI dropdowns. */
export const AVAILABLE_ANNOTATION_IDS: { id: string; displayName: string }[] = Object.values(
  ANNOTATIONS_BY_ID,
).map((a) => ({ id: a.id, displayName: a.displayName }));

/** Resolve a config-pinned annotation id to an annotation. Returns null when
 *  the id isn't registered (typo / outdated dashboard). */
export function annotationById(id: string | null | undefined): GenomeAnnotation | null {
  if (!id) return null;
  return ANNOTATIONS_BY_ID[id] ?? null;
}

/** Match a chromosome string to a bundled annotation, returning null if the
 *  chromosome isn't one we recognise. Comparison is case-insensitive and
 *  ignores leading ``chr`` for cross-source robustness. */
export function lookupAnnotation(chromosome: string | null | undefined): GenomeAnnotation | null {
  if (!chromosome) return null;
  const normalised = chromosome.replace(/^chr/i, '').trim();
  return (
    ANNOTATIONS_BY_ALIAS[normalised] ??
    ANNOTATIONS_BY_ALIAS[normalised.toUpperCase()] ??
    null
  );
}

/** Two-tier resolution: explicit ``annotation_id`` override wins, otherwise
 *  fall back to chromosome-name auto-detection. Used by the renderer so the
 *  same logic applies whether the user pinned an id in the YAML or relies on
 *  auto-detection. */
export function resolveAnnotation(
  annotationId: string | null | undefined,
  chromosome: string | null | undefined,
): GenomeAnnotation | null {
  return annotationById(annotationId) ?? lookupAnnotation(chromosome);
}
