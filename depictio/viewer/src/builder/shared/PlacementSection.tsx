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
 * One component, two mount points: `DesignShell` supplies its own surrounding
 * `Accordion` for the seven builders that go through it, and the figure builder
 * slots the item into the accordion already in its right-hand panel. `section`
 * lives on the base component model, so duplicating the control per builder
 * would only guarantee drift.
 *
 * Which list is offered depends on the component's type, exactly as the two
 * render paths are fed: interactive components join the filter panel's sections,
 * everything else joins the grid's.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Accordion, Group, Select, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchDashboard, SectionIcon } from 'depictio-react-core';
import type { DashboardData, FilterSectionSpec } from 'depictio-react-core';

import { useBuilderStore } from '../store/useBuilderStore';
import { implicitNames, sectionsFor } from '../../components/sections/sectionMutations';
import type { SectionKind } from '../../components/sections/sectionMutations';

export interface PlacementSectionProps {
  /** Accordion item value — keep it out of the accordion's `defaultValue` so
   *  the section stays collapsed. */
  itemValue?: string;
  /** Wrap the item in its own `Accordion`. Callers that already own one
   *  (the figure builder) leave this off and slot the item into theirs. */
  standalone?: boolean;
}

const PlacementSection: React.FC<PlacementSectionProps> = ({
  itemValue = 'placement',
  standalone = false,
}) => {
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

  const specs = useMemo<FilterSectionSpec[]>(() => {
    if (!dashboard) return [];
    // Include sections that only exist because a component names them: the
    // manager materialises those, but a dashboard authored purely in YAML may
    // not have been through it yet.
    return [
      ...sectionsFor(dashboard, kind),
      ...implicitNames(dashboard, kind).map((name) => ({ name })),
    ];
  }, [dashboard, kind]);

  const current = config.section ?? '';
  // A section the dashboard no longer declares must still show, or saving an
  // unrelated field would silently drop it.
  const options = useMemo(() => {
    const names = specs.map((s) => s.name);
    if (current && !names.includes(current)) names.unshift(current);
    return names.map((name) => ({ value: name, label: name }));
  }, [specs, current]);

  const specByName = useMemo(
    () => new Map(specs.map((s) => [s.name, s])),
    [specs],
  );

  // `placement: 'top'` controls render in the footer strip, which has no
  // sections at all.
  const disabled = componentType === 'interactive' && config.placement === 'top';

  // Nothing to place into: the Sections manager is where that starts, so a
  // disabled picker here would be pure noise on every dashboard that never
  // declared a section.
  if (options.length === 0) return null;

  const select = (
    <Select
      label="Section"
      description={
        disabled
          ? 'Footer controls are not grouped into sections.'
          : kind === 'filter'
            ? config.group
              ? 'Groups this filter under a collapsible header. Changing it clears the group, which cannot span two sections.'
              : 'Groups this filter under a collapsible header in the filter panel.'
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
            fallbackIcon="mdi:shape-outline"
          />
          <Text size="sm">{option.label}</Text>
        </Group>
      )}
    />
  );

  const item = (
    <Accordion.Item value={itemValue}>
      <Accordion.Control icon={<Icon icon="mdi:format-list-group" width={18} height={18} />}>
        <Text fw={700} size="sm">
          Placement
        </Text>
      </Accordion.Control>
      <Accordion.Panel>
        <Stack gap="sm">
          {select}
          <Text size="xs" c="dimmed">
            Optional — you can also move this component between sections later,
            from its menu on the dashboard.
          </Text>
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  );

  return standalone ? (
    <Accordion variant="separated" radius="md">
      {item}
    </Accordion>
  ) : (
    item
  );
};

export default PlacementSection;
