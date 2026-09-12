import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  ColorSwatch,
  Divider,
  Group,
  Paper,
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
import type { ColorByColumn } from '../../hooks/useColorByColumns';
import {
  COLOR_BY_NONE,
  selectableSelectionFilters,
  type ColorByState,
  type GroupingDisplay,
  type SelectionGroup,
} from '../../selectionGroups';
import { Z_LAYERS } from '../../zLayers';
import GroupColorSwatches from '../GroupColorSwatches';
import GroupingSteps from './GroupingSteps';
import PendingGroupForm from './PendingGroupForm';
import ValueListPreview from './ValueListPreview';
import { colorBySegmentValue, groupPreview, selectionCapableCount } from './groupingGuide';

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

// The panel sits in a 440px drawer, not a header popover, so it reads at the
// theme's own sizes rather than a step below them: 11px headings and labels
// made it dense to scan without buying any room back. Declared once so the
// dividers and the switches can't drift apart.
const SECTION_LABEL_STYLES = { label: { fontSize: 13, fontWeight: 600 } } as const;
const CONTROL_LABEL_STYLES = { label: { fontSize: 13 } } as const;

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
      size="sm"
      mt={6}
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
 *    With no group yet, the guided three steps (`GroupingSteps`) stand here
 *    instead of an explanatory paragraph; with a live selection,
 *    `PendingGroupForm` shows what is about to be saved. Both can be on
 *    screen at once — that is the last step of the guide happening.
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
  // Per-row edit popover (name + color); null when no row is being edited.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  // The last column the user coloured by. Picking "A column" on the segmented
  // control restores it rather than reopening an empty Select — flipping
  // between the two overrides to compare them is the common move.
  const [lastColumn, setLastColumn] = useState<string | null>(null);
  // "A column" is selected but none is chosen yet: the Select shows, the
  // override stays off. Without this the segment would snap back to "Nothing"
  // the instant it was clicked, since `colorBy` is still `none`.
  const [columnPending, setColumnPending] = useState(false);
  useEffect(() => {
    if (colorBy.kind !== 'column') return;
    setLastColumn(colorBy.columnName);
    setColumnPending(false);
  }, [colorBy]);

  const candidates = useMemo(() => selectableSelectionFilters(filters), [filters]);
  // How many tiles here could ever feed a group — quoted by the guide's first
  // step, so it speaks about this dashboard rather than the feature at large.
  const selectableCount = useMemo(() => selectionCapableCount(components), [components]);

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

  return (
    <Box>
      {/* ── Section 1: what every figure is coloured (or split) by ──────── */}
      <Group gap={6} wrap="nowrap" align="center">
        <Divider
          label="Color figures by"
          labelPosition="left"
          styles={SECTION_LABEL_STYLES}
          style={{ flex: 1 }}
        />
        <Tooltip
          label="Back to defaults: no coloring, overlay display, no card comparison. Saved groups are kept."
          withArrow
          openDelay={400}
        >
          <Button
            size="compact-sm"
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
            leftSection={<Icon icon="mdi:restore" width={14} height={14} />}
            styles={CONTROL_LABEL_STYLES}
          >
            Reset
          </Button>
        </Tooltip>
      </Group>

      {/* One control, three states. The two overrides used to be a Select in
          one section and a Switch in another, which read as two independent
          settings — they are not: one `ColorByState` backs both, so turning
          one on turns the other off, and users could not see why. Putting
          them on one segmented control makes the exclusivity structural. */}
      <SegmentedControl
        size="sm"
        mt={6}
        fullWidth
        value={colorBySegmentValue(colorBy, columnPending)}
        onChange={(v) => {
          if (v === 'column') {
            // Keep whatever column was last picked; otherwise wait for the
            // Select below rather than guessing one.
            onColorByChange(
              lastColumn ? { kind: 'column', columnName: lastColumn } : COLOR_BY_NONE,
            );
            setColumnPending(!lastColumn);
            return;
          }
          setColumnPending(false);
          onColorByChange(v === 'groups' ? { kind: 'groups' } : COLOR_BY_NONE);
        }}
        data={[
          { value: 'none', label: 'Nothing' },
          {
            value: 'column',
            // A disabled segment with no explanation reads as a bug. The
            // tooltip sits on the label, which still takes hover while the
            // input underneath is disabled.
            label: (
              <Tooltip
                label={
                  colorByColumns.length === 0
                    ? 'No categorical column on this dashboard to color by'
                    : 'Color by a column that is already in your data'
                }
                withArrow
                openDelay={400}
              >
                <Group gap={4} justify="center" wrap="nowrap">
                  <Icon icon="mdi:table-column" width={14} height={14} />
                  <span>A column</span>
                </Group>
              </Tooltip>
            ),
            disabled: colorByColumns.length === 0,
          },
          {
            value: 'groups',
            label: (
              <Tooltip
                label={
                  groups.length === 0
                    ? 'Draw a group first: lasso or box-select on a marked tile'
                    : 'Color by the groups you drew below'
                }
                withArrow
                openDelay={400}
              >
                <Group gap={4} justify="center" wrap="nowrap">
                  <Icon icon="mdi:select-group" width={14} height={14} />
                  <span>My groups</span>
                </Group>
              </Tooltip>
            ),
            disabled: groups.length === 0,
          },
        ]}
      />

      {/* The sentence that tells the two apart. Without it "Color by column"
          and "Color figures by groups" read as the same feature twice. */}
      <Text size="xs" c="dimmed" mt={6}>
        {colorBy.kind === 'column'
          ? 'A column already in your data: every figure whose dataset carries it is redrawn by its values.'
          : colorBy.kind === 'groups'
            ? 'The groups you drew below, which exist only on this dashboard.'
            : 'A column is a field already in your data. Groups are sets you draw yourself, by selecting points on a figure.'}
      </Text>

      {(colorBy.kind === 'column' || columnPending) && (
        <Tooltip
          label="Color every figure whose dataset carries the column"
          withArrow
          openDelay={400}
        >
          <Select
            size="sm"
            mt={6}
            data={columnSelectData}
            // Null (rather than the sentinel "None" value) when no column is
            // active, so `clearable`'s × only appears once there is something
            // to clear.
            value={colorBy.kind === 'column' ? colorBy.columnName : null}
            placeholder="Pick a column…"
            onChange={(v) => {
              setColumnPending(false);
              onColorByChange(
                !v || v === COLOR_BY_NONE_VALUE ? COLOR_BY_NONE : { kind: 'column', columnName: v },
              );
            }}
            clearable
            allowDeselect={false}
            searchable={colorByColumns.length > 8}
            // Portaled, with an explicit layer above the drawer that hosts the
            // panel: the drawer body scrolls, so an in-DOM dropdown would be
            // clipped by that overflow the moment the panel is taller than the
            // viewport.
            comboboxProps={{ withinPortal: true, zIndex: Z_LAYERS.tooltip }}
          />
        </Tooltip>
      )}
      {colorBy.kind !== 'none' && (
        <DisplayModeControl value={displayMode} onChange={onDisplayModeChange} />
      )}
      {colorBy.kind === 'groups' && (
        <Tooltip
          label="Off: figures drop rows that belong to no group instead of drawing them gray"
          withArrow
          openDelay={400}
        >
          <span style={{ display: 'flex', marginTop: 8 }}>
            <Switch
              size="sm"
              label="Show ungrouped (“Other”)"
              checked={showOther}
              onChange={(e) => onShowOtherChange(e.currentTarget.checked)}
              styles={CONTROL_LABEL_STYLES}
            />
          </span>
        </Tooltip>
      )}

      {/* ── Section 2: on-the-fly groups (creation + list) ──────────────── */}
      <Divider
        label={groups.length > 0 ? `Your groups (${groups.length})` : 'Your groups'}
        labelPosition="left"
        mt={14}
        styles={SECTION_LABEL_STYLES}
      />

      {/* The guide runs until the first group exists — after that the ritual
          is known and the panel gives the space back to the group list. Its
          third step stays on screen next to the pending form, which is what
          the step is describing. */}
      {groups.length === 0 && (
        <GroupingSteps
          selectableCount={selectableCount}
          hasSelection={candidates.length > 0}
        />
      )}

      {candidates.length > 0 ? (
        <PendingGroupForm
          candidates={candidates}
          components={components}
          groups={groups}
          onCreateGroup={onCreateGroup}
          onClearSelection={onClearSelection}
        />
      ) : (
        groups.length > 0 && (
          <Group gap={6} wrap="nowrap" mt={8} align="center">
            <Icon icon="mdi:selection-drag" width={15} height={15} style={{ opacity: 0.6 }} />
            <Text size="sm" c="dimmed">
              Lasso or box-select on a marked tile to add another group.
            </Text>
          </Group>
        )
      )}

      {groups.length > 0 && (
        <Stack
          gap={6}
          mt={8}
          // Taller than the 160 the header popover could afford: the panel is
          // a full-height side panel now, so more of the list fits before the
          // scroll starts.
          mah={340}
          // `scrollbarGutter: stable` + right padding: on overlay-scrollbar
          // platforms (macOS) the bar otherwise paints OVER the row's
          // rightmost buttons the moment the list becomes scrollable, and
          // clicks meant for them land on the scrollbar instead.
          style={{ overflowY: 'auto', scrollbarGutter: 'stable', paddingRight: 6 }}
        >
          {groups.map((g) => {
            const preview = groupPreview(g, components);
            return (
            // A card, not a line. A swatch plus a name plus a count made two
            // groups drawn on different columns — or on different datasets —
            // look identical, right up to the point where one of them silently
            // failed to reach a figure. The card says what the group is made
            // of, in the same shape `PendingGroupForm` showed before saving.
            <Paper key={g.id} withBorder radius="sm" p={8} style={{ minWidth: 0 }}>
            <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
              <ColorSwatch color={g.color} size={14} style={{ flexShrink: 0 }} />
              <Text
                size="sm"
                fw={600}
                truncate
                style={{ flex: '1 1 auto', minWidth: 0, cursor: 'default' }}
              >
                {g.name}
              </Text>
              <Tooltip
                label={
                  preview.values.total === preview.values.distinct
                    ? `${preview.values.distinct} values on ${preview.columnName}`
                    : `${preview.values.distinct} distinct values, from ${preview.values.total} selected points`
                }
                withArrow
                openDelay={400}
              >
                <Badge size="sm" variant="light" color="gray" style={{ flexShrink: 0 }}>
                  {preview.values.distinct.toLocaleString()}
                </Badge>
              </Tooltip>
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
                // Portaled above the hosting drawer — see the color-by Select:
                // the group list is itself a scroll container, which would
                // clip an in-DOM dropdown for every row but the first.
                zIndex={Z_LAYERS.tooltip}
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
                    {/* Color applies immediately: the figures recolor as
                        feedback, no confirmation step needed. */}
                    <GroupColorSwatches
                      value={g.color}
                      onSelect={(c) => onUpdateGroup(g.id, { color: c })}
                    />
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
            <Text size="xs" c="dimmed" mt={4} truncate>
              on <Text span size="xs" fw={600} c="dimmed">{preview.columnName}</Text>
              {preview.datasetLabel && (
                <>
                  {' in '}
                  <Text span size="xs" fw={600} c="dimmed">
                    {preview.datasetLabel}
                  </Text>
                </>
              )}
            </Text>
            {/* The values themselves. Two groups on the same column are only
                told apart by what is in them. Three rows here rather than the
                pending form's five: several cards share the panel. */}
            <Box mt={4}>
              <ValueListPreview values={preview.values} rows={3} withHeader={false} />
            </Box>
            </Paper>
          );
          })}
        </Stack>
      )}

      {/* ── Section 3: what the groups do to the cards ──────────────────── */}
      {groups.length > 0 && (
        <>
          <Divider
            label="In cards"
            labelPosition="left"
            mt={14}
            styles={SECTION_LABEL_STYLES}
          />
          <Stack gap={8} mt={6}>
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
                  size="sm"
                  label="Compare groups in cards"
                  checked={compareInCards}
                  // Disabled (not hidden, and not cleared) in column mode: the
                  // stored value survives, so leaving column mode resumes the
                  // comparison exactly as it was.
                  disabled={colorBy.kind === 'column'}
                  onChange={(e) => onCompareInCardsChange(e.currentTarget.checked)}
                  styles={CONTROL_LABEL_STYLES}
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
                    size="sm"
                    label="Show overall (All)"
                    checked={showOverall}
                    onChange={(e) => onShowOverallChange(e.currentTarget.checked)}
                    styles={CONTROL_LABEL_STYLES}
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
