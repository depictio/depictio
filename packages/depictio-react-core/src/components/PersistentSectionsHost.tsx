import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Responsive as ResponsiveGridLayout } from 'react-grid-layout';
import { GRID_BREAKPOINTS, GRID_COL_COUNTS, toSplitRows } from '../gridConfig';
import { Accordion, Badge, Button, Group } from '@mantine/core';
import { Icon } from '@iconify/react';

import type {
  BulkComputeOptions,
  InteractiveFilter,
  PersistentSection,
  StoredMetadata,
} from '../api';
import type { GroupRenderState } from '../selectionGroups';
import { bulkComputeCards } from '../api';
import { countActiveFilters } from '../activeFilters';
import { useCollapseState } from '../hooks/useCollapseState';
import { useRevealComponent } from '../reveal';
import {
  applyAccordionValue,
  SectionAccordion,
  SectionAccordionItem,
  SectionHeader,
} from './SectionAccordion';
import ComponentRenderer from './ComponentRenderer';
import { withSectionStyles } from './figureStyle';
import { normalizeLayout, responsiveLayouts, SectionSummary } from './DashboardGrid';
import { fitLayoutHeights, GRID_ROW_GAP_PX, SPLIT_ROW_PX, useAutofitHeights } from './autofit';
import { FilterStripSection, SectionFilterBar } from './interactive/strip/FilterStrip';
import { hasSectionBar, isStripSection, sectionRuns } from './interactive/strip/stripLayout';
import {
  filtersInScope,
  planScopedRequests,
  sectionScopeKey,
  type FilterScopes,
} from '../filterScope';

export interface PersistentSectionsHostProps {
  /** Persistent *grid* sections owned by sibling tabs. The caller filters out
   *  the ones the current tab owns — those render natively inside its own
   *  `DashboardGrid`, where they stay editable. */
  sections: PersistentSection[];
  /** Family id — the collapse state is keyed on it so folding a persistent
   *  section on one tab keeps it folded on every other. */
  familyId: string | null;
  /** Which edge this host renders at. Only used to key the collapse state:
   *  the two hosts a tab can mount must not write over each other's folds. */
  slot: 'top' | 'bottom';
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  refreshTick?: number;
  /** Color-by / split overrides (issue #89). Fanned-out members sit on the same
   *  screen as the tab's own grid and are fed the same filters, so they must
   *  take the same dashboard-wide visual override — otherwise turning on
   *  "Color by species" recolors the grid and silently skips the pinned
   *  section right above it, which reads as a broken component. */
  groupRender?: GroupRenderState;
  /** Group-comparison options for this host's own card bulk-compute, for the
   *  same reason: without them a pinned card is the only one on screen with no
   *  comparison strip. */
  bulkOptions?: BulkComputeOptions;
  /** Editor-only per-section action, rendered in the section header. A section
   *  fanned out here can only be changed on the tab that owns it, so the editor
   *  puts a jump to that tab where the "…" sits on an editable section. */
  renderSectionActions?: (section: PersistentSection) => React.ReactNode;
  /** Clears every filter. With filters active, a pinned section's header says
   *  so ("Filtered", "14 / 85") and offers this as its way back. */
  onResetFilters?: () => void;
  /** What a fanned-out filter bar's controls display — the instant filters,
   *  where `filters` is the debounced copy the data fetches use. */
  controlFilters?: InteractiveFilter[];
  /** Which filters belong to a section's own bar (`filterScope.ts`), the
   *  family-wide map the app builds. A fanned-out section with a bar of its
   *  own is keyed `sectionScopeKey(name, owner)`: its members see its bar's
   *  filters, and no other section's. */
  filterScopes?: FilterScopes;
  /** Clears the given filters (by index): a bar's "Reset". */
  onResetBarFilters?: (indices: string[]) => void;
}

/** The scope a fanned-out section's members filter in: its own bar's, if it
 *  has one, else none (the tab-wide filters only). */
const hostScopeOf = (s: PersistentSection): string | null =>
  hasSectionBar(s.spec) ? sectionScopeKey(s.spec.name, s.owner_dashboard_id) : null;

/** A section fanned out from another tab is keyed by owner + name: two tabs
 *  each declaring a persistent section with the same name stay two sections. */
const hostSectionKey = (s: PersistentSection) => `${s.owner_dashboard_id}:${s.spec.name}`;

/**
 * Renders the family's persistent grid sections on tabs that do not own them —
 * the "always in view" slot a metadata table lands in on every tab. The caller
 * mounts one host per `pin` edge, above and below the tab's own grid.
 *
 * Read-only by design: the section's geometry lives in its owner tab's
 * `right_panel_layout_data`, and this host must never feed a foreign section's
 * items into the viewing tab's layout merge (`DashboardGrid` assumes every item
 * it persists belongs to the current document). Each member renders against its
 * *owning* tab's id — the floating-map convention — so the per-component data
 * endpoints need no special casing.
 *
 * Card members get their values from a bulk-compute of their own: the app's
 * per-tab `bulkComputeCards` call only covers the tab being viewed, so the
 * host fires one more per owning tab, scoped to the fanned-out card ids and
 * fed the same (debounced) filters as everything else on screen.
 */
const PersistentSectionsHost: React.FC<PersistentSectionsHostProps> = ({
  sections,
  familyId,
  slot,
  filters,
  onFilterChange,
  refreshTick,
  groupRender,
  bulkOptions,
  renderSectionActions,
  onResetFilters,
  controlFilters,
  filterScopes,
  onResetBarFilters,
}) => {
  const renderable = useMemo(
    () =>
      sections
        .map((s) => ({ section: s, members: s.components }))
        .filter((s) => s.members.length > 0),
    [sections],
  );

  const collapsedByDefault = useMemo(
    () =>
      renderable
        .filter((s) => s.section.spec.collapsed)
        .map((s) => hostSectionKey(s.section)),
    [renderable],
  );
  const collapse = useCollapseState(
    `grid-section-collapsed:${familyId ?? 'family'}:persistent:${slot}`,
    collapsedByDefault,
  );

  // The dashboard search, asking for a component a sibling tab pins here: open
  // its section, as DashboardGrid does for the tab's own.
  useRevealComponent((index) => {
    const hit = renderable.find((s) => s.members.some((c) => c.metadata.index === index));
    if (!hit) return;
    const key = hostSectionKey(hit.section);
    if (!collapse.isOpen(key)) collapse.setAll([key], false);
  });

  // Same lazy-mount rule as DashboardGrid: a section that has never been opened
  // renders no grid at all, so a folded-by-default metadata table doesn't fetch
  // on every tab until someone actually opens it.
  const openKeys = renderable
    .filter((s) => collapse.isOpen(hostSectionKey(s.section)))
    .map((s) => hostSectionKey(s.section));
  const [renderedKeys, setRenderedKeys] = useState<Set<string>>(() => new Set(openKeys));
  useEffect(() => {
    setRenderedKeys((prev) => {
      const missing = openKeys.filter((k) => !prev.has(k));
      return missing.length ? new Set([...prev, ...missing]) : prev;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openKeys.join(' ')]);

  // Values for the fanned-out cards. Keyed by component index, like the app's
  // own bulk-compute state — indices are unique across a family, so one map
  // can hold every owner's results.
  const [cardValues, setCardValues] = useState<Record<string, unknown>>({});
  const [cardSecondaryValues, setCardSecondaryValues] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [cardsLoading, setCardsLoading] = useState(false);
  const cardFetchId = useRef(0);

  // Card ids per owning tab, each with the scope its section filters in.
  // Deliberately NOT gated on the lazy-mount set: a folded section's header
  // shows summary chips built from these values (see the `trailing` below), so
  // the cards are fetched even while the section has never been opened. Cards
  // are one cheap bulk call — the lazy-mount rule still spares the heavy
  // members (tables, figures).
  const cardsByOwner = useMemo(() => {
    const byOwner = new Map<string, { id: string; scope: string | null }[]>();
    for (const { section, members } of renderable) {
      const scope = hostScopeOf(section);
      for (const m of members) {
        if (m.metadata.component_type !== 'card') continue;
        const list = byOwner.get(m.dashboard_id) ?? [];
        list.push({ id: m.metadata.index, scope });
        byOwner.set(m.dashboard_id, list);
      }
    }
    return byOwner;
  }, [renderable]);
  const cardIdsByOwner = useMemo(
    () =>
      new Map([...cardsByOwner.entries()].map(([owner, cards]) => [owner, cards.map((c) => c.id)])),
    [cardsByOwner],
  );
  const cardIdsKey = useMemo(
    () =>
      [...cardIdsByOwner.entries()]
        .map(([owner, ids]) => `${owner}:${ids.join(',')}`)
        .sort()
        .join(' '),
    [cardIdsByOwner],
  );

  useEffect(() => {
    if (cardIdsByOwner.size === 0) return;
    const fetchId = ++cardFetchId.current;
    setCardsLoading(true);
    // One request per owner and per filter set: a section with a bar of its
    // own computes its cards under that bar's filters (`planScopedRequests`).
    Promise.all(
      [...cardsByOwner.entries()].flatMap(([owner, cards]) =>
        planScopedRequests(cards, filters, filterScopes).map((req) =>
          bulkComputeCards(owner, req.filters, req.ids, bulkOptions).catch((err) => {
            console.warn('[PersistentSectionsHost] bulk-compute failed:', err);
            return null;
          }),
        ),
      ),
    )
      .then((results) => {
        if (fetchId !== cardFetchId.current) return; // a newer fetch superseded us
        const values: Record<string, unknown> = {};
        const secondary: Record<string, Record<string, unknown>> = {};
        for (const res of results) {
          if (!res) continue;
          Object.assign(values, res.values);
          Object.assign(secondary, res.secondary_values || {});
        }
        setCardValues(values);
        setCardSecondaryValues(secondary);
      })
      .finally(() => {
        if (fetchId === cardFetchId.current) setCardsLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardIdsKey, JSON.stringify(filters), filterScopes, refreshTick]);

  // The same cards without filters: the denominator of the folded header's
  // "14 / 85". Fetched only while filters are active, and once per data
  // refresh, since the unfiltered values do not move with the filters.
  const filtered = countActiveFilters(filters) > 0;
  const [baseValues, setBaseValues] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    if (!filtered || cardIdsByOwner.size === 0 || baseValues) return;
    let cancelled = false;
    Promise.all(
      [...cardIdsByOwner.entries()].map(([owner, ids]) =>
        bulkComputeCards(owner, [], ids).catch(() => null),
      ),
    ).then((results) => {
      if (cancelled) return;
      const values: Record<string, unknown> = {};
      for (const res of results) if (res) Object.assign(values, res.values);
      setBaseValues(values);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered, cardIdsKey, baseValues]);
  useEffect(() => setBaseValues(null), [cardIdsKey, refreshTick]);

  // Measure our own wrapper; the accordion box chrome is accounted for with a
  // probe, mirroring DashboardGrid's `sectionInset`.
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const autoHeights = useAutofitHeights();
  const [containerWidth, setContainerWidth] = useState<number>(() =>
    typeof window !== 'undefined' ? window.innerWidth - 40 : 1200,
  );
  const [sectionInset, setSectionInset] = useState(0);
  useEffect(() => {
    if (!wrapperRef.current || typeof ResizeObserver === 'undefined') return;
    const measure = () => {
      const wrapper = wrapperRef.current;
      if (!wrapper) return;
      const next = wrapper.getBoundingClientRect().width;
      if (!next || next <= 0) return;
      setContainerWidth(Math.floor(next));
      const probe = wrapper.querySelector('[data-persistent-section-grid]');
      if (probe) {
        setSectionInset(Math.max(0, Math.round(next - probe.getBoundingClientRect().width)));
      }
    };
    const ro = new ResizeObserver(measure);
    ro.observe(wrapperRef.current);
    return () => ro.disconnect();
  }, []);

  if (renderable.length === 0) return null;

  // One owner tab's members as a read-only grid. `metas` are the members'
  // metadata in the style their section draws them in.
  const renderGrid = (
    metas: StoredMetadata[],
    members: PersistentSection['components'],
    section: PersistentSection,
    gridWidth: number,
  ) => {
    const stored = toSplitRows(normalizeLayout(metas, section.layouts, false));
    // The tab's filters, plus this section's own bar's if it has one.
    const sectionFilters = filtersInScope(filters, filterScopes, hostScopeOf(section));
    return (
      <ResponsiveGridLayout
      className="layout"
      // Fitted here as in DashboardGrid: a pinned section is
      // still a grid of tiles, and a text tile that sizes
      // itself on the tab that declares it has to do the same
      // on every tab that shows it. Always on — this host is
      // read-only, so a measurement can never be persisted.
      // Rescaled for every breakpoint by the same helper the
      // main grid uses: passing `lg` alone let react-grid-layout
      // generate the others, and its clamp collided the second
      // half-width tile with the first, stacking a two-table row
      // below 1440px.
      layouts={responsiveLayouts(
        fitLayoutHeights(metas, stored, autoHeights, true, SPLIT_ROW_PX),
      )}
      breakpoints={GRID_BREAKPOINTS}
      cols={GRID_COL_COUNTS}
      rowHeight={SPLIT_ROW_PX}
      width={gridWidth}
      // Same asymmetric gap as the main grid, from the same
      // constants: gridConfig.ts's header warns these two
      // surfaces must not drift.
      margin={[12, GRID_ROW_GAP_PX]}
      containerPadding={[0, 0]}
      isDraggable={false}
      isResizable={false}
      compactType="vertical"
    >
      {members.map((member) => (
        <div
          key={member.metadata.index}
          data-component-id={member.metadata.index}
          style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
        >
          <div
            style={{
              overflow: 'hidden',
              flex: 1,
              minHeight: 0,
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <ComponentRenderer
              // The OWNER tab, not the tab being viewed: data
              // endpoints take the dashboard id as a path param
              // and gate on the same project permission.
              dashboardId={member.dashboard_id}
              // Same rule as the owner tab's grid: the
              // section's card style unless the card sets one.
              metadata={withSectionStyles(member.metadata, section.spec)}
              filters={sectionFilters}
              onFilterChange={onFilterChange}
              refreshTick={refreshTick}
              groupRender={groupRender}
              cardValue={cardValues[member.metadata.index]}
              cardSecondaryValues={cardSecondaryValues[member.metadata.index]}
              cardLoading={cardsLoading}
            />
          </div>
        </div>
      ))}
    </ResponsiveGridLayout>
    );
  };

  // A filter bar renders on its own, without the accordion item: no header,
  // no fold. Its non-interactive members, if any, sit under it as a grid.
  const renderStrip = ({ section, members }: (typeof renderable)[number]) => {
    const key = hostSectionKey(section);
    const bar = members.filter((m) => m.metadata.component_type === 'interactive');
    const others = members.filter((m) => m.metadata.component_type !== 'interactive');
    const metas = others.map((m) => withSectionStyles(m.metadata, section.spec));
    return (
      <FilterStripSection
        key={key}
        name={section.spec.name}
        spec={section.spec}
        members={bar.map((m) => m.metadata)}
        filters={controlFilters ?? filters}
        onFilterChange={onFilterChange}
        onReset={
          onResetBarFilters ? () => onResetBarFilters(bar.map((m) => m.metadata.index)) : undefined
        }
        rest={others.length > 0 ? renderGrid(metas, others, section, containerWidth) : null}
      />
    );
  };

  const runs = sectionRuns(renderable, (s) => isStripSection(s.section.spec));

  return (
    // `flexShrink: 0`: the viewer mounts this inside a fixed-height column
    // flex container, which would otherwise squeeze a shrinkable host down to
    // zero height as soon as the tab's own grid fills the column.
    <div ref={wrapperRef} style={{ width: '100%', overflowX: 'hidden', flexShrink: 0 }}>
      {runs.map((run) => {
        if (run.strip) return renderStrip(run.section);
        const keys = run.sections.map((s) => hostSectionKey(s.section));
        return (
          <SectionAccordion
            key={keys[0]}
            value={keys.filter((k) => collapse.isOpen(k))}
            onChange={(open) => applyAccordionValue(open, keys, collapse)}
          >
            {run.sections.map(({ section, members: all }) => {
              const key = hostSectionKey(section);
              // A section with a bar of its own: its interactive members are the
              // bar, drawn under the heading, and the rest are its tiles.
              const withBar = hasSectionBar(section.spec);
              const bar = withBar
                ? all.filter((m) => m.metadata.component_type === 'interactive')
                : [];
              const members = withBar
                ? all.filter((m) => m.metadata.component_type !== 'interactive')
                : all;
              // "Filtered" when something narrows what this section shows.
              const sectionFiltered =
                countActiveFilters(filtersInScope(filters, filterScopes, hostScopeOf(section))) > 0;
              // In the style each card is drawn in, so the fitting below treats a
              // row of compact cards the way the owner tab's grid does.
              // Read-only, so in half rows (gridConfig's ROW_SPLIT), as DashboardGrid.
              const metas = members.map((m) => withSectionStyles(m.metadata, section.spec));
              const gridWidth = Math.max(100, containerWidth - sectionInset);
              return (
                <SectionAccordionItem
                  key={key}
                  value={key}
                  color={section.spec.color}
                  actions={
                    sectionFiltered && onResetFilters ? (
                      <Group gap={6} wrap="nowrap">
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          color="gray"
                          leftSection={<Icon icon="mdi:filter-remove-outline" width={14} />}
                          onClick={onResetFilters}
                        >
                          Reset filters
                        </Button>
                        {renderSectionActions?.(section)}
                      </Group>
                    ) : (
                      renderSectionActions?.(section)
                    )
                  }
                >
                  <Accordion.Control>
                    <SectionHeader
                      spec={section.spec}
                      name={section.spec.name}
                      badge={
                        sectionFiltered ? (
                          <Badge size="xs" variant="light" color={section.spec.color || 'blue'}>
                            Filtered
                          </Badge>
                        ) : undefined
                      }
                      // Folded, the section still tells you what it holds — same
                      // chips as DashboardGrid's own sections. PersistentSection
                      // members are adapted to the ComponentSection shape the
                      // summary expects.
                      trailing={
                        !collapse.isOpen(key) ? (
                          <SectionSummary
                            section={{
                              key,
                              sectionName: section.spec.name,
                              spec: section.spec,
                              members: metas,
                            }}
                            cardValues={cardValues}
                            baseValues={sectionFiltered && baseValues ? baseValues : undefined}
                          />
                        ) : undefined
                      }
                    />
                  </Accordion.Control>
                  <Accordion.Panel>
                    {withBar && (
                      <SectionFilterBar
                        name={section.spec.name}
                        spec={section.spec}
                        members={bar.map((m) => m.metadata)}
                        filters={controlFilters ?? filters}
                        onFilterChange={onFilterChange}
                        onReset={
                          onResetBarFilters
                            ? () => onResetBarFilters(bar.map((m) => m.metadata.index))
                            : undefined
                        }
                      />
                    )}
                    {renderedKeys.has(key) && (
                      <div data-persistent-section-grid>
                        {renderGrid(metas, members, section, gridWidth)}
                      </div>
                    )}
                  </Accordion.Panel>
                </SectionAccordionItem>
              );
            })}
          </SectionAccordion>
        );
      })}
    </div>
  );
};

export default PersistentSectionsHost;
