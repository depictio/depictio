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
import { PANEL_RESIZE_END_EVENT, isPanelResizing } from '../../utils/panelToggle';
import { useCollapseState } from '../../hooks/useCollapseState';
import type { InteractiveSection } from '../../utils/groupInteractive';
import {
  collapsedSectionKeys,
  matchesFilterSearch,
  sectionInteractiveComponents,
} from '../../utils/groupInteractive';
import {
  applyAccordionValue,
  SectionAccordion,
  SectionAccordionItem,
  SectionHeader,
} from '../SectionAccordion';
import {
  gridLayoutToMemberLayout,
  groupsToGridLayout,
  rowSpanForHeight,
  orderGroupsByLayout,
} from '../../utils/leftPanelLayout';
import ComponentRenderer from '../ComponentRenderer';
import InteractiveGroupCard from '../InteractiveGroupCard';
import ActiveFilterSummary from './ActiveFilterSummary';

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
/** Vertical gap react-grid-layout leaves between rows; needed to turn a
 *  measured pixel height back into a row span. */
const GRID_MARGIN = 8;
const DENSITY_STORAGE_KEY = 'filter-panel-density';
// Below this many controls the search box costs more room than it saves.
const SEARCH_THRESHOLD = 8;

/**
 * Collapse key for the active-filter summary, which folds through the same
 * persisted state as the sections and groups around it. Prefixed so it can't
 * collide with a `section:` / `group:` key or with a component index.
 */
const SUMMARY_KEY = 'summary:active-filters';

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
  /**
   * Host-provided per-section actions, mirroring `DashboardGrid`'s prop of the
   * same name: they land beside the section's fold control. The editor puts its
   * "…" there so the panel's sections are reached the same way the grid's are.
   */
  renderSectionActions?: (sectionName: string | null) => React.ReactNode;
  /** Section names that stay read-only even in edit mode — the persistent
   *  sections a sibling tab owns. They are shown so the author sees the panel
   *  a viewer will get, but they are edited on their owner tab, and their
   *  members must never reach this dashboard's `left_panel_layout_data`. */
  readOnlySections?: string[];
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
  /** Funnel filtering (issue #939). Omitted → the controls are hidden (the
   *  dashboard hasn't opted in, or the host — e.g. the editor — doesn't wire
   *  it). `onOpenView` opens the funnel overview modal; it's only offered
   *  while the toggle is on, since the overview is computed by the same
   *  opt-in machinery. */
  funnel?: {
    enabled: boolean;
    onToggle: () => void;
    onOpenView: () => void;
  };
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
  renderSectionActions,
  readOnlySections,
  onLayoutChange,
  collapsed = false,
  onToggleCollapsed,
  footer,
  funnel,
}) => {
  const [density, setDensity] = useState<FilterPanelDensity>(readDensity);
  const [search, setSearch] = useState('');

  const collapsedByDefault = useMemo(
    () => collapsedSectionKeys(filterSections),
    [filterSections],
  );
  // `filter-panel-sections-collapsed:`, NOT `filter-panel-collapsed:` — the
  // latter is `useFilterPanelOpen`'s key for the whole-panel boolean, and both
  // hooks are mounted together on every dashboard. Sharing the key would have
  // each one silently overwrite the other's payload (`boolean` vs `string[]`),
  // so the losing side falls back to its default on the next load. Matches the
  // `grid-section-collapsed:` naming used by DashboardGrid.
  const collapse = useCollapseState(
    `filter-panel-sections-collapsed:${dashboardId ?? 'unknown'}`,
    collapsedByDefault,
  );

  const visibleComponents = useMemo(
    () => components.filter((m) => matchesFilterSearch(m, search)),
    [components, search],
  );

  const sections = useMemo(
    () =>
      // `includeEmpty` only in edit mode, and only while nothing is being
      // searched for: a section created from the Sections manager has no members
      // yet, but a search that matches none of a section's filters should still
      // hide it rather than leave a row of empty headers behind.
      sectionInteractiveComponents(
        visibleComponents,
        filterSections,
        editMode && !search.trim(),
      ).map((s) => ({
        ...s,
        groups: orderGroupsByLayout(s.groups, layoutData),
      })),
    [visibleComponents, filterSections, layoutData, editMode, search],
  );

  const activeCount = countActiveFilters(filters);
  const compactMembers = density === 'compact';

  // Everything the panel can fold: its named sections and its group cards. The
  // grid's equivalent control only has sections to worry about; here a
  // dashboard may well group its filters without sectioning them, and a
  // "collapse all" that left those groups open would be a lie.
  const collapsibleKeys = useMemo(() => {
    const keys = sections.filter((s) => s.sectionName).map((s) => s.key);
    for (const s of sections) {
      for (const g of s.groups) if (g.groupName) keys.push(g.key);
    }
    return keys;
  }, [sections]);
  const anyOpen = collapsibleKeys.some((key) => collapse.isOpen(key));

  // A search narrows `groups` to the matches, so the grid only knows about
  // those rows. Persisting that layout would drop every filtered-out
  // component's saved position, so reordering is frozen until it clears.
  const searching = search.trim().length > 0;
  const dragEnabled = editMode && !searching;

  /**
   * Group key → rows its rendered card actually needs.
   *
   * `groupRowSpan` estimates from the member types, and the estimate is too
   * generous for a group card (its members render far more compactly than they
   * do on their own) and for a slider whose marks are off — leaving a tall
   * empty band under the card, since the grid never shrinks an item to its
   * contents. Measuring the card we drew and converting back to rows fixes both
   * without another table of magic numbers. It settles in one pass: the card's
   * height does not depend on the item's.
   */
  const [measuredSpans, setMeasuredSpans] = useState<Record<string, number>>({});
  const cardRefs = useRef<Map<string, HTMLElement>>(new Map());
  const observerRef = useRef<ResizeObserver | null>(null);
  // One stable callback per key: an inline arrow would be a new ref on every
  // render, so React would detach and re-attach every card each time and the
  // observer would re-fire for all of them.
  const cardRefCbs = useRef<Map<string, (node: HTMLDivElement | null) => void>>(new Map());
  const cardRef = useCallback((key: string) => {
    let cb = cardRefCbs.current.get(key);
    if (!cb) {
      cb = (node: HTMLDivElement | null) => registerCard(key, node);
      cardRefCbs.current.set(key, cb);
    }
    return cb;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const registerCard = useCallback((key: string, node: HTMLDivElement | null) => {
    const observer = observerRef.current;
    const prev = cardRefs.current.get(key);
    if (prev && prev !== node) observer?.unobserve(prev);
    if (!node) {
      cardRefs.current.delete(key);
      return;
    }
    cardRefs.current.set(key, node);
    observer?.observe(node);
  }, []);

  useEffect(() => {
    if (!editMode || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => {
      // The key travels on the element rather than through a reverse lookup:
      // the ref callback is re-created every render, so the map it fills is
      // briefly empty exactly when the observer fires.
      const measured = entries
        .map((entry) => ({
          key: (entry.target as HTMLElement).dataset.groupKey,
          rows: rowSpanForHeight(
            entry.target.getBoundingClientRect().height,
            ROW_HEIGHT,
            GRID_MARGIN,
          ),
        }))
        .filter((m): m is { key: string; rows: number } => Boolean(m.key));
      if (measured.length === 0) return;
      setMeasuredSpans((prev) => {
        let next = prev;
        for (const { key, rows } of measured) {
          if (prev[key] === rows) continue;
          if (next === prev) next = { ...prev };
          next[key] = rows;
        }
        return next;
      });
    });
    observerRef.current = observer;
    for (const el of cardRefs.current.values()) observer.observe(el);
    return () => {
      observer.disconnect();
      observerRef.current = null;
    };
  }, [editMode]);

  // A foreign persistent section renders as it does in the viewer even here:
  // no drag handles, no per-component actions, and no contribution to the
  // layout this dashboard persists.
  const readOnlyNames = useMemo(() => new Set(readOnlySections ?? []), [readOnlySections]);
  const isReadOnly = useCallback(
    (section: InteractiveSection) => Boolean(section.sectionName && readOnlyNames.has(section.sectionName)),
    [readOnlyNames],
  );

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
  // Room the section box leaves inside itself, measured the same way and for the
  // same reason as `DashboardGrid`'s: a grid handed the full panel width would
  // run past the box and get clipped.
  const [sectionInset, setSectionInset] = useState(0);
  const measureRef = useRef<() => void>(() => {});
  useEffect(() => {
    if (!wrapperRef.current || typeof ResizeObserver === 'undefined') return;
    const measure = () => {
      const wrapper = wrapperRef.current;
      if (!wrapper) return;
      const next = wrapper.getBoundingClientRect().width;
      if (!next || next <= 0) return;
      setMeasuredWidth(Math.floor(next));
      const probe = wrapper.querySelector('[data-section-grid]');
      if (probe) {
        setSectionInset(Math.max(0, Math.round(next - probe.getBoundingClientRect().width)));
      }
    };
    measureRef.current = measure;
    const ro = new ResizeObserver(() => {
      // Held still while the panel's own edge is being dragged, then measured
      // once on release — the same freeze `DashboardGrid` applies, and for the
      // same reason: this width changes on every pointermove of that drag.
      if (isPanelResizing()) return;
      measure();
    });
    ro.observe(wrapperRef.current);
    window.addEventListener(PANEL_RESIZE_END_EVENT, measure);
    measure();
    return () => {
      ro.disconnect();
      window.removeEventListener(PANEL_RESIZE_END_EVENT, measure);
    };
    // Keyed on `collapsed` because `wrapperRef` only has a node while the panel
    // is expanded — the collapsed branch returns the icon rail before
    // `framedBody` renders. A panel that mounts collapsed (the persisted state
    // from a previous visit) would otherwise never install the observer, and
    // `measuredWidth` would stay pinned at its seed for the rest of the session.
  }, [collapsed]);

  // Sections whose controls are actually mounted — the same additive rule the
  // grid applies to its own, and for the same reason: a folded `Accordion.Panel`
  // keeps its children mounted, so a section collapsed by default was still
  // fetching each control's option list or column range. See `renderedSections`
  // in DashboardGrid.
  const openSectionKeys = sections.filter((s) => collapse.isOpen(s.key)).map((s) => s.key);
  const [renderedSections, setRenderedSections] = useState<Set<string>>(
    () => new Set(openSectionKeys),
  );
  useEffect(() => {
    setRenderedSections((prev) => {
      const missing = openSectionKeys.filter((k) => !prev.has(k));
      return missing.length ? new Set([...prev, ...missing]) : prev;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openSectionKeys.join(' ')]);

  // The inset probe is a section, so it can only be measured once one has
  // rendered — and again whenever the set of them changes, which a search can do
  // without the panel itself resizing, or an expand can do on a panel whose
  // sections all started folded.
  useEffect(() => {
    measureRef.current();
  }, [sections, renderedSections]);

  const renderGroup = (group: InteractiveSection['groups'][number], readOnly = false) => {
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
          renderMemberActions={readOnly ? undefined : renderItemOverlay}
          showDragHandle={dragEnabled && !readOnly}
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
        showDragHandle={dragEnabled && !readOnly}
        extraActions={readOnly ? undefined : renderItemOverlay?.(m)}
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
        // A read-only section has no grid of its own, so it has no order to
        // merge — and its members belong to another dashboard's layout.
        if (isReadOnly(s)) continue;
        const layout =
          sectionLayoutsRef.current.get(s.key) ??
          groupsToGridLayout(s.groups, isCollapsed, measuredSpans);
        for (const item of gridLayoutToMemberLayout(layout, s.groups)) {
          merged.push({ ...item, y });
          y += item.h;
        }
      }
      onLayoutChange?.(merged);
    },
    [onLayoutChange, sections, searching, isCollapsed, isReadOnly, measuredSpans],
  );

  const renderSectionBody = (section: InteractiveSection) => {
    const readOnly = isReadOnly(section);
    if (!editMode || readOnly) {
      return (
        <Stack gap="sm">
          {section.groups.map((g) => (
            <React.Fragment key={g.key}>{renderGroup(g, readOnly)}</React.Fragment>
          ))}
        </Stack>
      );
    }
    return (
      <GridLayout
        className="layout left-filter-grid"
        layout={groupsToGridLayout(section.groups, isCollapsed, measuredSpans)}
        cols={1}
        rowHeight={ROW_HEIGHT}
        // Inside a section box the grid gets the room the box leaves; the
        // unsectioned bucket has no box and spans the panel.
        width={section.sectionName ? Math.max(80, measuredWidth - sectionInset) : measuredWidth}
        margin={[GRID_MARGIN, GRID_MARGIN]}
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
            {/* The measured wrapper, one level in: react-grid-layout clones its
                own child and overwrites any ref put on it, and that child is
                stretched to the item anyway — measuring it would just hand back
                the height we are trying to correct. */}
            <div
              ref={cardRef(g.key)}
              data-group-key={g.key}
              style={{ flexShrink: 0 }}
            >
              {renderGroup(g)}
            </div>
          </div>
        ))}
      </GridLayout>
    );
  };

  const renderSectionHeader = (section: InteractiveSection) => {
    const members = section.groups.flatMap((g) => g.members);
    const count = countActiveFilters(filters, members);
    return (
      <SectionHeader
        spec={section.spec}
        name={section.sectionName}
        badge={
          count > 0 ? (
            <Badge size="sm" variant="light" circle color={section.spec?.color || undefined}>
              {count}
            </Badge>
          ) : undefined
        }
      />
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
          <SectionAccordion
            compact
            value={named.filter((s) => collapse.isOpen(s.key)).map((s) => s.key)}
            onChange={(open) =>
              applyAccordionValue(
                open,
                named.map((s) => s.key),
                collapse,
              )
            }
          >
            {named.map((s) => (
              // No `color`: the panel's rails stay neutral so they don't pair
              // up with the grid's. See `SectionAccordionItem`.
              <SectionAccordionItem
                key={s.key}
                value={s.key}
                actions={renderSectionActions?.(s.sectionName ?? null)}
              >
                <Accordion.Control>{renderSectionHeader(s)}</Accordion.Control>
                <Accordion.Panel>
                  {/* Plain wrapper so the width available inside the section box
                      can be read off the DOM — see `sectionInset`. */}
                  {renderedSections.has(s.key) && (
                    <div data-section-grid>
                      {s.groups.length === 0 ? (
                        // Only reachable in edit mode (`includeEmpty`).
                        <Text size="xs" c="dimmed" ta="center" py="xs">
                          No filters yet — pick this section when creating one.
                        </Text>
                      ) : (
                        renderSectionBody(s)
                      )}
                    </div>
                  )}
                </Accordion.Panel>
              </SectionAccordionItem>
            ))}
          </SectionAccordion>
        )}
      </Stack>
    );
  })();

  const framedBody = (
    <div
      ref={wrapperRef}
      // The marker classes DashboardGrid sets on its own root, carrying the
      // same meaning here: app.css paints a per-cell border under
      // `.depictio-edit-mode` and strips every Paper border without it. Both
      // modes are classed so the panel matches the grid — a filter placed at
      // the top of the dashboard already renders frameless in view mode, and
      // the same control in the panel should not draw a box around itself just
      // because of where it sits. Edit mode keeps its borders: there the boxes
      // are the drag targets. The ref feeds the ResizeObserver that sizes the
      // per-section grids; it only exists on this expanded branch, which is why
      // that effect is keyed on `collapsed`.
      className={
        editMode ? 'depictio-dashboard-grid depictio-edit-mode' : 'depictio-dashboard-grid'
      }
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
        {/* Rotated so a 44px rail still says what it is. `vertical-rl` plus a
            180° turn reads bottom-to-top, the usual direction for a label on a
            left-hand edge. `aria-hidden` because the ActionIcon above already
            carries the accessible name — this is the same control, spelled out
            for sighted users, so exposing it twice would just add noise. */}
        <Text
          size="xs"
          fw={600}
          c="dimmed"
          aria-hidden
          onClick={onToggleCollapsed}
          style={{
            writingMode: 'vertical-rl',
            transform: 'rotate(180deg)',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            userSelect: 'none',
            cursor: onToggleCollapsed ? 'pointer' : undefined,
            whiteSpace: 'nowrap',
          }}
        >
          Filters
        </Text>
      </Paper>
    );
  }

  return (
    // No border and no surface of its own. The panel already occupies its own
    // column, and the app draws the divider between that column and the grid —
    // so a box around the whole thing is a second boundary in the same place,
    // and it nests: sections draw a rail, groups draw a card, and a control
    // outside a group draws its own Paper. The outermost frame is the one that
    // says the least and costs the most, since its border and radius come out
    // of a ~280px column. The collapsed rail keeps its border: there the box IS
    // the affordance, with nothing inside it to delimit.
    <Paper
      p="md"
      withBorder={false}
      radius="md"
      bg="transparent"
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
          {funnel && (
            <Tooltip
              label={
                funnel.enabled
                  ? 'Funnel filtering on — values with no remaining results are greyed out'
                  : 'Enable funnel filtering'
              }
              withArrow
              openDelay={400}
            >
              <ActionIcon
                variant={funnel.enabled ? 'filled' : 'subtle'}
                color={funnel.enabled ? 'teal' : 'gray'}
                size="sm"
                aria-label="Toggle funnel filtering"
                aria-pressed={funnel.enabled}
                onClick={funnel.onToggle}
                data-testid="funnel-toggle"
              >
                <Icon icon="mdi:filter-variant" width={16} height={16} />
              </ActionIcon>
            </Tooltip>
          )}
          {funnel?.enabled && (
            <Tooltip label="Show the funnel overview" withArrow openDelay={400}>
              <ActionIcon
                variant="subtle"
                color="teal"
                size="sm"
                aria-label="Show funnel overview"
                onClick={funnel.onOpenView}
                data-testid="funnel-view-button"
              >
                <Icon icon="mdi:chart-sankey" width={16} height={16} />
              </ActionIcon>
            </Tooltip>
          )}
          {collapsibleKeys.length > 0 && (
            <Tooltip
              label={anyOpen ? 'Collapse all' : 'Expand all'}
              withArrow
              openDelay={400}
            >
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                aria-label={anyOpen ? 'Collapse all' : 'Expand all'}
                onClick={() => collapse.setAll(collapsibleKeys, anyOpen)}
              >
                <Icon
                  icon={anyOpen ? 'mdi:unfold-less-horizontal' : 'mdi:unfold-more-horizontal'}
                  width={16}
                  height={16}
                />
              </ActionIcon>
            </Tooltip>
          )}
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

      <ActiveFilterSummary
        filters={filters}
        components={allMetadata ?? components}
        onClear={onFilterChange}
        open={collapse.isOpen(SUMMARY_KEY)}
        onToggle={() => collapse.toggle(SUMMARY_KEY)}
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
