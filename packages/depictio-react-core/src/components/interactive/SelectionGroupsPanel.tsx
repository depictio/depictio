import React, { useMemo, useState } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  ColorSwatch,
  Divider,
  Group,
  Popover,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { InteractiveFilter, StoredMetadata } from '../../api';
import { filterDisplayLabel } from '../../activeFilters';
import { TAB10_PALETTE } from '../../colors';
import type { ColorByColumn } from '../../hooks/useColorByColumns';
import {
  COLOR_BY_NONE,
  MAX_GROUP_VALUES,
  defaultGroupName,
  nextGroupColor,
  selectableSelectionFilters,
  type ColorByState,
  type GroupingDisplay,
  type SelectionGroup,
} from '../../selectionGroups';

export interface SelectionGroupsPanelProps {
  /** The dashboard's *user* filters — scanned for active selections to save.
   *  Group-derived filters never appear here; the apps compose those at the
   *  fetch boundary. */
  filters: InteractiveFilter[];
  /** Full stored_metadata, to label the source selection in the picker and
   *  the datasets in the column select. */
  components: StoredMetadata[];
  groups: SelectionGroup[];
  colorBy: ColorByState;
  /** Categorical columns offered in the "Color by column" select, with the
   *  data collections each belongs to (drives the per-dataset option groups
   *  on multi-dataset dashboards). */
  colorByColumns: ColorByColumn[];
  compareInCards: boolean;
  /** Overlay ("color") vs small-multiples ("facet") display of the override. */
  displayMode: GroupingDisplay;
  /** Whether ungrouped rows render as gray "Other" (groups mode). */
  showOther: boolean;
  /** Whether card comparisons include the "All rows" reference entry. */
  showOverall: boolean;
  /** Returns the created group, or null when the selection can't become one
   *  (over the value cap, no resolvable column). Null keeps the selection. */
  onCreateGroup: (filter: InteractiveFilter, name: string, color: string) => SelectionGroup | null;
  /** Called with the source selection filter after a group is saved; the app
   *  routes it to its normal filter-change handler with an empty value so the
   *  `(index, source)` slot frees up for the next selection. */
  onClearSelection: (filter: InteractiveFilter) => void;
  /** Patch a group's name and/or color. */
  onUpdateGroup: (id: string, patch: { name?: string; color?: string }) => void;
  onDeleteGroup: (id: string) => void;
  onToggleGroupFilter: (id: string) => void;
  onColorByChange: (next: ColorByState) => void;
  onCompareInCardsChange: (on: boolean) => void;
  onDisplayModeChange: (mode: GroupingDisplay) => void;
  onShowOtherChange: (on: boolean) => void;
  onShowOverallChange: (on: boolean) => void;
  /** Panel-level reset: every analysis mode back to defaults, groups kept. */
  onResetAnalysis: () => void;
}

const COLOR_BY_NONE_VALUE = '__depictio_none__';

/** Overlay-vs-split control, shared by the two sections so both modes read
 *  the same way. */
const DisplayModeControl: React.FC<{
  value: GroupingDisplay;
  onChange: (mode: GroupingDisplay) => void;
}> = ({ value, onChange }) => (
  <Tooltip
    label="Overlay draws the categories in one panel; Split gives each category its own small panel (figures that can't facet keep the overlay)"
    withArrow
    openDelay={400}
  >
    <SegmentedControl
      size="xs"
      mt={4}
      fullWidth
      data={[
        { value: 'color', label: 'Overlay' },
        { value: 'facet', label: 'Split' },
      ]}
      value={value}
      onChange={(v) => onChange(v === 'facet' ? 'facet' : 'color')}
    />
  </Tooltip>
);

/**
 * "Grouping" panel, in three sections:
 *
 * 1. **Color by column** — the standard categorical coloring of every figure,
 *    picked from the dashboard's columns (grouped per dataset when several
 *    data collections are on screen; "Shared" columns exist in more than one).
 * 2. **Groups** — save the current chart/table/map selection as a named,
 *    colored group; the saved groups are listed with their filter funnels.
 * 3. **Group options** — what to do with the groups: color/split the figures
 *    by them (overrides the column coloring), show or drop the ungrouped
 *    "Other" rows, and compare the groups inside cards.
 *
 * Coloring by groups and by a column are mutually exclusive by construction:
 * one `ColorByState` backs both controls, so turning one on visibly turns the
 * other off. Saving a group clears the selection it came from, which is what
 * lets a user lasso the next cohort while keeping the first: the dashboard's
 * selection protocol only holds one live selection per component.
 */
const SelectionGroupsPanel: React.FC<SelectionGroupsPanelProps> = ({
  filters,
  components,
  groups,
  colorBy,
  colorByColumns,
  compareInCards,
  displayMode,
  showOther,
  showOverall,
  onCreateGroup,
  onClearSelection,
  onUpdateGroup,
  onDeleteGroup,
  onToggleGroupFilter,
  onColorByChange,
  onCompareInCardsChange,
  onDisplayModeChange,
  onShowOtherChange,
  onShowOverallChange,
  onResetAnalysis,
}) => {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [name, setName] = useState('');
  const [color, setColor] = useState<string | null>(null);
  const [sourceIndex, setSourceIndex] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  // Per-row edit popover (name + color); null when no row is being edited.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');

  const candidates = useMemo(() => selectableSelectionFilters(filters), [filters]);

  // Column options, grouped per dataset when the dashboard spans several data
  // collections — a bare column name is ambiguous there ("which dataset's
  // `sample`?"). Columns present in more than one DC go under "Shared
  // columns": the override applies to every figure whose frame carries the
  // column, so pinning them to one dataset would under-promise.
  const columnSelectData = useMemo(() => {
    const none = { value: COLOR_BY_NONE_VALUE, label: 'None' };
    const distinctDcs = new Set(colorByColumns.flatMap((c) => c.dcIds));
    if (distinctDcs.size <= 1) {
      return [none, ...colorByColumns.map((c) => ({ value: c.name, label: c.name }))];
    }
    const dcLabel = (dcId: string): string => {
      const meta = components.find((m) => m.dc_id === dcId && m.data_collection_tag);
      return (meta?.data_collection_tag as string) || `dataset ${dcId.slice(-4)}`;
    };
    const shared = colorByColumns.filter((c) => c.dcIds.length > 1);
    const byDc = new Map<string, { value: string; label: string }[]>();
    for (const c of colorByColumns) {
      if (c.dcIds.length !== 1) continue;
      const items = byDc.get(c.dcIds[0]) ?? [];
      items.push({ value: c.name, label: c.name });
      byDc.set(c.dcIds[0], items);
    }
    const data: (
      | { value: string; label: string }
      | { group: string; items: { value: string; label: string }[] }
    )[] = [none];
    if (shared.length > 0) {
      data.push({
        group: 'Shared columns',
        items: shared.map((c) => ({ value: c.name, label: c.name })),
      });
    }
    for (const [dcId, items] of byDc) {
      data.push({ group: dcLabel(dcId), items });
    }
    return data;
  }, [colorByColumns, components]);

  const defaultColor = nextGroupColor(groups);
  const defaultName = defaultGroupName(groups);
  const selectedCandidate =
    candidates.find((f) => `${f.index}:${f.source}` === sourceIndex) ?? candidates[0];

  const openPopover = () => {
    setName(defaultName);
    setColor(null);
    setSourceIndex(null);
    setCreateError(null);
    setPopoverOpen(true);
  };

  const confirmCreate = () => {
    if (!selectedCandidate) return;
    const finalName = name.trim() || defaultName;
    const created = onCreateGroup(selectedCandidate, finalName, color ?? defaultColor);
    if (!created) {
      // Keep the selection so the user can retry or shrink it.
      setCreateError(
        `Couldn't save this selection as a group — it may exceed the ${MAX_GROUP_VALUES.toLocaleString()}-value cap.`,
      );
      return;
    }
    setCreateError(null);
    // Free the (index, source) selection slot so the next lasso starts clean.
    onClearSelection({ ...selectedCandidate, value: [] });
    setPopoverOpen(false);
  };

  return (
    <Box>
      {/* ── Section 1: standard color-by from a real column ─────────────── */}
      <Group gap={6} wrap="nowrap" align="center">
        <Divider
          label="Color by column"
          labelPosition="left"
          styles={{ label: { fontSize: 11, fontWeight: 600 } }}
          style={{ flex: 1 }}
        />
        <Tooltip
          label="Back to defaults: no coloring, overlay display, no card comparison. Saved groups are kept."
          withArrow
          openDelay={400}
        >
          <Button
            size="compact-xs"
            variant="subtle"
            color="gray"
            disabled={
              colorBy.kind === 'none' &&
              !compareInCards &&
              displayMode === 'color' &&
              showOther &&
              showOverall
            }
            onClick={onResetAnalysis}
            leftSection={<Icon icon="mdi:restore" width={12} height={12} />}
            styles={{ label: { fontSize: 11 } }}
          >
            Reset
          </Button>
        </Tooltip>
      </Group>
      <Tooltip
        label="Color every figure whose dataset carries the column"
        withArrow
        openDelay={400}
      >
        <Select
          size="xs"
          mt={4}
          data={columnSelectData}
          // Null (rather than the sentinel "None" value) when no column is
          // active, so `clearable`'s × only appears once there is something
          // to clear.
          value={colorBy.kind === 'column' ? colorBy.columnName : null}
          placeholder="None"
          onChange={(v) =>
            onColorByChange(
              !v || v === COLOR_BY_NONE_VALUE ? COLOR_BY_NONE : { kind: 'column', columnName: v },
            )
          }
          clearable
          allowDeselect={false}
          searchable={colorByColumns.length > 8}
          // The panel can live inside a header popover; a portaled dropdown
          // would count as an outside click there and close the whole panel.
          comboboxProps={{ withinPortal: false }}
        />
      </Tooltip>
      {colorBy.kind === 'column' && (
        <DisplayModeControl value={displayMode} onChange={onDisplayModeChange} />
      )}

      {/* ── Section 2: on-the-fly groups (creation + list) ──────────────── */}
      <Divider
        label="Groups"
        labelPosition="left"
        mt={10}
        styles={{ label: { fontSize: 11, fontWeight: 600 } }}
      />

      <Popover
        opened={popoverOpen}
        onChange={setPopoverOpen}
        width={260}
        position="bottom-start"
        withArrow
        shadow="md"
        trapFocus
        // See the Select above: stay in the local DOM so a click in this
        // nested popover doesn't close a hosting header popover.
        withinPortal={false}
      >
        <Popover.Target>
          <Tooltip
            label={
              candidates.length === 0
                ? 'Make a selection on a chart, table or map first'
                : 'Save the current selection as a named group'
            }
            withArrow
            openDelay={400}
          >
            <span style={{ display: 'inline-flex', width: '100%' }}>
              <Button
                mt={4}
                size="xs"
                variant="light"
                fullWidth
                leftSection={<Icon icon="mdi:selection-drag" width={14} height={14} />}
                disabled={candidates.length === 0}
                onClick={openPopover}
              >
                Save selection as group
              </Button>
            </span>
          </Tooltip>
        </Popover.Target>
        <Popover.Dropdown>
          <Stack gap="xs">
            {candidates.length > 1 && (
              <Select
                size="xs"
                label="Selection"
                data={candidates.map((f) => ({
                  value: `${f.index}:${f.source}`,
                  label: `${filterDisplayLabel(f, components)} (${
                    Array.isArray(f.value) ? f.value.length : 0
                  })`,
                }))}
                value={sourceIndex ?? `${candidates[0].index}:${candidates[0].source}`}
                onChange={setSourceIndex}
                allowDeselect={false}
                comboboxProps={{ withinPortal: false }}
              />
            )}
            <TextInput
              size="xs"
              label="Group name"
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') confirmCreate();
              }}
              data-autofocus
            />
            <Group gap={4}>
              {TAB10_PALETTE.map((c) => (
                <ColorSwatch
                  key={c}
                  color={c}
                  size={16}
                  style={{
                    cursor: 'pointer',
                    outline:
                      (color ?? defaultColor) === c
                        ? '2px solid var(--mantine-color-blue-5)'
                        : 'none',
                    outlineOffset: 1,
                  }}
                  onClick={() => setColor(c)}
                />
              ))}
            </Group>
            {selectedCandidate && Array.isArray(selectedCandidate.value) && (
              <Text size="xs" c="dimmed">
                {selectedCandidate.value.length} selected item
                {selectedCandidate.value.length === 1 ? '' : 's'}
              </Text>
            )}
            {createError && (
              <Text size="xs" c="red">
                {createError}
              </Text>
            )}
            <Button size="xs" onClick={confirmCreate} disabled={!selectedCandidate}>
              Save group
            </Button>
          </Stack>
        </Popover.Dropdown>
      </Popover>

      {candidates.length === 0 && groups.length === 0 && (
        <Text size="xs" c="dimmed" mt={4}>
          Lasso points on a chart with cross-filtering enabled (or tick table rows, or select on
          a map), then save the selection as a group to filter, color and compare.
        </Text>
      )}

      {groups.length > 0 && (
        <Stack
          gap={2}
          mt={6}
          mah={160}
          // `scrollbarGutter: stable` + right padding: on overlay-scrollbar
          // platforms (macOS) the bar otherwise paints OVER the row's
          // rightmost buttons the moment the list becomes scrollable, and
          // clicks meant for them land on the scrollbar instead.
          style={{ overflowY: 'auto', scrollbarGutter: 'stable', paddingRight: 6 }}
        >
          {groups.map((g) => (
            <Group key={g.id} gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
              <ColorSwatch color={g.color} size={12} style={{ flexShrink: 0 }} />
              <Tooltip
                label={`${g.values.length} items on ${g.columnName}`}
                withArrow
                openDelay={400}
              >
                <Text
                  size="xs"
                  fw={500}
                  truncate
                  style={{ flex: '1 1 auto', minWidth: 0, cursor: 'default' }}
                >
                  {g.name}
                </Text>
              </Tooltip>
              <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                {g.values.length}
              </Text>
              {/* sm, not xs: these are the panel's most-clicked controls and an
                  18px box around a 12px glyph collects near-misses, which read
                  as "the funnel does nothing" (observed in the field). */}
              <Popover
                opened={editingId === g.id}
                onChange={(open) => setEditingId(open ? g.id : null)}
                width={220}
                position="bottom-end"
                withArrow
                shadow="md"
                trapFocus
                withinPortal={false}
              >
                <Popover.Target>
                  <Tooltip label="Edit name and color" withArrow openDelay={400}>
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      size="sm"
                      aria-label={`Edit group ${g.name}`}
                      onClick={() => {
                        setEditName(g.name);
                        setEditingId(editingId === g.id ? null : g.id);
                      }}
                      style={{ flexShrink: 0 }}
                    >
                      <Icon icon="mdi:pencil-outline" width={14} height={14} />
                    </ActionIcon>
                  </Tooltip>
                </Popover.Target>
                <Popover.Dropdown>
                  <Stack gap="xs">
                    <TextInput
                      size="xs"
                      label="Group name"
                      value={editName}
                      onChange={(e) => setEditName(e.currentTarget.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          onUpdateGroup(g.id, { name: editName });
                          setEditingId(null);
                        }
                        if (e.key === 'Escape') setEditingId(null);
                      }}
                      data-autofocus
                    />
                    <Group gap={4}>
                      {TAB10_PALETTE.map((c) => (
                        <ColorSwatch
                          key={c}
                          color={c}
                          size={16}
                          style={{
                            cursor: 'pointer',
                            outline:
                              g.color === c ? '2px solid var(--mantine-color-blue-5)' : 'none',
                            outlineOffset: 1,
                          }}
                          // Color applies immediately: the figures recolor as
                          // feedback, no confirmation step needed.
                          onClick={() => onUpdateGroup(g.id, { color: c })}
                        />
                      ))}
                    </Group>
                    <Button
                      size="xs"
                      onClick={() => {
                        onUpdateGroup(g.id, { name: editName });
                        setEditingId(null);
                      }}
                    >
                      Done
                    </Button>
                  </Stack>
                </Popover.Dropdown>
              </Popover>
              <Tooltip
                label={g.filterActive ? 'Stop filtering by this group' : 'Filter by this group'}
                withArrow
                openDelay={400}
              >
                <ActionIcon
                  variant={g.filterActive ? 'filled' : 'subtle'}
                  color={g.filterActive ? 'blue' : 'gray'}
                  size="sm"
                  aria-label={
                    g.filterActive
                      ? `Stop filtering by group ${g.name}`
                      : `Filter by group ${g.name}`
                  }
                  onClick={() => onToggleGroupFilter(g.id)}
                  style={{ flexShrink: 0 }}
                >
                  <Icon icon="mdi:filter-variant" width={14} height={14} />
                </ActionIcon>
              </Tooltip>
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                ml={2}
                aria-label={`Delete group ${g.name}`}
                onClick={() => onDeleteGroup(g.id)}
                style={{ flexShrink: 0 }}
              >
                <Icon icon="mdi:close" width={14} height={14} />
              </ActionIcon>
            </Group>
          ))}
        </Stack>
      )}

      {/* ── Section 3: what to do with the groups ───────────────────────── */}
      {groups.length > 0 && (
        <>
          <Divider
            label="Group options"
            labelPosition="left"
            mt={10}
            styles={{ label: { fontSize: 11, fontWeight: 600 } }}
          />
          <Stack gap={6} mt={4}>
            <Tooltip
              label="Color every figure by group membership — overrides the column coloring above"
              withArrow
              openDelay={400}
            >
              <span style={{ display: 'flex' }}>
                <Switch
                  size="xs"
                  label="Color figures by groups"
                  checked={colorBy.kind === 'groups'}
                  onChange={(e) =>
                    onColorByChange(e.currentTarget.checked ? { kind: 'groups' } : COLOR_BY_NONE)
                  }
                  styles={{ label: { fontSize: 11 } }}
                />
              </span>
            </Tooltip>
            {colorBy.kind === 'groups' && (
              <>
                <DisplayModeControl value={displayMode} onChange={onDisplayModeChange} />
                <Tooltip
                  label="Off: figures drop rows that belong to no group instead of drawing them gray"
                  withArrow
                  openDelay={400}
                >
                  <span style={{ display: 'flex' }}>
                    <Switch
                      size="xs"
                      label="Show ungrouped (“Other”)"
                      checked={showOther}
                      onChange={(e) => onShowOtherChange(e.currentTarget.checked)}
                      styles={{ label: { fontSize: 11 } }}
                    />
                  </span>
                </Tooltip>
              </>
            )}
            <Tooltip
              label={
                colorBy.kind === 'column'
                  ? 'Paused while coloring by a column: cards comparing groups under figures grouped by something else would mix two encodings'
                  : "Show each card's metric broken down per group"
              }
              withArrow
              openDelay={400}
            >
              <span style={{ display: 'flex' }}>
                <Switch
                  size="xs"
                  label="Compare groups in cards"
                  checked={compareInCards}
                  // Disabled (not hidden, and not cleared) in column mode: the
                  // stored value survives, so leaving column mode resumes the
                  // comparison exactly as it was.
                  disabled={colorBy.kind === 'column'}
                  onChange={(e) => onCompareInCardsChange(e.currentTarget.checked)}
                  styles={{ label: { fontSize: 11 } }}
                />
              </span>
            </Tooltip>
            {compareInCards && colorBy.kind !== 'column' && (
              <Tooltip
                label="Add an “All rows” reference entry above the per-group rows"
                withArrow
                openDelay={400}
              >
                <span style={{ display: 'flex' }}>
                  <Switch
                    size="xs"
                    label="Show overall (All)"
                    checked={showOverall}
                    onChange={(e) => onShowOverallChange(e.currentTarget.checked)}
                    styles={{ label: { fontSize: 11 } }}
                  />
                </span>
              </Tooltip>
            )}
          </Stack>
        </>
      )}
    </Box>
  );
};

export default SelectionGroupsPanel;
