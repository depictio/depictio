/**
 * The sashimi kind's `genomespy` view: the same junctions and coverage the
 * Plotly panel draws, embedded as a zoomable GenomeSpy track.
 *
 * Mounted only while the view is selected, so a sashimi tile left on its
 * Plotly view never downloads GenomeSpy nor holds a WebGL slot. The embed goes
 * through the shared `useGenomeSpy` hook; the spec carries the shape (lanes,
 * colours, axis) and every data change (min-reads slider, dashboard filter,
 * region pick) is a `datasets.set` or a `zoomTo`, never a remount.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Text } from '@mantine/core';
import type { RootSpec } from '@genome-spy/core/spec/root.js';

import { useWebglSlot } from '../../../webglBudget';
import type { Contig, GeneRow, GenomeSpyThemeColors } from '../genomespy/genomeSpySpec';
import { BUILTIN_ASSEMBLIES } from '../genomespy/genomeSpySpec';
import { loadGeneAnnotation } from '../genomespy/geneAnnotations';
import {
  loadAssemblyContigs,
  setGenomeSpyRows,
  useGenomeSpy,
  zoomToRegion,
} from '../genomespy/useGenomeSpy';
import {
  buildSashimiGenomeSpySpec,
  COVERAGE_DATASET,
  EXONS_DATASET,
  sashimiContigs,
} from './sashimiGenomeSpySpec';
import type {
  SashimiCoverageDatum,
  SashimiExonDatum,
  SashimiJunctionDatum,
  SashimiRegion,
} from './sashimiGenomeSpySpec';

export interface SashimiGenomeSpyViewProps {
  junctions: SashimiJunctionDatum[];
  coverage: SashimiCoverageDatum[] | null;
  coverageShared: boolean;
  coverageTitle: string;
  coverageColour?: string | null;
  exons: SashimiExonDatum[];
  lanes: string[];
  annotations: string[];
  colorBy: 'annotation' | 'sample';
  laneColours: string[];
  annotationColours: string[];
  colors: GenomeSpyThemeColors;
  /** The window to show: the picked locus, a zoom, or a followed region. */
  region: SashimiRegion | null;
  annotation: 'none' | 'hg38' | 'mm10';
  logWidth: boolean;
  maxArcWidth: number;
  showCounts: boolean;
}

const SashimiGenomeSpyView: React.FC<SashimiGenomeSpyViewProps> = (props) => {
  const {
    junctions,
    coverage,
    exons,
    region,
    annotation,
    lanes,
    annotations,
    laneColours,
    annotationColours,
    colors,
  } = props;

  // One embed is one WebGL context; without a slot it draws on Canvas2D.
  const glGranted = useWebglSlot(true);
  const backend = glGranted ? 'webgl' : 'canvas';

  const assembly = annotation !== 'none' && BUILTIN_ASSEMBLIES.includes(annotation) ? annotation : null;
  const [assemblyContigs, setAssemblyContigs] = useState<Contig[] | null>(null);
  const [genes, setGenes] = useState<GeneRow[] | null>(null);
  const [annotationReady, setAnnotationReady] = useState<boolean>(!assembly);
  useEffect(() => {
    let cancelled = false;
    if (!assembly) {
      setAssemblyContigs(null);
      setGenes(null);
      setAnnotationReady(true);
      return undefined;
    }
    setAnnotationReady(false);
    Promise.all([loadAssemblyContigs(assembly), loadGeneAnnotation(assembly)]).then(
      ([contigs, genesAsset]) => {
        if (cancelled) return;
        setAssemblyContigs(contigs);
        setGenes(genesAsset?.genes ?? null);
        setAnnotationReady(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [assembly]);

  // A data-derived axis is latched from the first fetch that has junctions,
  // like genome_view's seed: a later empty fetch must not shrink the axis to
  // nothing under a live embed.
  const seedContigsRef = useRef<Contig[] | null>(null);
  if (!seedContigsRef.current && junctions.length) {
    seedContigsRef.current = sashimiContigs(junctions, coverage);
  }
  const contigs =
    assembly && assemblyContigs && assemblyContigs.length ? assemblyContigs : seedContigsRef.current;
  const axisAssembly = assembly && assemblyContigs && assemblyContigs.length ? assembly : null;

  // Read through refs so the spec memo keys on shape only.
  const dataRef = useRef({ junctions, coverage, exons, region });
  dataRef.current = { junctions, coverage, exons, region };

  const hasCoverage = coverage !== null;
  const built = useMemo(() => {
    if (!annotationReady || !contigs || !contigs.length) return null;
    const d = dataRef.current;
    return buildSashimiGenomeSpySpec({
      lanes,
      annotations,
      colorBy: props.colorBy,
      laneColours,
      annotationColours,
      colors,
      contigs,
      assembly: axisAssembly,
      initialRegion: d.region,
      junctions: d.junctions,
      coverage: hasCoverage ? (d.coverage ?? []) : null,
      coverageShared: props.coverageShared,
      coverageTitle: props.coverageTitle,
      coverageColour: props.coverageColour,
      exons: d.exons,
      genes,
      logWidth: props.logWidth,
      maxArcWidth: props.maxArcWidth,
      showCounts: props.showCounts,
    });
    // Arrays are compared by content: the renderer rebuilds them every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    annotationReady,
    contigs,
    axisAssembly,
    genes,
    hasCoverage,
    lanes.join('\u0000'),
    annotations.join('\u0000'),
    laneColours.join(','),
    annotationColours.join(','),
    colors.textColor,
    colors.gridColor,
    colors.palette.join(','),
    props.colorBy,
    props.coverageShared,
    props.coverageTitle,
    props.coverageColour,
    props.logWidth,
    props.maxArcWidth,
    props.showCounts,
  ]);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const { api, error } = useGenomeSpy(containerRef, (built?.spec ?? null) as RootSpec | null, {
    backend,
  });

  // Data moved under a live embed: swap the datasets in place.
  useEffect(() => {
    if (!api) return;
    setGenomeSpyRows(api, junctions as unknown as Record<string, unknown>[]);
    api.datasets.set(EXONS_DATASET, exons);
    if (coverage) api.datasets.set(COVERAGE_DATASET, coverage);
  }, [api, junctions, exons, coverage]);

  // A region pick, a zoom from the Plotly view, or a followed dashboard region.
  const regionKey = region ? `${region.chrom}:${region.start}-${region.end}` : '';
  useEffect(() => {
    const target = dataRef.current.region;
    if (!api || !target) return;
    void zoomToRegion(api, target);
  }, [api, regionKey]);

  return (
    <>
      {/* GenomeSpy sizes its canvas to this box; the frame's flex column
          gives it the height. */}
      <div
        ref={containerRef}
        className="depictio-sashimi-genomespy"
        style={{ width: '100%', height: '100%', minHeight: 200, position: 'relative' }}
      />
      {error ? (
        <Text size="xs" c="red" style={{ position: 'absolute', top: 4, left: 8 }}>
          GenomeSpy: {error}
        </Text>
      ) : null}
    </>
  );
};

export default SashimiGenomeSpyView;
