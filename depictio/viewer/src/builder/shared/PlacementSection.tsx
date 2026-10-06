/**
 * Where a component lands: the section it joins.
 *
 * Presented as a collapsed accordion section inside each builder's control
 * column rather than a full-width block of its own, because placement is a
 * secondary, optional choice — the primary way to set it is the "Move to
 * section" menu on the placed component, which knows the current section and
 * moves a whole group at once.
 *
 * Renders nothing when the dashboard declares no sections. Offering a picker
 * with only "No section" in it is a dead end, the same reason
 * `GridItemEditOverlay` hides its own menu in that case.
 *
 * One component, slotted as the last item of every builder's
 * `BuilderSections`. `section` lives on the base component model, so
 * duplicating the control per builder would only guarantee drift.
 *
 * Which list is offered depends on the component's type, exactly as the two
 * render paths are fed: interactive components join the filter panel's sections
 * or a filter bar (a grid section with `display: 'strip'`), everything else
 * joins the grid's tile sections.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Group, Select, Stack, Text } from '@mantine/core';
import { fetchDashboard, isStripSection, SectionIcon } from 'depictio-react-core';
import type { DashboardData, FilterSectionSpec } from 'depictio-react-core';

import { useBuilderStore } from '../store/useBuilderStore';
import { BuilderSection } from './BuilderSections';
import { implicitNames, sectionsFor } from '../../components/sections/sectionMutations';
import type { SectionKind } from '../../components/sections/sectionMutations';

export interface PlacementSectionProps {
  /** Section value — keep it out of the builder's `required` list so the
   *  section starts collapsed. */
  itemValue?: string;
}

const PlacementSection: React.FC<PlacementSectionProps> = ({ itemValue = 'placement' }) => {
  const componentType = useBuilderStore((s) => s.componentType);
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const config = useBuilderStore((s) => s.config) as {
    section?: string;
    group?: string;
    placement?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  useEffect(() => {
    if (!dashboardId) return;
    let cancelled = false;
    fetchDashboard(dashboardId)
      .then((dash) => {
        if (!cancelled) setDashboard(dash);
      })
      .catch((err) => {
        // Degrades to "no sections offered" rather than blocking authoring.
        console.warn('[PlacementSection] section list unavailable:', err);
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId]);

  const kind: SectionKind = componentType === 'interactive' ? 'filter' : 'grid';

  // A filter bar is a grid section, but what joins it is a filter.
  const bars = useMemo<FilterSectionSpec[]>(
    () => (dashboard ? sectionsFor(dashboard, 'grid').filter(isStripSection) : []),
    [dashboard],
  );

  const specs = useMemo<FilterSectionSpec[]>(() => {
    if (!dashboard) return [];
    // Include sections that only exist because a component names them: the
    // manager materialises those, but a dashboard authored purely in YAML may
    // not have been through it yet.
    const own = [
      ...sectionsFor(dashboard, kind),
      ...implicitNames(dashboard, kind).map((name) => ({ name })),
    ];
    if (kind === 'grid') return own.filter((s) => !isStripSection(s));
    // A bar wins a name it shares with a panel section (see `isStripMember`).
    const barNames = new Set(bars.map((b) => b.name));
    return own.filter((s) => !barNames.has(s.name));
  }, [dashboard, kind, bars]);

  const current = config.section ?? '';
  // A section the dashboard no longer declares must still show, or saving an
  // unrelated field would silently drop it.
  const options = useMemo(() => {
    const names = specs.map((s) => s.name);
    const barNames = kind === 'filter' ? bars.map((b) => b.name) : [];
    if (current && !names.includes(current) && !barNames.includes(current)) {
      names.unshift(current);
    }
    const item = (name: string) => ({ value: name, label: name });
    if (barNames.length === 0) return names.map(item);
    return [
      { group: 'Filter panel', items: names.map(item) },
      { group: 'Filter bar on the dashboard', items: barNames.map(item) },
    ];
  }, [specs, bars, kind, current]);
  const optionCount = specs.length + (kind === 'filter' ? bars.length : 0) + (current ? 1 : 0);

  const specByName = useMemo(
    () => new Map([...specs, ...bars].map((s) => [s.name, s])),
    [specs, bars],
  );
  const inBar = bars.some((b) => b.name === current);

  // `placement: 'top'` controls render in the footer strip, which has no
  // sections at all.
  const disabled = componentType === 'interactive' && config.placement === 'top';

  // Nothing to place into: the Sections manager is where that starts, so a
  // disabled picker here would be pure noise on every dashboard that never
  // declared a section.
  if (optionCount === 0) return null;

  const select = (
    <Select
      label="Section"
      description={
        disabled
          ? 'Footer controls are not grouped into sections.'
          : kind === 'filter'
            ? inBar
              ? 'Draws this filter in a filter bar on the dashboard, in one row with the others there.'
              : config.group
                ? 'Groups this filter under a collapsible header. Changing it clears the group, which cannot span two sections.'
                : 'Groups this filter under a collapsible header in the filter panel, or puts it in a filter bar.'
            : 'Groups this component under a collapsible header in the dashboard.'
      }
      placeholder="No section"
      data={options}
      value={current || null}
      onChange={(v) => {
        const next = v ?? '';
        // A group may not span two sections (validate_interactive_groups in
        // depictio/models/models/dashboards.py). That rule is only enforced on
        // the YAML model, not on the document the save endpoint validates, so
        // moving one member of a group would save happily and only blow up
        // later on export. Clearing the group here is what keeps that
        // impossible — and it matches the group picker, which only ever offers
        // the chosen section's groups anyway.
        patchConfig(
          kind === 'filter' && config.group && next !== current
            ? { section: next, group: '' }
            : { section: next },
        );
      }}
      clearable
      searchable
      disabled={disabled}
      comboboxProps={{ withinPortal: false }}
      renderOption={({ option }) => (
        <Group gap="xs" wrap="nowrap">
          <SectionIcon
            spec={specByName.get(option.value)}
            size={12}
            fallbackIcon={
              bars.some((b) => b.name === option.value) ? 'mdi:tune-variant' : 'mdi:shape-outline'
            }
          />
          <Text size="sm">{option.label}</Text>
        </Group>
      )}
    />
  );

  return (
    <BuilderSection
      value={itemValue}
      icon="mdi:format-list-group"
      title="Placement"
      subtitle={
        kind === 'filter'
          ? 'The filter-panel section or filter bar this control joins'
          : 'The dashboard section this component joins'
      }
    >
      <Stack gap="sm">
        {select}
        <Text size="xs" c="dimmed">
          Optional — you can also move this component between sections later,
          from its menu on the dashboard.
        </Text>
      </Stack>
    </BuilderSection>
  );
};

export default PlacementSection;
