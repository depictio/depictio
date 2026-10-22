/**
 * Preview for the genome browser builder.
 *
 * The browser itself is configured server-side from the *saved* component
 * (POST /dashboards/render_jbrowse/{dashboard}/{component}), so an unsaved
 * draft can't be drawn. The draft summary answers what the browser will open
 * and how it behaves: the reference and start position, the tracks it opens
 * by source (always-shown, manifest, UCSC, gene annotation) with their names,
 * then the interaction and loading settings. It mirrors the server's rule
 * (`build_jbrowse_payload`): always-shown tracks first, then the manifest rows
 * the dashboard filters let through (the first `initial_tracks` when none
 * applies), `max_tracks` in all. When editing a saved component, the live view
 * of its last saved version sits next to it.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Divider,
  Group,
  SegmentedControl,
  Stack,
  Text,
  ThemeIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { ComponentRenderer, fetchDataCollectionPreview } from 'depictio-react-core';
import type { PreviewResult } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import { useBuilderPreviewFilters } from '../useBuilderPreviewFilters';
import PreviewPanel from '../shared/PreviewPanel';
import type { JBrowseConfig } from './JBrowseBuilder';
import type { GenomicTracksProps } from './jbrowseApi';

// Manifests are small (a track per file); this reads all of a typical one, so
// the names and the format split cover every matching track.
const PREVIEW_ROWS = 500;
const SHOWN_NAMES = 6;

interface Props {
  /** The bound DC's genomic_tracks properties; null while loading or for a
   *  legacy jbrowse2 collection. */
  dcProps: GenomicTracksProps | null;
}

const plural = (n: number, word: string) =>
  `${n.toLocaleString('en-US')} ${word}${n === 1 ? '' : 's'}`;

interface NamedTrack {
  name: string;
  /** Track format (bigWig, bed...), shown dimmed beside the name. */
  note?: string | null;
}

/** The first tracks as a plain list, then "+N more". */
const Names: React.FC<{ tracks: NamedTrack[] }> = ({ tracks }) =>
  tracks.length === 0 ? null : (
    <Stack gap={2} pl={2}>
      {tracks.slice(0, SHOWN_NAMES).map((t, i) => (
        <Group key={`${t.name}-${i}`} gap="xs" wrap="nowrap" justify="space-between">
          <Text size="xs" truncate style={{ minWidth: 0 }}>
            {t.name}
          </Text>
          {t.note && (
            <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
              {t.note}
            </Text>
          )}
        </Group>
      ))}
      {tracks.length > SHOWN_NAMES && (
        <Text size="xs" c="dimmed">
          +{tracks.length - SHOWN_NAMES} more
        </Text>
      )}
    </Stack>
  );

/** One source of tracks: icon, name, count, what decides it, and its tracks. */
const Source: React.FC<{
  icon: string;
  title: string;
  count: string;
  detail: React.ReactNode;
  tracks?: NamedTrack[];
  muted?: boolean;
}> = ({ icon, title, count, detail, tracks = [], muted }) => (
  <Group gap="sm" align="flex-start" wrap="nowrap" opacity={muted ? 0.6 : 1}>
    <ThemeIcon variant="light" size="md" radius="sm" color={muted ? 'gray' : undefined}>
      <Icon icon={icon} width={16} />
    </ThemeIcon>
    <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
      <Group justify="space-between" wrap="nowrap" gap="xs">
        <Text size="sm" fw={600}>
          {title}
        </Text>
        <Text size="sm" fw={600} style={{ whiteSpace: 'nowrap' }}>
          {count}
        </Text>
      </Group>
      <Text size="xs" c="dimmed">
        {detail}
      </Text>
      <Names tracks={tracks} />
    </Stack>
  </Group>
);

/** A setting and its value, in the two-column settings list. */
const Setting: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <>
    <Text size="xs" c="dimmed">
      {label}
    </Text>
    <Text size="xs">{children}</Text>
  </>
);

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

  const maxTracks = config.max_tracks ?? 20;
  const initialTracks = config.initial_tracks ?? 5;
  const filtered = Boolean(data?.filter_applied);
  const matching = data?.total_rows ?? 0;

  // The manifest side of the server's rule, on the rows read here.
  const manifest = useMemo(() => {
    const rows = data?.rows ?? [];
    const idCol = dcProps?.trackIdColumn;
    const nameCol = dcProps?.nameColumn || idCol;
    const fmtCol = dcProps?.formatColumn;
    const cell = (row: Record<string, unknown>, col?: string | null) =>
      col && row[col] != null ? String(row[col]) : null;
    const isFasta = (row: Record<string, unknown>) => cell(row, fmtCol)?.toLowerCase() === 'fasta';
    const byId = new Map<string, Record<string, unknown>>();
    for (const row of rows) {
      const id = cell(row, idCol);
      if (id) byId.set(id, row);
    }
    const pinnedIds = config.default_tracks ?? [];
    const pinnedNames: NamedTrack[] = pinnedIds.map((id) => {
      const row = byId.get(id);
      return { name: (row && cell(row, nameCol)) || id, note: row ? cell(row, fmtCol) : null };
    });
    const candidates = (filtered ? rows : rows.slice(0, initialTracks)).filter(
      (row) => !isFasta(row) && !pinnedIds.includes(cell(row, idCol) ?? ''),
    );
    const room = Math.max(0, maxTracks - pinnedIds.length);
    const opening = candidates.slice(0, room);
    const formats = new Map<string, number>();
    for (const row of filtered ? rows : rows.filter((r) => !isFasta(r))) {
      const f = cell(row, fmtCol);
      if (f) formats.set(f, (formats.get(f) ?? 0) + 1);
    }
    return {
      pinnedNames,
      openingNames: opening.map(
        (row): NamedTrack => ({ name: cell(row, nameCol) ?? '—', note: cell(row, fmtCol) }),
      ),
      clipped: candidates.length > room,
      formats: [...formats].sort((a, b) => b[1] - a[1]),
      complete: rows.length >= matching,
    };
  }, [data, dcProps, config.default_tracks, filtered, initialTracks, maxTracks, matching]);

  if (!dcId) {
    return (
      <PreviewPanel
        minHeight={320}
        empty
        emptyMessage="Pick a genomic tracks data collection to preview its tracks."
      />
    );
  }

  const ownAssembly = config.assembly || null;
  const assembly = ownAssembly || dcProps?.assembly || null;
  const ucsc = config.ucsc_tracks ?? [];
  const annotation = config.show_annotation !== false;
  const locusDc = config.locus_from?.data_collection_tag;
  const selectionColumn = config.selection_column || dcProps?.sampleColumn || 'sample';
  const opened =
    manifest.pinnedNames.length + manifest.openingNames.length + ucsc.length;

  const manifestDetail = !data
    ? 'Reading the manifest…'
    : filtered
      ? `${plural(matching, 'manifest row')} ${matching === 1 ? 'matches' : 'match'} the dashboard filters${
          manifest.clipped ? `; the first ${manifest.openingNames.length} open (limit ${maxTracks})` : ''
        }.`
      : `No dashboard filter narrows the tracks yet: the first ${plural(
          initialTracks,
          'track',
        )} of ${matching.toLocaleString('en-US')} open. Filtering the dashboard opens the matching ones (up to ${maxTracks}).`;
  const formatLine = manifest.formats.length
    ? `${manifest.complete ? '' : `In the first ${PREVIEW_ROWS} rows: `}${manifest.formats
        .map(([f, n]) => `${f} ${n}`)
        .join(' · ')}`
    : null;

  const clickBehaviour = !config.selection_enabled
    ? 'Does not filter the dashboard'
    : config.selection_mode === 'visible_tracks'
      ? `The open tracks filter the dashboard by ${selectionColumn}`
      : `Clicking a feature filters the dashboard by its track's ${selectionColumn}`;

  const summary = (
    <Stack gap="md">
      <Stack gap={2}>
        <Group gap="xs" wrap="nowrap">
          <Icon icon="mdi:dna" width={20} />
          <Text fw={700} lineClamp={1}>
            {config.title || 'Genome browser'}
          </Text>
        </Group>
        <Text size="xs" c="dimmed">
          {assembly
            ? `${assembly}${ownAssembly ? '' : " (the collection's assembly)"}`
            : 'Assembly of the collection'}
          {' · '}
          {locusDc
            ? `opens on the first ${locusDc} row the filters keep`
            : config.location
              ? `opens on ${config.location}`
              : "opens on the assembly's default region"}
        </Text>
      </Stack>

      {isLegacy ? (
        <Text size="sm" c="dimmed">
          Legacy JBrowse2 collection: tracks come from its JBrowse session, there is no
          manifest to preview.
        </Text>
      ) : (
        <Stack gap="sm">
          <Group justify="space-between">
            <Text size="xs" fw={700} tt="uppercase" c="dimmed">
              Tracks at opening
            </Text>
            {data && (
              <Text size="xs" c="dimmed">
                {plural(opened, 'track')}
                {annotation ? ' + gene annotation' : ''}
              </Text>
            )}
          </Group>
          {manifest.pinnedNames.length > 0 && (
            <Source
              icon="mdi:pin-outline"
              title="Always shown"
              count={String(manifest.pinnedNames.length)}
              detail="Open whatever the filters, counted in the track limit."
              tracks={manifest.pinnedNames}
            />
          )}
          <Source
            icon="mdi:file-table-outline"
            title="Manifest tracks"
            count={data ? `${manifest.openingNames.length} of ${matching.toLocaleString('en-US')}` : '…'}
            detail={
              <>
                {manifestDetail}
                {formatLine && (
                  <>
                    <br />
                    {formatLine}
                  </>
                )}
              </>
            }
            tracks={manifest.openingNames}
            muted={!!data && manifest.openingNames.length === 0}
          />
          {ucsc.length > 0 && (
            <Source
              icon="mdi:web"
              title="UCSC tracks"
              count={String(ucsc.length)}
              detail="Read from UCSC's servers, not versioned with the dashboard."
              tracks={ucsc.map((name) => ({ name }))}
            />
          )}
          <Source
            icon="mdi:format-list-bulleted-type"
            title="Gene annotation"
            count={annotation ? 'on' : 'off'}
            detail={
              annotation
                ? "The assembly preset's gene track, when it ships one."
                : 'Turned off in Display.'
            }
            muted={!annotation}
          />
        </Stack>
      )}

      <Divider />
      <Box style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 12px' }}>
        <Setting label="Click">{clickBehaviour}</Setting>
        <Setting label="Loading">
          {config.force_load ? 'Force load on by default' : 'JBrowse size limits'}
          {config.fetch_size_limit_mb != null
            ? `, ${config.fetch_size_limit_mb} MB per track`
            : ''}
        </Setting>
        <Setting label="Track selector">
          {config.track_mode === 'all'
            ? 'Every manifest track can be opened'
            : 'Only the tracks matching the filters can be opened'}
        </Setting>
        {config.preset && <Setting label="Preset">{config.preset}</Setting>}
      </Box>

      <Text size="xs" c="dimmed">
        The genome view is built from the saved component: save to see this configuration in
        the browser.
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
