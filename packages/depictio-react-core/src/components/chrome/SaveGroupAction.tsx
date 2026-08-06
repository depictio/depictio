import React, { useContext, useState } from 'react';
import {
  ActionIcon,
  Button,
  ColorSwatch,
  Group,
  Popover,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { InteractiveFilter } from '../../api';
import { TAB10_PALETTE } from '../../colors';
import {
  MAX_GROUP_VALUES,
  defaultGroupName,
  nextGroupColor,
  selectableSelectionFilters,
  type SelectionGroup,
} from '../../selectionGroups';

/**
 * Everything the per-component "save selection as group" action needs from the
 * app root. Provided by the viewer/editor roots around their dashboard trees;
 * the null default removes the action entirely, so grids that don't do
 * grouping (project previews, catalog) are unchanged.
 */
export interface SaveGroupApi {
  groups: SelectionGroup[];
  /** The root's `createGroupFromFilter` — returns null when the selection
   *  can't become a group (over the value cap, no resolvable column). */
  createGroup: (filter: InteractiveFilter, name: string, color: string) => SelectionGroup | null;
  /** The root's filter-change handler; called with the emptied selection
   *  filter after a save so the `(index, source)` slot frees up. */
  clearSelection: (filter: InteractiveFilter) => void;
}

export const SaveGroupContext = React.createContext<SaveGroupApi | null>(null);

/** The component's live chart/table/map selection, if it has one. */
export function selectionCandidateFor(
  filters: InteractiveFilter[],
  index: string,
): InteractiveFilter | undefined {
  return selectableSelectionFilters(filters).find((f) => f.index === index);
}

/**
 * Chrome action shown on a component with a live selection: save it as a
 * group without a trip to the header "Analysis" menu. The action rides the
 * chrome's persistent-when-filtering row, so it is on screen exactly while
 * there is a selection to save.
 */
const SaveGroupAction: React.FC<{ filter: InteractiveFilter }> = ({ filter }) => {
  const api = useContext(SaveGroupContext);
  const [opened, setOpened] = useState(false);
  const [name, setName] = useState('');
  const [color, setColor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!api) return null;

  const values = Array.isArray(filter.value) ? filter.value.length : 0;
  const placeholder = defaultGroupName(api.groups);
  const fallbackColor = nextGroupColor(api.groups);

  const save = () => {
    const created = api.createGroup(filter, name.trim() || placeholder, color ?? fallbackColor);
    if (!created) {
      setError(
        `Couldn't save this selection as a group — it may exceed the ${MAX_GROUP_VALUES.toLocaleString()}-value cap.`,
      );
      return;
    }
    api.clearSelection({ ...filter, value: [] });
    setOpened(false);
    setName('');
    setColor(null);
    setError(null);
  };

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      width={240}
      position="bottom-end"
      withArrow
      shadow="md"
    >
      <Popover.Target>
        <Tooltip label="Save selection as group" withArrow openDelay={300}>
          <ActionIcon
            variant="filled"
            color="teal"
            size="sm"
            aria-label="Save selection as group"
            onClick={(e) => {
              e.stopPropagation();
              setError(null);
              setOpened((o) => !o);
            }}
          >
            <Icon icon="mdi:select-group" width={16} height={16} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown onClick={(e) => e.stopPropagation()}>
        <Text size="xs" c="dimmed" mb={4}>
          {values.toLocaleString()} selected value{values === 1 ? '' : 's'}
        </Text>
        <TextInput
          size="xs"
          placeholder={placeholder}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save();
          }}
          autoFocus
        />
        <Group gap={4} mt={6} wrap="wrap">
          {TAB10_PALETTE.map((c) => (
            <ColorSwatch
              key={c}
              color={c}
              size={16}
              style={{
                cursor: 'pointer',
                outline:
                  (color ?? fallbackColor) === c ? '2px solid var(--mantine-color-blue-5)' : 'none',
                outlineOffset: 1,
              }}
              onClick={() => setColor(c)}
            />
          ))}
        </Group>
        {error && (
          <Text size="xs" c="red" mt={6}>
            {error}
          </Text>
        )}
        <Button size="compact-xs" mt={8} fullWidth onClick={save}>
          Save group
        </Button>
      </Popover.Dropdown>
    </Popover>
  );
};

export default SaveGroupAction;
