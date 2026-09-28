import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Checkbox,
  Group,
  Popover,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { JBrowseTrackRow } from '../../api';
import { SHOW_ALL_CAP, countOpen, groupTrackRows, showAllPlan } from './trackMenu';

interface TrackMenuProps {
  rows: JBrowseTrackRow[];
  /** Track ids currently open in the view (kept live by the renderer). */
  openIds: string[];
  /** The native fullscreen element when the tile is fullscreen: the dropdown
   *  must be portalled into it or it would not be painted. */
  portalTarget: HTMLElement | null;
  disabled?: boolean;
  onToggle: (trackId: string, show: boolean) => void;
  onShowAll: (trackIds: string[]) => void;
  onHideAll: () => void;
  onBackToFilters: () => void;
}

/**
 * Chrome-toolbar track picker: one checkbox per track of the render payload,
 * grouped by manifest category, then UCSC and reference tracks.
 *
 * The checkboxes reflect the live view, and the choices made here drive it
 * directly; they hold until the next payload (a dashboard filter change), when
 * the renderer re-applies the filtered track set. "Back to filters" does that
 * right away.
 */
const TrackMenu: React.FC<TrackMenuProps> = ({
  rows,
  openIds,
  portalTarget,
  disabled,
  onToggle,
  onShowAll,
  onHideAll,
  onBackToFilters,
}) => {
  const [opened, setOpened] = useState(false);
  const [query, setQuery] = useState('');

  // Entering / leaving fullscreen moves the portal target: close rather than
  // leave a dropdown anchored to where the icon used to be.
  useEffect(() => setOpened(false), [portalTarget]);

  const open = useMemo(() => new Set(openIds), [openIds]);
  const groups = useMemo(
    () => (opened ? groupTrackRows(rows, query) : []),
    [opened, rows, query],
  );
  const plan = useMemo(() => showAllPlan(groups, SHOW_ALL_CAP), [groups]);
  const openCount = useMemo(() => countOpen(rows, openIds), [rows, openIds]);
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();

  return (
    <Popover
      key={portalTarget ? 'fullscreen' : 'page'}
      opened={opened}
      onChange={setOpened}
      width={340}
      position="bottom-end"
      withArrow
      shadow="md"
      trapFocus={false}
      portalProps={portalTarget ? { target: portalTarget } : undefined}
    >
      <Popover.Target>
        <Tooltip label="Tracks" withinPortal={false}>
          <ActionIcon
            variant={opened ? 'light' : 'subtle'}
            size="sm"
            aria-label="Tracks"
            aria-expanded={opened}
            data-testid="jbrowse-toggle-tracks"
            disabled={disabled}
            onClick={(e) => {
              e.stopPropagation();
              setOpened((o) => !o);
            }}
          >
            <Icon icon="mdi:format-list-checks" width={16} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown
        data-testid="jbrowse-track-menu"
        onClick={stop}
        onMouseDown={stop}
        onPointerDown={stop}
        onTouchStart={stop}
        p="xs"
      >
        <Stack gap={6}>
          <Group justify="space-between" wrap="nowrap">
            <Text size="sm" fw={600}>
              Tracks
            </Text>
            <Text size="xs" c="dimmed" data-testid="jbrowse-track-menu-count">
              {openCount} / {rows.length} open
            </Text>
          </Group>
          <TextInput
            size="xs"
            placeholder="Search tracks"
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
            leftSection={<Icon icon="mdi:magnify" width={14} />}
            data-testid="jbrowse-track-search"
            rightSection={
              query ? (
                <ActionIcon
                  size="xs"
                  variant="subtle"
                  color="gray"
                  aria-label="Clear search"
                  onClick={() => setQuery('')}
                >
                  <Icon icon="mdi:close" width={12} />
                </ActionIcon>
              ) : null
            }
          />
          <Group gap={4} wrap="wrap">
            <Button
              size="compact-xs"
              variant="light"
              disabled={!plan.total}
              onClick={() => onShowAll(plan.ids)}
              data-testid="jbrowse-tracks-show-all"
            >
              Show all ({plan.total})
            </Button>
            <Button
              size="compact-xs"
              variant="default"
              onClick={onHideAll}
              data-testid="jbrowse-tracks-hide-all"
            >
              Hide all
            </Button>
            <Button
              size="compact-xs"
              variant="subtle"
              leftSection={<Icon icon="mdi:filter-outline" width={12} />}
              onClick={onBackToFilters}
              data-testid="jbrowse-tracks-reset"
            >
              Back to filters
            </Button>
          </Group>
          {plan.capped && (
            <Text size="xs" c="orange">
              {plan.total} tracks match: "Show all" opens the first {SHOW_ALL_CAP}. Narrow the
              search to pick the others.
            </Text>
          )}
          <ScrollArea.Autosize mah={360} type="auto" offsetScrollbars>
            {groups.length === 0 ? (
              <Text size="xs" c="dimmed" py="xs">
                {rows.length ? 'No track matches the search.' : 'No tracks.'}
              </Text>
            ) : (
              <Stack gap={8}>
                {groups.map((g) => (
                  <Stack key={g.key} gap={4}>
                    <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                      {g.label} ({countOpen(g.rows, openIds)}/{g.rows.length})
                    </Text>
                    {g.rows.map((row) => (
                      <Checkbox
                        key={row.track_id}
                        size="xs"
                        checked={open.has(row.track_id)}
                        onChange={(e) => onToggle(row.track_id, e.currentTarget.checked)}
                        data-track-id={row.track_id}
                        label={
                          <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                            {row.color && (
                              <Box
                                component="span"
                                aria-hidden
                                style={{
                                  width: 10,
                                  height: 10,
                                  flexShrink: 0,
                                  borderRadius: 2,
                                  background: row.color,
                                  border: '1px solid var(--mantine-color-default-border)',
                                }}
                              />
                            )}
                            <Text size="xs" truncate title={row.name}>
                              {row.name}
                            </Text>
                          </Group>
                        }
                        styles={{ body: { alignItems: 'center' }, labelWrapper: { minWidth: 0 } }}
                      />
                    ))}
                  </Stack>
                ))}
              </Stack>
            )}
          </ScrollArea.Autosize>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
};

export default TrackMenu;
