import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import GridLayout, { Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import {
  Accordion,
  ActionIcon,
  Badge,
  Box,
  Button,
  Group,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { FilterSectionSpec, InteractiveFilter, StoredMetadata } from '../../api';
import { countActiveFilters } from '../../activeFilters';
import { useCollapseState } from '../../hooks/useCollapseState';
import type { InteractiveSection } from '../../utils/groupInteractive';
import {
  matchesFilterSearch,
  sectionInteractiveComponents,
} from '../../utils/groupInteractive';
import {
  gridLayoutToMemberLayout,
  groupsToGridLayout,
  orderGroupsByLayout,
} from '../../utils/leftPanelLayout';
import ComponentRenderer from '../ComponentRenderer';
import InteractiveGroupCard from '../InteractiveGroupCard';
import FilterChips from './FilterChips';

/**
 * The dashboard's left filter panel, shared by the viewer and the editor.
 *
 * Both apps used to render their own tree for this — the viewer inline in
 * App.tsx, the editor via a separate LeftFilterPanel — so grouping, ordering
 * and density silently diverged between view and edit mode. One component
 * with an `editMode` switch is what keeps them honest.
 *
 * Editing only changes the affordances layered on top: react-grid-layout for
 * drag-reordering, a grip per row, and the per-component action menu. The
 * grouping, collapse and density behaviour is identical in both modes.
 *
 * Two levels of nesting, both optional and both additive:
 *   section (accordion item)  →  group (collapsible card)  →  control
 * A dashboard that sets neither renders one unnamed section with one singleton
 * group per control, which is exactly the flat list this panel started as.
 *
 * Drag-reordering is scoped to a section: each renders its own grid, and the
 * saved layout concatenates them in section order. Moving a control between
 * sections is an authoring change (its `section` field), not a drag.
 */

// Compact filter rows: rowHeight 40 with h=2 gives 80px per row, tighter than
// the 100px Dash default so more filters fit before scrolling.
const ROW_HEIGHT = 40;
const DENSITY_STORAGE_KEY = 'filter-panel-density';
// Below this many controls the search box costs more room than it saves.
const SEARCH_THRESHOLD = 8;

/**
 * Width of the collapsed panel. Unlike the tab sidebar, the filter panel never
 * collapses to nothing: the rail keeps the active-filter count on screen, so a
 * dashboard can't look unfiltered while filters are silently applied.
 */
export const FILTER_PANEL_RAIL_WIDTH = 44;

export type FilterPanelDensity = 'comfortable' | 'compact';

export interface FilterPanelProps {
  /** Interactive components for the left panel — callers filter out `placement: 'top'`. */
  components: StoredMetadata[];
  /** Full stored_metadata, so chart/table selection chips can resolve a label. */
  allMetadata?: StoredMetadata[];
  filters: InteractiveFilter[];
  onFilterChange: (filter: InteractiveFilter) => void;
  onResetAllFilters?: () => void;
  /** `DashboardData.left_panel_layout_data` — drives ordering in both modes. */
  layoutData?: unknown;
  /** `DashboardData.filter_sections` — section order, icons, default collapse. */
  filterSections?: FilterSectionSpec[];
  /** Persisted per dashboard, so collapse state survives a reload. */
  dashboardId?: string | null;
  refreshTick?: number;
  editMode?: boolean;
  /** Editor-only per-component actions (edit / duplicate / delete). */
  renderItemOverlay?: (component: StoredMetadata) => React.ReactNode;
  /** Editor-only. Receives a component-keyed layout ready to persist. */
  onLayoutChange?: (layout: Layout[]) => void;
  /** Renders the icon rail instead of the panel. Owned by the app, which also
   *  owns the grid column the panel lives in. */
  collapsed?: boolean;
  /** Omitted when the panel can't be collapsed (e.g. inside the mobile drawer),
   *  which also hides the collapse control. */
  onToggleCollapsed?: () => void;
  /** Pinned below the filter list, outside its scroll area. Deliberately an
   *  opaque node: the apps put the docked map panel here, and this component
   *  has no business knowing that. */
  footer?: React.ReactNode;
}

function readDensity(): FilterPanelDensity {
  try {
    return localStorage.getItem(DENSITY_STORAGE_KEY) === 'compact' ? 'compact' : 'comfortable';
  } catch {
    return 'comfortable';
  }
}

const FilterPanel: React.FC<FilterPanelProps> = ({
  components,
  allMetadata,
  filters,
  onFilterChange,
  onResetAllFilters,
  layoutData,
  filterSections,
  dashboardId,
  refreshTick,
  editMode = false,
  renderItemOverlay,
  onLayoutChange,
  collapsed = false,
  onToggleCollapsed,
  footer,
}) => {
  const [density, setDensity] = useState<FilterPanelDensity>(readDensity);
  const [search, setSearch] = useState('');

  const collapsedByDefault = useMemo(
    () => (filterSections ?? []).filter((s) => s.collapsed).map((s) => `section:${s.name}`),
    [filterSections],
  );
  const collapse = useCollapseState(
    `filter-panel-collapsed:${dashboardId ?? 'unknown'}`,
    collapsedByDefault,
  );

  const visibleComponents = useMemo(
    () => components.filter((m) => matchesFilterSearch(m, search)),
    [components, search],
  );

  const sections = useMemo(
    () =>
      sectionInteractiveComponents(visibleComponents, filterSections).map((s) => ({
        ...s,
        groups: orderGroupsByLayout(s.groups, layoutData),
      })),
    [visibleComponents, filterSections, layoutData],
  );

  const activeCount = countActiveFilters(filters);
  const compactMembers = density === 'compact';

  // A search narrows `groups` to the matches, so the grid only knows about
  // those rows. Persisting that layout would drop every filtered-out
  // component's saved position, so reordering is frozen until it clears.
  const searching = search.trim().length > 0;
  const dragEnabled = editMode && !searching;

  const toggleDensity = useCallback(() => {
    setDensity((prev) => {
      const next = prev === 'compact' ? 'comfortable' : 'compact';
      try {
        localStorage.setItem(DENSITY_STORAGE_KEY, next);
      } catch {
        // ignore quota / disabled storage
      }
      return next;
    });
  }, []);

  // Self-measure so the editor grid never overflows into the content column
  // when the panel is narrower than the window-derived estimate.
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const [measuredWidth, setMeasuredWidth] = useState(280);
  useEffect(() => {
    if (!wrapperRef.current || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width;
      if (next && next > 0) setMeasuredWidth(Math.floor(next));
    });
    ro.observe(wrapperRef.current);
    return () => ro.disconnect();
  }, []);

  const renderGroup = (group: InteractiveSection['groups'][number]) => {
    if (group.groupName) {
      return (
        <InteractiveGroupCard
          groupName={group.groupName}
          members={group.members}
          filters={filters}
          onFilterChange={onFilterChange}
          refreshTick={refreshTick}
          collapsible
          open={collapse.isOpen(group.key)}
          onToggle={() => collapse.toggle(group.key)}
          renderMemberActions={renderItemOverlay}
          showDragHandle={dragEnabled}
        />
      );
    }
    const m = group.members[0];
    return (
      <ComponentRenderer
        metadata={m}
        filters={filters}
        onFilterChange={onFilterChange}
        refreshTick={refreshTick}
        compact={compactMembers}
        showDragHandle={dragEnabled}
        extraActions={renderItemOverlay?.(m)}
      />
    );
  };

  // Latest grid order per section, so a drag in one section can be merged with
  // the others' current order into the single component-keyed array we persist.
  const sectionLayoutsRef = useRef<Map<string, Layout[]>>(new Map());

  const isCollapsed = useCallback((key: string) => !collapse.isOpen(key), [collapse]);

  const handleSectionLayoutChange = useCallback(
    (sectionKey: string, next: Layout[]) => {
      if (searching) return;
      sectionLayoutsRef.current.set(sectionKey, next);
      const merged: Layout[] = [];
      let y = 0;
      for (const s of sections) {
        const layout =
          sectionLayoutsRef.current.get(s.key) ?? groupsToGridLayout(s.groups, isCollapsed);
        for (const item of gridLayoutToMemberLayout(layout, s.groups)) {
          merged.push({ ...item, y });
          y += item.h;
        }
      }
      onLayoutChange?.(merged);
    },
    [onLayoutChange, sections, searching, isCollapsed],
  );

  const renderSectionBody = (section: InteractiveSection) => {
    if (!editMode) {
      return (
        <Stack gap="sm">
          {section.groups.map((g) => (
            <React.Fragment key={g.key}>{renderGroup(g)}</React.Fragment>
          ))}
        </Stack>
      );
    }
    return (
      <GridLayout
        className="layout left-filter-grid"
        layout={groupsToGridLayout(section.groups, isCollapsed)}
        cols={1}
        rowHeight={ROW_HEIGHT}
        width={measuredWidth}
        margin={[8, 8]}
        containerPadding={[0, 0]}
        isDraggable={dragEnabled}
        isResizable={false}
        compactType="vertical"
        onLayoutChange={(next) => handleSectionLayoutChange(section.key, next)}
        draggableHandle=".react-grid-dragHandle"
      >
        {section.groups.map((g) => (
          <div
            key={g.key}
            data-component-id={g.key}
            style={{
              overflow: 'hidden',
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            {renderGroup(g)}
          </div>
        ))}
      </GridLayout>
    );
  };

  const renderSectionHeader = (section: InteractiveSection) => {
    const members = section.groups.flatMap((g) => g.members);
    const count = countActiveFilters(filters, members);
    return (
      <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
        {section.spec?.icon && (
          <Icon icon={section.spec.icon} width={15} height={15} style={{ flexShrink: 0 }} />
        )}
        <Text size="sm" fw={600} truncate>
          {section.sectionName}
        </Text>
        {count > 0 && (
          <Badge size="xs" variant="light" circle>
            {count}
          </Badge>
        )}
      </Group>
    );
  };

  const body = (() => {
    if (components.length === 0) {
      return (
        <Text size="sm" c="dimmed">
          No interactive components.
        </Text>
      );
    }
    if (sections.length === 0) {
      return (
        <Text size="sm" c="dimmed">
          No filter matches “{search}”.
        </Text>
      );
    }

    const unsectioned = sections.find((s) => !s.sectionName);
    const named = sections.filter((s) => s.sectionName);

    return (
      <Stack gap="sm">
        {unsectioned && renderSectionBody(unsectioned)}
        {named.length > 0 && (
          <Accordion
            multiple
            variant="separated"
            radius="md"
            chevronPosition="left"
            value={named.filter((s) => collapse.isOpen(s.key)).map((s) => s.key)}
            onChange={(open) => {
              // Mantine hands back the full open set; translate it into the
              // per-key toggles the persisted collapse state is built from.
              const openSet = new Set(open);
              for (const s of named) {
                if (openSet.has(s.key) !== collapse.isOpen(s.key)) collapse.toggle(s.key);
              }
            }}
            styles={{ content: { padding: 'var(--mantine-spacing-xs)' } }}
          >
            {named.map((s) => (
              <Accordion.Item key={s.key} value={s.key}>
                <Accordion.Control>{renderSectionHeader(s)}</Accordion.Control>
                <Accordion.Panel>
                  {s.spec?.description && (
                    <Text size="xs" c="dimmed" mb="xs">
                      {s.spec.description}
                    </Text>
                  )}
                  {renderSectionBody(s)}
                </Accordion.Panel>
              </Accordion.Item>
            ))}
          </Accordion>
        )}
      </Stack>
    );
  })();

  const framedBody = (
    <div
      ref={wrapperRef}
      // Edit mode only: these are the marker classes DashboardGrid sets on its
      // own root, and app.css keys the visible per-cell border off them. The
      // viewer deliberately stays unclassed — `.depictio-dashboard-grid:not(
      // .depictio-edit-mode)` strips Paper borders, and the filter column has
      // always shown its borders in view mode. The ref is unconditional: it
      // feeds the ResizeObserver that sizes the per-section grids.
      className={editMode ? 'depictio-dashboard-grid depictio-edit-mode' : undefined}
      style={{ width: '100%', overflowX: 'hidden' }}
    >
      {body}
    </div>
  );

  // Collapsed: an icon rail rather than nothing, so the active-filter count
  // stays visible. A dashboard showing filtered numbers must never look like
  // it is showing everything.
  if (collapsed) {
    return (
      <Paper
        // Padding kept to 2px: the rail column is 44px wide and the caller's
        // wrapper already spends 8 of them, so a `md`-sized ActionIcon (28px)
        // plus this padding and the border is what actually fits.
        p={2}
        withBorder
        radius="md"
        style={{
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 6,
          overflow: 'hidden',
        }}
        data-tour-id="filter-panel"
      >
        <Tooltip
          label={activeCount > 0 ? `Show filters (${activeCount} active)` : 'Show filters'}
          withArrow
          position="right"
        >
          <ActionIcon
            variant="subtle"
            color="gray"
            size="md"
            aria-label="Show filters"
            aria-expanded={false}
            onClick={onToggleCollapsed}
          >
            <Icon icon="mdi:filter-variant" width={20} height={20} />
          </ActionIcon>
        </Tooltip>
        {activeCount > 0 && (
          <Badge size="sm" variant="light" circle>
            {activeCount}
          </Badge>
        )}
      </Paper>
    );
  }

  return (
    <Paper
      p="md"
      withBorder
      radius="md"
      style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
      data-tour-id="filter-panel"
    >
      <Group justify="space-between" align="center" mb="xs" wrap="nowrap">
        <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
          {onToggleCollapsed && (
            <Tooltip label="Hide filters" withArrow openDelay={400}>
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                aria-label="Hide filters"
                aria-expanded
                onClick={onToggleCollapsed}
              >
                <Icon icon="mdi:chevron-left" width={16} height={16} />
              </ActionIcon>
            </Tooltip>
          )}
          <Title order={5}>Filters</Title>
          {activeCount > 0 && (
            <Badge size="sm" variant="light" circle>
              {activeCount}
            </Badge>
          )}
        </Group>
        <Group gap={4} wrap="nowrap">
          <Tooltip
            label={density === 'compact' ? 'Comfortable density' : 'Compact density'}
            withArrow
            openDelay={400}
          >
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              aria-label="Toggle filter density"
              onClick={toggleDensity}
            >
              <Icon
                icon={density === 'compact' ? 'mdi:view-sequential' : 'mdi:view-headline'}
                width={16}
                height={16}
              />
            </ActionIcon>
          </Tooltip>
          {onResetAllFilters && (
            <Button
              leftSection={<Icon icon="bx:reset" width={12} />}
              color="orange"
              // Filled only while there is something to reset, mirroring the
              // per-component ResetButton: a permanently filled orange button
              // reads as an alert on a panel that is otherwise quiet, which is
              // most of the time.
              variant={activeCount > 0 ? 'filled' : 'light'}
              size="xs"
              onClick={onResetAllFilters}
              disabled={activeCount === 0}
            >
              Reset all
            </Button>
          )}
        </Group>
      </Group>

      <FilterChips
        filters={filters}
        components={allMetadata ?? components}
        onClear={onFilterChange}
      />

      {components.length > SEARCH_THRESHOLD && (
        <TextInput
          mt="xs"
          size="xs"
          placeholder="Search filters…"
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          leftSection={<Icon icon="mdi:magnify" width={14} height={14} />}
          rightSection={
            search ? (
              <ActionIcon
                variant="subtle"
                color="gray"
                size="xs"
                aria-label="Clear search"
                onClick={() => setSearch('')}
              >
                <Icon icon="mdi:close" width={12} height={12} />
              </ActionIcon>
            ) : undefined
          }
        />
      )}

      <Box
        mt="sm"
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: 'auto',
          overflowX: 'hidden',
          // Reserve the scrollbar's width. Without it, the scrollbar appearing
          // changes the content width, which feeds the ResizeObserver above →
          // grid reflow → height change → scrollbar toggles again.
          scrollbarGutter: 'stable',
        }}
      >
        {framedBody}
      </Box>
      {footer}
    </Paper>
  );
};

export default FilterPanel;
