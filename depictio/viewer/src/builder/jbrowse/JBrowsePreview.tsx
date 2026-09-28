/**
 * Preview for the genome browser builder.
 *
 * The browser itself is configured server-side from the *saved* component
 * (POST /dashboards/render_jbrowse/{dashboard}/{component}), so an unsaved
 * draft can't be drawn. The preview therefore summarises what the draft will
 * show — the reference, the track limits, and the first manifest rows the
 * dashboard filters let through — and, when editing a saved component, offers
 * the live view of its last saved version next to that summary.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Box,
  Group,
  ScrollArea,
  SegmentedControl,
  Stack,
  Table,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { ComponentRenderer, fetchDataCollectionPreview } from 'depictio-react-core';
import type { PreviewResult } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import { useBuilderPreviewFilters } from '../useBuilderPreviewFilters';
import PreviewPanel from '../shared/PreviewPanel';
import type { JBrowseConfig } from './JBrowseBuilder';
import type { GenomicTracksProps } from './jbrowseApi';

const PREVIEW_ROWS = 50;
const SHOWN_ROWS = 12;

interface Props {
  /** The bound DC's genomic_tracks properties; null while loading or for a
   *  legacy jbrowse2 collection. */
  dcProps: GenomicTracksProps | null;
}

const JBrowsePreview: React.FC<Props> = ({ dcProps }) => {
  const dcId = useBuilderStore((s) => s.dcId);
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const existing = useBuilderStore((s) => s.existing);
  const dcConfigType = useBuilderStore((s) => s.dcConfigType);
  const config = useBuilderStore((s) => s.config) as JBrowseConfig;
  const previewFilters = useBuilderPreviewFilters();
  const filterKey = JSON.stringify(previewFilters);

  const savedJBrowse = existing?.component_type === 'jbrowse' ? existing : null;
  const [view, setView] = useState<'summary' | 'saved'>('summary');

  const [data, setData] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // `dcConfigType` is only known in the create flow; editing reads the type
  // from the DC config the builder fetched.
  const isLegacy = (dcConfigType || dcProps?.dcType || '').toLowerCase() === 'jbrowse2';

  useEffect(() => {
    if (!dcId || isLegacy) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchDataCollectionPreview(dcId, PREVIEW_ROWS, previewFilters)
      .then((res) => !cancelled && setData(res))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dcId, isLegacy, filterKey]);

  // The manifest columns worth showing, in reading order; the rest of the
  // manifest is in the columns description under the form.
  const shownColumns = useMemo(() => {
    if (!data?.columns?.length) return [];
    const wanted = [
      dcProps?.nameColumn,
      dcProps?.trackIdColumn,
      dcProps?.sampleColumn,
      config.selection_column,
      dcProps?.formatColumn,
      dcProps?.uriColumn,
    ];
    const out: string[] = [];
    for (const c of wanted) {
      if (c && data.columns.includes(c) && !out.includes(c)) out.push(c);
    }
    return out.length ? out : data.columns.slice(0, 4);
  }, [data, dcProps, config.selection_column]);

  if (!dcId) {
    return (
      <PreviewPanel
        minHeight={320}
        empty
        emptyMessage="Pick a genomic tracks data collection to preview its tracks."
      />
    );
  }

  const maxTracks = config.max_tracks ?? 20;
  const initialTracks = config.initial_tracks ?? 5;
  const assembly = config.assembly || dcProps?.assembly;
  const filtered = Boolean(data?.filter_applied);
  const matching = data?.total_rows ?? 0;
  const shownCount = filtered ? Math.min(matching, maxTracks) : Math.min(initialTracks, maxTracks);
  const plural = (n: number, word: string) => `${n.toLocaleString('en-US')} ${word}${n === 1 ? '' : 's'}`;
  const pinned = config.default_tracks?.length ?? 0;
  const ucsc = config.ucsc_tracks?.length ?? 0;
  const extras = [
    pinned ? `${pinned} always-shown` : '',
    ucsc ? plural(ucsc, 'UCSC track') : '',
  ].filter(Boolean);
  const countLine = [
    filtered
      ? `${plural(matching, 'manifest row')} ${matching === 1 ? 'matches' : 'match'} the dashboard filters`
      : `No filter applies: the view opens with the first ${plural(initialTracks, 'track')}`,
    `up to ${shownCount} shown (limit ${maxTracks})${extras.length ? `, plus ${extras.join(' and ')}` : ''}.`,
  ].join('; ');

  const summary = (
    <Stack gap="sm">
      <Group gap="xs" wrap="nowrap">
        <Icon icon="mdi:dna" width={20} color="var(--mantine-color-dimmed)" />
        <Text fw={700} lineClamp={1}>
          {config.title || 'Genome browser'}
        </Text>
      </Group>
      <Group gap={6}>
        <Badge variant="light" radius="sm">
          {assembly ? `Assembly: ${assembly}` : "Collection's assembly"}
        </Badge>
        <Badge variant="light" radius="sm" color="gray">
          {config.location || 'Default location'}
        </Badge>
        {config.preset && (
          <Badge variant="light" radius="sm" color="gray">
            Preset: {config.preset}
          </Badge>
        )}
        {config.selection_enabled && (
          <Badge variant="light" radius="sm" color="gray">
            Cross-filters on {config.selection_column || dcProps?.sampleColumn || 'sample'}
          </Badge>
        )}
        {ucsc > 0 && (
          <Badge variant="light" radius="sm" color="gray">
            UCSC: {ucsc}
          </Badge>
        )}
        {config.force_load && (
          <Badge variant="light" radius="sm" color="orange">
            Force load
          </Badge>
        )}
        {config.fetch_size_limit_mb != null && (
          <Badge variant="light" radius="sm" color="gray">
            Fetch limit: {config.fetch_size_limit_mb} MB
          </Badge>
        )}
        {config.locus_from?.data_collection_tag && (
          <Badge variant="light" radius="sm" color="gray">
            Follows {config.locus_from.data_collection_tag}
          </Badge>
        )}
      </Group>

      {isLegacy ? (
        <Text size="sm" c="dimmed">
          Legacy JBrowse2 collection: tracks come from its JBrowse session, there is no
          manifest to preview.
        </Text>
      ) : (
        data && (
          <>
            <Text size="xs" c="dimmed">
              {countLine}
            </Text>
            {data.rows.length > 0 ? (
              <ScrollArea.Autosize mah={320} type="auto">
                <Table striped highlightOnHover withTableBorder fz="xs">
                  <Table.Thead>
                    <Table.Tr>
                      {shownColumns.map((c) => (
                        <Table.Th key={c}>{c}</Table.Th>
                      ))}
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {data.rows.slice(0, SHOWN_ROWS).map((row, i) => (
                      <Table.Tr key={i}>
                        {shownColumns.map((c) => (
                          <Table.Td key={c} maw={220}>
                            <Text size="xs" truncate>
                              {row?.[c] == null ? '—' : String(row[c])}
                            </Text>
                          </Table.Td>
                        ))}
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea.Autosize>
            ) : (
              <Text size="sm" c="dimmed">
                No track matches the current filters.
              </Text>
            )}
          </>
        )
      )}
      <Text size="xs" c="dimmed">
        The genome view is built from the saved component — save to see this
        configuration in the browser.
      </Text>
    </Stack>
  );

  return (
    <Stack gap="xs">
      {savedJBrowse && dashboardId && (
        <SegmentedControl
          size="xs"
          data={[
            { value: 'summary', label: 'Draft summary' },
            { value: 'saved', label: 'Saved view' },
          ]}
          value={view}
          onChange={(v) => setView(v as 'summary' | 'saved')}
        />
      )}
      {view === 'saved' && savedJBrowse && dashboardId ? (
        <PreviewPanel minHeight={420}>
          <Stack gap="xs">
            <Text size="xs" c="dimmed">
              Last saved version — changes in the form apply after saving.
            </Text>
            <Box style={{ height: 420, position: 'relative' }}>
              <ComponentRenderer
                dashboardId={dashboardId}
                metadata={savedJBrowse}
                filters={previewFilters}
                showDragHandle={false}
              />
            </Box>
          </Stack>
        </PreviewPanel>
      ) : (
        <PreviewPanel minHeight={320} loading={loading} error={error}>
          {summary}
        </PreviewPanel>
      )}
    </Stack>
  );
};

export default JBrowsePreview;
