import React, { useContext, useState } from 'react';
import { ActionIcon, Button, Popover, Text, TextInput, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { InteractiveFilter } from '../../api';
import {
  GROUPING_COLOR,
  GROUP_SAVE_ERROR,
  defaultGroupName,
  nextGroupColor,
  selectableSelectionFilters,
  type SelectionGroup,
} from '../../selectionGroups';
import GroupColorSwatches from '../GroupColorSwatches';

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
  /** True while the user is working in analysis mode — the header Analysis
   *  panel is open, or a grouping mode is repainting the dashboard. Components
   *  a selection can be saved from advertise themselves only then, so ordinary
   *  viewing keeps its clean chrome. */
  analysisEngaged: boolean;
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
      setError(GROUP_SAVE_ERROR);
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
            // Same glyph, same color and the same light→filled progression as
            // the header "Analysis" button (GroupingHeaderControl): filled is
            // the actionable state.
            variant="filled"
            color={GROUPING_COLOR}
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
        <GroupColorSwatches value={color ?? fallbackColor} onSelect={setColor} mt={6} />
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

/**
 * The passive half of the same slot: a component that *could* feed a group but
 * has no selection yet.
 *
 * Without it, a selectable component is indistinguishable from a passive one
 * until the user happens to lasso it — the capability is real but invisible.
 * Shown only while analysis is engaged (see `SaveGroupApi.analysisEngaged`), so
 * it points at where to act exactly when that is the task at hand, and stays
 * out of the way the rest of the time. `SaveGroupAction` replaces it in the
 * same slot as soon as there is a selection to save.
 */
export const SelectionHintAction: React.FC = () => (
  <Tooltip
    label="Can be grouped — select here to create an analysis group"
    withArrow
    openDelay={200}
    position="bottom"
  >
    <ActionIcon
      size="sm"
      // The un-actioned half of the same progression: `light` here, `filled`
      // once there is a selection to save. Same glyph and theme color as the
      // header Analysis button, so a user who opened that panel recognises
      // these as the components it is talking about.
      variant="subtle"
      color={GROUPING_COLOR}
      className="dgl-no-drag"
      // Passive marker, not a control: the selection is made on the component
      // itself (lasso, row click, thumbnail click), so there is nothing to
      // trigger from here. Out of the tab order for that reason, but kept in
      // the accessibility tree and labelled — it is the only cue a screen
      // reader gets, since the outline is purely visual.
      tabIndex={-1}
      aria-label="Selectable: create an analysis group from a selection here"
      style={{ cursor: 'default' }}
    >
      <Icon icon="mdi:select-group" width={16} height={16} />
    </ActionIcon>
  </Tooltip>
);

export default SaveGroupAction;
