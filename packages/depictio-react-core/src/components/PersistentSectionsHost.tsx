import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Responsive as ResponsiveGridLayout } from 'react-grid-layout';
import { Accordion } from '@mantine/core';

import type { InteractiveFilter, PersistentSection } from '../api';
import { bulkComputeCards } from '../api';
import { useCollapseState } from '../hooks/useCollapseState';
import {
  applyAccordionValue,
  SectionAccordion,
  SectionAccordionItem,
  SectionHeader,
} from './SectionAccordion';
import ComponentRenderer from './ComponentRenderer';
import { normalizeLayout } from './DashboardGrid';

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
  /** Editor-only per-section action, rendered in the section header. A section
   *  fanned out here can only be changed on the tab that owns it, so the editor
   *  puts a jump to that tab where the "…" sits on an editable section. */
  renderSectionActions?: (section: PersistentSection) => React.ReactNode;
}

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
  renderSectionActions,
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

  // Card ids per owning tab, restricted to sections whose grid is mounted —
  // the same lazy rule the members below follow, so a folded section's cards
  // cost nothing until it is opened.
  const cardIdsByOwner = useMemo(() => {
    const byOwner = new Map<string, string[]>();
    for (const { section, members } of renderable) {
      if (!renderedKeys.has(hostSectionKey(section))) continue;
      for (const m of members) {
        if (m.metadata.component_type !== 'card') continue;
        const list = byOwner.get(m.dashboard_id) ?? [];
        list.push(m.metadata.index);
        byOwner.set(m.dashboard_id, list);
      }
    }
    return byOwner;
  }, [renderable, renderedKeys]);
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
    Promise.all(
      [...cardIdsByOwner.entries()].map(([owner, ids]) =>
        bulkComputeCards(owner, filters, ids).catch((err) => {
          console.warn('[PersistentSectionsHost] bulk-compute failed:', err);
          return null;
        }),
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
  }, [cardIdsKey, JSON.stringify(filters), refreshTick]);

  // Measure our own wrapper; the accordion box chrome is accounted for with a
  // probe, mirroring DashboardGrid's `sectionInset`.
  const wrapperRef = useRef<HTMLDivElement | null>(null);
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

  const keys = renderable.map((s) => hostSectionKey(s.section));

  return (
    // `flexShrink: 0`: the viewer mounts this inside a fixed-height column
    // flex container, which would otherwise squeeze a shrinkable host down to
    // zero height as soon as the tab's own grid fills the column.
    <div ref={wrapperRef} style={{ width: '100%', overflowX: 'hidden', flexShrink: 0 }}>
      <SectionAccordion
        value={keys.filter((k) => collapse.isOpen(k))}
        onChange={(open) => applyAccordionValue(open, keys, collapse)}
      >
        {renderable.map(({ section, members }) => {
          const key = hostSectionKey(section);
          return (
            <SectionAccordionItem
              key={key}
              value={key}
              color={section.spec.color}
              actions={renderSectionActions?.(section)}
            >
              <Accordion.Control>
                <SectionHeader spec={section.spec} name={section.spec.name} />
              </Accordion.Control>
              <Accordion.Panel>
                {renderedKeys.has(key) && (
                  <div data-persistent-section-grid>
                    <ResponsiveGridLayout
                      className="layout"
                      layouts={{
                        lg: normalizeLayout(
                          members.map((m) => m.metadata),
                          section.layouts,
                          false,
                        ),
                      }}
                      breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480 }}
                      cols={{ lg: 8, md: 6, sm: 4, xs: 2 }}
                      rowHeight={100}
                      width={Math.max(100, containerWidth - sectionInset)}
                      margin={[12, 4]}
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
                              metadata={member.metadata}
                              filters={filters}
                              onFilterChange={onFilterChange}
                              refreshTick={refreshTick}
                              cardValue={cardValues[member.metadata.index]}
                              cardSecondaryValues={cardSecondaryValues[member.metadata.index]}
                              cardLoading={cardsLoading}
                            />
                          </div>
                        </div>
                      ))}
                    </ResponsiveGridLayout>
                  </div>
                )}
              </Accordion.Panel>
            </SectionAccordionItem>
          );
        })}
      </SectionAccordion>
    </div>
  );
};

export default PersistentSectionsHost;
