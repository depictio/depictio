/**
 * Record card: which tile's selection drives the card.
 *
 * The card shows the row somebody picked elsewhere, so the one thing an author
 * has to say is where that pick comes from. `linked_component` names the tile;
 * `selection_source` narrows the gesture (lasso on a scatter or row pick on a
 * table) when no single tile is named. Both are plain config fields, not
 * column bindings, so they travel as viz overrides and ride through the save
 * path's viz-control layer untouched.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Paper, SegmentedControl, Select, Stack, Text } from '@mantine/core';
import { fetchDashboard } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import {
  RecordCardSelectionSource,
  SelectionEmitter,
  findEmitter,
  selectionEmitters,
} from './recordCardLink';

/** Sentinel for the explicit "Any selection" option: Mantine Select cannot
 *  carry `null` as an option value. */
const ANY = '__any__';

const SOURCE_OPTIONS: { value: RecordCardSelectionSource; label: string }[] = [
  { value: 'any', label: 'Any' },
  { value: 'scatter_selection', label: 'Scatter lasso' },
  { value: 'table_selection', label: 'Table rows' },
];

export interface RecordCardLinkSettingsProps {
  /** The config the card renders with (saved or catalog blob plus overrides). */
  config: Record<string, unknown> | null;
  /** The column bound to the card's `id` role (`id_col`). */
  idCol: string | null;
  /** Writes config fields; `undefined` drops a key the saved config never had. */
  onChange: (patch: Record<string, unknown>) => void;
}

const RecordCardLinkSettings: React.FC<RecordCardLinkSettingsProps> = ({
  config,
  idCol,
  onChange,
}) => {
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const componentId = useBuilderStore((s) => s.componentId);
  const [metadata, setMetadata] = useState<StoredMetadata[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!dashboardId) return;
    let cancelled = false;
    fetchDashboard(dashboardId)
      .then((dash) => {
        if (!cancelled) setMetadata(dash.stored_metadata ?? []);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId]);

  const emitters = useMemo(
    () => selectionEmitters(metadata ?? [], componentId),
    [metadata, componentId],
  );

  const linkedRaw = typeof config?.linked_component === 'string' ? config.linked_component : null;
  const linked: SelectionEmitter | undefined = findEmitter(emitters, linkedRaw);
  const source = (
    typeof config?.selection_source === 'string' ? config.selection_source : 'any'
  ) as RecordCardSelectionSource;

  const pickLinked = (value: string | null) => {
    if (!value || value === ANY) {
      onChange({ linked_component: undefined });
      return;
    }
    const emitter = emitters.find((e) => e.value === value);
    // Following a named tile only makes sense on the source that tile emits,
    // so the gesture filter follows the pick.
    onChange({
      linked_component: value,
      ...(emitter ? { selection_source: emitter.source } : {}),
    });
  };

  const data = [
    { value: ANY, label: 'Any selection' },
    ...emitters.map((e) => ({ value: e.value, label: `${e.label} (${e.typeLabel})` })),
  ];

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Text fw={600} size="sm">
          Selection
        </Text>
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Linked component
          </Text>
          <Select
            placeholder={metadata == null && !loadError ? 'Loading components…' : 'Any selection'}
            description="The tile whose selection fills the card. Any selection follows whichever tile the reader picks in."
            data={data}
            value={linked ? linked.value : linkedRaw ? linkedRaw : ANY}
            onChange={pickLinked}
            clearable
            searchable
            nothingFoundMessage="No selecting component on this dashboard"
          />
          {loadError ? (
            <Text size="xs" c="red">
              Could not list this dashboard's components: {loadError}
            </Text>
          ) : null}
          {metadata != null && emitters.length === 0 ? (
            <Text size="xs" c="dimmed">
              No other component on this dashboard emits a selection yet. Turn on
              row selection on a table or selection on a scatter to link one.
            </Text>
          ) : null}
          {linkedRaw && metadata != null && !linked ? (
            <Alert color="yellow" variant="light">
              <Text size="xs">
                The linked component "{linkedRaw}" is not on this dashboard or no longer
                emits a selection.
              </Text>
            </Alert>
          ) : null}
          {linked && linked.column && idCol && linked.column !== idCol ? (
            <Text size="xs" c="dimmed">
              {linked.label} selects on "{linked.column}" while the card matches on "{idCol}".
              The card only finds a record when those values line up, directly or through a
              project link.
            </Text>
          ) : null}
        </Stack>
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Selection source
          </Text>
          <SegmentedControl
            data={SOURCE_OPTIONS}
            value={source}
            onChange={(v) => onChange({ selection_source: v })}
            fullWidth
            size="xs"
          />
          <Text size="xs" c="dimmed">
            Which gesture the card follows when several tiles select at once.
          </Text>
        </Stack>
      </Stack>
    </Paper>
  );
};

export default RecordCardLinkSettings;
