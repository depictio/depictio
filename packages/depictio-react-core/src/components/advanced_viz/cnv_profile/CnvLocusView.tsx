import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { Text } from '@mantine/core';
import type { RootSpec } from '@genome-spy/core/spec/root.js';

import type { InteractiveFilter, StoredMetadata } from '../../../api';
import { genomeRegionFilters } from '../../../selection';
import type { FollowedRegion } from '../genomicAxis';
import { regionFromInterval } from '../genomespy/genomeSpySpec';
import type { GeneRow } from '../genomespy/genomeSpySpec';
import {
  setGenomeSpyRows,
  useGenomeSpy,
  zoomToRegion,
} from '../genomespy/useGenomeSpy';
import type { GenomeSpyBackend } from '../genomespy/useGenomeSpy';
import { buildCnvLocusSpec } from './cnvLocusSpec';
import type { CnvLocusColors, LocusDatum } from './cnvLocusSpec';

export interface CnvLocusViewProps {
  metadata: StoredMetadata;
  /** The locus dataset, already narrowed to the samples that get tracks. */
  data: LocusDatum[];
  lanes: string[];
  faceted: boolean;
  showBaf: boolean;
  yRange: number;
  pointSize: number;
  gainThreshold: number;
  lossThreshold: number;
  colors: CnvLocusColors;
  genes: readonly GeneRow[] | null;
  backend: GenomeSpyBackend;
  /** Chromosome and start columns of the collection, which the brush filters on. */
  chromColumn: string;
  startColumn: string;
  /** A region brushed elsewhere on the dashboard; the tracks zoom onto it. */
  followedRegion: FollowedRegion | null;
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/**
 * The `cnv_profile` locus view: GenomeSpy's ASCAT layout on the tile's rows.
 *
 * Same mount model as `genome_view` (`useGenomeSpy`): the spec carries the
 * shape (which tracks, which samples, colours, thresholds) and is rebuilt only
 * when that shape changes; a new sample, a moved filter or a refresh swaps the
 * dataset in place, which keeps the reader's zoom. The brush publishes the same
 * `genome_selection` pair as `genome_view` (`genomeRegionFilters`), so any
 * genomic tile of the section follows it, and an incoming region zooms the
 * tracks.
 */
const CnvLocusView: React.FC<CnvLocusViewProps> = ({
  metadata,
  data,
  lanes,
  faceted,
  showBaf,
  yRange,
  pointSize,
  gainThreshold,
  lossThreshold,
  colors,
  genes,
  backend,
  chromColumn,
  startColumn,
  followedRegion,
  onFilterChange,
}) => {
  // The spec is built from the data present when the shape last changed; later
  // rows are swapped in below. Until some rows exist there is no genome to lay
  // out, so emptiness is part of the shape.
  const dataRef = useRef(data);
  dataRef.current = data;
  const hasData = data.length > 0;
  const colourKey = JSON.stringify(colors);
  const lanesKey = lanes.join('\u0000');
  const brush = Boolean(onFilterChange);

  const built = useMemo(
    () =>
      hasData
        ? buildCnvLocusSpec({
            data: dataRef.current,
            lanes,
            faceted,
            showBaf,
            yRange,
            pointSize,
            gainThreshold,
            lossThreshold,
            colors,
            genes,
            brush,
          })
        : null,
    // `lanes` and `colors` are keyed by value: hosts hand fresh arrays each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [hasData, lanesKey, faceted, showBaf, yRange, pointSize, gainThreshold, lossThreshold, colourKey, genes, brush],
  );
  const spec = (built?.spec ?? null) as RootSpec | null;
  const contigs = built?.contigs ?? null;

  const handleBrush = useCallback(
    (interval: number[] | null) => {
      if (!onFilterChange || !contigs) return;
      const region = regionFromInterval(contigs, interval);
      for (const filter of genomeRegionFilters(metadata, chromColumn, startColumn, region)) {
        onFilterChange(filter);
      }
    },
    [onFilterChange, contigs, metadata, chromColumn, startColumn],
  );

  const containerRef = useRef<HTMLDivElement | null>(null);
  const { api, error } = useGenomeSpy(containerRef, spec, {
    backend,
    onBrush: brush ? handleBrush : undefined,
  });

  useEffect(() => {
    if (!api) return;
    try {
      setGenomeSpyRows(api, data as unknown as Record<string, unknown>[]);
    } catch {
      // A shape change (facet, BAF, thresholds) and a data change can land in
      // the same commit: the hook has then already finalised this `api` and
      // not yet published its successor, which is built from the current rows
      // anyway and gets them again when it arrives.
    }
  }, [api, data]);

  useEffect(() => {
    if (!api || !followedRegion) return;
    const size = contigs?.find((c) => c.name === followedRegion.chrom)?.size;
    if (size === undefined) return;
    const end = Number.isFinite(followedRegion.end) ? Math.min(followedRegion.end, size) : size;
    // A rejected zoom comes from an embed the hook finalised in the same commit;
    // its successor zooms again when it is published.
    zoomToRegion(api, { chrom: followedRegion.chrom, start: followedRegion.start, end }).catch(
      () => undefined,
    );
  }, [api, followedRegion, contigs]);

  const message = error ?? (hasData ? null : 'No rows for this sample');
  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', minHeight: 200 }}>
      <div
        ref={containerRef}
        className="depictio-cnv-locus"
        style={{ position: 'absolute', inset: 0 }}
      />
      {message ? (
        <Text
          size="sm"
          c="dimmed"
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            pointerEvents: 'none',
            textAlign: 'center',
          }}
        >
          {message}
        </Text>
      ) : null}
    </div>
  );
};

export default CnvLocusView;
