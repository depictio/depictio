import React, { useState } from 'react';
import { Badge, Button, Group, Paper, Select, Stack, Text, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { InteractiveFilter, StoredMetadata } from '../../api';
import { filterDisplayLabel } from '../../activeFilters';
import {
  GROUP_SAVE_ERROR,
  defaultGroupName,
  nextGroupColor,
  useGroupingColor,
  useGroupingColorVar,
  type SelectionGroup,
} from '../../selectionGroups';
import { Z_LAYERS } from '../../zLayers';
import GroupColorSwatches from '../GroupColorSwatches';
import { selectionKey, selectionPreview } from './groupingGuide';
import ValueListPreview from './ValueListPreview';

/** Matches the panel's other input labels (see SelectionGroupsPanel). */
const CONTROL_LABEL_STYLES = { label: { fontSize: 13 } } as const;

/**
 * The live selection, shown before it is saved.
 *
 * Saving used to be a button that opened a popover: the user clicked "Save
 * selection as group" without ever being told what "the selection" was — how
 * many values, on which column, from which tile — and the group's color only
 * appeared after the fact. This is that popover unfolded into the panel, with
 * the read-out in front of the inputs, so the whole answer to "what am I about
 * to save?" is on screen and saving is still one click.
 *
 * It mirrors `chrome/SaveGroupAction` (the in-place entry point on a tile's
 * own chrome) deliberately: same defaults via `defaultGroupName` /
 * `nextGroupColor` as a *placeholder* rather than pre-filled text, same
 * swatch row, same `GROUP_SAVE_ERROR`, same "save then free the selection
 * slot" sequence. Two entry points, one story.
 */
const PendingGroupForm: React.FC<{
  /** Live selections a group can be made from (the panel's `candidates`);
   *  never empty — the panel renders this only when there is one. */
  candidates: InteractiveFilter[];
  /** Stored metadata, to name the source tile in the read-out. */
  components: StoredMetadata[];
  groups: SelectionGroup[];
  /** The app's `createGroupFromFilter` — null when the selection can't become
   *  a group (over the value cap, no resolvable column). */
  onCreateGroup: (filter: InteractiveFilter, name: string, color: string) => SelectionGroup | null;
  /** Called with the emptied source filter after a save, freeing the
   *  `(index, source)` slot for the next selection. */
  onClearSelection: (filter: InteractiveFilter) => void;
}> = ({ candidates, components, groups, onCreateGroup, onClearSelection }) => {
  const [sourceKey, setSourceKey] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [color, setColor] = useState<string | null>(null);
  // The selection a refusal belongs to, rather than a bare flag: the user
  // answers "too many values" by lassoing a smaller cohort, and the warning
  // has to clear itself the moment they do.
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const groupingColor = useGroupingColor();
  const groupingColorVar = useGroupingColorVar();

  // Falls back to the first candidate whenever the remembered one is gone —
  // selections come and go under the panel as the user works.
  const selected = candidates.find((f) => selectionKey(f) === sourceKey) ?? candidates[0];
  const preview = selected ? selectionPreview(selected, components) : null;
  const placeholder = defaultGroupName(groups);
  const effectiveColor = color ?? nextGroupColor(groups);

  if (!selected || !preview) return null;

  const key = selectionKey(selected);

  const save = () => {
    const created = onCreateGroup(selected, name.trim() || placeholder, effectiveColor);
    if (!created) {
      // Keep the selection so the user can retry or shrink it.
      setErrorKey(key);
      return;
    }
    setErrorKey(null);
    setName('');
    setColor(null);
    onClearSelection({ ...selected, value: [] });
  };

  return (
    <Paper
      withBorder
      radius="sm"
      p="sm"
      mt={8}
      // Accent rule in the grouping color, the same hue as the header button
      // and the tile markers — this card is the third station of that one
      // journey, and it is the only card in the panel that is *pending*.
      style={{ borderLeft: `3px solid ${groupingColorVar}` }}
      data-testid="pending-group-form"
    >
      <Stack gap="xs">
        <Group gap={6} justify="space-between" wrap="nowrap">
          <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
            <Icon icon="mdi:selection-drag" width={16} height={16} />
            <Text size="sm" fw={600}>
              Selection ready
            </Text>
          </Group>
          <Badge size="sm" variant="light" color={groupingColor} style={{ flexShrink: 0 }}>
            {preview.values.distinct.toLocaleString()}
            {preview.values.distinct === 1 ? ' value' : ' values'}
          </Badge>
        </Group>

        <Text size="sm" c="dimmed">
          on{' '}
          <Text span size="sm" fw={600} c="dimmed">
            {preview.columnName}
          </Text>
          {preview.sourceLabel && (
            <>
              {' from '}
              <Text span size="sm" fw={600} c="dimmed">
                {preview.sourceLabel}
              </Text>
            </>
          )}
        </Text>

        {/* The actual ids, listed: the difference between "42 values" and
            "42 values, and they are the ones I meant". */}
        <ValueListPreview values={preview.values} rows={5} />

        {candidates.length > 1 && (
          <Select
            size="sm"
            label="From"
            styles={CONTROL_LABEL_STYLES}
            data={candidates.map((f) => ({
              value: selectionKey(f),
              label: `${filterDisplayLabel(f, components)} (${
                Array.isArray(f.value) ? f.value.length : 0
              })`,
            }))}
            value={key}
            onChange={setSourceKey}
            allowDeselect={false}
            // Portaled, unlike the panel's old popover-hosted selects: the
            // panel now sits in a drawer whose body scrolls, and an in-DOM
            // dropdown gets clipped by that overflow. The explicit layer keeps
            // it above the drawer it is opened from.
            comboboxProps={{ withinPortal: true, zIndex: Z_LAYERS.tooltip }}
          />
        )}

        <TextInput
          size="sm"
          label="Group name"
          styles={CONTROL_LABEL_STYLES}
          placeholder={placeholder}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save();
          }}
        />

        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Color
          </Text>
          <GroupColorSwatches value={effectiveColor} onSelect={setColor} />
        </Stack>

        {errorKey === key && (
          <Text size="sm" c="red">
            {GROUP_SAVE_ERROR}
          </Text>
        )}

        <Button
          size="sm"
          fullWidth
          color={groupingColor}
          leftSection={<Icon icon="mdi:select-group" width={14} height={14} />}
          onClick={save}
          data-testid="save-selection-as-group"
        >
          {/* Same words as the tile-chrome action's own button
              (chrome/SaveGroupAction) — one action, one name. */}
          Save group
        </Button>
      </Stack>
    </Paper>
  );
};

export default PendingGroupForm;
