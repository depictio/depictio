import React, { useCallback, useMemo, useState } from 'react';
import { Autocomplete, Group, Select, Text } from '@mantine/core';

import type { InteractiveFilter, StoredMetadata } from '../../../api';
import { genomeRegionFilters } from '../../../selection';
import type { Contig, GeneRow, GenomeRegion } from './genomeSpySpec';
import { findGenes, formatLocus, geneWindow, resolveLocus } from './locusParse';

/**
 * The address bar of a locus section: type `chr7:55,000,000-56,000,000` or a
 * gene symbol and every tile bound to the same coordinates follows.
 *
 * It emits exactly what the `genome_view` brush emits, the two ordinary
 * filters of `genomeRegionFilters`, so there is one way a region travels the
 * dashboard and not two. Typing is then the same act as dragging, and the
 * chromosome Select beside it is the same act again with no range.
 *
 * Deliberately not a genome browser's address bar in one respect: it never
 * navigates anything by itself. It writes a filter, the filter reaches the
 * tiles, and the tiles decide what to do with it (a genome_view zooms, a
 * coverage_track clamps its axis, a transcript_structure changes gene). That
 * is why it needs no knowledge of who is listening.
 */

interface Props {
  /** The emitting tile: its index and dc_id ride on both filters. */
  metadata: StoredMetadata;
  /** This tile's own chromosome and position columns. */
  chrColumn: string;
  posColumn: string;
  /** Contigs to offer, from the assembly or derived from the data. */
  contigs: readonly Contig[] | null;
  /** Gene table for symbol search, `null` when no annotation lane is loaded. */
  genes: readonly GeneRow[] | null;
  /** Absent on read-only hosts: the control then renders disabled. */
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** The region currently in force, to show in the field. */
  region?: { chrom: string; start: number; end: number } | null;
}

const LocusInput: React.FC<Props> = ({
  metadata,
  chrColumn,
  posColumn,
  contigs,
  genes,
  onFilterChange,
  region,
}) => {
  const [text, setText] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  const contigNames = useMemo(() => (contigs ?? []).map((c) => c.name), [contigs]);

  const emit = useCallback(
    (next: GenomeRegion | null) => {
      if (!onFilterChange) return;
      for (const filter of genomeRegionFilters(metadata, chrColumn, posColumn, next)) {
        onFilterChange(filter);
      }
    },
    [onFilterChange, metadata, chrColumn, posColumn],
  );

  const submit = useCallback(
    (raw: string) => {
      const value = raw.trim();
      if (!value) {
        setError(null);
        emit(null);
        return;
      }
      const resolved = resolveLocus(value, contigNames, genes);
      if (!resolved) {
        setError(
          genes?.length
            ? 'Not a locus on this collection, and no gene of that name'
            : 'Not a locus on this collection',
        );
        return;
      }
      setError(null);
      setText(formatLocus(resolved.chrom, resolved.start, resolved.end));
      emit({
        chroms: [resolved.chrom],
        range:
          resolved.start !== null && resolved.end !== null
            ? [resolved.start, resolved.end]
            : null,
      });
    },
    [contigNames, genes, emit],
  );

  /** Gene suggestions for what is being typed, never for a locus string. */
  const suggestions = useMemo(() => {
    if (!genes?.length || text.includes(':')) return [] as string[];
    return findGenes(genes, text).map((g) => g.name);
  }, [genes, text]);

  const placeholder = region ? formatLocus(region.chrom, region.start, region.end) : 'chr7:55,000,000-56,000,000';

  return (
    <Group gap={6} wrap="nowrap" align="flex-start">
      <Select
        size="xs"
        w={120}
        aria-label="Chromosome"
        placeholder="Chromosome"
        value={region?.chrom ?? null}
        data={contigNames}
        onChange={(v) => {
          setText('');
          setError(null);
          // A contig with no range is the whole contig, which is what the
          // brush publishes when it spans one.
          emit(v ? { chroms: [v], range: null } : null);
        }}
        disabled={!onFilterChange || contigNames.length === 0}
        clearable
        searchable={contigNames.length > 8}
      />
      <Autocomplete
        size="xs"
        w={230}
        aria-label="Locus or gene"
        placeholder={placeholder}
        value={text}
        data={suggestions}
        error={error}
        disabled={!onFilterChange}
        onChange={(v) => {
          setText(v);
          if (error) setError(null);
        }}
        onOptionSubmit={(v) => {
          const gene = findGenes(genes, v, 1)[0];
          if (!gene) {
            submit(v);
            return;
          }
          const window = geneWindow(gene);
          setText(formatLocus(window.chrom, window.start, window.end));
          setError(null);
          emit({ chroms: [window.chrom], range: [window.start, window.end] });
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            submit(text);
          }
        }}
      />
      {!genes?.length ? (
        <Text size="xs" c="dimmed" style={{ alignSelf: 'center' }}>
          chr:start-end
        </Text>
      ) : null}
    </Group>
  );
};

export default LocusInput;
