import React, { Suspense, lazy, useRef, useState } from 'react';
import {
  ActionIcon,
  CloseButton,
  Group,
  Popover,
  SegmentedControl,
  Stack,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { TILE_ACTION_STYLE } from '../chrome/actionStyles';
import { useFullscreenPortalTarget } from '../chrome/useFullscreenPortalTarget';
import DataGridModal from '../data/DataGridModal';
import type { RegionGridProps } from './RegionPicker';
import TableActions, { useIsFullscreen } from './TableActions';
import { columnsCsv, downloadText, exportFileName } from './tableExport';

// Both grids pull AG Grid in: loaded on the first open, as the other tiles'.
const DataGridBody = lazy(() => import('../data/DataGridBody'));
const RegionGrid = lazy(() => import('./RegionPicker').then((m) => ({ default: m.RegionGrid })));

type Tab = 'regions' | 'tracks';

interface Props {
  /** The tile's tracks, column-oriented (the manifest rows). */
  trackRows: Record<string, unknown[]>;
  trackColumns?: string[];
  /** The regions of `locus_from`, as the navigator's picker reads them; none
   *  without a `locus_from`, and the table is then the tracks alone. */
  regions?: RegionGridProps | null;
  /** The regions tab's label: "Peaks", "Consensus", "Regions". */
  regionsLabel?: string;
}

/**
 * The genome browser's data table: the regions it navigates (the rows of
 * `locus_from`, the same grid as the navigator's picker, a click moves the
 * view there) and the tracks it can draw. One entry point for both, in the
 * popover or enlarged in a dialog.
 */
const JBrowseDataPopover: React.FC<Props> = ({
  trackRows,
  trackColumns,
  regions,
  regionsLabel = 'Regions',
}) => {
  const [opened, setOpened] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<Tab>('regions');
  const portalTarget = useFullscreenPortalTarget();
  const shown: Tab = regions ? tab : 'tracks';
  // The tracks table's own actions (the regions tab carries its own, next to
  // its search: its rows are paged from the server). Reset remounts the grid,
  // which drops its filters and sorting.
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const fullscreen = useIsFullscreen(bodyRef);
  const [gridKey, setGridKey] = useState(0);

  const close = () => {
    setOpened(false);
    setExpanded(false);
  };

  const header = (
    <Group gap={6} justify="space-between" wrap="nowrap">
      {regions ? (
        <SegmentedControl
          size="xs"
          value={shown}
          onChange={(v) => setTab(v === 'tracks' ? 'tracks' : 'regions')}
          data={[
            { value: 'regions', label: regionsLabel },
            { value: 'tracks', label: 'Tracks' },
          ]}
        />
      ) : (
        <span />
      )}
      <Group gap={6} wrap="nowrap">
        {shown === 'tracks' ? (
          <TableActions
            fullscreenRef={bodyRef}
            onReset={() => setGridKey((k) => k + 1)}
            onDownload={() => downloadText(exportFileName('genome_browser_tracks'), columnsCsv(trackRows, trackColumns))}
            downloadDisabled={Object.keys(trackRows).length === 0}
          />
        ) : null}
        <Tooltip label={expanded ? 'Shrink the table' : 'Enlarge the table'} withinPortal={false}>
          <ActionIcon
            size="sm"
            variant="subtle"
            color="gray"
            aria-label={expanded ? 'Shrink the data table' : 'Enlarge the data table'}
            onClick={() => setExpanded((v) => !v)}
          >
            <Icon icon={expanded ? 'mdi:fullscreen-exit' : 'mdi:fullscreen'} width={16} height={16} />
          </ActionIcon>
        </Tooltip>
        <CloseButton size="sm" aria-label="Close the data table" onClick={close} />
      </Group>
    </Group>
  );

  const body = (
    <Stack
      gap="xs"
      ref={bodyRef}
      // Native fullscreen shows this element alone: it needs a page of its own.
      style={fullscreen ? { height: '100%', padding: 12, background: 'var(--mantine-color-body)' } : undefined}
    >
      {header}
      <Suspense fallback={null}>
        {shown === 'regions' && regions ? (
          <RegionGrid
            {...regions}
            height={expanded ? '70vh' : undefined}
            onSelect={(call) => {
              regions.onSelect(call);
              close();
            }}
          />
        ) : (
          <DataGridBody
            key={gridKey}
            dataRows={trackRows}
            dataColumns={trackColumns}
            expanded={expanded}
            // Fullscreen: what the header row and the padding leave.
            height={fullscreen ? 'calc(100vh - 96px)' : undefined}
          />
        )}
      </Suspense>
    </Stack>
  );

  return (
    <>
      <Popover
        position="bottom-end"
        shadow="md"
        withArrow
        // AG Grid portals its column menus to the page: a click on one reads
        // as outside. Closed by the button, the icon or Escape.
        closeOnClickOutside={false}
        closeOnEscape
        opened={opened && !expanded}
        onChange={setOpened}
        portalProps={{ target: portalTarget }}
      >
        <Popover.Target>
          <ActionIcon
            variant={opened ? 'filled' : 'subtle'}
            color={TILE_ACTION_STYLE.data.color}
            size="sm"
            aria-label="Show underlying data"
            title={TILE_ACTION_STYLE.data.label}
            data-tile-action="data"
            onClick={() => setOpened((v) => !v)}
          >
            <Icon icon={TILE_ACTION_STYLE.data.icon} width={16} height={16} />
          </ActionIcon>
        </Popover.Target>
        <Popover.Dropdown p="sm" style={{ width: 'min(820px, 88vw)', maxHeight: '85vh', overflow: 'auto' }}>
          {expanded ? null : body}
        </Popover.Dropdown>
      </Popover>
      {/* Mounted only while enlarged: a closed modal still leaves a portal
          behind, which a fullscreen tile lays out as a child. */}
      {opened && expanded ? (
        <DataGridModal opened onClose={close}>
          {body}
        </DataGridModal>
      ) : null}
    </>
  );
};

export default JBrowseDataPopover;
